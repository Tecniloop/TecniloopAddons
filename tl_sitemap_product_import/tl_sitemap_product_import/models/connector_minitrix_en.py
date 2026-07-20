from odoo import models

from .connector_maerklin_en import SitemapConnectorMaerklinEn


class SitemapConnectorMinitrixEn(models.AbstractModel):
    """Fuente independiente para la gama Minitrix de escala N (1:160)."""

    _name = 'sitemap.connector.minitrix_en'
    _inherit = 'sitemap.connector.trix_en'
    _description = 'Conector Minitrix Europa'

    _CATALOG_START_URLS = (
        'https://www.trix.de/en/products/minitrix/all-items',
    )
    _CATALOG_PATH_TOKENS = ('/minitrix/',)

    def _collect_products(self, source, limit=0):
        entries = self._fallback_catalog_entries(source, limit=limit)
        if not entries:
            raise ValueError('No se pudieron descubrir productos de Minitrix.')
        return entries, {}

    def fetch_preview(self, source, url):
        # Saltamos la validación de exclusión de la clase Trix y reutilizamos
        # directamente el parser común heredado de Märklin.
        values = SitemapConnectorMaerklinEn.fetch_preview(self, source, url)
        line = (values.get('attributes', {}).get('Línea de producto') or [''])[0]
        if str(line).casefold() != 'minitrix':
            raise ValueError('El artículo no pertenece a la gama Minitrix.')
        values['category_path'] = values.get('category_path') or 'Minitrix'
        return values
