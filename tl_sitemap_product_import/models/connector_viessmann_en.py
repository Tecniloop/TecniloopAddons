import html
import json
import re
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

from lxml import html as lxml_html
from odoo import models


class SitemapConnectorViessmannEnBase(models.AbstractModel):
    _name = 'sitemap.connector.viessmann_en_base'
    _inherit = 'sitemap.import.service'
    _description = 'Base común de conectores Viessmann Modelltechnik'

    _BRAND_FILTER = False
    _PRODUCT_RE = re.compile(r'^/en/(?:[^/?#]+/)+(?P<sku>\d{3,6})/?$', re.I)
    _PRICE_RE = re.compile(r'(?P<price>\d{1,5}(?:[.\s]\d{3})*[.,]\d{2})\s*€')
    _SKU_RE = re.compile(r'(?:Article\s*(?:no\.?|number)|Item\s*(?:no\.?|number)|Art\.?\s*No\.?)\s*:?\s*(\d{3,6})', re.I)
    _SCALE_RE = re.compile(r'(?<!\w)(H0|H0e|H0m|TT|N|Z|0|G|IIm)(?!\w)', re.I)

    @classmethod
    def _clean(cls, value):
        return re.sub(r'\s+', ' ', html.unescape(str(value or '')).replace('\xa0', ' ')).strip()

    @classmethod
    def _canonical_url(cls, value):
        parts = urlsplit(html.unescape(str(value or '')).strip())
        host = parts.netloc.casefold().removeprefix('www.')
        if host != 'viessmann-modell.com':
            return False
        path = re.sub(r'/+', '/', parts.path or '/')
        return urlunsplit(('https', 'viessmann-modell.com', path.rstrip('/'), '', ''))

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
                    kind = item.get('@type')
                    if kind == 'Product' or (isinstance(kind, list) and 'Product' in kind):
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
        entries = list(products.values())
        if self._BRAND_FILTER:
            filtered = []
            session = self._get_session(source)
            for item in entries:
                try:
                    response = self._http_get(session, item['url'], source)
                    tree = lxml_html.fromstring(response.content)
                    name = self._clean(' '.join(tree.xpath('//h1//text()')))
                    text = self._clean(' '.join(tree.xpath('//body//text()')))
                    context = (name + ' ' + text + ' ' + item['url']).casefold()
                    brand = 'Viessmann'
                    for candidate, canonical in (('kibri', 'Kibri'), ('vollmer', 'Vollmer'), ('viessmann', 'Viessmann')):
                        if candidate in context:
                            brand = canonical
                            break
                    if brand == self._BRAND_FILTER:
                        filtered.append(item)
                        if limit and len(filtered) >= limit:
                            break
                except Exception:
                    continue
            entries = filtered
        elif limit:
            entries = entries[:limit]
        if not entries:
            raise ValueError('El sitemap de Viessmann no contiene fichas para la marca configurada.')
        return entries

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
                value = float(str(raw).replace(',', '.'))
                if value > 0 and currency in {'EUR', '€'}:
                    return value, 'EUR'
            except Exception:
                pass
        for raw in tree.xpath('//*[@itemprop="price"]/@content | //meta[@property="product:price:amount"]/@content | //*[@data-price]/@data-price'):
            try:
                value = float(str(raw).replace(',', '.'))
                if value > 0:
                    return value, 'EUR'
            except Exception:
                continue
        text = cls._clean(' '.join(tree.xpath('//*[contains(@class,"price") or contains(@class,"product-detail-price")]//text()')))
        matches = cls._PRICE_RE.findall(text)
        if matches:
            raw = matches[0].replace('.', '').replace(' ', '').replace(',', '.')
            return float(raw), 'EUR'
        return 0.0, 'EUR'

    @classmethod
    def _breadcrumbs(cls, tree):
        values = []
        for text in tree.xpath('//*[contains(@class,"breadcrumb")]//a//text() | //*[contains(@class,"breadcrumb")]//*[self::span or self::li]//text()'):
            value = cls._clean(text)
            if value and value.casefold() not in {'home', 'product range', 'assortment'} and value not in values:
                values.append(value)
        return values

    @classmethod
    def _pairs(cls, tree):
        result = {}
        for row in tree.xpath('//table//tr'):
            label = cls._clean(' '.join(row.xpath('./th[1]//text() | ./td[1]//text()')))
            value = cls._clean(' '.join(row.xpath('./td[last()]//text()')))
            if label and value and label.casefold() != value.casefold():
                result.setdefault(label, [])
                if value not in result[label]:
                    result[label].append(value)
        for dl in tree.xpath('//dl'):
            for dt, dd in zip(dl.xpath('./dt'), dl.xpath('./dd')):
                label = cls._clean(' '.join(dt.xpath('.//text()')))
                value = cls._clean(' '.join(dd.xpath('.//text()')))
                if label and value:
                    result.setdefault(label, [])
                    if value not in result[label]:
                        result[label].append(value)
        return result

    @classmethod
    def _images(cls, tree, product, page_url):
        values = []
        image = product.get('image') if product else None
        if isinstance(image, list): values.extend(image)
        elif isinstance(image, dict): values.append(image.get('url') or image.get('contentUrl'))
        elif image: values.append(image)
        values.extend(tree.xpath('//meta[@property="og:image"]/@content | //a[contains(@class,"gallery") or contains(@class,"lightbox")]/@href | //*[contains(@class,"product-detail-media")]//img/@src | //img/@data-zoom-image | //img/@data-src'))
        result = []
        for value in values:
            if not value: continue
            absolute = urljoin(page_url, str(value))
            lowered = absolute.casefold()
            if absolute.startswith('http') and not any(x in lowered for x in ('logo', 'icon', 'flag')) and absolute not in result:
                result.append(absolute)
        return result

    def fetch_preview(self, source, url):
        response = self._http_get(self._get_session(source), url, source)
        tree = lxml_html.fromstring(response.content)
        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical = self._canonical_url(canonical_values[0] if canonical_values else response.url)
        if not self._product_match(canonical): canonical = self._canonical_url(url)
        match = self._product_match(canonical)
        if not match: raise ValueError('La URL de Viessmann ya no corresponde a una ficha inglesa válida.')
        products = self._json_ld_products(tree)
        product = products[0] if products else {}
        name = self._clean(product.get('name')) or self._clean(' '.join(tree.xpath('//h1//text()'))) or self._clean(self._meta(tree, 'og:title'))
        if not name: raise ValueError('La ficha Viessmann no publica un nombre reconocible.')
        text = self._clean(' '.join(tree.xpath('//body//text()')))
        code = self._clean(product.get('sku')) if product else ''
        if not code:
            sku_match = self._SKU_RE.search(text)
            code = sku_match.group(1) if sku_match else match.group('sku')
        price, currency = self._price(tree, product)
        short = self._clean(product.get('description')) if product else ''
        blocks = []
        for node in tree.xpath('//*[@itemprop="description"] | //*[contains(@class,"product-detail-description") or contains(@class,"product-description")]'):
            value = self._clean(' '.join(node.xpath('.//text()')))
            if len(value) > 20 and value not in blocks: blocks.append(value)
        full = '\n\n'.join(blocks) or short
        breadcrumbs = self._breadcrumbs(tree)
        attrs = self._pairs(tree)
        context = ' '.join([name, text] + breadcrumbs)
        scale = self._SCALE_RE.search(context)
        if scale:
            scale_code = scale.group(1)
            attrs.setdefault('Escala ferroviaria', [scale_code])
            numeric = {'H0':'1:87','H0e':'1:87','H0m':'1:87','TT':'1:120','N':'1:160','Z':'1:220','0':'1:45','G':'1:22,5','IIm':'1:22,5'}.get(scale_code)
            if numeric: attrs.setdefault('Escala', [numeric])
        folded = context.casefold()
        brand = 'Viessmann'
        for candidate in ('kibri', 'vollmer', 'viessmann'):
            if candidate in folded or candidate in canonical.casefold():
                brand = candidate.title()
                break
        if self._BRAND_FILTER and brand != self._BRAND_FILTER:
            raise ValueError('La ficha pertenece a %s y no a %s.' % (brand, self._BRAND_FILTER))
        attrs.setdefault('Marca', [brand])
        for token, label, value in (
            ('dcc', 'Sistema digital', 'DCC'), ('märklin motorola', 'Sistema digital', 'MM'),
            ('multiprotocol', 'Sistema digital', 'Multiprotocolo'), ('led', 'Iluminación', 'LED'),
            ('carmotion', 'Línea de producto', 'CarMotion'), ('emotion', 'Línea de producto', 'eMotion'),
            ('railmotion', 'Línea de producto', 'RailMotion'), ('sound', 'Sonido', 'Sí'),
        ):
            if token in folded:
                attrs.setdefault(label, [])
                if value not in attrs[label]: attrs[label].append(value)
        images = self._images(tree, product, canonical)
        eans = []
        for key in ('gtin13','gtin14','gtin12','gtin8','gtin','ean'):
            if product and product.get(key):
                normal = self._normalise_gtin(product.get(key))
                if normal: eans.append({'ean':normal,'sku':code,'label':name,'external_variant_id':code})
        return {
            'name': name, 'description': full or short, 'short_description': short or (blocks[0] if blocks else ''),
            'full_description': full, 'attributes': attrs, 'price': price, 'price_available': bool(price),
            'currency': currency or 'EUR', 'main_image_url': images[0] if images else False, 'image_urls': images,
            'canonical_url': canonical, 'style_code': code, 'color_code': False,
            'category_path': ' / '.join([brand] + breadcrumbs),
            'ean_variants': self._normalise_ean_variants(eans), 'ean_complete': True,
        }


class SitemapConnectorViessmannViessmann(models.AbstractModel):
    _name = 'sitemap.connector.viessmann_viessmann'
    _inherit = 'sitemap.connector.viessmann_en_base'
    _description = 'Conector Viessmann Europa'
    _BRAND_FILTER = 'Viessmann'


class SitemapConnectorViessmannKibri(models.AbstractModel):
    _name = 'sitemap.connector.viessmann_kibri'
    _inherit = 'sitemap.connector.viessmann_en_base'
    _description = 'Conector Kibri Europa'
    _BRAND_FILTER = 'Kibri'


class SitemapConnectorViessmannVollmer(models.AbstractModel):
    _name = 'sitemap.connector.viessmann_vollmer'
    _inherit = 'sitemap.connector.viessmann_en_base'
    _description = 'Conector Vollmer Europa'
    _BRAND_FILTER = 'Vollmer'
