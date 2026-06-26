TL BC3 Product
==============

Importa conceptos de catálogo BC3/FIEBDC como productos Odoo 19.

Características principales:

* Usa ``res.brand`` del módulo OCA ``brand`` para representar fabricantes como marcas.
* Añade ``brand_id`` a ``product.template`` mediante ``res.brand.mixin``.
* Crea categorías de sitio web empezando por una categoría raíz con el nombre del fabricante/marca.
* Crea subcategorías de eCommerce a partir de la estructura de capítulos BC3.
* Importa imágenes referenciadas por ``~G`` y por ``~F`` como registros ``product.image`` de eCommerce.
* No crea ``product.document`` para imágenes adicionales.
