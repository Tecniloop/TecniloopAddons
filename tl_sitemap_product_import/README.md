# Importación de productos por sitemap (Odoo 19)

M�dulo para importar y mantener actualizado un catálogo de productos en Odoo
a partir del sitemap público de **una o varias tiendas online**, cada una
con su propio **conector**: código específico de ese sitio (cuántos
sub-sitemaps combinar, cómo extraer el estilo/color/categoría de cada URL).
No hay un único motor "genérico" intentando cubrir cualquier estructura
posible mediante parámetros: se comprobó con dos sitios reales (Skechers
España y Mustang Shoes) que la forma del sitemap y de la URL de producto
puede variar bastante incluso entre sitios con la **misma** plataforma de
comercio electrónico (Salesforce Commerce Cloud, en ambos casos), así que
cada sitio tiene su propio conector explícito en vez de una configuración
genérica cada vez más forzada. Lo que sí es igual para cualquier sitio -
HTTP, robots.txt, parseo de XML de sitemaps, resolución de categorías con
mapeos, descarga de imágenes, creación del producto en Odoo- vive en un
servicio base compartido, y **el modelo intermedio de productos
(`sitemap.product.staging`) también es el mismo para todas las fuentes**,
con un campo que indica de qué fuente viene cada fila.

Incluye cuatro fuentes de ejemplo ya configuradas (ver
`data/sitemap_import_source_demo.xml`): "Skechers España", "Mustang Shoes
España", "Pikolinos España" y "Panama Jack España" -esta última sobre
Shopify en vez de Salesforce Commerce Cloud, la prueba de que separar la
lógica por conectores realmente aísla las diferencias entre plataformas.
Ver "Limitaciones conocidas" para las particularidades de cada una.

## Arquitectura: fuentes + conectores + staging compartido

- **`sitemap.import.source`** (menú *Fuentes*): un registro por sitio web,
  con su URL de sitemap, el conector que usa, y ajustes que sí son solo
  datos (no lógica) y por tanto tiene sentido que sean configurables: red,
  categorías raíz, etiquetas, si se importan imágenes, etc.
- **Conector** (`models/connector_skechers_es.py`,
  `models/connector_mtng_es.py`): un `AbstractModel` por sitio que hereda
  la mecánica común de `sitemap.import.service` e implementa 3 métodos
  específicos de ESE sitio:
  - `get_product_entries(source, category_filter=None, limit=0)`: qué
    sub-sitemaps son "de productos" y cómo combinarlos (Skechers tiene
    uno; Mustang tiene nueve -sitemap_0-product.xml a sitemap_8-product.xml-
    que hay que fusionar, no coger solo el primero).
  - `get_image_map(source)`: lo mismo para las imágenes.
  - `fetch_preview(source, url)`: cómo extraer nombre/precio/descripción
    (normalmente reutilizando `_fetch_og_meta`, ya que las metaetiquetas
    Open Graph son un estándar muy extendido) y, sobre todo, el patrón de
    URL propio de ese sitio para el código de estilo/color y para saber
    qué segmentos de la ruta son categoría.
- **`sitemap.import.service`** (`AbstractModel` base): HTTP, robots.txt
  (con parser propio, ver más abajo), lectura de sitemaps XML, resolución
  de categorías de Odoo con mapeos, descarga de imágenes y creación del
  `product.template`. No toma ninguna decisión específica de un sitio.
- **`sitemap.product.staging`**: el modelo intermedio, compartido por
  todas las fuentes/conectores, con un campo `source_id` (y así
  `batch_id.source_id`) que indica de qué fuente/sitemap viene cada fila.

## Cómo funciona

El proceso tiene tres fases separadas a propósito, para no crear productos
de más ni sobrecargar la base de datos con contenido que quizá no haga
falta:

1. **Recopilar** — Para la fuente elegida, su conector decide qué
   sub-sitemaps leer y combinar, y se crea una fila por cada URL de
   producto encontrada en `sitemap.product.staging`, dentro de un lote
   (`sitemap.import.batch`). En este paso NO se descarga nada de cada
   ficha todavía.
2. **Vista previa** — Para cada fila pendiente, el conector descarga la
   ficha y extrae nombre, descripción, precio, moneda, categoría y el
   código de estilo/color según SU propio patrón de URL. Se guardan esos
   datos en la propia fila de staging, junto con la URL de la imagen
   principal como simple texto de referencia. **No se descarga ninguna
   imagen ni contenido binario en este paso.**
3. **Importar (selección manual)** — En la vista lista de
   `sitemap.product.staging` (con la URL, la fuente, el nombre, el precio
   y la categoría de cada producto) seleccionas todos los productos o solo
   algunos -de una o varias fuentes/conectores a la vez- y ejecutas
   "Importar productos seleccionados" desde el menú de acciones (⚙). Solo
   entonces se crea/actualiza el `product.template` correspondiente en
   Odoo y se descargan sus imágenes -reutilizando los datos ya obtenidos
   en el paso 2, sin volver a pedir la ficha. La fila de staging queda
   enlazada al producto creado (`product_tmpl_id`) y a su fuente
   (`source_id`).

**Excepción pensada para mantener el catálogo al día**: si una fila de
staging corresponde a una URL que **ya fue importada antes** (está
enlazada a un `product.template`), el paso 2 la actualiza automáticamente
de punta a punta -incluidas imágenes- sin esperar a que la selecciones de
nuevo. La selección manual solo se pide para decidir qué productos
**nuevos** quieres añadir al catálogo; los que ya aceptaste se mantienen
sincronizados solos.

Además, gracias a `<lastmod>` del sitemap, si una URL no ha cambiado desde
la última vez que se le hizo vista previa o se importó, se marca como
"sin cambios" y no se vuelve a descargar.

## Instalación

1. Copia la carpeta `tl_sitemap_product_import` en tu carpeta de addons.
2. Dependencias Python: `lxml` y `requests` (ya forman parte de los
   requisitos estándar de Odoo). Dependencia de módulo: `website_sale` -ver
   la nota en `__manifest__.py` si no quieres instalar la app de eCommerce.
3. Actualiza la lista de aplicaciones e instala "Importación de productos
   por sitemap".

## Añadir un sitio nuevo

**Si el sitio usa una estructura de sitemap/URL ya cubierta** por un
conector existente (poco probable salvo que sea literalmente el mismo
sistema), basta con crear una fuente nueva en el menú *Fuentes* eligiendo
ese conector y su URL de sitemap.

**En el caso general** (estructura distinta, que es lo esperable), hace
falta un conector nuevo:

1. Crea `models/connector_<nombre>.py` con un `AbstractModel`:
   `_name = 'sitemap.connector.<nombre>'`, `_inherit = 'sitemap.import.service'`.
2. Implementa `get_product_entries`, `get_image_map` y `fetch_preview`
   mirando `connector_skechers_es.py` (caso simple, un sitemap) y
   `connector_mtng_es.py` (caso con varios sitemaps a fusionar y prefijo
   de idioma en la URL) como referencia. Usa los métodos ya heredados del
   servicio base para lo genérico: `_fetch_sitemap_index_locs`,
   `_fetch_urlset`, `_fetch_image_urlset`, `_fetch_og_meta`.
3. Regístralo en `models/__init__.py` y añade la opción en
   `CONNECTOR_SELECTION`, en `models/sitemap_import_source.py`.
4. Crea la fuente en el menú *Fuentes* con ese conector.

No hace falta tocar `sitemap_import_service.py` ni ningún otro conector
existente: cada uno vive en su propio fichero, así que un sitio con una
estructura rara no puede romper -ni obligar a complicar- los demás.

## Uso

- **Menú Fuentes**: alta y configuración de cada sitio (conector, URL de
  sitemap, red, categorías raíz, etiquetas...).
- **Menú Importar productos**: abre el asistente. Elige la fuente,
  opcionalmente un filtro de categoría (p. ej. `mujer/calzado/zapatillas`)
  y un límite de productos para probar antes de explorar el catálogo
  completo. Al confirmar se crea un lote, se recopilan las URLs, se
  obtiene la vista previa de las 20 primeras (sin imágenes, sin crear
  productos) y te lleva directamente a la lista para revisarlas.
- **Menú Productos (vista previa)**: la vista lista principal, con la
  fuente de cada fila. Selecciona las que quieras (o todas, con la
  casilla de la cabecera) y usa **"Importar productos seleccionados"** en
  el menú de acciones (⚙) para crearlas/actualizarlas de verdad en Odoo;
  ahí es cuando se descargan sus imágenes. Puedes seleccionar productos
  de varias fuentes a la vez.
- **Menú Lotes de importación**: resumen de cada sincronización por
  fuente (pendientes, con vista previa, importados, sin cambios,
  errores), con un botón para continuar obteniendo vistas previas y un
  botón inteligente "Productos" que abre la lista filtrada a ese lote.
- **Menú Explorar categorías / Mapeo de categorías**: ver la sección de
  categorías más abajo (ambos, por fuente).
- **Menú Productos**: todos los productos importados por el módulo
  (de cualquier fuente), con acceso directo a su ficha de origen.

### Automatizar la obtención de vistas previas

Para catálogos grandes (miles de URLs), el asistente solo obtiene vista
previa de un primer grupo pequeño. El resto se completa mediante el cron
**"Importación por sitemap: Obtener vistas previas pendientes"** (Ajustes >
Técnico > Automatización > Acciones programadas), desactivado por
defecto: actívalo para que la lista se vaya rellenando sola en segundo
plano, para **todas** las fuentes con lotes en curso. Este cron nunca
crea productos por sí solo en URLs nuevas -eso siempre requiere tu
selección manual en la lista-, salvo para refrescar productos que ya
habías importado antes (ver más arriba).

El cron **"Importación por sitemap: Sincronización periódica"** (también
desactivado por defecto) crea automáticamente un lote nuevo cada día para
cada fuente que tenga marcada "Activar sincronización periódica
automática"; gracias a la comprobación de `<lastmod>`, estas
sincronizaciones repetidas son económicas: solo se vuelve a pedir lo que
realmente ha cambiado.

## Categorías: internas, e-commerce y mapeo manual (por fuente)

Por cada producto, el módulo resuelve dos árboles de categoría a partir de
la ruta que calcula el conector de la fuente (p. ej.
`Mujer/Calzado/Zapatillas/Zapatillas Casual`):

- **Categoría interna** (`product.category`, campo `categ_id`): siempre se
  crea/asigna.
- **Categoría de comercio electrónico** (`product.public.category`, campo
  `public_categ_ids`): se crea/asigna si "Importar categorías de comercio
  electrónico" está activo en la fuente (por defecto sí).

Por defecto, ambos árboles se crean anidados debajo de una categoría raíz
con el **nombre de la fuente** (una para cada tipo; configurables en la
ficha de la fuente como "Categoría raíz (interna)" y "Categoría raíz
(comercio electrónico)").

**Mapeo manual** (menú *Mapeo de categorías*): cada mapeo pertenece a una
fuente concreta -dos fuentes distintas pueden usar el mismo texto de ruta
sin interferirse-. Si ya tienes categorías propias y no quieres que se
cree un árbol nuevo, crea un registro indicando la fuente y:
- `Ruta de categoría de origen`: la ruta completa o solo el principio de
  ella, p. ej. `Mujer/Calzado` o `Mujer/Calzado/Zapatillas/Zapatillas Casual`.
- La categoría interna y/o de comercio electrónico ya existente a la que
  quieres que apunte.

Se aplica el mapeo cuya ruta coincida con el **prefijo más largo** de la
ruta real del producto; los segmentos que sobren después del prefijo
mapeado se siguen creando anidados debajo de la categoría indicada (en vez
de debajo de la raíz de la fuente). Por ejemplo, si mapeas `Mujer/Calzado`
a tu categoría "Zapatería Mujer", un producto con ruta
`Mujer/Calzado/Zapatillas/Zapatillas Casual` quedará como
`Zapatería Mujer > Zapatillas > Zapatillas Casual`. Si prefieres una
categoría fija sin más anidación, mapea la ruta completa del producto.

El asistente **Explorar categorías** (mismo menú, con selector de fuente)
pide al conector la lista completa de URLs de producto y deriva la
categoría de cada una solo a partir del patrón de URL -sin descargar
ninguna ficha, así que es rápido incluso con miles de referencias- y lista
todas las rutas distintas junto con el nº de productos de cada una, para
que sepas exactamente qué rutas mapear antes de lanzar la importación.

Al actualizar un producto en sincronizaciones posteriores, si el mapeo
cambia y la categoría e-commerce resultante es distinta de la que asignó
el importador la última vez, se retira la anterior y se añade la nueva sin
tocar otras categorías de comercio electrónico que hayas añadido a mano
(se controla con el campo `sitemap_public_categ_id` de cada producto).

## robots.txt y buenas prácticas

El módulo comprueba `robots.txt` antes de cada sincronización
(`respect_robots_txt`, activo por defecto en cada fuente; lo usan todos
los conectores, vía `check_robots` heredado del servicio base). El
comprobador está escrito a medida porque `urllib.robotparser` de la
librería estándar de Python **no interpreta correctamente los comodines
`*`** que usan muchos robots.txt reales -comprobado tanto contra el de
skechers.es como el de mtngshoes.com, ambos con reglas del tipo
`Disallow: /carrito*` que la librería estándar ignora silenciosamente.

Además, se aplica un retraso configurable entre peticiones
(`request_delay`, 1 s por defecto) y un `User-Agent` identificable, ambos
por fuente. Aun así, antes de un uso recurrente en producción con un sitio
nuevo conviene confirmar que encaja con sus términos de uso.

## Limitaciones conocidas

- **Tallas y stock**: el selector de tallas y el stock por talla suelen
  cargarse mediante JavaScript en la ficha de producto, por lo que no
  están en el HTML que descargan los conectores. Cada URL del sitemap se
  importa como producto simple (sin variantes), con el código de estilo y
  de color guardados en la ficha para referencia. Si consigues acceso a un
  feed oficial de alguna marca (EDI, API de partner, etc.) con stock por
  talla, se puede ampliar el conector de esa fuente para crear ahí los
  atributos "Talla"/"Color" y las variantes correspondientes.
- **Conector de Mustang Shoes, verificado solo en parte**: la combinación
  de sub-sitemaps (9 de productos + 9 de imágenes reales) y el patrón de
  URL para estilo/color/categoría están confirmados con datos reales (el
  sitemap índice y 4 URLs de producto reales). La extracción de
  nombre/precio/descripción reutiliza las metaetiquetas Open Graph, igual
  que Skechers -algo esperable al ser también Salesforce Commerce Cloud-,
  pero esto no se ha confirmado todavía contra el HTML real de una ficha
  de Mustang; revísalo en las primeras vistas previas reales.
- **Conector de Pikolinos**: sin metaetiqueta de precio -precio y
  categoría se leen del texto/migas de pan de la página, más frágil ante
  cambios de diseño que una metaetiqueta-. El sitemap mezcla ~28-30
  idiomas/países por producto; el conector filtra solo `es-es`. Algunas
  URLs redirigen a una página de categoría en vez de a un producto
  (probables artículos descatalogados); se detectan comparando la URL
  solicitada con la canónica devuelta y se marcan como error en la cola en
  vez de importarse con precio 0€ y sin imagen. El color no está en la URL
  del sitemap (va por parámetro `?dwvar_..._color=`, no enumerado allí);
  se usa el que la propia ficha indica como color por defecto.
- **Conector de Panama Jack (Shopify)**: primer conector sobre una
  plataforma distinta a las otras tres (Salesforce Commerce Cloud). Sí
  tiene metaetiqueta de precio (`og:price:amount`), pero en formato
  europeo con coma decimal ("179,00"); se parsea aparte del servicio base,
  que asume punto decimal. Sin categoría verificada -no se encontró una
  miga de pan fiable en la ficha probada, así que los productos quedan
  bajo la raíz "Panama Jack" sin más anidación-. Sin sitemap de imágenes
  propio: solo se importa la imagen principal. Posible mejora sin
  verificar: Shopify puede exponer cada producto como JSON en
  `<url>.json`, con datos ya estructurados; no se pudo comprobar contra
  este sitio en concreto, pero merece la pena probarlo a mano antes de
  confiar a ciegas en el HTML actual.
- **Moneda**: el precio se importa tal cual figura en la web de cada
  fuente. Si la moneda de la compañía en Odoo no coincide, habría que
  añadir conversión.

## Permisos

Todos los modelos del módulo con datos propios (fuentes, lotes, staging,
mapeos, asistentes) están dados de alta solo para el grupo
"Administración/Ajustes" (`base.group_system`). Si quieres que otros
usuarios (p. ej. compras o catálogo) puedan revisar y seleccionar
productos sin ser administradores, amplía el acceso en Ajustes > Usuarios
y Compañías > Grupos, o pide el cambio y se añade un grupo propio del
módulo. Los conectores y el servicio base son `AbstractModel` (no
almacenan datos), así que no necesitan fila propia en
`ir.model.access.csv`.

## Estructura del módulo

```
models/
  sitemap_import_source.py      Una fuente por sitio web: qué conector usa, sitemap, red, categorías
  sitemap_category_mapping.py   Mapeo de rutas de categoría de una fuente -> categorías existentes
  sitemap_product_staging.py    Modelo intermedio COMPARTIDO: vista previa ligera + selección + enlace
  sitemap_import_batch.py       Orquestación de un lote de sincronización (despacha al conector de la fuente)
  sitemap_import_service.py     Servicio BASE: solo mecánica genérica + ganchos que cada conector implementa
  connector_skechers_es.py      Conector Skechers España (un sitemap de productos, uno de imágenes)
  connector_mtng_es.py          Conector Mustang Shoes España (varios sitemaps a fusionar, prefijo de idioma)
  connector_pikolinos_es.py     Conector Pikolinos España (filtro de idioma es-es, precio/categoría por texto)
  connector_panamajack_es.py    Conector Panama Jack España (Shopify: precio con coma decimal, sin sitemap de imágenes)
  product_template.py           Campos sitemap_* añadidos a product.template (incluye sitemap_source_id)
wizards/
  sitemap_import_wizard.py             Asistente de lanzamiento manual (con selector de fuente)
  sitemap_category_explorer_wizard.py  Asistente para listar las rutas de categoría de una fuente
data/
  sitemap_import_source_demo.xml       Fuentes de ejemplo: Skechers España y Mustang Shoes España
```
