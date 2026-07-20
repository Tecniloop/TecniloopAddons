import html
import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html
from odoo import models


class SitemapConnectorAnesteDatankEs(models.AbstractModel):
    """Conector del catálogo público de Aneste Datank."""

    _name = 'sitemap.connector.aneste_datank_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Aneste Datank España'

    _HOST = 'anestedatank.com'
    _PRODUCT_RE = re.compile(r'^/(?:en/)?products/[^/]+/?$', re.I)
    _SKU_FROM_TITLE_RE = re.compile(r'^\s*([0-9A-Z][0-9A-Z+.-]{1,24})\s+(.+?)\s*$', re.I)
    _SCALE_RE = re.compile(r'(?<![A-Z0-9])(H0|HO|N|TT|Z|G)(?![A-Z0-9])', re.I)
    _GTIN_RE = re.compile(r'\b(?:EAN|GTIN|Barcode|Código de barras)\s*:?\s*(\d{8}|\d{12}|\d{13}|\d{14})\b', re.I)

    @classmethod
    def _clean(cls, value):
        return re.sub(r'\s+', ' ', html.unescape(str(value or '')).replace('\xa0', ' ')).strip()

    @classmethod
    def _canonical_url(cls, value):
        parts = urlsplit(html.unescape(str(value or '')).strip())
        host = parts.netloc.casefold().removeprefix('www.')
        if host != cls._HOST:
            return False
        path = re.sub(r'/+', '/', parts.path or '/')
        return urlunsplit(('https', 'www.anestedatank.com', path.rstrip('/') or '/', '', ''))

    @classmethod
    def _is_product_url(cls, value):
        canonical = cls._canonical_url(value)
        return bool(canonical and cls._PRODUCT_RE.match(urlsplit(canonical).path))

    def _read_sitemap(self, source, url, visited=None):
        visited = visited or set()
        canonical = self._canonical_url(url)
        if not canonical or canonical in visited:
            return []
        visited.add(canonical)
        response = self._http_get(self._get_session(source), canonical, source)
        root = etree.fromstring(response.content)
        local = etree.QName(root.tag).localname
        ns = {'sm': root.nsmap.get(None) or 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        if local == 'sitemapindex':
            result = []
            for child in root.xpath('//sm:sitemap/sm:loc/text()', namespaces=ns):
                child_url = self._canonical_url(child)
                if not child_url:
                    continue
                path = urlsplit(child_url).path.casefold()
                if 'products' in path or path.endswith('/wp-sitemap.xml'):
                    result.extend(self._read_sitemap(source, child_url, visited))
            return result
        result = []
        for node in root.xpath('//sm:url', namespaces=ns):
            loc = node.xpath('./sm:loc/text()', namespaces=ns)
            if not loc:
                continue
            lastmod = node.xpath('./sm:lastmod/text()', namespaces=ns)
            result.append({
                'url': self._canonical_url(loc[0]) or self._clean(loc[0]),
                'lastmod': self._parse_lastmod(lastmod[0]) if lastmod else False,
            })
        return result

    def get_product_entries(self, source, category_filter=None, limit=0):
        entries = self._read_sitemap(source, source.sitemap_index_url)
        needle = self._clean(category_filter).casefold()
        products = {}
        for item in entries:
            url = self._canonical_url(item.get('url'))
            if not self._is_product_url(url):
                continue
            if needle and needle not in url.casefold():
                continue
            products.setdefault(url, {'url': url, 'lastmod': item.get('lastmod') or False})
            if limit and len(products) >= limit:
                break
        if not products:
            raise ValueError('El sitemap de Aneste Datank no contiene fichas /products/ reconocibles.')
        return list(products.values())

    def get_image_map(self, source):
        return {}

    @staticmethod
    def _meta(tree, name):
        values = tree.xpath(f'//meta[@property={json.dumps(name)} or @name={json.dumps(name)}]/@content')
        return values[0].strip() if values else False

    @classmethod
    def _json_ld_products(cls, tree):
        products = []
        for raw in tree.xpath('//script[@type="application/ld+json"]/text()'):
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            stack = payload if isinstance(payload, list) else [payload]
            while stack:
                item = stack.pop()
                if isinstance(item, list):
                    stack.extend(item)
                elif isinstance(item, dict):
                    typ = item.get('@type')
                    if typ == 'Product' or (isinstance(typ, list) and 'Product' in typ):
                        products.append(item)
                    stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
        return products

    @classmethod
    def _breadcrumbs(cls, tree):
        values = []
        for raw in tree.xpath('//*[contains(@class,"breadcrumb")]//a//text() | //nav[contains(@aria-label,"readcrumb")]//a//text()'):
            value = cls._clean(raw)
            if value and value.casefold() not in {'inicio', 'home', 'catálogo', 'catalogue', 'productos', 'products'} and value not in values:
                values.append(value)
        return values

    @classmethod
    def _images(cls, tree, product, page_url):
        candidates = []
        image = product.get('image') if product else None
        if isinstance(image, list):
            candidates.extend(image)
        elif isinstance(image, dict):
            candidates.append(image.get('url') or image.get('contentUrl'))
        elif image:
            candidates.append(image)
        candidates.extend(tree.xpath('//meta[@property="og:image"]/@content | //main//img/@data-src | //main//img/@data-lazy-src | //main//img/@src | //article//img/@src'))
        result = []
        for raw in candidates:
            if not raw:
                continue
            url = urljoin(page_url, str(raw))
            folded = url.casefold()
            if not url.startswith('http') or any(token in folded for token in ('logo', 'icon', 'avatar', 'flag-', '/flags/')):
                continue
            if url not in result:
                result.append(url)
        return result

    def fetch_preview(self, source, url):
        response = self._http_get(self._get_session(source), url, source)
        tree = lxml_html.fromstring(response.content)
        canonicals = tree.xpath('//link[@rel="canonical"]/@href')
        canonical = self._canonical_url(canonicals[0] if canonicals else response.url) or self._canonical_url(url)
        if not self._is_product_url(canonical):
            raise ValueError('La URL no corresponde a una ficha de producto de Aneste Datank.')

        products = self._json_ld_products(tree)
        product = products[0] if products else {}
        title = self._clean(product.get('name')) or self._clean(' '.join(tree.xpath('//h1[1]//text()'))) or self._clean(self._meta(tree, 'og:title'))
        match = self._SKU_FROM_TITLE_RE.match(title)
        if not match:
            slug = urlsplit(canonical).path.rstrip('/').split('/')[-1]
            match = self._SKU_FROM_TITLE_RE.match(slug.replace('-', ' '))
        if not match:
            raise ValueError('La ficha de Aneste Datank no publica una referencia al inicio del nombre.')
        sku = match.group(1).upper().rstrip('-.')
        name = title

        description = self._clean(product.get('description')) if product else ''
        blocks = []
        for heading in tree.xpath('//main//*[self::h2 or self::h3][contains(translate(normalize-space(.),"DESCRIPCIÓN DEL PRODUCTO","descripción del producto"),"descripción")] | //article//*[self::h2 or self::h3]'):
            for sibling in heading.itersiblings():
                if sibling.tag in {'h1', 'h2', 'h3'}:
                    break
                value = self._clean(' '.join(sibling.xpath('.//text()')))
                if value and value not in blocks:
                    blocks.append(value)
        if blocks:
            description = '\n\n'.join(blocks[:6])
        if not description:
            description = self._clean(self._meta(tree, 'description'))

        page_text = self._clean(' '.join(tree.xpath('//main//text() | //article//text()')))
        attrs = {'Marca': ['Aneste Datank'], 'Referencia fabricante': [sku]}
        scale_match = self._SCALE_RE.search(' '.join([name, description, page_text]))
        if scale_match:
            gauge = scale_match.group(1).upper().replace('HO', 'H0')
            attrs['Escala ferroviaria'] = [gauge]
            scale_map = {'H0': '1:87', 'N': '1:160', 'TT': '1:120', 'Z': '1:220', 'G': '1:22.5'}
            if gauge in scale_map:
                attrs['Escala'] = [scale_map[gauge]]

        dimensions = []
        for pattern in (
            r'\b\d+(?:[.,]\d+)?\s*[x×]\s*\d+(?:[.,]\d+)?(?:\s*[x×]\s*\d+(?:[.,]\d+)?)?\s*mm\b',
            r'\b\d+(?:[.,]\d+)?\s*mm\s+de\s+altura\b',
            r'\b\d+(?:[.,]\d+)?\s*mm\b',
        ):
            dimensions.extend(re.findall(pattern, description, re.I))
        if dimensions:
            attrs['Dimensiones'] = list(dict.fromkeys(self._clean(v) for v in dimensions))[:5]
        quantity = re.search(r'\b(?:incluye|contiene|bolsa con|pack de)\s+(\d+)\s+(?:unidades?|piezas?)\b', description, re.I)
        if quantity:
            attrs['Unidades por envase'] = [quantity.group(1)]

        images = self._images(tree, product, canonical)
        eans = []
        candidates = []
        if product:
            candidates.extend([product.get('gtin8'), product.get('gtin12'), product.get('gtin13'), product.get('gtin14')])
        candidates.extend(self._GTIN_RE.findall(page_text))
        for raw in candidates:
            gtin = self._normalise_gtin(raw)
            if gtin:
                eans.append({'ean': gtin, 'sku': sku, 'label': name, 'external_variant_id': sku})

        breadcrumbs = self._breadcrumbs(tree)
        return {
            'name': name,
            'description': description,
            'short_description': description,
            'full_description': description,
            'attributes': attrs,
            'price': 0.0,
            'price_available': False,
            'currency': 'EUR',
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical,
            'style_code': sku,
            'color_code': False,
            'category_path': ' / '.join(['Aneste Datank'] + breadcrumbs),
            'ean_variants': self._normalise_ean_variants(eans),
            'ean_complete': True,
        }
