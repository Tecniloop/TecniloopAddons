import re
from urllib.parse import urlparse

from odoo import models

# ".../free-beige-84847_61499.html" -> estilo=84847, color=61499
# Confirmado con URLs reales: free-negro-84837_61789.html, free-blanco-84806_61087.html,
# free-gris-84801_60567.html (el nº mostrado en el título de la ficha es el de color).
STYLE_COLOR_RE = re.compile(r'-(\d+)_(\d+)\.html?$')


class SitemapConnectorMtngEs(models.AbstractModel):
    """Conector para mtngshoes.com (también Salesforce Commerce Cloud, pero con una
    estructura de sitemap distinta a la de Skechers -de ahí que viva en su propio
    conector en vez de reutilizar parámetros genéricos-.

    Estructura real comprobada en el sitemap índice (adjuntado por el usuario):
    - NUEVE sub-sitemaps de productos: sitemap_0-product.xml .. sitemap_8-product.xml
      -> hay que leerlos y combinarlos TODOS, no solo el primero.
    - NUEVE sub-sitemaps de imágenes: sitemap_9-image.xml .. sitemap_17-image.xml
      -> mismo caso.
    - Todas las URLs llevan un prefijo de idioma, p. ej. /es-ES/.
    - URL de producto (confirmada con ejemplos reales), p. ej.:
      /es-ES/hombre/calzado/zapatillas/free/free-beige-84847_61499.html
      -> aquí el nombre del producto y los códigos van en UN SOLO segmento final
      (a diferencia de Skechers, que los separa en dos), por lo que la categoría se
      obtiene quitando el primer segmento (idioma) y el último (producto), no solo
      un nº fijo de segmentos finales.
    """
    _name = 'sitemap.connector.mtng_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Mustang Shoes España'

    def get_product_entries(self, source, category_filter=None, limit=0):
        sub_sitemaps = self._fetch_sitemap_index_locs(source, source.sitemap_index_url)
        product_sitemaps = [s for s in sub_sitemaps if 'product' in s.lower()]
        entries, seen = [], set()
        for sitemap_url in product_sitemaps:
            for entry in self._fetch_urlset(source, sitemap_url):
                if entry['url'] in seen:
                    continue
                if category_filter and category_filter.lower() not in entry['url'].lower():
                    continue
                seen.add(entry['url'])
                entries.append(entry)
                if limit and len(entries) >= limit:
                    return entries
        return entries

    def get_image_map(self, source):
        sub_sitemaps = self._fetch_sitemap_index_locs(source, source.sitemap_index_url)
        image_sitemaps = [s for s in sub_sitemaps if 'image' in s.lower()]
        image_map = {}
        for sitemap_url in image_sitemaps:
            for url, images in self._fetch_image_urlset(source, sitemap_url).items():
                image_map.setdefault(url, []).extend(images)
        return image_map

    def fetch_preview(self, source, url):
        data = self._fetch_og_meta(source, url)
        canonical = data['canonical_url']
        data['style_code'], data['color_code'] = self.parse_style_color(canonical)
        data['category_path'] = '/'.join(self.parse_category_path(canonical))
        return data

    @staticmethod
    def parse_style_color(url):
        match = STYLE_COLOR_RE.search(urlparse(url).path)
        if not match:
            return False, False
        return match.group(1) or False, match.group(2) or False

    @staticmethod
    def parse_category_path(url):
        segments = [s for s in urlparse(url).path.split('/') if s]
        # segments[0] es el prefijo de idioma (es-ES); el último es el producto en sí.
        if len(segments) <= 2:
            return []
        category_segments = segments[1:-1]
        return [seg.replace('-', ' ').strip().title() for seg in category_segments]
