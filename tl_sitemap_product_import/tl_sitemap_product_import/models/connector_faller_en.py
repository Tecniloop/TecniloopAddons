import html
import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html
from odoo import models


class SitemapConnectorFallerEnBase(models.AbstractModel):
    """Conector del catálogo inglés de FALLER y POLA G."""

    _name = 'sitemap.connector.faller_en_base'
    _inherit = 'sitemap.import.service'
    _description = 'Conector FALLER Europa inglés'

    _BRAND_FILTER = False
    _HOST = 'faller.de'
    _LANG_PREFIX = '/en/'
    _PRODUCT_RE = re.compile(r'^/en/(?:[^/]+/)+\d+/[^/]+/?$', re.I)
    _SKU_RE = re.compile(r'(?<!\d)(\d{5,6}(?:[A-Z]{1,3})?)(?!\d)', re.I)
    _GTIN_RE = re.compile(r'\b(?:EAN|GTIN|Barcode)\s*:?[\s\u00a0]*(\d{8}|\d{12}|\d{13}|\d{14})\b', re.I)
    _PRICE_RE = re.compile(r'(?:€|EUR\s*)\s*(\d{1,5}(?:[.,]\d{2}))|(?P<after>\d{1,5}(?:[.,]\d{2}))\s*(?:€|EUR)\b', re.I)

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
        return urlunsplit(('https', 'www.faller.de', path.rstrip('/') or '/', '', ''))

    @classmethod
    def _is_product_url(cls, value):
        canonical = cls._canonical_url(value)
        if not canonical:
            return False
        path = urlsplit(canonical).path
        excluded = ('/en/downloads', '/en/news', '/en/service', '/en/contact', '/en/search')
        return bool(path.startswith(cls._LANG_PREFIX) and cls._PRODUCT_RE.match(path) and not path.startswith(excluded))

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
                if child_url and urlsplit(child_url).path.startswith('/en/'):
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
            raise ValueError('El sitemap inglés de FALLER no contiene fichas con el patrón esperado.')
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
            if value and value.casefold() not in {'home', 'en'} and value not in values:
                values.append(value)
        return values

    @classmethod
    def _label_values(cls, tree):
        labels = {}
        for row in tree.xpath('//table//tr | //dl/*[self::dt or self::dd] | //*[contains(@class,"product--properties") or contains(@class,"product-detail") ]//*[self::li or self::div]'):
            text = cls._clean(' '.join(row.xpath('.//text()')))
            if not text:
                continue
            if row.tag == 'tr':
                cells = [cls._clean(' '.join(cell.xpath('.//text()'))) for cell in row.xpath('./th|./td')]
                if len(cells) >= 2 and cells[0] and cells[1]:
                    labels.setdefault(cells[0].rstrip(':'), cells[1])
            elif row.tag == 'dt':
                nxt = row.getnext()
                if nxt is not None and nxt.tag == 'dd':
                    labels.setdefault(text.rstrip(':'), cls._clean(' '.join(nxt.xpath('.//text()'))))
            else:
                match = re.match(r'^([^:]{2,45}):\s*(.+)$', text)
                if match:
                    labels.setdefault(match.group(1).strip(), match.group(2).strip())
        return labels

    @classmethod
    def _value(cls, labels, *names):
        folded = {cls._clean(k).casefold(): v for k, v in labels.items()}
        for name in names:
            if name.casefold() in folded:
                return cls._clean(folded[name.casefold()])
        return False

    @classmethod
    def _price(cls, tree, product, text):
        offers = product.get('offers') if product else None
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if isinstance(offers, dict):
            currency = str(offers.get('priceCurrency') or '').upper()
            raw = offers.get('price') or offers.get('lowPrice')
            try:
                price = float(str(raw).replace(',', '.'))
                if price > 0 and currency == 'EUR':
                    return price
            except Exception:
                pass
        focused = cls._clean(' '.join(tree.xpath('//*[@itemprop="price"]/@content | //*[contains(@class,"price")]//text()')))
        match = cls._PRICE_RE.search(focused) or cls._PRICE_RE.search(text)
        if match:
            raw = match.group(1) or match.group('after')
            return float(raw.replace(',', '.'))
        return 0.0

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
        candidates.extend(tree.xpath('//meta[@property="og:image"]/@content | //main//img/@data-src | //main//img/@data-zoom-image | //main//img/@src | //main//a[contains(@href,"media")]/@href'))
        result = []
        for raw in candidates:
            if not raw:
                continue
            url = urljoin(page_url, str(raw))
            folded = url.casefold()
            if not url.startswith('http') or any(token in folded for token in ('logo', 'icon', 'sprite', 'payment', 'avatar')):
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
            raise ValueError('La URL de FALLER no corresponde a una ficha de producto reconocida.')

        products = self._json_ld_products(tree)
        product = products[0] if products else {}
        name = self._clean(product.get('name')) or self._clean(' '.join(tree.xpath('//h1[1]//text()'))) or self._clean(self._meta(tree, 'og:title'))
        text = self._clean(' '.join(tree.xpath('//main//text()')))
        labels = self._label_values(tree)

        sku_candidates = [product.get('sku'), product.get('mpn'), self._value(labels, 'Item number', 'Article number', 'Art. no.'), text]
        sku = False
        for candidate in sku_candidates:
            match = self._SKU_RE.search(self._clean(candidate))
            if match:
                sku = match.group(1).upper()
                break
        if not name or not sku:
            raise ValueError('La ficha FALLER no publica nombre o referencia reconocible.')

        brand = 'POLA G' if 'pola g' in (' '.join(self._breadcrumbs(tree)) + ' ' + name + ' ' + text).casefold() else 'FALLER'
        if self._BRAND_FILTER and brand != self._BRAND_FILTER:
            raise ValueError('La ficha pertenece a %s y no a %s.' % (brand, self._BRAND_FILTER))
        attrs = {'Marca': [brand], 'Referencia fabricante': [sku]}
        mapping = (
            ('Track gauge', 'Escala ferroviaria'), ('Dimensions', 'Dimensiones'),
            ('Epoch', 'Época'), ('Lighting/Electronics', 'Iluminación/Electrónica'),
            ('Construction instruction', 'Instrucciones de montaje'), ('Difficulty', 'Dificultad'),
            ('Item status', 'Estado del artículo'), ('Delivery date', 'Fecha de entrega'),
            ('Kategorie', 'Categoría publicada'), ('Category', 'Categoría publicada'),
        )
        for source_label, target in mapping:
            value = self._value(labels, source_label)
            if value:
                attrs[target] = [value]
        scale = self._value(labels, 'Track gauge')
        scale_map = {'H0': '1:87', 'HO': '1:87', 'N': '1:160', 'TT': '1:120', 'Z': '1:220', 'G': '1:22.5'}
        if scale and scale.upper() in scale_map:
            attrs['Escala'] = [scale_map[scale.upper()]]
        if re.search(r'\bmoveable model\s*:?\s*yes\b', text, re.I):
            attrs['Modelo móvil'] = ['Sí']
        if 'car system' in text.casefold():
            attrs['Sistema'] = ['FALLER Car System']
        if 'led' in text.casefold():
            attrs.setdefault('Iluminación', []).append('LED')

        description = self._clean(product.get('description')) if product else ''
        if not description:
            description = self._clean(self._meta(tree, 'description'))
        desc_blocks = []
        for heading in tree.xpath('//main//*[self::h2 or self::h3][contains(translate(normalize-space(.),"DESCRIPTION","description"),"description")]'):
            for sibling in heading.itersiblings():
                if sibling.tag in {'h2', 'h3'}:
                    break
                value = self._clean(' '.join(sibling.xpath('.//text()')))
                if value and value not in desc_blocks:
                    desc_blocks.append(value)
        if desc_blocks:
            description = '\n\n'.join(desc_blocks[:6])

        price = self._price(tree, product, text)
        images = self._images(tree, product, canonical)
        eans = []
        ean_candidates = []
        if product:
            ean_candidates.extend([product.get('gtin8'), product.get('gtin12'), product.get('gtin13'), product.get('gtin14')])
        ean_candidates.extend(self._GTIN_RE.findall(text))
        for raw in ean_candidates:
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
            'price': price,
            'price_available': bool(price),
            'currency': 'EUR',
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical,
            'style_code': sku,
            'color_code': False,
            'category_path': ' / '.join([brand] + breadcrumbs),
            'ean_variants': self._normalise_ean_variants(eans),
            'ean_complete': True,
        }


class SitemapConnectorFallerFaller(models.AbstractModel):
    _name = 'sitemap.connector.faller_faller'
    _inherit = 'sitemap.connector.faller_en_base'
    _description = 'Conector FALLER Europa'
    _BRAND_FILTER = 'FALLER'


class SitemapConnectorFallerPolaG(models.AbstractModel):
    _name = 'sitemap.connector.faller_pola_g'
    _inherit = 'sitemap.connector.faller_en_base'
    _description = 'Conector POLA G Europa'
    _BRAND_FILTER = 'POLA G'
