import html
import json
import re
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

from lxml import html as lxml_html

from odoo import models


class SitemapConnectorHapeEs(models.AbstractModel):
    """Conector de la tienda española de juguetes Hape."""

    _name = 'sitemap.connector.hape_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Hape España'

    _PRODUCT_RE = re.compile(r'^/(?!.*(?:/|^)(?:juguetes|edad|colecciones)/?$)[^/?#]+-(?P<sku>[A-Z]\d{4,6})/?$', re.I)
    _SKU_RE = re.compile(r'\b(?:Número de artículo|Número de producto|Article number|SKU)\s*:?\s*([A-Z]\d{4,6})\b', re.I)
    _PRICE_RE = re.compile(r'(?P<price>\d{1,4}(?:[.\s]\d{3})*,\d{2})\s*€')

    @classmethod
    def _clean(cls, value):
        return re.sub(r'\s+', ' ', html.unescape(str(value or '')).replace('\xa0', ' ')).strip()

    @classmethod
    def _canonical_url(cls, value):
        parts = urlsplit(html.unescape(str(value or '')).strip())
        host = parts.netloc.casefold().removeprefix('www.')
        if host != 'es.hape.com':
            return False
        path = re.sub(r'/+', '/', parts.path or '/')
        return urlunsplit(('https', 'es.hape.com', path.rstrip('/'), '', ''))

    @classmethod
    def _product_match(cls, value):
        canonical = cls._canonical_url(value)
        return cls._PRODUCT_RE.match(urlparse(canonical).path) if canonical else False

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
                    item_type = item.get('@type')
                    if item_type == 'Product' or (isinstance(item_type, list) and 'Product' in item_type):
                        products.append(item)
                    stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
        return products

    def get_product_entries(self, source, category_filter=None, limit=0):
        entries = self._fetch_urlset(source, source.sitemap_index_url)
        products = {}
        needle = self._clean(category_filter).casefold()
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
                'El sitemap de Hape España no contiene fichas con referencia al final de la URL '
                '(por ejemplo -e0448) o su estructura ha cambiado.'
            )
        return list(products.values())[:limit] if limit else list(products.values())

    def get_image_map(self, source):
        return {}

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
        for raw in tree.xpath('//*[@itemprop="price"]/@content | //meta[@property="product:price:amount"]/@content'):
            try:
                price = float(str(raw).replace(',', '.'))
                if price > 0:
                    return price, 'EUR'
            except Exception:
                continue
        focused = cls._clean(' '.join(tree.xpath(
            '//main//*[contains(@class,"product") or @itemprop="offers" or contains(@class,"price")]//text()'
        )))
        match = cls._PRICE_RE.search(focused)
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
            '//*[@data-gallery-role="gallery-placeholder"]//img/@src | '
            '//*[contains(@class,"product") and contains(@class,"media")]//img/@src | '
            '//img[@data-zoom-image]/@data-zoom-image | //img/@data-src'
        ))
        result = []
        for value in candidates:
            if not value:
                continue
            absolute = urljoin(page_url, str(value))
            lowered = absolute.casefold()
            if absolute.startswith('http') and not any(x in lowered for x in ('logo', 'icon', 'flag')) and absolute not in result:
                result.append(absolute)
        return result

    @classmethod
    def _breadcrumbs(cls, tree):
        values = []
        for text in tree.xpath(
            '//*[contains(@class,"breadcrumb")]//a//text() | '
            '//*[contains(@class,"breadcrumb")]//*[self::span or self::li]//text()'
        ):
            value = cls._clean(text)
            if value and value.casefold() not in {'inicio', 'home', 'hape'} and value not in values:
                values.append(value)
        return values

    @classmethod
    def _description_blocks(cls, tree, product):
        short = cls._clean(product.get('description')) if product else ''
        if not short:
            short = cls._clean(' '.join(tree.xpath(
                '//*[contains(@class,"product") and contains(@class,"subtitle")]//text() | '
                '//*[@itemprop="description"]//text()'
            )))
        blocks = []
        for xpath in (
            '//*[@itemprop="description"]',
            '//*[contains(@class,"product") and contains(@class,"description")]',
            '//*[contains(@class,"description") and not(contains(@class,"short"))]',
            '//*[self::section or self::div][.//*[self::h2 or self::h3][contains(translate(normalize-space(.),"DESCRIPCIÓNARACTERÍSTICASCONSEJOS","descripcionaracteristicasconsejos"),"descripción") or contains(translate(normalize-space(.),"CARACTERÍSTICAS","características"),"características")]]',
        ):
            for node in tree.xpath(xpath):
                text = cls._clean(' '.join(node.xpath('.//text()')))
                if 20 < len(text) < 8000 and text not in blocks:
                    blocks.append(text)
        full = '\n\n'.join(blocks)
        return short or (blocks[0] if blocks else ''), full or short

    @classmethod
    def _specifications(cls, tree):
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
        # Magento/Shopware specification layouts frequently use adjacent labels and values.
        for node in tree.xpath('//*[contains(@class,"product-detail-properties") or contains(@class,"additional-attributes") or contains(@class,"specification")]'):
            texts = [cls._clean(t) for t in node.xpath('.//*[self::dt or self::dd or self::th or self::td]//text()')]
            texts = [t for t in texts if t]
            for i in range(0, len(texts) - 1, 2):
                pairs.setdefault(texts[i], [])
                if texts[i + 1] not in pairs[texts[i]]:
                    pairs[texts[i]].append(texts[i + 1])
        return pairs

    @classmethod
    def _attributes(cls, tree, breadcrumbs):
        attrs = cls._specifications(tree)
        page_text = cls._clean(' '.join(tree.xpath('//main//text() | //*[@id="maincontent"]//text()')))
        age = re.search(r'(?:Grupo de edad|Edad recomendada)\s*:?\s*((?:Desde|A partir de)\s+\d+\s+(?:meses|años)|\d+\s*[-–]\s*\d+\s*(?:Y|años))', page_text, re.I)
        if age:
            attrs.setdefault('Grupo de edad', [cls._clean(age.group(1))])
        learning = []
        for text in tree.xpath(
            '//a[contains(@href,"aprend") or contains(@href,"learning") or contains(@href,"efect")]/text() | '
            '//*[contains(@class,"learning") or contains(@class,"skill")]//text()'
        ):
            value = cls._clean(text)
            if value and 2 < len(value) < 80 and value not in learning:
                learning.append(value)
        if learning:
            attrs.setdefault('Efectos de aprendizaje', learning)
        if breadcrumbs:
            attrs.setdefault('Ruta Hape', breadcrumbs)
        return attrs

    def fetch_preview(self, source, url):
        session = self._get_session(source)
        response = self._http_get(session, url, source)
        tree = lxml_html.fromstring(response.content)
        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical = self._canonical_url(canonical_values[0] if canonical_values else response.url)
        match = self._product_match(canonical) or self._product_match(url)
        if not match:
            raise ValueError('La URL de Hape ya no corresponde a una ficha con referencia al final.')
        if not self._product_match(canonical):
            canonical = self._canonical_url(url)

        products = self._json_ld_products(tree)
        product = products[0] if products else {}
        name = self._clean(product.get('name')) if product else ''
        if not name:
            name = self._clean(' '.join(tree.xpath('//h1//text()')))
        if not name:
            name = self._clean(self._meta(tree, 'og:title'))
        if not name:
            raise ValueError('La ficha Hape no publica un nombre reconocible.')

        page_text = self._clean(' '.join(tree.xpath('//body//text()')))
        code = self._clean(product.get('sku')) if product else ''
        if not code:
            code_match = self._SKU_RE.search(page_text)
            code = code_match.group(1).upper() if code_match else match.group('sku').upper()
        if not re.fullmatch(r'[A-Z]\d{4,6}', code or '', re.I):
            code = match.group('sku').upper()

        price, currency = self._price(tree, product)
        short_description, full_description = self._description_blocks(tree, product)
        images = self._images(tree, product, canonical)
        breadcrumbs = self._breadcrumbs(tree)
        attributes = self._attributes(tree, breadcrumbs)

        ean_variants = []
        candidates = []
        for key in ('gtin13', 'gtin14', 'gtin12', 'gtin8', 'gtin', 'ean'):
            if product and product.get(key):
                candidates.append(product.get(key))
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

        category = ['Hape'] + (breadcrumbs or ['Juguetes'])
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
            'category_path': ' / '.join(category),
            'ean_variants': ean_variants,
            'ean_complete': True,
        }
