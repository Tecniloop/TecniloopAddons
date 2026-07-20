import html
import logging
import re
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorTrixEn(models.AbstractModel):
    """Conector para Trix H0 y Trix Express.

    Trix comparte la base técnica de catálogo del grupo Märklin, pero utiliza
    su propio dominio, familias de producto y escalas. Se hereda el parser de
    ficha de Märklin y se sustituyen descubrimiento, canonicalización y
    categorización para no mezclar dominios ni catálogos.
    """

    _name = 'sitemap.connector.trix_en'
    _inherit = 'sitemap.connector.maerklin_en'
    _description = 'Conector Trix Europa'

    _HOST = 'www.trix.de'
    _PRODUCT_RE = re.compile(
        r'^/en/products/details/article/(?P<code>\d{4,8})(?:/[^/?#]+)?/?$',
        re.IGNORECASE,
    )

    @classmethod
    def _canonical_url(cls, value):
        raw = html.unescape(str(value or '')).strip().replace('\\/', '/')
        if not raw:
            return False
        parts = urlsplit(raw)
        host = parts.netloc.casefold().removeprefix('www.')
        if host != 'trix.de':
            return False
        path = re.sub(r'/+', '/', parts.path or '/')
        if path != '/':
            path = path.rstrip('/')
        return urlunsplit((parts.scheme or 'https', cls._HOST, path, '', ''))

    def _candidate_sitemaps(self, source):
        candidates = []
        session = self._get_session(source)
        for candidate in (
            source.sitemap_index_url,
            'https://www.trix.de/robots.txt',
            'https://www.trix.de/en/robots.txt',
        ):
            if not candidate or candidate in candidates:
                continue
            try:
                response = session.get(
                    candidate,
                    timeout=source.request_timeout or 30,
                    allow_redirects=True,
                )
                if response.status_code >= 400:
                    continue
                candidates.extend(self._robots_sitemaps(response.text, response.url))
                payload = response.content.lstrip()
                if payload.startswith((b'<?xml', b'<urlset', b'<sitemapindex')) \
                        or payload[:2] == b'\x1f\x8b':
                    candidates.insert(0, response.url)
            except Exception as exc:
                _logger.info('Trix: no se pudo consultar %s: %s', candidate, exc)
        candidates.extend([
            'https://www.trix.de/en/sitemap.xml',
            'https://www.trix.de/sitemap.xml',
            'https://www.trix.de/sitemap_index.xml',
            'https://www.trix.de/sitemapindex.xml',
        ])
        return list(dict.fromkeys(candidates))

    _CATALOG_START_URLS = (
        'https://www.trix.de/en/products/trix-h0/all-items',
        'https://www.trix.de/en/products/trix-express/all-items',
    )
    _CATALOG_PATH_TOKENS = ('/trix-h0/', '/trix-express/')

    def _fallback_catalog_entries(self, source, limit=0):
        start_urls = list(self._CATALOG_START_URLS)
        queue = list(start_urls)
        visited = set()
        products = {}
        session = self._get_session(source)

        while queue and len(visited) < 650:
            page_url = queue.pop(0)
            if page_url in visited:
                continue
            visited.add(page_url)
            try:
                response = self._http_get(session, page_url, source)
                tree = lxml_html.fromstring(response.content)
            except Exception as exc:
                _logger.info('Trix: catálogo no accesible %s: %s', page_url, exc)
                continue
            for product_url in self._product_links_from_tree(tree, response.url):
                key = self._product_key(product_url)
                if key and key not in products:
                    products[key] = {'url': product_url, 'lastmod': False}
            if limit and len(products) >= limit:
                break
            for href in tree.xpath('//a[@href]/@href'):
                absolute = self._canonical_url(urljoin(response.url, href))
                if not absolute or self._product_match(absolute):
                    continue
                path = urlparse(absolute).path
                if not path.startswith('/en/products/'):
                    continue
                if any(token in path for token in self._CATALOG_PATH_TOKENS) \
                        and absolute not in visited and absolute not in queue:
                    queue.append(absolute)
        return list(products.values())


    def _collect_products(self, source, limit=0):
        entries = self._fallback_catalog_entries(source, limit=limit)
        if not entries:
            raise ValueError('No se pudieron descubrir productos de Trix H0/Express.')
        return entries, {}

    def fetch_preview(self, source, url):
        values = super().fetch_preview(source, url)
        line = (values.get('attributes', {}).get('Línea de producto') or [''])[0]
        if str(line).casefold() == 'minitrix':
            raise ValueError('El artículo pertenece a Minitrix y debe importarse desde esa fuente.')
        return values

    @classmethod
    def _detail_attributes(cls, tree, lines, name):
        attributes = super()._detail_attributes(tree, lines, name)
        page_text = ' '.join(lines)
        if re.search(r'\bMinitrix\b', page_text, re.IGNORECASE):
            attributes['Línea de producto'] = ['Minitrix']
            attributes.setdefault('Escala ferroviaria', ['N'])
            attributes.setdefault('Escala', ['1:160'])
        elif re.search(r'\bTrix\s+Express\b', page_text, re.IGNORECASE):
            attributes['Línea de producto'] = ['Trix Express']
        elif re.search(r'\bTrix\s+H0\b', page_text, re.IGNORECASE):
            attributes['Línea de producto'] = ['Trix H0']
        if re.search(r'\bSX2\b', page_text):
            attributes.setdefault('Sistema digital', [])
            if 'SX2' not in attributes['Sistema digital']:
                attributes['Sistema digital'].append('SX2')
        if re.search(r'(?<!\w)SX(?!\w)', page_text):
            attributes.setdefault('Sistema digital', [])
            if 'SX' not in attributes['Sistema digital']:
                attributes['Sistema digital'].append('SX')
        return attributes

    @classmethod
    def _category_path(cls, attributes, name):
        segments = []
        line = (attributes.get('Línea de producto') or [False])[0]
        if line:
            segments.append(line)
        gauge = (attributes.get('Escala ferroviaria') or [False])[0]
        if gauge and not line:
            segments.append(f'Escala {gauge}')
        kind = (attributes.get('Tipo de producto ferroviario') or [False])[0]
        segments.extend(cls._translated_kind(kind))
        return segments or ['Productos Trix']
