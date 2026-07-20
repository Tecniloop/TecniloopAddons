# Importación de productos por sitemap para Odoo 19

Módulo multi-fuente para descubrir, previsualizar e importar productos desde los
sitemaps públicos de tiendas online. Cada web dispone de un conector específico,
mientras que la gestión de lotes, staging, categorías, imágenes y productos se
comparte entre todos los conectores.

## Fuentes incluidas

- Skechers España.
- Mustang Shoes España.
- Pikolinos España.
- Panama Jack España.
- Miguel Bellido España.
- Levi's España.
- Fruit of the Loom Europa.
- Blend Europa.
- SELECTED España.
- Geox España.
- Callaghan España.
- Fluchos España.
- Pitillos España.
- Gioseppo España.
- BH Bikes España.
- Lapierre Bikes España.
- WeThePeople BMX.
- Mondraker España.
- Cervélo España.
- Colnago España.
- Bicicletas Quer B2B España.
- Ridley Bikes España.
- GT Bicycles.
- Conor Bikes España.
- MERIDA BIKES España.
- Orbea España.
- Scalextric España.
- NINCO España.
- Electrotren España.
- Jouef Europa (catálogo UK y precio oficial EUR).
- Arnold Europa (precio oficial EUR).
- Rivarossi Europa (precio oficial EUR).
- Lima Europa (precio oficial EUR).
- Pocher Europa (precio oficial EUR).
- Hornby Europa (precio oficial EUR).
- Airfix Europa (precio oficial EUR).
- Corgi y Corgi Premiums Europa (precio oficial EUR).
- Humbrol Europa (precio oficial EUR).
- Bassett-Lowke Europa (precio oficial EUR).

Las fuentes se crean automáticamente al instalar o actualizar el módulo y pueden
editarse desde el menú de configuración del importador.

## Proceso

1. El usuario crea un lote y recopila las URLs de producto del sitemap.
2. El cron o la acción manual obtiene una vista previa ligera de cada producto.
3. El usuario selecciona las filas que desea importar.
4. El módulo crea o actualiza `product.template`, categorías, atributos informativos e imágenes.
5. En sincronizaciones posteriores, los productos ya aceptados se actualizan
   automáticamente cuando cambia la fecha `lastmod` del sitemap.

## Pikolinos España

Fuente incluida: `https://www.pikolinos.com/sitemap_index.xml`. El conector
recorre índices y `urlset` anidados, incluidos XML gzip y namespaces variables,
y conserva únicamente las fichas españolas
`/es-es/<modelo>-<referencia>.html`. Deduplica por referencia y, cuando la URL
expone un parámetro `dwvar_*_color`, por referencia y color.

Pikolinos usa Salesforce Commerce Cloud. Para cada ficha el conector consulta
primero el endpoint JSON público `/es-es/product/quickview?pid=<pid>`, que
proporciona el precio de venta vigente, moneda, datos de producto y galería. De
esta forma no se confunden con el precio los importes de envío y promociones del
pie de página. Si el endpoint no está disponible, se utilizan JSON-LD y selectores
HTML limitados al bloque de precio. La referencia se guarda sin la extensión
`.html`, el color se obtiene de la variación seleccionada o del texto `Color:` y
las categorías se toman de las migas de pan.

El sitemap puede publicar una sola URL maestra aunque la ficha ofrezca varios
colores. En ese caso se importa el color predeterminado como producto simple; las
tallas y los demás colores todavía no generan variantes de Odoo.

## Conector Miguel Bellido

`https://www.miguelbellido.es/sitemap.xml` pertenece a una tienda Shopify. El
sitemap raíz es un índice que contiene sitemaps de productos, colecciones,
páginas y blog. El conector sigue exclusivamente los ficheros
`sitemap_products_*.xml` del idioma español y descarta las rutas `/en/`.

Para cada ficha intenta primero el endpoint Ajax público de Shopify:

```
/products/<handle>.js
```

Este endpoint proporciona datos estructurados de título, descripción, precio,
tipo de producto, opciones, variantes e imágenes. El conector utiliza:

- El precio vigente como `list_price`.
- El campo `type` como categoría del producto.
- El `handle` como código de estilo estable.
- Las opciones de color como código/color informativo.
- La imagen destacada y la galería de imágenes, hasta el límite configurado en
  la fuente.

Si el endpoint Ajax no está disponible, el conector usa como respaldo JSON-LD,
Open Graph y el contenido HTML de la ficha.

## Conector Levi's España

`https://www.levi.com/ES/es_ES/sitemap.xml` se procesa de forma dinámica como
`urlset` o como índice de otros sitemaps, incluidos índices anidados y ficheros
XML comprimidos. Si el frontal redirige ese recurso al mapa del sitio HTML, el
conector localiza el catálogo general y recorre su paginación como respaldo.
Solo se aceptan URLs españolas de producto terminadas en `/p/<código>`.

La ruta anterior al slug del producto se convierte en la categoría de Odoo. De
la ficha se obtienen el título, el precio vigente, el color, el bloque "Acerca
de este estilo", el código `Style #` y las imágenes del mismo artículo
publicadas en Adobe Scene7. El conector descarta las imágenes de recomendaciones
y productos relacionados comparando el identificador del recurso con el código
de estilo.

Las tallas y longitudes que aparecen en la ficha continúan siendo información de
la web: esta versión importa cada combinación de estilo/color como un producto
simple y no crea variantes de talla.


## Recuperación de EAN/GTIN

Todos los conectores pasan por un flujo común de identificación de códigos de
barras. Se aceptan únicamente GTIN-8, GTIN-12/UPC-A, EAN-13 y GTIN-14 cuyo
dígito de control sea válido, evitando confundir referencias, SKU o IDs de
variante con un EAN.

- En Shopify se leen `barcode`, SKU, disponibilidad y opciones de cada variante
  desde `/products/<handle>.js`.
- En Pikolinos se consultan la vista rápida y los endpoints públicos de
  variación por talla.
- En Salesforce Commerce Cloud y plataformas equivalentes se analizan
  JSON-LD, JSON incrustado y URLs públicas de variación encontradas en la
  ficha, respetando el límite configurado en la fuente.
- En el resto de conectores se buscan las propiedades Schema.org `gtin`,
  `gtin8`, `gtin12`, `gtin13`, `gtin14`, `ean` y `barcode`.

Los códigos se guardan en `sitemap.product.ean` con su talla/variante externa,
SKU, disponibilidad e identificador remoto. Si la ficha contiene exactamente
un GTIN inequívoco, se asigna al `barcode` de la única variante de Odoo. Si
contiene varios códigos, se conservan todos en la pestaña **Importación** y no
se asigna uno arbitrariamente al producto simple. Un barcode manual tampoco se
sobrescribe, y los conflictos con otros productos se omiten.

Las fuentes incluyen los ajustes **Recuperar EAN/GTIN** y **Máximo de peticiones
de variantes por producto**. Los productos ya importados obtendrán sus códigos
en la siguiente sincronización forzada o cuando cambie el `lastmod` del
sitemap.

## Limitación de variantes

Cada URL se importa actualmente como un producto simple de Odoo. Aunque Shopify
proporciona las variantes de talla y color, este módulo no crea todavía
`product.attribute`, `product.template.attribute.line` ni variantes
`product.product`. Las opciones se conservan como información de staging y del
producto importado.

## Categorías

Los conectores con URLs jerárquicas pueden derivar la categoría directamente de
la ruta. En Shopify las URLs son planas (`/products/<handle>`), por lo que el
conector Miguel Bellido toma la categoría del campo `type` del producto.

El módulo permite mapear las rutas de categoría de cada fuente a categorías
internas y categorías de comercio electrónico existentes.

## Imágenes

Las imágenes no se descargan durante la vista previa. Sus URLs se guardan en el
staging y los binarios se descargan únicamente al importar o actualizar un
producto aceptado. Las imágenes creadas por el módulo se identifican con el
prefijo `[Sitemap Import]`.

## Red y robots.txt

Cada fuente permite configurar:

- User-Agent.
- Timeout.
- Retraso entre peticiones.
- Respeto de `robots.txt`.
- Número de vistas previas por ejecución.
- Número máximo de imágenes por producto.

## Estructura principal

```
models/
  sitemap_import_source.py
  sitemap_import_batch.py
  sitemap_product_staging.py
  sitemap_product_ean.py
  sitemap_category_mapping.py
  sitemap_import_service.py
  connector_skechers_es.py
  connector_mtng_es.py
  connector_pikolinos_es.py
  connector_panamajack_es.py
  connector_miguelbellido_es.py
  connector_levis_es.py
  connector_fruitoftheloom_eu.py
  connector_blendcompany_eu.py
  connector_selected_es.py
  connector_geox_es.py
  connector_callaghan_es.py
  connector_fluchos_es.py
  connector_pitillos_es.py
  connector_gioseppo_es.py
  connector_bhbikes_es.py
  product_template.py
wizards/
  sitemap_import_wizard.py
  sitemap_category_explorer_wizard.py
data/
  sitemap_import_source_demo.xml
  ir_cron_data.xml
```


## Fruit of the Loom Europa

Fuente incluida: `https://www.fruitoftheloom.eu/s/sitemap-view-1.xml`.
El conector procesa el sitemap XML y, si Salesforce no lo entrega correctamente,
usa como respaldo el catálogo paginado. Procesa fichas
`/shop/p/<slug>/<referencia>`, deduplica las URLs
con `?color=`, conserva la referencia de siete dígitos y obtiene nombre,
descripción, categorías e imágenes desde JSON-LD/Open Graph/HTML. El sitio es
un catálogo para distribuidores y no suele publicar precios, por lo que se
importa 0,00 cuando no existe un importe explícito. En sincronizaciones
posteriores conserva cualquier precio introducido en Odoo mientras la web siga
sin publicar uno. Tallas y colores no se convierten todavía en variantes de
Odoo.

## Conector Blend Europa

Fuente preconfigurada:

- **Nombre:** Blend Europa
- **Conector:** `sitemap.connector.blendcompany_eu`
- **Sitemap:** `https://www.blendcompany.com/en-eu/sitemap.xml`

El conector reconoce las fichas por el patrón
`/en-eu/<slug>--<estilo>-<color>`. Como el sitio puede publicar varias URLs
para la misma combinación estilo-color, las deduplica por la referencia
numérica. Obtiene nombre, precio vigente, color, descripción, categorías e
imágenes mediante JSON-LD, Open Graph y HTML visible. En rebajas prioriza el
primer precio vigente publicado. Las tallas y longitudes no se convierten aún
en atributos o variantes de Odoo.



## SELECTED España

Fuente incluida: `https://www.selected.com/es-es/sitemap/root`. El conector
acepta índices y urlsets con o sin namespace, índices anidados y XML gzip. Solo
incorpora fichas españolas con patrón
`/es-es/p/<slug>/<estilo>_<color>[_<variante>]`, deduplicando por la referencia
completa. La ficha aporta nombre, precio actual, color, descripción, categorías
y galería de imágenes de Salesforce Commerce Cloud. Si el endpoint de sitemap
no entrega XML, se utiliza de forma segura el catálogo paginado como respaldo.
Las tallas no se convierten todavía en variantes de Odoo.


## Geox España

Fuente incluida: `https://www.geox.com/es-ES/sitemap_index.xml`. El conector
recorre índices y `urlset` anidados, con o sin namespace y también comprimidos
con gzip. Solo admite fichas españolas terminadas en un código de producto de
16 caracteres, por ejemplo
`/es-ES/chaleco_acolchado-azul_medianoche-jaysen_mujer-W6525DT3146F1624.html`.

Deduplica por el código completo y separa los primeros 11 caracteres como
referencia de artículo/material y los últimos 5 como código técnico de color.
De la ficha obtiene modelo, tipo de producto, precio vigente, color comercial,
descripción, categorías y galería. Las imágenes de `geox-cdn.thron.com` se
normalizan a una petición de hasta 1600 x 1600 píxeles y se filtran por la
referencia para no incorporar recomendaciones. En precios rebajados conserva
el importe vigente y, cuando Geox publica un intervalo por talla, utiliza el
importe mínimo. Las tallas no generan aún variantes de Odoo.


## Callaghan España

Fuente incluida:
`https://callaghan.es/sitemap_products_1.xml?from=8661866217740&to=8790897033484`.
Es un `urlset` de productos Shopify que publica las fichas bajo
`/products/<handle>` e incluye imágenes mediante `image:image`. El conector
acepta únicamente productos del dominio español y elimina parámetros o barras
finales para evitar duplicados.

Para la vista previa consulta primero el endpoint Ajax público
`/products/<handle>.js`, del que obtiene el título, descripción, precio vigente,
variantes e imágenes. También consulta el HTML para leer el título SEO, la URL
canónica y el color comercial, sin usar importes generales de la página. Así no
confunde el precio principal con accesorios recomendados, promociones o gastos
de envío. Si el endpoint Ajax falla, utiliza JSON-LD y Open Graph como respaldo.

El código de estilo se obtiene del prefijo del nombre o del handle, por ejemplo
`16100`. El color se extrae del título SEO de formato
`MATERIAL / COLOR | TECNOLOGÍA`, de las etiquetas Shopify o de una opción de
color. La categoría combina el público detectado en la ficha o el handle
(Hombre, Mujer, Niño o Niña) con el tipo de producto. Las tallas siguen siendo
variantes de Shopify y esta versión importa cada ficha/color como un producto
simple de Odoo.

## Fluchos España

Fuente incluida: `https://fluchos.es/sitemap.xml`. Fluchos utiliza Shopify y el
sitemap raíz combina mapas de productos, colecciones, páginas y blog. El conector
sigue exclusivamente los recursos `sitemap_products_*.xml`, acepta los dominios
`fluchos.es`/`www.fluchos.es`, descarta rutas de otros idiomas y conserva fichas
`/products/<handle>`.

La vista previa consulta primero `/products/<handle>.js` para obtener de forma
estructurada el nombre, la descripción, el precio vigente, las variantes de talla
y la galería. El HTML se usa para validar la URL canónica y leer el bloque de
materiales, donde Fluchos publica una referencia propia para cada combinación. Por
ejemplo, en `PRIME W F2335 Deportivo Marrón` se guarda `F2335` como código de
estilo y `506014 - Marrón claro` como código de color/referencia.

El público se obtiene de las etiquetas Shopify y, cuando no está publicado, del
rango de tallas; el tipo se deriva del nombre y del tipo Shopify (deportivos,
mocasines, zapatos, sandalias, botines, etc.). Se importan hasta ocho imágenes en
alta resolución. Cada ficha/color continúa siendo un producto simple de Odoo y las
tallas no generan todavía variantes.



## Pitillos España

Fuente incluida: `https://calzadospitillos.com/sitemap.xml`. Pitillos utiliza
Shopify y publica las fichas principales bajo `/products/<handle>`. El conector
sigue solo los sub-sitemaps `sitemap_products_*.xml`, descarta las rutas
traducidas `/en/`, `/it/` y `/fr/`, y elimina parámetros de variante para
evitar duplicados.

La vista previa combina el endpoint público `/products/<handle>.js` con el HTML
de la ficha. Del endpoint obtiene precio vigente, descripción, variantes e
imágenes; del HTML obtiene el modelo completo, el color visible y las
características técnicas. Un modelo como `30213-CREMA` se guarda como código de
estilo `30213` y código de color `CREMA`. También se incorporan a la descripción
datos como género, material, suela, plantilla, altura y tipo de piso cuando la
ficha los publica.

La categoría combina el género de la ficha con el tipo de calzado deducido del
nombre y de las etiquetas Shopify. Las tallas siguen siendo variantes de
Shopify y cada modelo-color se importa como un producto simple de Odoo.


Gioseppo España
----------------
* Fuente: ``https://gioseppo.com/robots.txt``.
* El conector lee las directivas ``Sitemap:`` en cada ejecución y conserva solo
  los mapas españoles ``/es-es/sitemap_products_*.xml``.
* Fichas: ``/es-es/products/<handle>``; datos estructurados mediante ``.js``.
* Separa la referencia visible ``REF: 76475-P-NEGRO`` en estilo ``76475`` y
  código de color ``P-NEGRO``.
* Usa las migas de pan y etiquetas Shopify para las categorías, y conserva la
  galería de imágenes en alta resolución.


## BH Bikes España

Fuente incluida: `https://www.bhbikes.com/sitemap.xml`. El índice distribuye las
URLs entre varios mapas `/cache/sitemap_<hex>.xml`; el conector recorre todos los
`urlset`, incluso si aparecen anidados o comprimidos, y filtra únicamente fichas
del mercado español bajo `/es_ES/bicicletas/` y `/es_ES/equipamiento/` cuyo último
segmento termina en una referencia comercial, por ejemplo `TE706`, `K2653` o
`387464100`. Las categorías se derivan de la ruta y las URLs se deduplican por
referencia de modelo.

La ficha aporta nombre, precio vigente, descripción, colores y la galería de
`bhbikes.b-cdn.net`. El precio se toma primero de JSON-LD/Open Graph y, como
respaldo, del bloque de precio, descartando las cuotas mensuales de financiación.
El conector busca GTIN/EAN en JSON-LD, JSON incrustado, atributos HTML y endpoints
públicos de variantes. También revisa las URLs de cada color descubiertas mediante
el parámetro `c`, respetando el límite de peticiones configurado. Un modelo puede
contener varios colores y tallas: se mantiene como producto simple y todos los EAN
recuperados se conservan en `sitemap.product.ean`; solo se asigna `barcode` cuando
existe un único código inequívoco.

## Lapierre Bikes España

Fuente incluida: `https://lapierrebikes.com/sitemap.xml`. Lapierre utiliza
Shopify y publica el mercado español bajo `/es-es/products/<handle>`. El
conector sigue únicamente los sitemaps de producto, descarta otros mercados y
consulta el endpoint Ajax localizado `.js`.

Se importa el nombre, descripción, precio vigente, tipo de bicicleta, colores,
tamaños de cuadro y galería. El código estable se obtiene del sufijo del handle:
por ejemplo `pulsium-80-lprta` se guarda como estilo `LPRTA`; las variantes
publican SKU como `LPRTA440`. Los `barcode` válidos de Shopify se conservan como
EAN/GTIN por tamaño/color. Si existen varios códigos, no se asigna ninguno de
forma arbitraria al producto simple de Odoo.


## WeThePeople BMX

Fuente incluida: `https://wethepeoplebmx.de/sitemap.xml`. La web oficial es un
catálogo Webflow del fabricante, no la tienda europea enlazada desde el menú. El
conector procesa `urlset`, índices anidados y XML gzip, y filtra exclusivamente
fichas de producto bajo carpetas como `/bikes/`, `/frames/`, `/forks/`,
`/handlebars/`, `/stems-headsets/`, `/grips-barends/`, `/wheels-rims/` y las
demás familias de componentes. Si Webflow devuelve temporalmente HTML en lugar
del XML, recorre las páginas de índice como respaldo y vuelve a aplicar el mismo
filtro estricto.

La vista previa obtiene el nombre, descripción, colores, principales
especificaciones y galería del producto. La categoría se deriva de la carpeta y
se refina según el tipo de componente, el diámetro de la bicicleta o la
modalidad del cuadro. Como el catálogo oficial no suele publicar precios, se
marca `price_available=False` para no borrar un precio introducido manualmente
en Odoo. El código de estilo usa primero un SKU o número de artículo publicado y,
si no existe, conserva el slug estable de la URL como referencia web.

La recuperación de EAN busca exclusivamente GTIN válidos en JSON-LD, JSON
incrustado y atributos/endpoints públicos de la ficha, con validación del dígito
de control GS1. No convierte el slug, medidas, pesos o referencias internas en
EAN. Si la web no publica códigos, el producto se importa sin barcode.


## Mondraker España

Fuente incluida: `https://mondraker.com/sitemapindex.xml`. El conector recorre
índices anidados y XML gzip, selecciona el mercado español `/es/es/` y filtra
las páginas editoriales, familias, tecnología, noticias y soporte. Las fichas
son principalmente planas, por ejemplo `/es/es/2025-foxy-carbon-rr`; algunas
referencias de ropa pueden contener un segundo segmento.

La vista previa valida que la página contenga los marcadores propios de una
ficha Mondraker (tallas, información, componentes, geometría, galería o precio),
y extrae nombre, descripción, precio vigente, tallas, colores, categoría y
galería. Se clasifican bicicletas, e-bikes, cuadros, ropa y componentes.

El código de estilo usa primero SKU, MPN, productID o referencia publicada. Si
la web no ofrece una referencia comercial, se conserva el slug canónico como
referencia web estable. Los EAN/GTIN se buscan en JSON-LD, JSON incrustado,
atributos y endpoints públicos de variación y siempre se validan mediante el
dígito de control GS1. Si existen varios códigos por talla, se guardan en la
tabla de variantes externas y no se asigna uno arbitrariamente al barcode del
producto simple.


## Cervélo España

Fuente: `https://www.cervelo.com/sitemap.xml`  
Conector: `sitemap.connector.cervelo_es`

El conector recorre índices y mapas de URL, selecciona el mercado español
mediante `/es-ES/` o `hreflang=es-ES` y conserva únicamente fichas de modelo
bajo `/es-ES/bikes/<slug>`. Excluye páginas de colección como carretera,
triatlón, off-road y e-bikes.

Cada ficha de Cervélo contiene varias configuraciones, colores y tallas en una
misma URL. El módulo crea un producto simple por modelo, incorpora la lista de
configuraciones a la descripción y usa el precio mínimo publicado como precio
informativo. Los GTIN se buscan en JSON-LD, `__NEXT_DATA__`, JSON incrustado y
endpoints públicos; cuando hay varios se conservan por variante sin asignar uno
arbitrariamente al barcode del producto simple.

## Colnago España

La fuente ``https://www.colnago.com/sitemap.xml`` utiliza el conector
``sitemap.connector.colnago_es``. El conector recorre índices y urlsets,
selecciona el mercado ``es-ES`` y admite dos tipos de ficha:

- ``/es-es/products/<handle>``: productos Shopify estándar. Se consulta el
  endpoint Ajax ``.js`` para precio, variantes, SKU, imágenes y barcode/EAN.
- ``/es-es/premium-bikes/<handle>``: páginas editoriales de modelos premium.
  Se obtienen nombre, descripción, precio, colores, imágenes y GTIN publicados
  mediante JSON-LD, HTML o JSON incrustado.

Los GTIN se validan con el dígito de control GS1. Si una bicicleta o artículo
publica varios códigos por montaje o talla, se conservan en la tabla de EAN de
variantes externas y no se asigna uno arbitrariamente al producto simple.

## Bicicletas Quer B2B España

El conector ``sitemap.connector.bicicletasquer_es`` parte de
``https://b2b.bicicletasquer.com/robots.txt``. Lee las directivas ``Sitemap:``
de PrestaShop y, si robots.txt está protegido por el WAF, prueba los nombres XML
habituales y finalmente el mapa HTML ``/es/mapa-del-sitio``. Solo acepta fichas
españolas con el patrón ``/es/<categoría>/<id>-<slug>.html``. Recupera precio,
referencia, categorías, colores, tallas e imágenes. Los EAN se extraen de
JSON-LD, JSON incrustado y objetos ``combinations`` de PrestaShop; si hay varios
por talla o color quedan almacenados como variantes externas y no se asigna uno
arbitrario al producto simple. El archivado automático se deja desactivado por
defecto porque el descubrimiento HTML de respaldo puede ser parcial.

## Ridley Bikes España

La fuente ``https://www.ridley-bikes.com/robots.txt`` declara el índice
``sitemap_index.xml``. El conector selecciona fichas españolas con el patrón
``/es_ES/bikes/<referencia>`` y normaliza también los enlaces alternativos
``/en_ES/`` al idioma español. Cada URL representa una configuración concreta
de bicicleta, por lo que la referencia final de la URL se usa como código
estable. Se importan nombre, precio, montaje, diseño/talla, categoría,
descripción e imágenes. Los EAN/GTIN se buscan en JSON-LD, estado JavaScript,
atributos HTML y endpoints públicos de variantes; si hay varios códigos se
conservan en ``sitemap.product.ean`` sin asignar uno arbitrariamente al producto
simple. El archivado automático queda desactivado por defecto para proteger el
catálogo si el índice o algún sub-sitemap responde parcialmente.

## GT Bicycles

La fuente ``https://gtbicycles.com/robots.txt`` declara el sitemap Shopify
``https://gtbicycles.com/sitemap.xml``. El conector sigue únicamente los mapas
de producto y acepta fichas ``/products/<handle>``. Obtiene nombre, descripción,
categoría, tallas, colores, imágenes y SKU desde la respuesta Ajax ``.js``.

Los ``barcode`` válidos de cada variante se guardan como EAN/GTIN junto con su
talla, color, SKU, disponibilidad e identificador Shopify. Si hay varios códigos
no se asigna uno arbitrariamente al producto simple. Muchas bicicletas del
catálogo oficial muestran solo ``Find a dealer``; en ese caso se marca que no
hay precio público y una sincronización no elimina el precio manual de Odoo.
El archivado automático queda desactivado por defecto para proteger el catálogo
ante respuestas parciales del sitemap global.


## Conor Bikes España

El conector `sitemap.connector.conor_es` trabaja con el catálogo público
PrestaShop de `https://conorbikes.com/es/`. Intenta primero `robots.txt` y los
nombres habituales de sitemap XML de PrestaShop. Si no encuentra un XML útil,
recorre la categoría general paginada `/es/2-inicio`, que enumera el catálogo.

Las fichas siguen normalmente este patrón:

```
/es/<categoria>/<id_producto>-<id_combinacion>-<slug>-<ean13>.html
```

El conector importa nombre, precio, referencia, categorías, colores, tallas,
especificaciones e imágenes. El EAN seleccionado se recupera de la URL y de la
ficha, y el resto de combinaciones se busca en los objetos JavaScript de
PrestaShop. Si hay varios EAN por color o talla, se conservan en
`sitemap.product.ean` y no se asigna uno arbitrariamente al producto simple.


## MERIDA BIKES España

El conector `sitemap.connector.merida_es` trabaja con el catálogo público de
`https://www.merida-bikes.com/es-es`. Las fichas se publican bajo
`/es-es/bike/<id-modelo>[-<id-artículo>][/<slug>]`; las distintas formas de una
misma ficha se deduplican por el identificador de modelo y se conserva la URL
más específica.

El descubrimiento intenta primero `robots.txt` y los endpoints XML habituales.
Cuando no existe un sitemap de productos utilizable, recorre de forma acotada
el buscador público `/es-es/bikefinder` y sus páginas de familia. La fuente se
crea con archivado automático desactivado para evitar bajas falsas si el
buscador devuelve un catálogo parcial.

La vista previa recupera nombre, descripción, especificaciones, tallas, colores,
precio cuando se publica, imágenes y categoría. Busca SKU/MPN/productID y GTIN
en JSON-LD, JSON incrustado, atributos HTML y endpoints públicos descubiertos.
Si la web no publica una referencia comercial, utiliza `MERIDA-<id>` como
referencia web estable, sin tratarla como EAN. Los múltiples GTIN por talla o
configuración se conservan en `sitemap.product.ean`.

## Orbea España

El conector `sitemap.connector.orbea_es` parte de
`https://www.orbea.com/es-es/`. El `robots.txt` público permite el rastreo pero
no declara actualmente un sitemap. Por ello se prueban primero los endpoints
XML habituales y después se recorren de forma acotada las páginas públicas de
familias y los catálogos de bicicletas, ruedas, accesorios, ropa y cascos.

Reconoce tanto fichas planas como `/es-es/onna-50`, `/es-es/orca-m30` o
`/es-es/ra80ltd-cs-shimano-hg-set` como las rutas históricas anidadas de
`/es-es/equipamiento/...` y `/es-es/oprema/...`. Las páginas `/m/...` y
`/catalogo/...` se usan solo para descubrir productos y nunca se importan como
fichas.

La vista previa valida que la página contenga marcadores propios de producto y
recupera nombre, precio base, tallas, colores, especificaciones, categoría,
imágenes y referencia. En bicicletas configurables se evita confundir los
suplementos de componentes con el precio de la bicicleta. Los EAN/GTIN se
buscan en JSON-LD, JSON incrustado, atributos HTML y endpoints de variantes;
si existen varios códigos por talla, color o configuración se conservan en
`sitemap.product.ean` sin asignar uno arbitrariamente al producto simple.

El archivado automático queda desactivado porque el descubrimiento mediante
catálogos puede ser parcial si la web cambia la carga dinámica de resultados.



Conector Scalextric España
---------------------------
* Fuente: ``https://scalextric.es/robots.txt``. El fichero declara el índice
  ``https://scalextric.es/2_index_sitemap.xml``.
* Plataforma PrestaShop. Reconoce fichas ``/<categoria>/<id>-<slug>-<ean>.html``.
* Importa categoría, referencia, EAN, precio, descripción breve, descripción
  ampliada e imágenes.
* Extrae atributos técnicos informativos, especialmente ``Escala`` (por ejemplo
  ``1:32`` o ``1:64``), además de gama, sistema y luces cuando la ficha lo publica.
* Los atributos se crean con ``create_variant = no_variant`` para no generar
  variantes de producto. La descripción breve se lleva a ``description_sale`` y
  la ampliada a ``description_ecommerce``.
* El archivado automático queda desactivado porque el descubrimiento HTML de
  respaldo puede ser parcial si el índice XML no responde.

## Conector NINCO España

* Fuente: ``https://www.ninco.com/robots.txt``. PrestaShop declara el índice
  ``https://www.ninco.com/1_index_sitemap.xml``.
* Reconoce las fichas españolas ``/es/<id>-<slug>.html`` y aplica validación
  adicional porque algunas categorías antiguas usan el mismo formato de URL.
* Importa categoría, referencia, precio cuando se publica, descripción breve,
  descripción ampliada, imagen principal y galería.
* Extrae atributos técnicos informativos como ``Escala`` (``1:10``, ``1:18``,
  ``1:32``, ``1:43`` o ``1:64``), motor, tipo de vehículo, tracción, batería,
  cargador, emisora, velocidad, acabado, tipo de coche slot, dimensiones y edad.
* Los atributos se crean con ``create_variant = no_variant``. La descripción
  breve se lleva a ``description_sale`` y la ampliada a ``description_ecommerce``.
* Busca EAN/GTIN en JSON-LD, datos PrestaShop, atributos HTML y combinaciones
  Ajax. Solo asigna el barcode de Odoo cuando existe un único GTIN válido.
* El archivado automático queda desactivado porque el respaldo mediante
  categorías paginadas puede ser parcial si el índice XML no responde.



## Electrotren España

La fuente `https://es.electrotren.com/robots.txt` descubre el sitemap oficial y
filtra exclusivamente fichas `/products/`. El conector importa la descripción
corta, la información ampliada, el contenido del paquete, precio, referencia,
imágenes y GTIN publicados. Las especificaciones ferroviarias se crean como
atributos informativos `no_variant`, incluyendo escala, H0/HO, época, DCC,
motor, compañía ferroviaria, color, radio mínimo, luces y pantógrafo.

## Jouef Europa: catálogo UK y precio oficial EUR

La fuente `https://uk.jouef.com/robots.txt` declara el sitemap oficial. El
conector conserva fichas `/products/` y extrae referencia, precio oficial en EUR,
descripción, contenido del paquete, imágenes y GTIN publicados. Las secciones
`Product Info`, `What's Inside` y `Tech Specs` se procesan por separado.

Las especificaciones se crean como atributos informativos `no_variant`: escala,
escala ferroviaria H0/HO, época, DCC, motor, volante de inercia, operador,
color, curva mínima, pantógrafo, luces, carrocería metálica, enganche corto,
topes con resorte y estado del producto. Las categorías inglesas conocidas se
traducen al español antes de crearlas en Odoo.



El catálogo y las descripciones se descubren en `uk.jouef.com`, pero el precio se consulta en la ficha equivalente de `fr.jouef.com`. Se importa el precio oficial publicado en EUR, incluidos descuentos propios del mercado francés; no se convierte el importe GBP. Si la ficha francesa no publica precio o no puede validarse contra la misma referencia, el precio se considera no publicado y no se sobrescribe un precio manual de Odoo.

## Precios oficiales EUR en la plataforma Hornby

Los conectores Hornby no convierten importes desde GBP. Todas las fichas pasan
por una capa común que consulta el escaparate oficial de la marca en EUR y
valida que la referencia sea la misma. Electrotren reutiliza su ficha española
(`es.electrotren.com`) y Jouef consulta la equivalente francesa
(`fr.jouef.com`). Arnold (`de.arnoldmodel.com`), Rivarossi (`it.rivarossi.com`) y Lima
(`it.limamodel.it`) leen directamente sus escaparates continentales. Hornby,
Airfix, Corgi/Corgi Premiums, Humbrol, Pocher y Bassett-Lowke utilizan el selector
oficial EUR de sus tiendas británicas. Si el selector o la ficha EUR no publica
un precio verificable, se conserva el precio manual de Odoo.


## Resto de marcas Hornby Hobbies

La versión 19.0.1.31.0 añade una base común para las restantes tiendas oficiales
Hornby Hobbies. Todas comparten el patrón `/products/<slug>-<referencia>`, el
sitemap de la plataforma, los bloques de descripción, contenido y especificaciones,
y la recuperación de imágenes y GTIN.

Fuentes añadidas:

- Arnold Alemania: modelismo ferroviario N y TT, precio directo en EUR.
- Rivarossi Italia: modelismo ferroviario H0, precio directo en EUR.
- Lima Italia: modelismo ferroviario, precio directo en EUR.
- Hornby: trenes, vías, DCC, edificios y repuestos.
- Airfix: kits, escala, piezas, nivel de dificultad y opciones de decoración.
- Corgi y Corgi Premiums: vehículos, aviación y cultura popular en una sola fuente.
- Humbrol: pinturas, acabados, volumen, aplicación, secado y superficies.
- Pocher: kits de gran escala, coches, motocicletas, motores y vitrinas.
- Bassett-Lowke: catálogo ferroviario y coleccionismo.

Para las tiendas británicas se intenta el selector oficial de moneda EUR mediante
la sesión y las variantes públicas del selector. No se realiza conversión desde
GBP. Si la tienda no devuelve un precio EUR, `price_available` queda desactivado
y no se sobrescribe un precio introducido manualmente en Odoo.


## Märklin Europa

El conector `sitemap.connector.maerklin_en` procesa el sitemap internacional
`https://www.maerklin.de/en/sitemap.xml` y las fichas
`/en/products/details/article/<número>`. Recupera número de artículo, precio EUR,
escala, época, tipo de producto, prototipo, descripción del modelo, funciones
digitales, imágenes y estado de fabricación. Las URLs con sufijos de navegación
se deduplican por artículo y los productos históricos sin precio no borran un
precio manual de Odoo.


## Trix Europa

El conector `sitemap.connector.trix_en` procesa las áreas Trix H0 y Trix Express del catálogo oficial. Minitrix se separa en una fuente propia para evitar duplicados.

El conector `sitemap.connector.minitrix_en` recorre exclusivamente `https://www.trix.de/en/products/minitrix/all-items`, importa la gama N a escala 1:160 y reutiliza el parser técnico del grupo Märklin/Trix para precio EUR, referencia, época, funciones digitales, imágenes y GTIN/EAN.

Anteriormente, el conector Trix procesaba `https://www.trix.de/en/sitemap.xml`
y las fichas `/en/products/details/article/<número>`. Reutiliza el parser técnico
del grupo Märklin, pero mantiene dominio, descubrimiento y categorías propios.
Importa Trix H0, Minitrix y Trix Express, precio recomendado EUR, escala, época,
tipo, descripciones, imágenes, GTIN y funciones digitales DCC, SX, SX2 y mfx.

## LGB Europa

El conector `sitemap.connector.lgb_en` acepta el sitemap solicitado en
`https://www.lgb.de/en/sitemap.xml` y normaliza las fichas inglesas al dominio
internacional `www.lgb.com`. Recupera precio EUR, referencia, descripción,
imágenes, GTIN y atributos de escala G, época, radio mínimo, decoder, sonido,
luces y funciones digitales. El archivado automático queda desactivado.


### Preiser Figuren Europa

- Descubrimiento principal: `https://www.preiserfiguren.de/sitemap.php`.
- El mapa HTML enlaza páginas de catálogo que contienen varias referencias; el conector crea una URL lógica independiente por artículo mediante `tl_article`.
- Extrae referencia, nombre, escala, línea/categoría, acabado, tipo de presentación e imágenes asociadas cuando la página permite vincularlas.
- La lista de precios es independiente de las páginas de catálogo. Si no hay una asociación inequívoca referencia-precio, `price_available=False` para conservar el precio manual de Odoo.
- Archivado automático desactivado porque el mapa combina novedades, entregas, archivos y páginas de catálogo.


### ROCO España

- Fuente principal: `https://www.roco.cc/res/`, respetando las reglas publicadas en `robots.txt`.
- Descubrimiento paginado desde `/res/productos.html`, con fichas españolas bajo `/res/productos/.../<referencia>-<slug>.html`.
- Importa referencia, nombre, categorías, descripciones, precio oficial EUR, imágenes, GTIN publicado y atributos ferroviarios (escala, época, sistema digital, sonido e iluminación).
- El archivado automático queda desactivado para evitar bajas erróneas ante filtros de disponibilidad o bloqueos temporales del catálogo.

### Fleischmann España

- Fuente principal: `https://www.fleischmann.de/fes/`.
- Descubrimiento paginado desde `/fes/productos.html`, con fichas españolas bajo `/fes/productos/.../<referencia>-<slug>.html`.
- Importa referencia, nombre, categorías, descripciones, precio oficial EUR, imágenes, GTIN publicado y atributos ferroviarios como escala, época, alimentación DC/DCC, sonido e iluminación.
- El catálogo publica filtros de disponibilidad y archivo; el archivado automático queda desactivado para evitar bajas erróneas si el catálogo cambia de filtro o bloquea temporalmente una página.


## PIKO Europa

La fuente **PIKO Europa** usa `https://www.piko-shop.de/sitemap_en.xml` y conserva
únicamente las fichas inglesas bajo `/en/artikel/`. Importa referencia, EAN/GTIN,
precio oficial EUR, descripciones, imágenes, categorías, escalas G/H0/TT/N, época,
alimentación AC/DC, interfaz digital, DCC/mfx/RailCom, sonido, iluminación y el resto
de especificaciones técnicas publicadas. El archivado automático permanece desactivado.


BRAWA Europa
------------
* Usa ``https://www.brawa.de/sitemap.xml`` anunciado en ``robots.txt`` y conserva
  exclusivamente fichas inglesas ``/en/products/.../<artículo>-<slug>``.
* Importa referencia, nombre, descripciones del modelo y del prototipo, imágenes,
  escala, época, alimentación AC/DC, sistema digital, sonido, iluminación, interfaz,
  radio mínimo, longitud y las referencias alternativas publicadas en la misma ficha.
* La web pública no ofrece un PVP individual inequívoco en cada ficha; por ello el
  conector no utiliza tarifas PDF ni sobrescribe precios manuales de Odoo.


## Hape España

La fuente **Hape España** usa `https://es.hape.com/sitemap.xml`. El conector
conserva únicamente fichas españolas cuya URL termina en la referencia Hape
(por ejemplo `-e0448`). Importa referencia, nombre, precio EUR vigente,
descripciones, categorías, imágenes, grupo de edad, efectos de aprendizaje,
número de piezas, dimensiones, peso, baterías y las demás especificaciones
publicadas. Los GTIN/EAN solo se conservan cuando la ficha los publica y superan
la validación estándar. El archivado automático permanece desactivado.


## Viessmann Modelltechnik Europa

La fuente usa `https://viessmann-modell.com/sitemap.xml` y conserva las fichas inglesas terminadas en referencia numérica. Importa productos de Viessmann, kibri y Vollmer con referencia, precio EUR, descripciones, imágenes, GTIN publicado, escala y atributos técnicos como DCC/MM, LED, CarMotion, eMotion y RailMotion. El archivado automático permanece desactivado.


REE Modèles Francia
-------------------
La fuente usa ``https://ree-modeles.com/robots.txt`` como punto de entrada y recorre de forma acotada únicamente ``/catalogue/``. Como una página de catálogo puede reunir varias referencias, el conector genera una URL virtual por artículo mediante ``ree_ref`` para crear un staging y un producto Odoo independientes. Importa referencia, nombre/livrea, escala H0/H0m/H0e/N, época, sistema analógico/DCC, sonido, AC de tres carriles, humo, decoder ESU, imágenes y GTIN cuando se publique. El fabricante no publica un PVP inequívoco en estas fichas, por lo que ``price_available`` queda desactivado y no se sobrescriben precios manuales. El archivado automático permanece desactivado.

## BEMO Modelleisenbahnen Europa

La fuente usa `https://www.bemo-modellbahn.de/wp-sitemap.xml` y recorre el índice WordPress para conservar únicamente fichas individuales bajo `/produkt/`. Importa referencia BEMO, precio recomendado EUR, descripción, detalles del modelo, imágenes, escala 0m/H0m/H0e/H0, época, radio mínimo, disponibilidad, entrega prevista y atributos como DCC, ESU, sonido, LED, AC/DC, Metal Collection, kit y tracción por cremallera. No archiva automáticamente productos porque el fabricante mantiene un archivo histórico separado y puede reintroducir referencias.



## Bachmann Europe UK (multimarca)

El conector recorre las categorías públicas de bachmann.co.uk y conserva fichas `/product/category/...`. Detecta la marca publicada (Bachmann Branchline, Graham Farish, Liliput, EFE Rail, Scenecraft, Woodland Scenics y otras marcas distribuidas), SKU, escala, época, disponibilidad, descripción, imágenes y características DCC/sonido. Los precios públicos están en GBP: no se convierten a EUR ni sobrescriben precios manuales.

## FALLER Europa (incluye POLA G)

La fuente usa `https://www.faller.de/en/sitemap_index.xml`, recorre sus sub-sitemaps ingleses y conserva las fichas individuales cuyo patrón contiene el identificador interno y el slug del producto. Importa referencia, nombre, precio oficial EUR, EAN/GTIN, imágenes, descripción, categoría, escala, época, dimensiones, dificultad, disponibilidad, fecha prevista, instrucciones, iluminación/electrónica y datos de modelos móviles o Car System. Detecta `POLA G` como marca independiente cuando la ficha pertenece a esa gama; el resto se asigna a `FALLER`. El archivado automático permanece desactivado para evitar bajas por cambios temporales del sitemap o disponibilidad.


### Aneste Datank España

El conector ``sitemap.connector.aneste_datank_es`` procesa el índice WordPress
``https://www.anestedatank.com/wp-sitemap.xml`` y conserva únicamente fichas
``/products/<referencia>-<slug>/``. Extrae referencia, nombre, descripción,
categorías, imágenes, escala ferroviaria, escala numérica, dimensiones, unidades
por envase y GTIN válidos cuando estén publicados. El sitio es un catálogo B2B
sin precios públicos, por lo que nunca sustituye el precio manual de Odoo.


## NOCH Alemania (19.0.1.48.0)

El conector ``sitemap.connector.noch_de`` procesa ``https://www.noch.de/sitemap.xml``
y conserva exclusivamente fichas individuales con el patrón ``/<slug>/<referencia>/``.
Extrae referencia, nombre, fabricante o marca publicada, precio EUR, descripción,
imágenes, GTIN/EAN validado, escalas, dimensiones, peso, disponibilidad y fecha
prevista. NOCH distribuye también marcas asociadas; el fabricante de JSON-LD o de
la ficha se conserva como marca, usando NOCH solo como valor por defecto. El
archivado automático queda desactivado.


## Dimensiones de producto (19.0.1.49.0)

El módulo depende de OCA `product_dimension`. Las dimensiones físicas publicadas por los conectores se normalizan a milímetros y se escriben en `product_length`, `product_width`, `product_height` y `dimensional_uom_id`. Se revisan NOCH, FALLER, Aneste Datank, NINCO, BRAWA, Electrotren, Jouef y la plataforma Hornby. Las dimensiones de embalaje permanecen como atributos informativos y no sustituyen las dimensiones del producto.



## 19.0.1.52.0 - Dimensiones físicas del embalaje

Las medidas exteriores y el peso del embalaje del fabricante dejan de crear
registros `product.packaging`, ya que ese modelo representa formatos comerciales
de venta o compra. El módulo incluido `tl_product_package_dimensions` añade en la
pestaña Inventario del producto campos propios para longitud, anchura, altura,
unidad dimensional, peso, unidad de peso y volumen calculado del embalaje.

Los conectores mantienen la distinción entre dimensiones del artículo
(`product_dimension`) y dimensiones de su embalaje. Una sincronización que no
publique medidas de caja no borra valores introducidos manualmente.


## 19.0.1.53.0 — separación de marcas y submarcas

Las plataformas multimarca se dividen en fuentes independientes, compartiendo parser base:

- Bachmann UK: una fuente por cada marca detectada.
- NOCH: NOCH, Rokuhan, Athearn, AMMO y PROXXON.
- FALLER: FALLER y POLA G.
- Viessmann Modelltechnik: Viessmann, Kibri y Vollmer.

El descubrimiento valida la marca antes de crear staging para impedir que una URL se importe desde dos fuentes.


## 19.0.1.55.0 - Compatibilidad UoM de Odoo 19

Odoo 19 eliminó el modelo `uom.category` y el campo `category_id` de `uom.uom`. El módulo específico de dimensiones de embalaje ya no declara campos Many2one hacia ese modelo ni dominios basados en categorías. La compatibilidad de unidades se valida mediante la jerarquía de unidades de Odoo 19 (`relative_uom_id` y `_has_common_reference`), usando metro como referencia para dimensiones y kilogramo para peso.


## 19.0.1.57.0

- Migra las restricciones SQL al API `models.Constraint` de Odoo 19.
- Incluye una utilidad de diagnóstico para detectar clases Odoo cuyo `_name` no sea texto.


## 19.0.1.60.0

- Las descripciones importadas se guardan en los campos OCA de
  `product_sale_description`: `description_sale_short` y
  `description_sale_long`.
- El campo core `description_ecommerce` se limpia y deja de utilizarse para
  evitar que algunas plantillas lo rendericen superpuesto a la imagen.
- `description_sale`, usado en presupuestos, recibe únicamente texto plano y
  nunca etiquetas HTML de la ficha de origen.


## 19.0.1.61.0 - Catalogo completo de Conor

El conector de Conor ya no considera exhaustivo el sitemap XML. Combina sus
entradas con los productos visibles en las categorias generales de PrestaShop,
consultadas con `resultsPerPage=99999`, y deduplica por ID de producto. Esto
evita omitir bicicletas nuevas o combinaciones que todavía no aparecen en el
sitemap publico.

## 19.0.1.62.0

- Conor Bikes: se añaden como fuentes permanentes del catálogo completo las categorías de e-bikes y accesorios con `resultsPerPage=99999`.
- El descubrimiento combina bicicletas, bicicletas eléctricas, accesorios, categoría general y sitemaps, deduplicando por ID maestro de producto PrestaShop.
