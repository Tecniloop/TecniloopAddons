# tl_piko_product_import

Importador de productos por **scraping HTML** para Odoo 19, pensado para tiendas
sin API pública (caso de partida: `piko-shop.de`, sistema propietario sin API).

Autor: Tecniloop · Licencia: LGPL-3 · Versión: 19.0.1.4.0

## Arquitectura

```
tl.piko.scraper   (AbstractModel)  Servicio HTTP + parseo. Sin estado.
tl.piko.source    (Model)          Configuración por tienda: URLs, reglas, selectores.
tl.piko.category  (Model)          Páginas de categoría a rastrear (con paginación).
tl.piko.product   (Model)          Staging: una línea por ficha rastreada.
product.template  (Inherit)        Trazabilidad + banderas de bloqueo.
```

Flujo asíncrono. Los botones **solo encolan**; el trabajo HTTP lo hace el cron:

1. **Encolar fuente** → `queue_state = queued` + `ir.cron._trigger()`.
2. `_cron_run_sources()` descubre URLs (sitemap / categorías / lista), crea las
   líneas en estado `queued` y dispara la cola de líneas.
3. `_cron_process_queue()` procesa por lotes: rastrea, aplica reglas y (si
   `auto_import`) crea o actualiza el producto.

## Estrategia de parseo (en cascada)

1. `JSON-LD` schema.org `Product` → nombre, sku, gtin, precio, disponibilidad, imagen.
2. Open Graph / `<meta>`.
3. XPath configurables por fuente (pestaña *Selectores*).
4. Heurísticas de texto: etiquetas «Artikelnummer / Item number / SKU» y EAN de 8/13/14 dígitos.

Así el módulo funciona sin tocar código en la mayoría de tiendas, y cuando el
sitio no publica datos estructurados basta con rellenar los XPath.

## Reglas de seguridad de datos

- Nunca vacía campos: si el scrape no trae valor, no se escribe.
- `piko_price_locked` en el producto → el precio nunca se sobrescribe.
- `piko_no_overwrite` → el producto queda excluido de toda actualización.
- El EAN solo se rellena si está vacío (`update_barcode`).
- La imagen solo se descarga si el producto no tiene ya `image_1920`.
- Emparejamiento: `piko_external_id` → `default_code` → `barcode`.

## Buenas prácticas de rastreo

- `respect_robots` activo por defecto; `request_delay` mínimo recomendado 1–2 s.
- Reintentos con espera progresiva ante HTTP 429/503.
- `max_products` limita cada ejecución; el cron va acumulando por pasadas.
- El cron (`ir_cron_tl_piko_sync`) se instala **desactivado**: actívalo cuando
  hayas validado los selectores contra un lote pequeño.

## Aviso legal

El scraping puede vulnerar las condiciones de uso del sitio de origen y, en la
UE, los derechos *sui generis* sobre bases de datos. Antes de usarlo en
producción conviene tener autorización del titular o un acuerdo de distribución
(en el caso de PIKO, existe acceso de distribuidor con listas de precios y datos
de artículo, que es el camino correcto frente al rastreo).

## Instalación

```bash
pip install requests lxml     # normalmente ya presentes en Odoo
# copiar el módulo en el addons_path y actualizar la lista de aplicaciones
odoo -u tl_piko_product_import -d <bd>
```

Tras instalar, asigna el grupo *Gestor de importaciones* al usuario y activa la
fuente de ejemplo «PIKO Webshop», que viene archivada a propósito.

## Pendiente / posible evolución

- Reutilizar el conector como fuente 41 de `tl_sitemap_product_import`.
- Variantes: por ahora se crea plantilla; los atributos técnicos como
  `no_variant` se dejarían al conector específico.
- Proveedor por defecto y `seller_ids` con precio de coste.

## Reglas de características (19.0.1.1.0)

`tl.piko.attribute.rule` convierte el texto de la ficha en atributos
**`no_variant`**. El modelo fuerza `create_variant = no_variant` en cualquier
atributo que use, y la importación **nunca** escribe en atributos que sí generan
variantes: el scraping no puede crear variantes por diseño.

Campos de la regla: origen del texto (nombre / referencia / descripción / URL /
ruta de categoría / todo), regex, valor fijo o grupo capturado, tabla de
normalización `capturado = Valor final`, primera o última coincidencia,
múltiples coincidencias y prioridad por secuencia (la primera regla que acierta
cierra ese atributo salvo que desactives *Detener el atributo al acertar*).

Juego precargado para PIKO: Escala, Época, Administración ferroviaria,
Corriente, Sonido, Interfaz digital, Tipo de tracción y Gama. La época usa
*última coincidencia* para no confundir la serie (`V 60.10`, `V 200.1`) con la
época; la escala cae a H0 como valor por defecto, que es el comportamiento
correcto en este catálogo.

Los valores de atributo se crean solos al vuelo, así que ampliar el catálogo de
administraciones o interfaces es solo editar la regex y la normalización.


## Ejecución asíncrona sin queue_job (19.0.1.2.0)

Todo el trabajo pesado vive en crons; el worker HTTP solo escribe estado.

- **Disparo**: `ir.cron._trigger()` sobre `ir_cron_tl_piko_queue` e
  `ir_cron_tl_piko_sources`. Es el mecanismo de tareas diferidas del core: el
  cron worker recoge el trabajo casi de inmediato, sin dependencia externa.
- **Lotes y presupuesto**: `_cron_process_queue()` trabaja en lotes de 20 con un
  presupuesto de `CRON_TIME_BUDGET` segundos. Al agotarse, se auto-redispara,
  así que un catálogo de miles de fichas nunca choca contra `limit_time_real_cron`.
- **Concurrencia**: advisory lock de sesión (`pg_try_advisory_lock`) para la
  cola de líneas y lock transaccional por fuente
  (`pg_try_advisory_xact_lock`). Dos crons simultáneos no duplican trabajo.
- **Aislamiento de fallos**: cada línea se procesa dentro de
  `cr.savepoint()`, de modo que un error no aborta el lote.
- **Reintentos**: `attempt_count` + `next_attempt_date` con backoff exponencial
  (`retry_backoff_minutes` × 2ⁿ) hasta `max_attempts`; después, estado `error`.
  Cuando solo quedan líneas esperando backoff, la cola se redispara con
  `_trigger(at=<fecha>)` en vez de girar en vacío.
- **Commits**: solo dentro de crons, vía `_commit_batch()`, que usa
  `ir.cron._commit_progress()` si la versión lo expone y cae a `cr.commit()` si
  no. Fuera del cron no hay ni un commit.

`action_scrape` sigue existiendo para depurar, pero lanza `UserError` con más de
10 líneas: lo correcto es *Encolar*.

### Requisito de despliegue

Hace falta al menos un worker de cron (`--max-cron-threads >= 1`; con 2 la cola
y el descubrimiento avanzan en paralelo). En modo `--dev` con un solo hilo el
disparo funciona igual, solo que en serie.


## Notas de compatibilidad Odoo 19

- `res.groups.category_id` ya no existe: la categoría se define en un registro
  `res.groups.privilege` y el grupo la referencia con `privilege_id`.
- `res.users.groups_id` pasa a `group_ids` (el módulo no asigna grupos por XML).
- `_sql_constraints` dejó de aplicarse: las restricciones usan `models.Constraint`.


## Fuente preconfigurada: PIKO Webshop EN (19.0.1.3.0)

Entrada `https://www.piko-shop.de/en.html?lang=en`. Se instala **archivada**.

- `base_url` = `https://www.piko-shop.de`, `lang_code` = `en`.
- `extra_params` = `lang=en`: el campo nuevo añade parámetros fijos a **cada**
  petición (también a las imágenes), sin ensuciar las URLs guardadas en el
  staging, que se quedan canónicas.
- `product_url_regex` = `/en/artikel/[^/]+-\d+\.html`, que excluye páginas sin
  id de artículo como `/en/artikel/ersatzteil.html`.
- 74 categorías del menú real del sitio en inglés (G, H0, TT, N, New 2026,
  Fanshop), más la home EN y *New in our shop* como semillas de novedades.

### Paginación (verificada 08/2026)

    página 1 -> /en/warengruppe/<slug>-<id>/l-100/o-artikelnr_asc.html
    página N -> .../l-100/o-artikelnr_asc/p-{N-1}.html      (p es base 0)

La categoría marca `paginated`, `page_size` (18/50/100), `order_key` y
`page_count`; `page_pattern` sigue disponible como override con `{page}`
(base 0) o `{page1}`. El rastreo corta en cuanto una página no aporta URLs
**nuevas**, así que `page_count` es solo un tope de seguridad y no importa que
vaya holgado.

Las categorías raíz de escala listan también los artículos de sus
subcategorías, de modo que la fuente rastrea solo H0 / G / TT / N (más New 2026
y Fanshop): ~40 peticiones de listado para ~3.800 fichas, frente a las ~70
hojas del menú.
