import html
import json
import re
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

from lxml import html as lxml_html

from odoo import models


class SitemapConnectorBrawaEn(models.AbstractModel):
    """Conector del catálogo internacional en inglés de BRAWA."""

    _name = 'sitemap.connector.brawa_en'
    _inherit = 'sitemap.import.service'
    _description = 'Conector BRAWA Europa (inglés)'

    _HOSTS = {'brawa.de', 'www.brawa.de'}
    _PRODUCT_RE = re.compile(
        r'^/en/products/(?:[^/]+/)+(?P<article>\d{4,6})-[^/?#]+/?$', re.I
    )
    _ITEM_RE = re.compile(r'\b(?:Item\s*no\.?|Best\.?-?Nr\.?)\s*:?[\s\xa0]*(\d{4,6})\b', re.I)
    _ERA_RE = re.compile(r'(?<!\w)(I|II|III|IV|V|VI)(?!\w)')
    _SCALE_RE = re.compile(r'(?<!\w)(H0|HO|N|TT|Z|0|IIm|G)(?!\w)', re.I)
    _GTIN_RE = re.compile(r'\b(?:EAN|GTIN)\s*:?[\s\xa0]*(\d{8}|\d{12}|\d{13}|\d{14})\b', re.I)

    @classmethod
    def _clean(cls, value):
        return re.sub(r'\s+', ' ', html.unescape(str(value or '')).replace('\xa0', ' ')).strip()

    @classmethod
    def _canonical_url(cls, value):
        parts = urlsplit(html.unescape(str(value or '')).strip())
        host = parts.netloc.casefold().removeprefix('www.')
        if host != 'brawa.de':
            return False
        path = re.sub(r'/+', '/', parts.path or '/')
        return urlunsplit(('https', 'www.brawa.de', path.rstrip('/'), '', ''))

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
            products.setdefault(canonical, {
                'url': canonical,
                'lastmod': item.get('lastmod') or False,
            })
            if limit and len(products) >= limit:
                break
        if not products:
            raise ValueError(
                'El sitemap de BRAWA no contiene fichas inglesas con el patrón '
                '/en/products/.../<artículo>-<slug> o su estructura ha cambiado.'
            )
        return list(products.values())[:limit] if limit else list(products.values())

    def get_image_map(self, source):
        return {}

    @classmethod
    def _json_ld_products(cls, tree):
        result = []
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
                    kind = item.get('@type')
                    if kind == 'Product' or isinstance(kind, list) and 'Product' in kind:
                        result.append(item)
                    stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
        return result

    @classmethod
    def _breadcrumbs(cls, tree):
        values = []
        for text in tree.xpath(
            '//*[contains(@class,"breadcrumb")]//a//text() | '
            '//*[contains(@class,"breadcrumb")]//*[self::span or self::li]//text()'
        ):
            value = cls._clean(text)
            if value and value.casefold() not in {'home', 'products'} and value not in values:
                values.append(value)
        return values

    @classmethod
    def _descriptions(cls, tree, product):
        short = cls._clean(product.get('description')) if product else ''
        blocks = []
        for xpath in (
            '//*[@itemprop="description"]',
            '//*[contains(@class,"product-detail") and contains(@class,"description")]',
            '//*[contains(@class,"model-details")]',
            '//*[contains(@class,"product-description")]',
            '//*[contains(@class,"original") and contains(@class,"info")]',
        ):
            for node in tree.xpath(xpath):
                text = cls._clean(' '.join(node.xpath('.//text()')))
                if len(text) > 30 and text not in blocks:
                    blocks.append(text)
        full = '\n\n'.join(blocks)
        return short or (blocks[0] if blocks else ''), full or short

    @classmethod
    def _images(cls, tree, product, page_url, article):
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
            '//a[contains(@class,"lightbox") or contains(@class,"fancybox")]/@href | '
            '//img[contains(@src,"/produkte/")]/@src | '
            '//img[contains(@data-src,"/produkte/")]/@data-src'
        ))
        result = []
        for value in candidates:
            if not value:
                continue
            absolute = urljoin(page_url, str(value))
            if absolute.startswith('http') and absolute not in result:
                result.append(absolute)
        # BRAWA publica una imagen principal estable por referencia de cabecera.
        fallback = f'https://www.brawa.de/fileadmin/user_upload/produkte/webp/mobil_700/{article}.webp'
        if fallback not in result:
            result.append(fallback)
        return result

    @classmethod
    def _attributes(cls, tree, name, breadcrumbs, page_text, item_numbers):
        attrs = {}
        context = ' '.join(breadcrumbs + [name, page_text])
        scale_match = cls._SCALE_RE.search(context)
        if scale_match:
            scale = scale_match.group(1).upper().replace('HO', 'H0')
            attrs['Escala ferroviaria'] = [scale]
            numeric = {'H0': '1:87', 'N': '1:160', 'TT': '1:120', 'Z': '1:220', '0': '1:45', 'IIM': '1:22,5', 'G': '1:22,5'}.get(scale)
            if numeric:
                attrs['Escala'] = [numeric]
        era = cls._ERA_RE.search(context)
        if era:
            attrs['Época'] = [era.group(1).upper()]
        if item_numbers:
            attrs['Referencias BRAWA'] = item_numbers
        tokens = (
            ('Direct current', 'Alimentación', 'DC'),
            ('Alternating current', 'Alimentación', 'AC'),
            ('Digital EXTRA', 'Sistema digital', 'Digital EXTRA'),
            ('Analogue BASIC+', 'Sistema', 'Analógico BASIC+'),
            ('PluX22', 'Interfaz digital', 'PluX22'),
            ('Next18', 'Interfaz digital', 'Next18'),
            ('DCC', 'Sistema digital', 'DCC'),
            ('integrated locomotive sound', 'Sonido', 'Integrado'),
            ('prepared for locomotive sound', 'Sonido', 'Preparado'),
            ('interior lighting', 'Iluminación', 'Interior'),
            ('LED', 'Iluminación', 'LED'),
        )
        folded = context.casefold()
        for token, label, value in tokens:
            if token.casefold() in folded:
                attrs.setdefault(label, [])
                if value not in attrs[label]:
                    attrs[label].append(value)
        for label, pattern in (
            ('Radio mínimo', r'(?:minimum radius|radius)\s*:?[\s\xa0]*(\d+)'),
            ('Longitud entre topes', r'(?:length over buffer|lüp)\s*:?[\s\xa0]*(\d+)'),
            ('Fecha prevista', r'Delivery date\s*:?[\s\xa0]*([^\n|]{2,30})'),
        ):
            match = re.search(pattern, page_text, re.I)
            if match:
                value = cls._clean(match.group(1))
                if label in {'Radio mínimo', 'Longitud entre topes'}:
                    value += ' mm'
                attrs[label] = [value]
        return attrs

    def fetch_preview(self, source, url):
        session = self._get_session(source)
        response = self._http_get(session, url, source)
        tree = lxml_html.fromstring(response.content)
        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical = self._canonical_url(canonical_values[0] if canonical_values else response.url)
        if not self._product_match(canonical):
            canonical = self._canonical_url(url)
        match = self._product_match(canonical)
        if not match:
            raise ValueError('La URL de BRAWA ya no corresponde a una ficha inglesa de producto.')

        products = self._json_ld_products(tree)
        product = products[0] if products else {}
        name = self._clean(product.get('name')) or self._clean(' '.join(tree.xpath('//h1//text()')))
        if not name:
            name = self._clean(self._meta(tree, 'og:title'))
        if not name:
            raise ValueError('La ficha BRAWA no publica un nombre reconocible.')

        page_text = self._clean(' '.join(tree.xpath('//body//text()')))
        article = match.group('article')
        item_numbers = []
        for value in self._ITEM_RE.findall(page_text):
            if value not in item_numbers:
                item_numbers.append(value)
        if article not in item_numbers:
            item_numbers.insert(0, article)

        short_description, full_description = self._descriptions(tree, product)
        breadcrumbs = self._breadcrumbs(tree) or ['BRAWA']
        attributes = self._attributes(tree, name, breadcrumbs, page_text, item_numbers)
        images = self._images(tree, product, canonical, article)

        ean_variants = []
        gtin_candidates = []
        for key in ('gtin13', 'gtin14', 'gtin12', 'gtin8', 'gtin', 'ean'):
            if product and product.get(key):
                gtin_candidates.append(product.get(key))
        gtin_candidates.extend(self._GTIN_RE.findall(page_text))
        for candidate in gtin_candidates:
            normal = self._normalise_gtin(candidate)
            if normal:
                ean_variants.append({
                    'ean': normal,
                    'sku': article,
                    'label': name,
                    'external_variant_id': article,
                })
        ean_variants = self._normalise_ean_variants(ean_variants)

        # BRAWA no muestra un PVP individual fiable en la ficha pública; no se usa la tarifa PDF.
        return {
            'name': name,
            'description': full_description or short_description,
            'short_description': short_description,
            'full_description': full_description,
            'attributes': attributes,
            'price': 0.0,
            'price_available': False,
            'currency': 'EUR',
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical,
            'style_code': article,
            'color_code': False,
            'category_path': ' / '.join(['BRAWA'] + breadcrumbs),
            'ean_variants': ean_variants,
            'ean_complete': True,
        }
