import json
import logging
import re
from html import unescape
from urllib.parse import urljoin, urlparse

from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorAutentiShoesEs(models.AbstractModel):
    """Conector para autentishoes.com (WooCommerce + Yoast)."""

    _name = 'sitemap.connector.autentishoes_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Autenti Shoes España'

    _PRODUCT_PATH_RE = re.compile(r'^/producto/[^/]+/?$', re.IGNORECASE)

    @classmethod
    def _is_product_url(cls, url):
        parsed = urlparse(str(url or ''))
        host = parsed.netloc.lower().split(':', 1)[0]
        return (
            host in {'autentishoes.com', 'www.autentishoes.com'}
            and bool(cls._PRODUCT_PATH_RE.match(parsed.path or ''))
        )

    def get_product_entries(self, source, category_filter=None, limit=0):
        try:
            children = self._fetch_sitemap_index_locs(source, source.sitemap_index_url)
        except Exception as exc:
            _logger.warning('Autenti Shoes: no se pudo leer el índice sitemap: %s', exc)
            children = []

        product_maps = [url for url in children if 'product-sitemap' in url.lower()]
        if not product_maps:
            product_maps = [
                urljoin(source.sitemap_index_url, '/product-sitemap.xml'),
            ]

        entries = []
        for sitemap_url in product_maps:
            try:
                entries.extend(self._fetch_urlset(source, sitemap_url))
            except Exception as exc:
                _logger.warning(
                    'Autenti Shoes: se omite el sitemap de productos %s: %s',
                    sitemap_url, exc,
                )

        needle = str(category_filter or '').strip().casefold()
        result = []
        seen = set()
        for entry in entries:
            url = str((entry or {}).get('url') or '').strip()
            if not self._is_product_url(url):
                continue
            canonical = url.split('#', 1)[0].split('?', 1)[0].rstrip('/') + '/'
            if needle and needle not in canonical.casefold():
                continue
            if canonical in seen:
                continue
            seen.add(canonical)
            result.append({'url': canonical, 'lastmod': entry.get('lastmod') or False})
            if limit and len(result) >= limit:
                break
        return result

    def get_image_map(self, source):
        return {}

    @staticmethod
    def _clean(value):
        if value is None or isinstance(value, (dict, list)):
            return ''
        return re.sub(r'\s+', ' ', unescape(str(value))).strip()

    @classmethod
    def _walk_json(cls, value):
        if isinstance(value, dict):
            yield value
            for nested in value.values():
                if isinstance(nested, (dict, list)):
                    yield from cls._walk_json(nested)
        elif isinstance(value, list):
            for item in value:
                yield from cls._walk_json(item)

    @classmethod
    def _product_json_ld(cls, tree):
        for raw in tree.xpath('//script[@type="application/ld+json"]/text()'):
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            for node in cls._walk_json(payload):
                node_type = node.get('@type')
                types = node_type if isinstance(node_type, list) else [node_type]
                if any(str(item).casefold() == 'product' for item in types if item):
                    return node
        return {}

    @classmethod
    def _images(cls, product, tree, base_url):
        values = []
        raw_images = product.get('image') if isinstance(product, dict) else []
        if not isinstance(raw_images, list):
            raw_images = [raw_images]
        for item in raw_images:
            if isinstance(item, dict):
                item = item.get('url') or item.get('contentUrl')
            if item:
                values.append(urljoin(base_url, str(item)))
        values.extend(tree.xpath(
            '//div[contains(@class,"woocommerce-product-gallery")]//a[@href]/@href | '
            '//div[contains(@class,"woocommerce-product-gallery")]//img/@data-large_image | '
            '//div[contains(@class,"woocommerce-product-gallery")]//img/@src'
        ))
        result = []
        for value in values:
            value = urljoin(base_url, str(value).strip())
            if value and value not in result:
                result.append(value)
        return result

    @classmethod
    def _variations(cls, tree):
        variants = []
        for raw in tree.xpath('//*[@data-product_variations]/@data-product_variations'):
            try:
                payload = json.loads(unescape(raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(payload, list):
                continue
            for item in payload:
                if not isinstance(item, dict):
                    continue
                attrs = item.get('attributes') or {}
                labels = []
                if isinstance(attrs, dict):
                    for key, value in attrs.items():
                        value = cls._clean(value)
                        if not value:
                            continue
                        label = re.sub(r'^attribute_(?:pa_)?', '', str(key), flags=re.I)
                        label = label.replace('_', ' ').replace('-', ' ').strip().title()
                        labels.append(f'{label}: {value}')
                sku = cls._clean(item.get('sku'))
                ean = (
                    item.get('gtin') or item.get('ean') or item.get('barcode')
                    or item.get('global_unique_id')
                )
                variants.append({
                    'ean': ean,
                    'sku': sku,
                    'label': ' / '.join(labels) or sku,
                    'source_variant_id': item.get('variation_id'),
                    'available': bool(item.get('is_in_stock', True)),
                })
        return variants

    @classmethod
    def _category_path(cls, product, tree):
        values = []
        category = product.get('category') if isinstance(product, dict) else False
        if isinstance(category, list):
            values.extend(cls._clean(item) for item in category)
        elif category:
            values.append(cls._clean(category))
        if not values:
            values.extend(
                cls._clean(value)
                for value in tree.xpath(
                    '//nav[contains(@class,"woocommerce-breadcrumb")]//a/text() | '
                    '//span[contains(@class,"posted_in")]//a/text()'
                )
            )
        ignored = {'inicio', 'home', 'tienda', 'shop', 'producto', 'productos'}
        result = []
        for value in values:
            if value and value.casefold() not in ignored and value not in result:
                result.append(value)
        return '/'.join(result)

    def fetch_preview(self, source, url):
        session = self._get_session(source)
        response = self._http_get(session, url, source)
        tree = lxml_html.fromstring(response.content)
        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical_url = urljoin(response.url, canonical_values[0]) if canonical_values else response.url
        if not self._is_product_url(canonical_url):
            raise ValueError('La URL ya no corresponde a una ficha de producto de Autenti Shoes.')

        product = self._product_json_ld(tree)
        name = self._clean(product.get('name')) if product else ''
        if not name:
            name = self._clean(' '.join(tree.xpath('//h1[1]//text()')))

        description = self._clean(product.get('description')) if product else ''
        if not description:
            description = self._clean(' '.join(tree.xpath(
                '//div[contains(@class,"woocommerce-product-details__short-description")]//text()'
            )))

        offers = product.get('offers') if isinstance(product, dict) else {}
        if isinstance(offers, list):
            offers = next((item for item in offers if isinstance(item, dict)), {})
        price_raw = offers.get('price') or offers.get('lowPrice') if isinstance(offers, dict) else False
        currency = offers.get('priceCurrency') if isinstance(offers, dict) else 'EUR'
        try:
            price = float(str(price_raw or '0').replace('.', '').replace(',', '.')) if ',' in str(price_raw or '') else float(price_raw or 0)
        except (TypeError, ValueError):
            price = 0.0

        sku = self._clean(product.get('sku')) if product else ''
        if not sku:
            sku = self._clean(' '.join(tree.xpath('//span[contains(@class,"sku")]/text()')))

        eans = self._variations(tree)
        for field in ('gtin', 'gtin8', 'gtin12', 'gtin13', 'gtin14', 'ean', 'barcode'):
            value = product.get(field) if isinstance(product, dict) else False
            if value:
                eans.append({'ean': value, 'sku': sku, 'label': name})

        images = self._images(product, tree, canonical_url)
        color_values = [
            self._clean(value)
            for value in tree.xpath('//select[contains(@name,"attribute_pa_color") or contains(@name,"attribute_color")]/option[@value!=""]/text()')
        ]
        size_values = [
            self._clean(value)
            for value in tree.xpath('//select[contains(@name,"attribute_pa_talla") or contains(@name,"attribute_talla")]/option[@value!=""]/text()')
        ]
        attributes = {}
        if color_values:
            attributes['Color'] = list(dict.fromkeys(v for v in color_values if v))
        if size_values:
            attributes['Talla'] = list(dict.fromkeys(v for v in size_values if v))

        return {
            'name': name or canonical_url,
            'description': description,
            'price': price,
            'currency': currency or 'EUR',
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical_url,
            'category_path': self._category_path(product, tree),
            'style_code': sku or urlparse(canonical_url).path.rstrip('/').split('/')[-1].upper(),
            'color_code': False,
            'attributes': attributes,
            'ean_variants': self._normalise_ean_variants(eans),
            'ean_complete': True,
        }
