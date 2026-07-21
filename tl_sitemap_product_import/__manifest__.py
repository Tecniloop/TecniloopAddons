{
    'name': 'Importación de productos por sitemap',
    'version': '19.0.1.83.0',
    'category': 'Sales/Sales',
    'summary': 'Importa y actualiza productos desde el sitemap público de una o varias tiendas online',
    'description': """
Importación de productos por sitemap (multi-fuente, por conectores)
=====================================================================

Este módulo importa y mantiene actualizado un catálogo de productos en Odoo
a partir del sitemap público de una o varias tiendas online. Cada sitio se
da de alta como una "fuente" (URL de sitemap, categorías raíz, etiquetas,
ajustes de red...) que usa un "conector": código específico de ese sitio
que sabe cuántos sitemaps de productos/imágenes combinar y cómo extraer
nombre/precio/categoría/código de cada ficha.

A propósito NO hay un único servicio "genérico" con parámetros intentando
cubrir cualquier estructura posible: se comprobó con dos sitios reales
(Skechers España y Mustang Shoes) que la forma del sitemap y de la ficha de
producto puede variar bastante incluso entre sitios con la misma
plataforma de comercio electrónico -nº de sub-sitemaps a combinar, si
publican metaetiquetas Open Graph o no, estructura de la URL...-, así que
cada sitio tiene su propio conector (`models/connector_*.py`), y
solo lo que es genuinamente igual para cualquier sitio (HTTP, robots.txt,
parseo de XML de sitemaps, resolución de categorías con mapeos, descarga
de imágenes, creación del producto en Odoo) vive en un servicio base
compartido. Añadir un sitio nuevo con una estructura distinta es escribir
un conector nuevo, no ampliar una configuración genérica.

Funcionalidad principal
------------------------
* Recupera EAN/GTIN válidos (GTIN-8, UPC/GTIN-12, EAN-13 y GTIN-14),
  conserva todos los códigos por talla/variante y solo asigna el barcode de Odoo
  cuando la ficha publica exactamente un código inequívoco.
* Da de alta tantas fuentes (sitios web) como necesites en "Fuentes", cada
  una con su conector; incluye cuarenta y ocho fuentes de ejemplo ya configuradas
  (Skechers España, Mustang Shoes España, Pikolinos España, Panama Jack,
  Miguel Bellido España, Levi's España, Fruit of the Loom Europa, Blend Europa, SELECTED España, Geox España, Callaghan España, Fluchos España, Pitillos España, Gioseppo España, BH Bikes España, Lapierre Bikes España, WeThePeople BMX, Mondraker España, Cervélo España, Colnago España, Bicicletas Quer B2B España, Ridley Bikes España, GT Bicycles, Conor Bikes España, MERIDA BIKES España, Orbea España, Scalextric España, NINCO España, Electrotren España, Jouef Europa, Arnold Europa, Rivarossi Europa, Lima Europa,
  Pocher Europa, Hornby Europa, Airfix Europa, Corgi/Corgi Premiums Europa,
  Humbrol Europa, Bassett-Lowke Europa (precio EUR) y Märklin Europa; los conectores de la plataforma Hornby leen siempre el precio oficial del mercado EUR, sin convertir divisas; cada fuente usa un conector adaptado a
  la estructura real de su sitemap y sus fichas).
* Guarda cada URL de producto encontrada en un modelo intermedio de vista
  previa ("staging", compartido por todas las fuentes), con nombre, precio,
  categoría y descripción -pero SIN descargar imágenes ni otro contenido
  pesado, para no sobrecargar la base de datos con productos que quizá no
  se lleguen a importar.
* En una vista lista (con la URL de origen, la fuente y el resto de datos
  ligeros), el usuario selecciona todos o solo algunos productos -de una o
  varias fuentes a la vez- y lanza "Importar productos seleccionados" desde
  el menú de acciones (⚙): solo entonces se crean/actualizan de verdad los
  product.template de Odoo y se descargan sus imágenes. Cada fila de
  staging queda enlazada al producto resultante y a su fuente.
* Los productos que ya se importaron antes se refrescan automáticamente en
  sincronizaciones posteriores (nombre, precio, imágenes) sin necesidad de
  volver a seleccionarlos: la selección manual solo se pide para decidir
  qué productos NUEVOS entran en el catálogo.
* Usa la fecha <lastmod> del sitemap para omitir vistas previas de
  productos que no han cambiado desde la última sincronización.
* Comprueba robots.txt (con soporte real de comodines "*") antes de
  empezar, y aplica un retraso configurable entre peticiones, por fuente.
* Incluye crons desactivados por defecto: uno para ir obteniendo vistas
  previas pendientes (de todas las fuentes) y otro para lanzar
  sincronizaciones periódicas (de las fuentes marcadas para ello).
* Crea automáticamente tanto la categoría interna (product.category) como
  la categoría de comercio electrónico (product.public.category) de cada
  producto, anidadas bajo una categoría raíz propia de cada fuente.
* Permite mapear cualquier ruta de categoría de una fuente (o un prefijo de
  ella) a una categoría interna y/o de comercio electrónico YA EXISTENTE,
  en lugar de crear una nueva; incluye un asistente para explorar qué
  rutas de categoría existen realmente en el catálogo de cada fuente
  -leyendo solo el sitemap, sin descargar fichas- antes de mapear.

Limitaciones conocidas
------------------------
* Muchas tiendas cargan el selector de tallas y el stock por talla mediante
  JavaScript, por lo que no están en el HTML que descargan los conectores.
  Cada URL del sitemap se importa como producto simple (sin variantes), con
  el código de estilo y color extraído de la propia URL. Puede ampliarse
  conector a conector para consumir un feed/endpoint de variaciones si se
  dispone de acceso oficial.
* El conector de Mustang Shoes está verificado con datos reales para la
  parte de sitemaps (los 9 sub-sitemaps de productos y 9 de imágenes del
  índice real, que hay que combinar, no coger solo el primero) y para el
  patrón de URL de ficha (estilo/color y categoría, confirmados con 4 URLs
  de producto reales). La extracción de nombre/precio/descripción reutiliza
  las mismas metaetiquetas Open Graph que Skechers (algo habitual en sitios
  Salesforce Commerce Cloud, la misma plataforma que usa Mustang según su
  robots.txt), pero esto NO se ha confirmado todavía contra el HTML real de
  una ficha de Mustang -conviene revisarlo en las primeras vistas previas
  reales y ajustar `connector_mtng_es.py` si ese sitio no expone esas
  metaetiquetas.
* El conector de Pikolinos está verificado con una ficha real completa:
  no hay metaetiqueta de precio (a diferencia de Skechers/Mustang), así que
  el precio y la categoría se extraen del texto/migas de pan de la página,
  no de metaetiquetas -es un mecanismo más fràgil ante cambios de diseño de
  la web-. El selector de migas de pan usado (`_extract_breadcrumb` en
  `connector_pikolinos_es.py`) es una aproximación por selectores CSS
  habituales, sin confirmar contra el HTML en bruto real del sitio; si no
  encuentra nada, el producto se importa igualmente pero sin categoría
  específica. Además, cada producto aparece en el sitemap una vez por cada
  país/idioma que vende Pikolinos (~28-30 veces); el conector filtra solo
  las URLs `es-es`, y algunas URLs del sitemap redirigen a una página de
  categoría en vez de mostrar un producto (posibles artículos
  descatalogados) -se detectan y se marcan como error en la cola en vez de
  importarse vacías.
* **Conector de Miguel Bellido**: identifica únicamente los sub-sitemaps
  de productos de Shopify, consulta primero el endpoint Ajax público
  `/products/<handle>.js`, usa el tipo de producto como categoría y conserva la
  galería de imágenes en staging para descargarla al importar. Si el endpoint
  Ajax falla, utiliza JSON-LD, Open Graph y HTML como respaldo.
* **Conector de Levi's España**: acepta tanto un sitemap de URLs como un
  índice de sitemaps (también anidado o comprimido), conserva únicamente las
  fichas españolas cuyo patrón termina en `/p/<código>`, deriva la categoría de
  la ruta y extrae de la ficha el precio vigente, color, descripción y galería
  Scene7. Las tallas publicadas en la ficha no se crean todavía como variantes.

* **Conector de Fruit of the Loom Europa**: procesa el sitemap de Salesforce
  Experience Cloud `sitemap-view-1.xml`, conserva únicamente las fichas actuales
  `/shop/p/<slug>/<referencia>`, elimina parámetros de color para no duplicar la
  misma referencia y extrae JSON-LD, Open Graph, migas de pan e imágenes públicas.
  El catálogo está orientado a distribuidores y normalmente no publica precios;
  en ese caso el producto entra con precio 0 para que se complete en Odoo y las
  sincronizaciones posteriores conservan el precio manual. Los colores y tallas
  todavía no se crean como variantes.

* **Conector de Blend Europa**: procesa el sitemap del mercado `en-eu`,
  identifica las fichas por el sufijo estable `--<estilo>-<color>` y deduplica
  los alias que Blend publica para una misma combinación. Extrae nombre, precio
  vigente, color comercial, descripción, migas de pan e imágenes desde JSON-LD,
  Open Graph y HTML. Las tallas y longitudes todavía no crean variantes.

* **Conector de SELECTED España**: recorre el endpoint `sitemap/root` aunque
  publique un índice anidado, un `urlset` o contenido gzip, conserva únicamente
  fichas `/es-es/p/<slug>/<estilo>_<color>[_<variante>]` y deduplica por la
  referencia completa. Extrae el precio vigente (incluidos descuentos), color,
  descripción, migas de pan y galería de Salesforce Commerce Cloud. Si el
  sitemap deja temporalmente de responder como XML, usa el catálogo paginado
  español como mecanismo de respaldo. Las tallas aún no crean variantes.

* **Conector de Pikolinos España**: recorre `sitemap_index.xml`, combina mapas
  de producto e imágenes y conserva únicamente fichas `/es-es/<modelo>-<referencia>.html`.
  Consulta el endpoint JSON público de vista rápida de Salesforce Commerce Cloud para
  obtener precio vigente, moneda, color e imágenes sin confundir importes del pie de
  página. Usa JSON-LD y HTML como respaldo y obtiene las categorías de las migas de pan.
  Si el sitemap no enumera todos los colores, se importa el color predeterminado de la
  ficha como producto simple.

* **Conector de Geox España**: recorre `sitemap_index.xml`, incluidos índices
  anidados y XML gzip, y conserva solo fichas `/es-ES/<slug>-<código>.html` cuyo
  código final tiene 16 caracteres. Divide la referencia en artículo/material y
  color, extrae el precio vigente (también rangos y rebajas), color comercial,
  descripción, migas de pan y galería de Geox Thron CDN. Las tallas se mantienen
  como información de la web y no crean variantes.


* **Conector de Gioseppo España**: usa ``robots.txt`` como índice dinámico,
  selecciona únicamente las directivas ``/es-es/sitemap_products_*.xml`` y
  consulta el endpoint Ajax de Shopify para precio, descripción, variantes e
  imágenes. Completa la referencia ``REF: <estilo>-<color>`` y las categorías
  con las migas de pan de la ficha. Las tallas todavía no crean variantes.

* **Conector de Fluchos España**: procesa el índice Shopify `sitemap.xml`, sigue
  únicamente los mapas `sitemap_products_*.xml` y conserva las fichas españolas
  `/products/<handle>`. Consulta el endpoint Ajax `.js` para precio, descripción,
  tallas e imágenes y enriquece el resultado con el HTML para guardar el código de
  estilo, la referencia comercial de la combinación/color y el color visible. Cada
  ficha/color se importa como producto simple; las tallas aún no generan variantes.


* **Conector de BH Bikes España**: recorre el índice distribuido en mapas
  ``/cache/sitemap_<hex>.xml``, conserva únicamente fichas españolas bajo
  ``/es_ES/bicicletas/`` y ``/es_ES/equipamiento/`` terminadas en una referencia
  comercial, y deduplica por esa referencia. Extrae nombre, precio vigente,
  categorías, colores, galería del CDN de BH y GTIN/EAN publicados en JSON,
  atributos HTML o endpoints de color/talla. Cada modelo se mantiene como producto
  simple y los códigos múltiples se conservan en la tabla de variantes externas.

* **Conector de Lapierre Bikes España**: procesa el índice Shopify, conserva
  únicamente fichas localizadas ``/es-es/products/<handle>`` y consulta el
  endpoint Ajax ``.js`` para recuperar precio, SKU, opciones, galería y EAN/GTIN
  por tamaño de cuadro y color. El código de estilo se deriva del sufijo estable
  del handle, por ejemplo ``LPRTA`` en ``pulsium-80-lprta``.

* **Conector de WeThePeople BMX**: procesa el sitemap Webflow y conserva solo
  fichas de bicicletas, cuadros y componentes bajo carpetas de producto como
  ``/bikes/``, ``/frames/``, ``/forks/`` o ``/handlebars/``. Extrae nombre,
  descripción, colores, especificaciones y galería. El sitio oficial es un
  catálogo de fabricante y normalmente no publica precio ni EAN; en ese caso
  no sobrescribe precios manuales y solo guarda GTIN que superen la validación
  GS1 desde JSON-LD, JSON incrustado o atributos de la ficha.


* **Conector de Mondraker España**: procesa ``sitemapindex.xml`` y conserva
  únicamente fichas del mercado ``/es/es/``. Distingue productos de páginas
  editoriales y familias mediante filtros de URL y validación de marcadores de
  ficha, extrae precio, tallas, colores, categorías, descripción y galería, y
  recupera GTIN válidos desde JSON-LD, JSON incrustado o endpoints públicos.

* **Conector de Cervélo España**: procesa ``sitemap.xml`` e índices anidados,
  prioriza enlaces alternativos ``hreflang=es-ES`` y conserva únicamente fichas
  de modelo bajo ``/es-ES/bikes/<modelo>``. La ficha reúne varias configuraciones,
  colores y tallas; el conector guarda esas opciones en la descripción, usa el
  precio mínimo publicado como referencia del producto simple y recupera GTIN
  válidos desde JSON-LD, ``__NEXT_DATA__`` y objetos de configuraciones.

* **Conector de Colnago España**: procesa ``sitemap.xml`` e índices anidados,
  prioriza enlaces alternativos ``hreflang=es-ES`` y conserva fichas Shopify
  estándar bajo ``/es-es/products/`` y páginas de modelos premium bajo
  ``/es-es/premium-bikes/``. En productos Shopify consulta el endpoint Ajax
  ``.js`` para recuperar precio, SKU, opciones, imágenes y EAN por variante;
  en páginas premium usa JSON-LD, HTML y JSON incrustado como respaldo.

* **Conector de Bicicletas Quer B2B España**: usa ``robots.txt`` como índice
  dinámico de los sitemaps PrestaShop y, si el WAF bloquea ese recurso, prueba
  los nombres XML habituales y el mapa HTML español como respaldo. Conserva
  únicamente fichas ``/es/<categoría>/<id>-<slug>.html``, extrae precio,
  referencia, categorías, colores, tallas e imágenes, y recupera EAN/GTIN desde
  JSON-LD y los objetos de combinaciones de PrestaShop.

* **Conector de Ridley Bikes España**: lee ``robots.txt`` y sigue el
  ``sitemap_index.xml`` relativo, prioriza el mercado ``/es_ES/`` y conserva
  únicamente configuraciones de bicicleta bajo ``/es_ES/bikes/<referencia>``.
  Extrae nombre, montaje, diseño/talla, precio, categorías, descripción e
  imágenes, y recupera GTIN válidos desde JSON-LD, estado JavaScript, atributos
  HTML y endpoints públicos de variación.

* **Conector de GT Bicycles**: lee ``robots.txt`` para localizar el índice
  Shopify, sigue únicamente los mapas de productos y conserva fichas
  ``/products/<handle>``. Consulta el endpoint Ajax ``.js`` para recuperar
  opciones de talla/color, SKU, galería y EAN por variante. Cuando el catálogo
  solo muestra “Find a dealer” y no publica precio positivo, conserva cualquier
  precio introducido manualmente en Odoo.

* **Conector de Conor Bikes España**: procesa los sitemaps PrestaShop cuando
  están disponibles y usa como respaldo la paginación completa de
  ``/es/2-inicio``. Conserva fichas ``/es/<categoría>/<producto>-<combinación>-
  <slug>-<ean>.html``, extrae precio, referencia, color, talla, especificaciones
  e imágenes, y recupera el EAN tanto desde la URL como desde JSON-LD y los
  objetos de combinaciones de PrestaShop.


* **Conector de Electrotren España**: lee ``robots.txt`` para localizar
  ``sitemap.xml`` y conserva únicamente fichas ``/products/<slug>-<referencia>``.
  Separa la descripción comercial, la información ampliada y el contenido del
  paquete; recupera precio, referencia, galería y EAN/GTIN publicados, y crea
  atributos informativos para escala, escala ferroviaria, época, DCC, motor,
  operador, color, radio mínimo, luces, pantógrafo y restantes especificaciones.


* **Conector de Jouef Europa (precio EUR)**: lee ``robots.txt`` para localizar ``sitemap.xml``
  y conserva fichas ``/products/<slug>-<referencia>`` de la plataforma Hornby
  Hobbies. Importa el precio oficial en EUR, referencia, descripción, contenido
  del paquete, galería y GTIN publicados. Convierte las especificaciones ``Tech
  Specs`` en atributos informativos para escala, H0/HO, época, DCC, motor,
  operador, color, curva mínima, luces, pantógrafo y estado del producto.

* **Resto de marcas Hornby Hobbies**: añade Arnold, Rivarossi, Lima, Hornby,
  Airfix, Corgi/Corgi Premiums, Humbrol, Pocher y Bassett-Lowke mediante una base
  común. Los mercados continentales leen directamente EUR; las tiendas UK usan
  el selector oficial EUR y nunca convierten importes GBP. Cada marca mantiene
  categorías y atributos específicos sin generar variantes de Odoo.

* **Conector de Märklin Europa**: procesa el sitemap inglés y conserva fichas
  ``/en/products/details/article/<número>``. Deduplica los sufijos de navegación
  por número de artículo, importa el precio recomendado en EUR, prototipo,
  descripción del modelo, funciones digitales, imágenes, escala, época, tipo de
  producto y estado de fabricación. Los artículos históricos sin precio público
  no sobrescriben precios manuales de Odoo.

* **Conector de Panama Jack**: primer conector sobre Shopify (los otros
  tres son Salesforce Commerce Cloud), verificado con una ficha real. Sí
  tiene metaetiqueta de precio (`og:price:amount`), a diferencia de Joma y
  Pikolinos, pero en formato europeo con coma decimal ("179,00"); el
  conector la parsea aparte porque el servicio base asume punto decimal.
  Sin categoría verificada (no se encontró miga de pan fiable en la ficha
  probada); los productos entran bajo la raíz "Panama Jack" sin más
  anidación. Sin sitemap de imágenes propio: solo se importa la imagen
  principal. Nota para explorar más adelante: Shopify puede exponer cada
  producto como JSON en "<url>.json" -no se ha podido comprobar contra
  este sitio en concreto por restricciones de la herramienta de
  investigación usada, pero si funciona sería una fuente de datos más
  fiable que el HTML actual; ver el docstring de
  `connector_panamajack_es.py`.
* Antes de usarlo de forma recurrente en producción con un sitio nuevo,
  revisa que el uso automatizado es compatible con sus términos de uso; el
  robots.txt del sitio ya se comprueba automáticamente en cada
  sincronización.
""",
    'author': 'Tecniloop',
    'license': 'LGPL-3',
    # NOTA: 'website_sale' (la app de eCommerce) se añade como dependencia porque
    # el modelo de categoría de comercio electrónico (product.public.category) vive
    # ahí. Si tu base de datos no tiene instalada la tienda online, instalar este
    # módulo la instalará también a ella (y a sus propias dependencias: website,
    # sale, sale_management...). Si no quieres esto, puedes quitar 'website_sale'
    # de esta lista y desactivar "Importar categorías de comercio electrónico" en
    # cada fuente; el resto del módulo funciona igual sin esa parte.
    'depends': ['product', 'website_sale', 'website_sale_product_description', 'product_dimension', 'tl_product_package_dimensions', 'queue_job', 'website_sale_product_attachment'],
    'external_dependencies': {
        'python': ['lxml', 'requests'],
    },
    'data': [
        'data/queue_job_data.xml',
        'security/ir.model.access.csv',
        'data/sitemap_import_source_demo.xml',
        'data/ir_cron_data.xml',
        'views/sitemap_import_source_views.xml',
        'views/sitemap_import_batch_views.xml',
        'views/sitemap_import_wizard_views.xml',
        'views/sitemap_product_staging_views.xml',
        'views/sitemap_category_mapping_views.xml',
        'views/sitemap_category_explorer_wizard_views.xml',
        'views/product_template_views.xml',
        'views/ir_attachment_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
