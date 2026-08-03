# tl_piko_product_import

Importador de productos por **scraping HTML** para Odoo 19, pensado para tiendas
sin API pública (caso de partida: `piko-shop.de`, sistema propietario sin API).

Autor: Tecniloop · Licencia: LGPL-3 · Versión: 19.0.12.0.0

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
- `groups_id` pasa a `group_ids` en todos los modelos que lo llevan
  (`res.users`, `ir.actions.server`, `ir.ui.menu`...). El atributo XML
  `groups="..."` de vistas y menús sigue funcionando; el campo, no.
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


## Categorías (19.0.2.0.0)

El breadcrumb de la ficha trae la ruta completa con los ids del sitio:

    Home / H0 Scale / Locos DC / Expert DC / Electric locos
              20         373       376          306

Se guarda en la línea como `categ_path` + `categ_external_ids` y se vuelca a dos
sitios distintos, porque son cosas distintas:

| Destino | Campo | Modo en la fuente |
| --- | --- | --- |
| Contable | `categ_id` (una sola) | `categ_mode`: fija / primer nivel / último nivel |
| eCommerce | `public_categ_ids` (varias) | `public_categ_mode`: no importar / ruta completa / solo la última |

Por defecto: `categ_id` **fija** (la raíz de la fuente) y **ruta completa** en
categorías web. Es lo sensato: `categ_id` arrastra cuentas contables y reglas de
abastecimiento, así que conviene dejarlo grueso; la navegación de la tienda es
donde el árbol de 70 nodos tiene sentido.

Reglas:

- El árbol se crea bajo la categoría raíz de la fuente, con `parent_id` encadenado.
- Emparejamiento por `piko_external_id` (el id del sitio) y, si no, por nombre
  dentro del mismo padre: si PIKO renombra una categoría, no se duplica el árbol.
- `public_categ_ids` se **añade**, nunca se reemplaza: las categorías puestas a
  mano sobreviven a las sincronizaciones.
- `categ_id` solo se fija al crear, salvo que actives `update_categ`.

Extracción del breadcrumb: JSON-LD `BreadcrumbList` → contenedor con clase
`breadcrumb` → heurística que descarta el megamenú (>12 enlaces) y prefiere el
bloque que menciona el nombre del producto. Se filtran «Home» y el «Back»
duplicado.

El sitio **sí publica JSON-LD** (`BreadcrumbList` y `WebPage`), aunque no sea
visible al extraer la página como texto. Dos particularidades de su
`BreadcrumbList`: el nombre va dentro de `item`, no en el `ListItem`, y la lista
incluye la home y el propio artículo. Por eso solo se conservan los nodos cuya
URL es `/warengruppe/<slug>-<id>.html`.

Otros arreglos de esta versión, salidos de leer una ficha real:

- **Precio de respaldo**: si ningún JSON-LD `Product` ni XPath aporta precio, se
  busca el primer importe en euros posterior al `<h1>`.
- **EAN**: se prefiere una coincidencia de 13 dígitos, porque el nº WEEE
  (`DE 24216800`) también encajaba como EAN-8 y ganaba por posición.


## Tabla de características (19.0.3.0.0)

Las fichas traen una tabla *Features* de dos columnas. Se parsea entera
(`tl.piko.product.spec_json`) y es ahora la fuente preferente:

- **Campos base directos**: `Item number` → referencia, `EAN` → código de
  barras, `Manufacturer` → marca. Sin regex ni ambigüedad con el nº WEEE.
- **Atributos**: la regla admite `field_source = spec` con una `spec_label` y el
  modo `value` («Valor de la fila»), que toma el valor tal cual y lo pasa por la
  tabla de normalización. Las reglas de tabla van en secuencia 5, antes que las
  del título, que quedan como respaldo para fichas sin tabla.

Ojo con el idioma: en las páginas `/en/` las **etiquetas** están en inglés pero
los **valores** vienen en alemán (`Gleichstrom`, `ja`, `ab 14 Jahren`), de ahí la
normalización en cada regla.

Contraste sobre la ficha 21002 (BR E 410):

| Atributo | Con tabla | Solo título |
| --- | --- | --- |
| Corriente | DC (2 carriles) | DC (2 carriles) |
| Sonido | Con sonido | **Sin sonido** (mal) |
| Época | Ep. III | Ep. III |
| Interfaz digital | PluX22 | — |
| Decoder incorporado | PluX22 Sounddecoder | — |
| Edad recomendada | 14+ | — |

Atributos nuevos: *Decoder incorporado* y *Edad recomendada*. Los numéricos de
la tabla (`Measurement`, `Minimum radius`, `Number of Traction Tyres`) se
guardan en `spec_json` pero no se convierten en atributos, porque generarían un
valor distinto por medida.


## Registro de actividad (19.0.4.0.0)

Campo `log_level` en la fuente:

| Nivel | Qué se publica en el chatter |
| --- | --- |
| Silencioso | nada (solo log del servidor) |
| Resumen | inicio/fin de descubrimiento, cierre de cada lote y **todos los errores** |
| Detallado | además, una línea por ficha y por página de categoría |
| Depuración | además, cada petición HTTP |

Todo se escribe siempre en el log del servidor con el prefijo `[<fuente>]`; el
nivel solo decide qué llega al chatter.

Las entradas se acumulan en un buffer en memoria y se vuelcan **como un único
mensaje por lote** (o cada 200 entradas). Un `message_post` por ficha llenaría
el chatter de miles de mensajes y multiplicaría los INSERT en `mail_message`.
El buffer, además, sobrevive al rollback del savepoint de una línea fallida, así
que el error queda registrado aunque su transacción se deshaga.

Ejemplo de línea de ficha (nivel detallado):

    OK 21002: importado — 325.0 € · EAN 4015615210023 · 8 caract. · H0 Scale / Locos DC / Expert DC / Electric locos · producto #4271

Las líneas de staging **no** llevan chatter propio, a propósito: `mail.thread`
sobre miles de registros es coste de escritura y de almacenamiento que no
compensa cuando el registro agregado vive en la fuente.


## Descubrimiento reanudable (19.0.5.0.0)

Medido en producción: **una página de listado de piko-shop.de tarda ~30 s**. Con
~40 páginas, recorrer el catálogo entero son ~23 minutos en una sola llamada, muy
por encima de `limit_time_real_cron`: el worker muere, la transacción se deshace
y la fuente vuelve a `queued` sin dejar rastro ni líneas. Justo el síntoma de
"horas en cola sin avanzar".

Ahora el descubrimiento es un generador página a página (`iter_discovery`) y:

- crea las líneas y **commitea tras cada página**, así que nada se pierde;
- guarda el avance en la categoría (`next_page`, `discovery_state`);
- corta a los `DISCOVERY_TIME_BUDGET` segundos (90), deja la fuente en `queued`
  y se auto-redispara para continuar por donde iba;
- `discover(source, limit=N)` corta de verdad el rastreo al llegar a N, en vez
  de recorrerlo todo y recortar el resultado al final.

Fin de la paginación: página sin fichas **o idéntica a la anterior**.

Botón *Reiniciar descubrimiento* para volver a empezar desde la primera página;
*Ejecutar en segundo plano* ya lo reinicia por su cuenta.

`timeout` por defecto sube de 30 a 60 s: con respuestas de ~30 s, 30 iba al
límite.


## Migración a queue_job (19.0.6.0.0)

Fuera la cola casera (`ir.cron._trigger()`, `FOR UPDATE SKIP LOCKED`,
presupuestos de tiempo). Ahora depende de **`queue_job` (OCA)**.

### Granularidad

| Job | Unidad | Duración típica |
| --- | --- | --- |
| `tl.piko.source._job_discover_page` | una página de listado | ~30 s |
| `tl.piko.product._job_process_line` | una ficha | ~30 s |

Cada job de página encola las fichas que encuentra **y el job de la página
siguiente**: la cadena avanza sola y ninguna unidad se acerca a
`limit_time_real`. Era justo el fallo del diseño anterior, que intentaba
recorrer 40 páginas en una sola ejecución de cron.

### Reintentos

`_is_transient()` separa los fallos de red (timeout, 502/503/504, 429, conexión
reseteada) de los de datos. Los primeros se relanzan como `RetryableJobError`
con `seconds=` y los reintenta queue_job; los segundos marcan la línea en
`error` y no se reintentan, porque volver a pedir la misma ficha rota no la va a
arreglar.

### Canal

Dos subcanales bajo `root.piko`: **`discovery`** para los jobs de página y
**`lines`** para los de ficha. Compartir canal no funciona: la cadena de páginas
ocupa la capacidad y ninguna ficha se ejecuta hasta terminar el catálogo entero.

La capacidad **no** es un campo del modelo; va en `odoo.conf`:

    [queue_job]
    channels = root:1,root.piko.discovery:1,root.piko.lines:2

Con capacidad 1 los jobs de scraping se ejecutan de uno en uno, que es la forma
correcta de ser cortés con el servidor de origen, mejor que confiar solo en
`request_delay`.

### Duplicados

`identity_key=identity_exact` en todos los encolados: pulsar dos veces "Ejecutar"
no duplica el trabajo mientras el job siga pendiente.

### Crons que quedan

Solo planificación y mantenimiento: sincronización diaria (desactivada),
limpieza semanal (desactivada) y un **reencolado de huérfanas** cada 2 h, que
recupera las líneas en `queued` cuyo job ya no existe (jobrunner caído a mitad).

### Requisito de despliegue

`queue_job` necesita su runner. En el `odoo.conf`:

    server_wide_modules = base,web,queue_job

    [queue_job]
    channels = root:1,root.piko:1

Sin eso los jobs se quedan en `pending` para siempre — el mismo tipo de fallo
silencioso que teníamos con el cron.


## Descripción de eCommerce (19.0.8.0.0)

La descripción larga va al campo **`public_description`** del módulo OCA
`website_sale_product_description` (Html, `sanitize_attributes=False`), no a
`description_sale`.

- El scraper guarda el **HTML original** del bloque de descripción
  (`tl.piko.product.description_html`): párrafos, listas y negritas se
  conservan. Solo se eliminan `script`, `style` y `noscript`.
- Selección del bloque: `xpath_description_html` de la fuente si está definido;
  si no, contenedores habituales (`itemprop=description`,
  `.product-description`, `.beschreibung`, `.description`…). Se descartan los
  candidatos con menos de 60 caracteres y los que son tablas de más de 3 filas,
  para no confundirlo con la migas de pan ni con la tabla de características.
- `description_target` en la fuente: eCommerce (por defecto) / venta / ambas.
- Si `website_sale_product_description` no estuviera instalado, se omite sin
  romper.

### Rectificar productos ya importados

Ver «Resincronización de contenido» más abajo.


## Concurrencia y transacciones abortadas (19.0.8.1.0)

Con `root.piko.lines:2`, dos jobs pueden crear productos a la vez y chocar en el
flush de variantes de `product.template`: Postgres devuelve
`SerializationFailure`. Es un conflicto normal, no un error de datos.

Lo delicado es el manejo: con la transacción **abortada**, cualquier `write` o
`message_post` lanza `InFailedSqlTransaction` y convierte un fallo recuperable
en uno definitivo, con una traza que apunta al sitio equivocado (el chatter, no
la creación del producto).

Por eso `_job_process_line` intercepta `psycopg2.Error` **antes** que el
`except` genérico y, si el `pgcode` es de concurrencia (40001, 40P01, 55P03,
25P02), relanza `RetryableJobError` sin tocar la base de datos: ni estado, ni
contador de intentos, ni registro. El rollback y el reintento los hace
queue_job.

`ignore_retry=True` para que estos reintentos no gasten el cupo de
`max_retries`: perder una ficha por haber coincidido con otra sería absurdo.

`flush_log()` además envuelve el `message_post` en try/except: el registro es
accesorio y nunca debe tumbar un trabajo.

Si los conflictos son frecuentes, baja la concurrencia a
`root.piko.lines:1` — se pierde paralelismo, pero el cuello de botella real es
el servidor de origen, no Odoo.


## Medios y adjuntos (19.0.9.0.0)

Analizada la ficha 21002 (BR E 410), faltaba todo esto:

| Contenido | En la ficha | Destino en Odoo |
| --- | --- | --- |
| Galería | 5 imágenes en `/media/oart_0/oart_s/oart_<id>/` | 1ª → `image_1920`, resto → `product.image` |
| Vídeo | `youtube.com/embed/<id>` | `product.image.video_url` |
| Descargas | 5 enlaces `is.php?id=N` | `ir.attachment` público + `website_attachment_ids` |
| Medidas | Measurement, Minimum radius, Traction Tyres | `product_properties` |
| Características | Interior Lighting, Coupling, Directional lights, Kind of measurement | 4 atributos `no_variant` nuevos |

Detalles que importan:

- **Las imágenes se filtran por la carpeta del artículo** (`/media/oart_`). Sin
  ese filtro entraban el logo de cabecera y los iconos de GLS/DHL del pie, que
  viven en `/media/k2757/`.
- **Las descargas se filtran por `is.php?id=`**, no por estar en una lista: la
  ficha tiene también secciones de accesorios y recambios llenas de enlaces a
  otros artículos.
- **Idempotencia**: la URL de origen se guarda en `ir.attachment.description`,
  así que resincronizar no duplica adjuntos; las imágenes se comparan por
  nombre de fichero.
- `website_name` del adjunto toma el rótulo del enlace («Bedienungsanl./
  Ersatzteilliste 21002»), que es lo que verá el cliente en la tienda.
- Límite de tamaño por adjunto (`attachment_max_mb`, 20 por defecto).
- Las medidas van a **propiedades**, no a atributos ni a campos: ver abajo.

Nuevas dependencias: `website_sale_product_attachment`.

Acción de servidor **«Recuperar imágenes, vídeo y adjuntos (PIKO)»** en
Productos → *Acciones*, para completar lo ya importado: relee la ficha y añade
solo lo que falte.


## Medidas como propiedades (19.0.10.0.0)

Se retiran los campos `piko_length_mm`, `piko_min_radius_mm` y
`piko_traction_tyres`. Las medidas pasan a `product.template.product_properties`:

- **Sin columnas nuevas** en la tabla de productos.
- **Definición por categoría** (`product.category.product_properties_definition`),
  creada al vuelo la primera vez: "Radio mínimo" aparece en material rodante y
  no en tornillos.
- Tipos nativos: `float` para longitud y radio, `integer` para aros.

Por qué no atributos: cada longitud generaría su propio
`product.attribute.value` (195, 196, 197…), con miles de registros basura y
filtros de tienda inservibles.

### Presentación en la tienda

Las propiedades **no se muestran solas**: el bloque de especificaciones de
`website_sale` renderiza líneas de atributo y nada más. La plantilla
`templates/product_properties.xml` añade una tabla con las propiedades del
producto en la ficha.

Anclaje: **`#o_wsale_product_details_content`**, la columna de detalles.

Descartado `#product_attributes_simple` (el bloque de specs del core): está en
el arch de `website_sale.product`, pero **`website_sale_comparison` lo
reemplaza** por su propia tabla, así que desaparece del arch combinado y la
herencia falla con "no puede ser localizado". Tampoco sirve anclar en su
sustituto (`#product_specifications`, `#product_full_spec`), que solo existe si
ese módulo está instalado.

Descartado `#product_full_description`: lleva
`t-field="product.website_description"`, así que lo insertado dentro lo
sobrescribe el valor del campo.

Los xpath usan `//*[@id=...]` y no `//div[@id=...]`: atar el anclaje a la
etiqueta rompe la vista si el core cambia el elemento.

**Lección**: validar contra el fuente de la rama no basta. Lo que decide es el
**arch combinado de la instancia**, con sus módulos y su tema:

    v = env.ref('website_sale.product')
    arch = v.with_context(inherit_branding=False)._get_combined_arch()
    print(sorted({e.get('id') for e in arch.iter() if e.get('id')}))

### Limitación conocida

Las propiedades no son filtrables en la tienda ni agrupables como un campo
normal. Si algún día hace falta "locomotoras de menos de 200 mm" como filtro de
catálogo, eso sí pediría campos reales.


## Campos nativos en vez de OCA (19.0.11.0.0)

Validado contra el fuente de Odoo 19 (`addons/product`, `addons/website_sale`):
dos de las tres necesidades ya están cubiertas por el core, así que las
dependencias OCA sobraban.

| Necesidad | Antes (OCA) | Ahora (core 19) |
| --- | --- | --- |
| Descripción eCommerce | `public_description` | `product.template.description_ecommerce` |
| Descargas en la ficha | `website_attachment_ids` | `product.document` + `shown_on_product_page` |
| Vídeo | — | `product.image.video_url` → `embed_code` |

`depends` pierde `website_sale_product_description` y
`website_sale_product_attachment`. Si están instalados igualmente, se siguen
rellenando (`public_description`, `website_name`, `public=True` y el enlace en
`website_attachment_ids`), para no dejar a medias las bases que ya los usaban.

Detalles verificados en el fuente:

- `product.document` hace `_inherits` de `ir.attachment`, así que `name`,
  `datas`, `mimetype`, `res_model`, `res_id` y `description` se pasan en el
  mismo `create` y el adjunto se crea solo.
- `product_document_ids` es un `One2many` por `res_id` con dominio
  `res_model = product.template`; la deduplicación usa `description`, donde se
  guarda la URL de origen.
- `product.image` vive en `website_sale` (no en `product`) y su `embed_code` se
  computa desde `video_url` con `get_video_embed_code`.
- El bloque nativo de documentos de la ficha es `div#product_documents`, y solo
  lista los que tienen `shown_on_product_page` — de ahí la opción
  `publish_attachments`.


## Resincronización de contenido (19.0.12.0.0)

Las dos acciones anteriores (descripción por un lado, medios por otro) se
funden en una sola, y se mueven de la vista genérica de Productos a la de
**Productos rastreados** del módulo.

Por qué ahí: quien rectifica contenido importado trabaja sobre el staging, que
es donde están la URL de origen, la tabla de características extraída y el
registro de lo que se obtuvo. En la vista de Productos la acción aparecía
también sobre productos que no vienen del scraping.

**Productos rastreados → seleccionar → Acciones → «Resincronizar contenido
desde el origen (PIKO)»**, o el botón del formulario. Encola
`_job_refresh_content`, que relee la ficha y actualiza:

- descripción (HTML original) en `description_ecommerce`
- características (reglas de tabla y de título)
- propiedades (medidas)
- categorías de eCommerce
- galería, vídeo y descargas

**No toca nombre, precio ni código de barras**: es una rectificación de
contenido, no una reimportación. Y respeta `piko_no_overwrite`.

Detalle: si la línea ya estaba en `imported`, el rescrapeo no la degrada a
`parsed` — el estado se restaura al terminar.

Queda además el botón *Enviar solo la descripción al producto* en la pestaña
Descripción, para el caso puntual en que no haga falta releer la ficha.
