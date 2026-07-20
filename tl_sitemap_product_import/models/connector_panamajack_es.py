import json
import re
from html import unescape
from urllib.parse import urljoin, urlparse

from lxml import html as lxml_html

from odoo import models


class SitemapConnectorPanamajackEs(models.AbstractModel):
    """Conector Shopify para el catálogo español de Panama Jack."""

    _name = 'sitemap.connector.panamajack_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Panama Jack España'

    def _is_default_locale(self, url):
        path = urlparse(url).path
        return not path.startswith('/en/')

    def get_product_entries(self, source, category_filter=None, limit=0):
        sub_sitemaps = self._fetch_sitemap_index_locs(source, source.sitemap_index_url)
        product_sitemaps = [
            sitemap_url
            for sitemap_url in sub_sitemaps
            if 'product' in sitemap_url.lower() and self._is_default_locale(sitemap_url)
        ]
        entries, seen = [], set()
        for sitemap_url in product_sitemaps:
            for entry in self._fetch_urlset(source, sitemap_url):
                if entry['url'] in seen:
                    continue
                if category_filter and category_filter.lower() not in entry['url'].lower():
                    continue
                seen.add(entry['url'])
                entries.append(entry)
                if limit and len(entries) >= limit:
                    return entries
        return entries

    def get_image_map(self, source):
        return {}

    @staticmethod
    def _clean_text(value):
        if not value:
            return ''
        if isinstance(value, (dict, list)):
            return ''
        return re.sub(r'\s+', ' ', unescape(str(value))).strip()

    @classmethod
    def _strip_html(cls, value):
        if not value:
            return ''
        try:
            return cls._clean_text(lxml_html.fromstring(f'<div>{value}</div>').text_content())
        except (TypeError, ValueError):
            return cls._clean_text(value)

    @classmethod
    def _walk_json(cls, value):
        if isinstance(value, dict):
            yield value
            graph = value.get('@graph')
            if isinstance(graph, list):
                for item in graph:
                    yield from cls._walk_json(item)
            for nested in value.values():
                if isinstance(nested, (dict, list)) and nested is not graph:
                    yield from cls._walk_json(nested)
        elif isinstance(value, list):
            for item in value:
                yield from cls._walk_json(item)

    @classmethod
    def _product_json_ld(cls, tree):
        for raw_value in tree.xpath('//script[@type="application/ld+json"]/text()'):
            raw_value = raw_value.strip()
            if not raw_value:
                continue
            try:
                payload = json.loads(raw_value)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            for node in cls._walk_json(payload):
                node_type = node.get('@type')
                types = node_type if isinstance(node_type, list) else [node_type]
                if any(str(item).lower() == 'product' for item in types if item):
                    return node
        return {}

    @staticmethod
    def _absolute_image(value, base_url):
        if isinstance(value, dict):
            value = value.get('url') or value.get('contentUrl')
        if not value:
            return False
        value = str(value).strip()
        if value.startswith('//'):
            return 'https:' + value
        return urljoin(base_url, value)

    @classmethod
    def _json_ld_images(cls, node, base_url):
        raw_images = node.get('image') or []
        if not isinstance(raw_images, list):
            raw_images = [raw_images]
        images = []
        for raw_image in raw_images:
            image_url = cls._absolute_image(raw_image, base_url)
            if image_url and image_url not in images:
                images.append(image_url)
        return images

    def _fetch_shopify_product(self, source, canonical_url):
        """Use Shopify's product JSON endpoint when available.

        This endpoint is more reliable than theme-specific meta tags and exposes the
        product title, prices and complete image gallery. Failures intentionally fall
        back to the rendered HTML because stores may disable either endpoint.
        """
        session = self._get_session(source)
        base_url = canonical_url.split('?', 1)[0].rstrip('/')
        for suffix in ('.js', '.json'):
            try:
                response = self._http_get(session, base_url + suffix, source)
                payload = response.json()
            except Exception:  # noqa: BLE001 - fallback is expected for disabled endpoints
                continue
            product = payload.get('product') if isinstance(payload, dict) else None
            if not isinstance(product, dict) and isinstance(payload, dict):
                product = payload
            if isinstance(product, dict) and (product.get('title') or product.get('name')):
                return product
        return {}

    @classmethod
    def _shopify_images(cls, product, base_url):
        images = []
        raw_images = product.get('images') or []
        if not isinstance(raw_images, list):
            raw_images = [raw_images]
        featured = product.get('featured_image') or product.get('featuredImage')
        if featured:
            raw_images.insert(0, featured)
        for raw_image in raw_images:
            if isinstance(raw_image, dict):
                raw_image = raw_image.get('src') or raw_image.get('url')
            image_url = cls._absolute_image(raw_image, base_url)
            if image_url and image_url not in images:
                images.append(image_url)
        return images

    @classmethod
    def _shopify_price(cls, product):
        values = []
        variants = product.get('variants') or []
        for variant in variants if isinstance(variants, list) else []:
            if not isinstance(variant, dict):
                continue
            raw_price = variant.get('price')
            if raw_price in (None, ''):
                continue
            try:
                number = float(str(raw_price).replace(',', '.'))
                # The .js endpoint normally provides integer cents; JSON-LD/other
                # Shopify endpoints normally provide decimal currency units.
                if isinstance(raw_price, int) or (str(raw_price).isdigit() and number >= 1000):
                    number /= 100.0
                if number > 0:
                    values.append(number)
            except (TypeError, ValueError):
                continue
        direct = product.get('price')
        if direct not in (None, ''):
            try:
                number = float(str(direct).replace(',', '.'))
                if isinstance(direct, int) or (str(direct).isdigit() and number >= 1000):
                    number /= 100.0
                if number > 0:
                    values.append(number)
            except (TypeError, ValueError):
                pass
        return min(values) if values else 0.0

    @staticmethod
    def _dom_images(tree, base_url):
        candidates = tree.xpath(
            '//main//img/@src | //main//img/@data-src | //main//img/@data-original | '
            '//img[contains(@class,"product")]/@src | '
            '//img[contains(@class,"product")]/@data-src'
        )
        images = []
        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate or candidate.startswith('data:'):
                continue
            if candidate.startswith('//'):
                candidate = 'https:' + candidate
            else:
                candidate = urljoin(base_url, candidate)
            candidate = re.sub(r'([?&])width=\d+', '', candidate).rstrip('?&')
            if candidate not in images:
                images.append(candidate)
        return images

    def fetch_preview(self, source, url):
        session = self._get_session(source)
        response = self._http_get(session, url, source)
        tree = lxml_html.fromstring(response.content)

        def meta(prop):
            values = tree.xpath(
                f'//meta[@property="{prop}"]/@content | //meta[@name="{prop}"]/@content'
            )
            return values[0].strip() if values and values[0].strip() else False

        canonical_els = tree.xpath('//link[@rel="canonical"]/@href')
        canonical_url = canonical_els[0].strip() if canonical_els else url
        canonical_url = urljoin(url, canonical_url)

        product_json = self._fetch_shopify_product(source, canonical_url)
        product_ld = self._product_json_ld(tree)

        h1_values = [self._clean_text(value) for value in tree.xpath('//h1//text()')]
        h1_title = self._clean_text(' '.join(value for value in h1_values if value))
        title_values = tree.xpath('//title/text()')
        html_title = self._clean_text(title_values[0].split('|')[0]) if title_values else ''
        title = (
            self._clean_text(product_json.get('title') or product_json.get('name'))
            or self._clean_text(product_ld.get('name'))
            or self._clean_text(meta('og:title'))
            or h1_title
            or html_title
        )
        if not title or title.lower().startswith(('http://', 'https://')):
            raise ValueError('No se pudo extraer el nombre real de la ficha de Panama Jack.')

        description = (
            self._strip_html(product_json.get('body_html') or product_json.get('description'))
            or self._strip_html(product_ld.get('description'))
            or self._clean_text(meta('og:description') or meta('description'))
        )

        images = self._shopify_images(product_json, canonical_url)
        for image_url in self._json_ld_images(product_ld, canonical_url):
            if image_url not in images:
                images.append(image_url)
        og_image = self._absolute_image(meta('og:image') or meta('twitter:image'), canonical_url)
        if og_image and og_image not in images:
            images.append(og_image)
        for image_url in self._dom_images(tree, canonical_url):
            if image_url not in images:
                images.append(image_url)

        offers = product_ld.get('offers') or {}
        if isinstance(offers, list):
            offers = next((offer for offer in offers if isinstance(offer, dict)), {})
        price = self._shopify_price(product_json)
        if not price and isinstance(offers, dict):
            price = self._parse_price(offers.get('lowPrice') or offers.get('price') or '0')
        if not price:
            price = self._parse_price(meta('product:price:amount') or meta('og:price:amount') or '0')
        if not price:
            visible_prices = tree.xpath(
                '//*[contains(@class,"price") and not(ancestor::*[contains(@style,"display:none")])]/text()'
            )
            for visible_price in visible_prices:
                price = self._parse_price(visible_price)
                if price:
                    break

        currency = (
            (offers.get('priceCurrency') if isinstance(offers, dict) else False)
            or meta('product:price:currency')
            or meta('og:price:currency')
            or 'EUR'
        )

        text_content = self._clean_text(tree.text_content())
        color_match = re.search(
            r'Color:\s*([^\n]+?)(?:\s+Forro:|\s+Ref:|\s+Talla\b|$)',
            text_content,
            flags=re.IGNORECASE,
        )
        color_code = self._clean_text(color_match.group(1)) if color_match else False

        style_code = urlparse(canonical_url).path.rstrip('/').split('/')[-1].upper() or False
        sku = product_ld.get('sku') or product_ld.get('mpn') or False
        if not sku:
            variants = product_json.get('variants') or []
            if variants and isinstance(variants[0], dict):
                sku = variants[0].get('sku') or False

        return {
            'name': title,
            'description': description,
            'price': price,
            'price_available': bool(price),
            'currency': currency,
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical_url,
            'style_code': style_code,
            'default_code': sku or style_code,
            'color_code': color_code,
            'category_path': self._clean_text(
                product_json.get('product_type') or product_ld.get('category') or ''
            ),
            'brand_name': self._clean_text(
                product_json.get('vendor')
                or ((product_ld.get('brand') or {}).get('name') if isinstance(product_ld.get('brand'), dict) else product_ld.get('brand'))
                or 'Panama Jack'
            ),
        }

    @staticmethod
    def _parse_price(price_str):
        if price_str in (None, False, ''):
            return 0.0
        match = re.search(r'\d[\d.,\s]*', str(price_str))
        if not match:
            return 0.0
        value = match.group(0).replace('\xa0', '').replace(' ', '')
        if ',' in value and '.' in value:
            if value.rfind(',') > value.rfind('.'):
                value = value.replace('.', '').replace(',', '.')
            else:
                value = value.replace(',', '')
        elif ',' in value:
            value = value.replace('.', '').replace(',', '.')
        try:
            return float(value)
        except ValueError:
            return 0.0
