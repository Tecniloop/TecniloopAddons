{
    'name': 'Importación de productos por sitemap',
    'version': '19.0.1.0.0',
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
* Da de alta tantas fuentes (sitios web) como necesites en "Fuentes", cada
  una con su conector; incluye cuatro fuentes de ejemplo ya configuradas
  (Skechers España, Mustang Shoes España, Pikolinos España y Panama Jack
  España -esta última sobre Shopify, no Salesforce Commerce Cloud como las
  otras tres, prueba de que el diseño por conectores realmente aísla las
  diferencias de plataforma-).
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
* El precio se importa tal cual figura en la web. Si la moneda de la
  compañía en Odoo no coincide con la del sitio, deberás adaptar la
  conversión.
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
    'depends': ['product', 'website_sale'],
    'external_dependencies': {
        'python': ['lxml', 'requests'],
    },
    'data': [
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
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
