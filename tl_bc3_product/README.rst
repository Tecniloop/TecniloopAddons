TL BC3 Product
==============

Importa catálogos FIEBDC/BC3 como productos Odoo 19.

Características principales:

* Importación desde ficheros BC3 ya parseados por ``tl_bc3_base``.
* Maestro de fabricantes con URL BC3/ZIP del catálogo.
* Importación por lotes para catálogos grandes, procesable manualmente o por cron.
* Compatibilidad con OCA ``brand``: el fabricante se gestiona como ``res.brand`` y se escribe ``brand_id`` solo si el campo existe en producto.
* Creación de categorías de sitio web empezando por la marca/fabricante y subcategorías por capítulos BC3.
* Imágenes ``~G`` / ``~F`` como medios ecommerce ``product.image``; no se crean documentos para imágenes.
* Medios relacionados desde ZIP, URL base del BC3 o carpeta de servidor.
