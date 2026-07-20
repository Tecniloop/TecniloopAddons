import re
from urllib.parse import urljoin, urlparse

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

    @staticmethod
    def _canonical_url(value):
        parsed = urlparse(str(value or '').strip())
        if parsed.netloc.lower() not in {'mtngshoes.com', 'www.mtngshoes.com'}:
            return False
        path = re.sub(r'/+', '/', parsed.path or '/')
        return f'https://www.mtngshoes.com{path.rstrip("/") or "/"}'

    @classmethod
    def _is_product_url(cls, value):
        canonical = cls._canonical_url(value)
        return bool(canonical and STYLE_COLOR_RE.search(urlparse(canonical).path))

    @classmethod
    def _is_catalog_url(cls, value):
        canonical = cls._canonical_url(value)
        if not canonical:
            return False
        path = urlparse(canonical).path
        return path.startswith('/es-ES/') and not cls._is_product_url(canonical) and not re.search(
            r'\.(?:pdf|jpe?g|png|gif|webp|svg|xml|json)$', path, re.IGNORECASE,
        )

    @classmethod
    def _product_key(cls, value):
        canonical = cls._canonical_url(value)
        match = STYLE_COLOR_RE.search(urlparse(canonical).path) if canonical else None
        return f'{match.group(1)}_{match.group(2)}' if match else False

    def get_product_entries(self, source, category_filter=None, limit=0):
        sitemap_entries = []
        try:
            sub_sitemaps = self._fetch_sitemap_index_locs(source, source.sitemap_index_url)
        except Exception:
            sub_sitemaps = []
        product_sitemaps = [s for s in sub_sitemaps if 'product' in s.lower()]
        if not product_sitemaps:
            product_sitemaps = [source.sitemap_index_url]
        for sitemap_url in product_sitemaps:
            try:
                sitemap_entries.extend(self._fetch_urlset(source, sitemap_url))
            except Exception:
                continue

        # Salesforce Commerce Cloud puede publicar fragmentos de sitemap no
        # sincronizados. Se fusiona además el catálogo español navegable.
        html_entries = self._discover_html_product_entries(
            source,
            start_urls=[
                'https://www.mtngshoes.com/es-ES/',
                'https://www.mtngshoes.com/es-ES/mujer/',
                'https://www.mtngshoes.com/es-ES/hombre/',
                'https://www.mtngshoes.com/es-ES/ninos/',
            ],
            is_product_url=self._is_product_url,
            is_category_url=self._is_catalog_url,
            canonicalize=self._canonical_url,
            max_pages=350,
        )
        return self._merge_discovery_entries(
            'Mustang',
            [('sitemap', sitemap_entries), ('catalogo_html', html_entries)],
            key_getter=self._product_key,
            category_filter=category_filter,
            limit=limit,
        )

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
