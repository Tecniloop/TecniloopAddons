import html
import logging
import re
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorLgbEn(models.AbstractModel):
    """Conector para el catálogo internacional LGB de escala G.

    La marca publica enlaces tanto bajo lgb.de como bajo lgb.com. El conector
    acepta ambos, pero normaliza las fichas al dominio internacional lgb.com,
    que es donde se sirve actualmente el catálogo inglés.
    """

    _name = 'sitemap.connector.lgb_en'
    _inherit = 'sitemap.connector.maerklin_en'
    _description = 'Conector LGB Europa'

    _HOST = 'www.lgb.com'
    _PRODUCT_RE = re.compile(
        r'^/(?:en/)?products/details/article/(?P<code>\d+)(?:/[^/?#]+)?/?$',
        re.IGNORECASE,
    )

    @classmethod
    def _canonical_url(cls, value):
        raw = html.unescape(str(value or '')).strip().replace('\\/', '/')
        if not raw:
            return False
        parts = urlsplit(raw)
        host = parts.netloc.casefold().removeprefix('www.')
        if host not in {'lgb.de', 'lgb.com'}:
            return False
        path = re.sub(r'/+', '/', parts.path or '/')
        if path.startswith('/en/products/'):
            path = path[3:]
        if path != '/':
            path = path.rstrip('/')
        return urlunsplit((parts.scheme or 'https', cls._HOST, path, '', ''))

    def _candidate_sitemaps(self, source):
        candidates = []
        session = self._get_session(source)
        for candidate in (
            source.sitemap_index_url,
            'https://www.lgb.de/robots.txt',
            'https://www.lgb.de/en/robots.txt',
            'https://www.lgb.com/robots.txt',
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
                _logger.info('LGB: no se pudo consultar %s: %s', candidate, exc)
        candidates.extend([
            'https://www.lgb.de/en/sitemap.xml',
            'https://www.lgb.de/sitemap.xml',
            'https://www.lgb.com/sitemap.xml',
            'https://www.lgb.com/sitemap_index.xml',
        ])
        return list(dict.fromkeys(candidates))

    def _fallback_catalog_entries(self, source, limit=0):
        start_urls = [
            'https://www.lgb.com/products/products',
            'https://www.lgb.com/products/narrow-gauge/all-items',
            'https://www.lgb.com/products/standard-gauge/all-items',
            'https://www.lgb.com/products/accessories-track/all-items',
            'https://www.lgb.com/new-items',
            'https://www.lgb.com/service/product-database',
        ]
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
                _logger.info('LGB: catálogo no accesible %s: %s', page_url, exc)
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
                if not (path.startswith('/products/') or path.startswith('/service/')):
                    continue
                if any(token in path for token in (
                    '/narrow-gauge/', '/standard-gauge/', '/accessories-track/',
                    '/products', '/product-search', '/product-database',
                )) and absolute not in visited and absolute not in queue:
                    queue.append(absolute)
        return list(products.values())

    @classmethod
    def _gauge_attributes(cls, raw_value):
        attributes = super()._gauge_attributes(raw_value)
        value = cls._normalise_text(raw_value)
        if value and ('lgb' in value.casefold() or re.search(r'\bG\b', value)):
            attributes['Escala ferroviaria'] = ['G']
            attributes.setdefault('Escala', ['1:22.5'])
        return attributes

    @classmethod
    def _detail_attributes(cls, tree, lines, name):
        attributes = super()._detail_attributes(tree, lines, name)
        page_text = ' '.join(lines)
        attributes['Marca'] = ['LGB']
        attributes.setdefault('Escala ferroviaria', ['G'])
        attributes.setdefault('Escala', ['1:22.5'])

        radius = re.search(
            r'(?:minimum|min\.?)[^\d]{0,30}radius[^\d]{0,15}(\d{3,4})\s*mm',
            page_text,
            re.IGNORECASE,
        )
        if radius:
            attributes['Radio mínimo'] = [f'{radius.group(1)} mm']
        if re.search(r'\bMZS\b', page_text):
            attributes.setdefault('Sistema digital', [])
            if 'MZS' not in attributes['Sistema digital']:
                attributes['Sistema digital'].append('MZS')
        if re.search(r'\b(mfx|DCC)\b', page_text, re.IGNORECASE):
            attributes.setdefault('Decoder digital', [])
            for value in re.findall(r'\b(mfx|DCC)\b', page_text, re.IGNORECASE):
                normalized = 'mfx' if value.casefold() == 'mfx' else 'DCC'
                if normalized not in attributes['Decoder digital']:
                    attributes['Decoder digital'].append(normalized)
        return attributes

    @classmethod
    def _category_path(cls, attributes, name):
        kind = (attributes.get('Tipo de producto ferroviario') or [False])[0]
        segments = ['Escala G']
        segments.extend(cls._translated_kind(kind))
        return segments or ['Productos LGB']
