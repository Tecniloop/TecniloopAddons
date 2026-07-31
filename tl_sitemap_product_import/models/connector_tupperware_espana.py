from odoo import models


class SitemapConnectorTupperwareEspana(models.AbstractModel):
    """Conector para la tienda Shopify oficial de Tupperware España.

    La tienda española publica los productos, colecciones y recetas en la raíz
    del dominio (``/products``, ``/collections`` y ``/blogs``), a diferencia de
    tupperware.com, donde el conector existente fuerza el escaparate ``/es``.

    Se reutiliza el parser completo de Tupperware: catálogo Shopify, variantes,
    imágenes, colecciones, textos HTML visibles y sincronización de recetas.
    """

    _name = 'sitemap.connector.tupperware_espana'
    _inherit = 'sitemap.connector.tupperware_com'
    _description = 'Conector Tupperware España'

    # El español es el idioma principal del dominio, por lo que no se debe
    # insertar /es delante de las URLs descubiertas.
    _SPANISH_PREFIX = ''
