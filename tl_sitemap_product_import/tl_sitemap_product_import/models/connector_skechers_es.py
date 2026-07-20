import re

from odoo import models

# ".../111_LTGY.html" -> estilo=111, color=LTGY ; ".../SK7.html" -> estilo=SK7, sin color
STYLE_COLOR_RE = re.compile(r'/([A-Za-z0-9\.\-%]+?)(?:_([A-Z0-9]+))?\.html?$')


class SitemapConnectorSkechersEs(models.AbstractModel):
    """Conector para skechers.es (Salesforce Commerce Cloud).

    Estructura real comprobada en el sitemap índice:
    - Un único sub-sitemap de productos: sitemap_0-product.xml
    - Un único sub-sitemap de imágenes: sitemap_1-image.xml
    - URL de producto: .../<segmentos de categoría>/<nombre-producto>/<estilo>[_<color>].html
      (el nombre del producto y el código son DOS segmentos finales distintos)
    """
    _name = 'sitemap.connector.skechers_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Skechers España'

    def get_product_entries(self, source, category_filter=None, limit=0):
        sub_sitemaps = self._fetch_sitemap_index_locs(source, source.sitemap_index_url)
        product_sitemap = next((s for s in sub_sitemaps if 'product' in s.lower()), None)
        if not product_sitemap:
            return []
        entries = []
        for entry in self._fetch_urlset(source, product_sitemap):
            if category_filter and category_filter.lower() not in entry['url'].lower():
                continue
            entries.append(entry)
            if limit and len(entries) >= limit:
                break
        return entries

    def get_image_map(self, source):
        sub_sitemaps = self._fetch_sitemap_index_locs(source, source.sitemap_index_url)
        image_sitemap = next((s for s in sub_sitemaps if 'image' in s.lower()), None)
        if not image_sitemap:
            return {}
        return self._fetch_image_urlset(source, image_sitemap)

    def fetch_preview(self, source, url):
        data = self._fetch_og_meta(source, url)
        canonical = data['canonical_url']
        data['style_code'], data['color_code'] = self.parse_style_color(canonical)
        data['category_path'] = '/'.join(self.parse_category_path(canonical))
        return data

    @staticmethod
    def parse_style_color(url):
        from urllib.parse import urlparse
        match = STYLE_COLOR_RE.search(urlparse(url).path)
        if not match:
            return False, False
        return match.group(1) or False, match.group(2) or False

    @staticmethod
    def parse_category_path(url):
        from urllib.parse import urlparse
        segments = [s for s in urlparse(url).path.split('/') if s]
        # Los dos últimos segmentos son "nombre-del-producto" y "codigo.html".
        category_segments = segments[:-2] if len(segments) > 2 else []
        return [seg.replace('-', ' ').strip().title() for seg in category_segments]
