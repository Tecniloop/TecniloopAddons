import html
import json
import logging
import re
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorPikoEn(models.AbstractModel):
    """Conector del sitemap y catálogo internacional en inglés de PIKO."""

    _name = 'sitemap.connector.piko_en'
    _inherit = 'sitemap.import.service'
    _description = 'Conector PIKO Europa (inglés)'

    _HOSTS = {'piko-shop.de', 'www.piko-shop.de'}
    _PRODUCT_RE = re.compile(r'^/en/artikel/[^/?#]+-(?P<page_id>\d+)\.html/?$', re.IGNORECASE)
    _PRICE_RE = re.compile(r'(?P<price>\d{1,5}(?:[.\s]\d{3})*,\d{2})\s*€')
    _ITEM_RE = re.compile(r'(?:Item\s*(?:Number|number)|Artikelnummer)\s*:\s*([A-Z0-9._/-]+)', re.I)
    _EAN_RE = re.compile(r'\bEAN\s*:\s*(\d{8}|\d{12}|\d{13}|\d{14})\b', re.I)
    _ERA_RE = re.compile(r'(?<!\w)(I{1,3}(?:\s*[-/]\s*I{1,3})?|IV|V|VI)(?!\w)', re.I)
    _SCALE_RE = re.compile(r'(?<!\w)(H0|TT|N|G)(?:\s+Scale)?(?!\w)', re.I)

    @classmethod
    def _clean(cls, value):
        return re.sub(r'\s+', ' ', html.unescape(str(value or '')).replace('\xa0', ' ')).strip()

    @classmethod
    def _canonical_url(cls, value):
        parts = urlsplit(html.unescape(str(value or '')).strip())
        host = parts.netloc.casefold().removeprefix('www.')
        if host != 'piko-shop.de':
            return False
        path = re.sub(r'/+', '/', parts.path or '/')
        return urlunsplit(('https', 'www.piko-shop.de', path.rstrip('/'), '', ''))

    @classmethod
    def _product_match(cls, value):
        canonical = cls._canonical_url(value)
        return cls._PRODUCT_RE.match(urlparse(canonical).path) if canonical else False

    @staticmethod
    def _meta(tree, name):
        values = tree.xpath(
            f'//meta[@property={json.dumps(name)} or @name={json.dumps(name)}]/@content'
        )
        return values[0].strip() if values else False

    def get_product_entries(self, source, category_filter=None, limit=0):
        entries = self._fetch_urlset(source, source.sitemap_index_url)
        products = {}
        needle = str(category_filter or '').casefold()
        for item in entries:
            canonical = self._canonical_url(item.get('url'))
            if not self._product_match(canonical):
                continue
            if needle and needle not in canonical.casefold():
                continue
            products.setdefault(canonical, {'url': canonical, 'lastmod': item.get('lastmod') or False})
            if limit and len(products) >= limit:
                break
        if not products:
            raise ValueError(
                'El sitemap inglés de PIKO no contiene fichas con el patrón /en/artikel/*.html '
                'o su estructura ha cambiado.'
            )
        return list(products.values())[:limit] if limit else list(products.values())

    def get_image_map(self, source):
        return {}

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
                    item_type = item.get('@type')
                    if item_type == 'Product' or (isinstance(item_type, list) and 'Product' in item_type):
                        products.append(item)
                    stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
        return products

    @classmethod
    def _price(cls, tree, product):
        offers = product.get('offers') if product else None
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if isinstance(offers, dict):
            raw = offers.get('price') or offers.get('lowPrice')
            currency = str(offers.get('priceCurrency') or 'EUR').upper()
            try:
                price = float(str(raw).replace(',', '.'))
                if price > 0 and currency in {'EUR', '€'}:
                    return price, 'EUR'
            except Exception:
                pass
        for raw in tree.xpath(
            '//*[@itemprop="price"]/@content | //*[@data-price]/@data-price | '
            '//*[contains(@class,"price")]/@data-price'
        ):
            try:
                price = float(str(raw).replace(',', '.'))
                if price > 0:
                    return price, 'EUR'
            except Exception:
                continue
        text = cls._clean(' '.join(tree.xpath(
            '//*[contains(@class,"price") or contains(@class,"product-price")]//text()'
        )))
        match = cls._PRICE_RE.search(text)
        if match:
            return float(match.group('price').replace('.', '').replace(' ', '').replace(',', '.')), 'EUR'
        return 0.0, 'EUR'

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
        candidates.extend(tree.xpath(
            '//meta[@property="og:image"]/@content | '
            '//a[contains(@class,"fancybox") or contains(@class,"lightbox")]/@href | '
            '//*[contains(@class,"product") and contains(@class,"image")]//img/@src | '
            '//img[@data-zoom-image]/@data-zoom-image | //img[@data-large]/@data-large'
        ))
        result = []
        for value in candidates:
            if not value:
                continue
            absolute = urljoin(page_url, str(value))
            if absolute.startswith('http') and absolute not in result:
                result.append(absolute)
        return result

    @classmethod
    def _descriptions(cls, tree, product):
        short = cls._clean(product.get('description')) if product else ''
        blocks = []
        for xpath in (
            '//*[@itemprop="description"]',
            '//*[contains(@class,"artikelbeschreibung")]',
            '//*[contains(@class,"product-description")]',
            '//*[contains(@class,"description") and not(self::meta)]',
        ):
            for node in tree.xpath(xpath):
                text = cls._clean(' '.join(node.xpath('.//text()')))
                if len(text) > 20 and text not in blocks:
                    blocks.append(text)
        full = '\n\n'.join(blocks)
        return short or (blocks[0] if blocks else ''), full or short

    @classmethod
    def _breadcrumbs(cls, tree):
        values = []
        for text in tree.xpath(
            '//*[contains(@class,"breadcrumb")]//a//text() | '
            '//*[contains(@class,"breadcrumb")]//*[self::span or self::li]//text()'
        ):
            value = cls._clean(text)
            if value and value.casefold() not in {'home', 'piko webshop'} and value not in values:
                values.append(value)
        return values

    @classmethod
    def _feature_pairs(cls, tree):
        pairs = {}
        for row in tree.xpath('//table//tr'):
            label = cls._clean(' '.join(row.xpath('./th[1]//text() | ./td[1]//text()')))
            value = cls._clean(' '.join(row.xpath('./td[last()]//text()')))
            if label and value and label.casefold() != value.casefold():
                pairs.setdefault(label, [])
                if value not in pairs[label]:
                    pairs[label].append(value)
        for node in tree.xpath('//dl'):
            labels = node.xpath('./dt')
            values = node.xpath('./dd')
            for label_node, value_node in zip(labels, values):
                label = cls._clean(' '.join(label_node.xpath('.//text()')))
                value = cls._clean(' '.join(value_node.xpath('.//text()')))
                if label and value:
                    pairs.setdefault(label, [])
                    if value not in pairs[label]:
                        pairs[label].append(value)
        return pairs

    @classmethod
    def _attributes(cls, tree, name, breadcrumbs):
        attrs = cls._feature_pairs(tree)
        focused = cls._clean(' '.join(tree.xpath(
            '//*[contains(@class,"product") or contains(@class,"artikel") or @id="content"]//text()'
        )))
        feature_text = ' '.join(
            [label for label in attrs] +
            [value for values in attrs.values() for value in values]
        )
        context = ' '.join(breadcrumbs + [name, focused, feature_text])
        scale = cls._SCALE_RE.search(context)
        if scale:
            scale_code = scale.group(1).upper()
            attrs.setdefault('Escala ferroviaria', [scale_code])
            numeric = {'H0': '1:87', 'TT': '1:120', 'N': '1:160', 'G': '1:22,5'}.get(scale_code)
            if numeric:
                attrs.setdefault('Escala', [numeric])
        era = cls._ERA_RE.search(context)
        if era:
            attrs.setdefault('Época', [re.sub(r'\s+', '', era.group(1).upper())])
        token_map = (
            ('Gleichstrom', 'Alimentación', 'DC'), ('direct current', 'Alimentación', 'DC'),
            ('Wechselstrom', 'Alimentación', 'AC'), ('alternating current', 'Alimentación', 'AC'),
            ('DCC', 'Sistema digital', 'DCC'), ('mfx', 'Sistema digital', 'mfx'),
            ('RailCom', 'Sistema digital', 'RailCom'), ('PluX22', 'Interfaz digital', 'PluX22'),
            ('PluX16', 'Interfaz digital', 'PluX16'), ('Next18', 'Interfaz digital', 'Next18'),
            ('NEM 652', 'Interfaz digital', 'NEM 652'), ('sound', 'Sonido', 'Sí'),
            ('Sounddecoder', 'Sonido', 'Sí'), ('LED', 'Iluminación', 'LED'),
        )
        folded = context.casefold()
        for token, label, value in token_map:
            if token.casefold() in folded:
                attrs.setdefault(label, [])
                if value not in attrs[label]:
                    attrs[label].append(value)
        return attrs

    def fetch_preview(self, source, url):
        session = self._get_session(source)
        response = self._http_get(session, url, source)
        tree = lxml_html.fromstring(response.content)
        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical = self._canonical_url(canonical_values[0] if canonical_values else response.url)
        if not self._product_match(canonical):
            canonical = self._canonical_url(url)
        if not self._product_match(canonical):
            raise ValueError('La URL de PIKO ya no corresponde a una ficha bajo /en/artikel/.')

        products = self._json_ld_products(tree)
        product = products[0] if products else {}
        name = self._clean(product.get('name')) or self._clean(' '.join(tree.xpath('//h1//text()')))
        if not name:
            name = self._clean(self._meta(tree, 'og:title'))
        if not name:
            raise ValueError('La ficha PIKO no publica un nombre reconocible.')

        page_text = self._clean(' '.join(tree.xpath('//body//text()')))
        code = self._clean(product.get('sku')) if product else ''
        if not code:
            match = self._ITEM_RE.search(page_text)
            code = match.group(1) if match else ''
        if not code:
            raise ValueError('La ficha PIKO no publica un número de artículo reconocible.')

        price, currency = self._price(tree, product)
        short_description, full_description = self._descriptions(tree, product)
        images = self._images(tree, product, canonical)
        breadcrumbs = self._breadcrumbs(tree)
        if not breadcrumbs:
            breadcrumbs = ['PIKO']
        attributes = self._attributes(tree, name, breadcrumbs)

        ean_variants = []
        candidates = []
        for key in ('gtin13', 'gtin14', 'gtin12', 'gtin8', 'gtin', 'ean'):
            if product and product.get(key):
                candidates.append(product.get(key))
        candidates.extend(self._EAN_RE.findall(page_text))
        for candidate in candidates:
            normal = self._normalise_gtin(candidate)
            if normal:
                ean_variants.append({
                    'ean': normal,
                    'sku': code,
                    'label': name,
                    'external_variant_id': code,
                })
        ean_variants = self._normalise_ean_variants(ean_variants)

        return {
            'name': name,
            'description': full_description or short_description,
            'short_description': short_description,
            'full_description': full_description,
            'attributes': attributes,
            'price': price,
            'price_available': bool(price),
            'currency': currency or 'EUR',
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical,
            'style_code': code,
            'color_code': False,
            'category_path': ' / '.join(['PIKO'] + breadcrumbs),
            'ean_variants': ean_variants,
            'ean_complete': True,
        }
