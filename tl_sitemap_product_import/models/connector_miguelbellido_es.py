import json
import logging
import re
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorMiguelBellidoEs(models.AbstractModel):
    """Conector para miguelbellido.es (Shopify, español como idioma principal).

    El sitemap raíz de Shopify es un índice que mezcla productos, colecciones,
    páginas y entradas de blog. Este conector sigue únicamente los sub-sitemaps
    ``sitemap_products_*.xml`` del idioma principal y descarta las rutas ``/en/``.

    Para la vista previa se intenta primero la API Ajax pública de Shopify
    ``/products/<handle>.js``. Devuelve datos estructurados de producto (precio,
    tipo, opciones, variantes e imágenes) y evita depender del diseño HTML del
    tema. Si el endpoint no está disponible, se usa una extracción de respaldo
    desde JSON-LD/Open Graph y el texto visible de la ficha.
    """

    _name = 'sitemap.connector.miguelbellido_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Miguel Bellido España'

    @staticmethod
    def _is_default_locale(url):
        path = urlparse(url).path.lower()
        return not path.startswith('/en/')

    def _get_product_sitemaps(self, source):
        sub_sitemaps = self._fetch_sitemap_index_locs(source, source.sitemap_index_url)
        product_sitemaps = [
            sitemap_url
            for sitemap_url in sub_sitemaps
            if 'sitemap_products_' in sitemap_url.lower()
            and self._is_default_locale(sitemap_url)
        ]
        # Respaldo para una fuente que apunte directamente a un urlset de productos.
        if not product_sitemaps and 'product' in source.sitemap_index_url.lower():
            product_sitemaps = [source.sitemap_index_url]
        return product_sitemaps

    def get_product_entries(self, source, category_filter=None, limit=0):
        entries = []
        seen = set()
        for sitemap_url in self._get_product_sitemaps(source):
            for entry in self._fetch_urlset(source, sitemap_url):
                product_url = entry['url']
                path = urlparse(product_url).path.lower()
                if not self._is_default_locale(product_url) or not path.startswith('/products/'):
                    continue
                # En Shopify la URL de producto es plana. Este filtro sirve para buscar
                # por texto del handle; la categoría real se obtiene después del campo
                # "type" del endpoint Ajax durante la vista previa.
                if category_filter and category_filter.lower() not in product_url.lower():
                    continue
                if product_url in seen:
                    continue
                seen.add(product_url)
                entries.append(entry)
                if limit and len(entries) >= limit:
                    return entries
        return entries

    def get_image_map(self, source):
        """Shopify publica la imagen principal dentro del sitemap de productos.

        Las imágenes adicionales se obtienen del endpoint Ajax y se guardan en la
        fila de staging por el servicio base, por lo que aquí solo se combina lo
        publicado explícitamente en el sitemap.
        """
        image_map = {}
        for sitemap_url in self._get_product_sitemaps(source):
            for product_url, image_urls in self._fetch_image_urlset(source, sitemap_url).items():
                if not self._is_default_locale(product_url):
                    continue
                current = image_map.setdefault(product_url, [])
                for image_url in image_urls:
                    absolute_url = self._absolute_url(image_url, product_url)
                    if absolute_url and absolute_url not in current:
                        current.append(absolute_url)
        return image_map

    @staticmethod
    def parse_category_path(url):
        # Las URLs son /products/<handle>; la categoría no está codificada en la URL.
        return []

    @staticmethod
    def _ajax_product_url(product_url):
        parts = urlsplit(product_url)
        path = parts.path.rstrip('/')
        if path.endswith('.js'):
            ajax_path = path
        else:
            ajax_path = f'{path}.js'
        return urlunsplit((parts.scheme, parts.netloc, ajax_path, '', ''))

    @staticmethod
    def _absolute_url(value, base_url):
        if not value:
            return False
        value = str(value).strip()
        if value.startswith('//'):
            return f'https:{value}'
        return urljoin(base_url, value)

    @staticmethod
    def _money_from_cents(value):
        if value in (None, False, ''):
            return 0.0
        try:
            return float(value) / 100.0
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _parse_display_price(value):
        if value in (None, False, ''):
            return 0.0
        text = str(value).strip().replace('\xa0', '').replace('€', '')
        text = re.sub(r'[^0-9,.-]', '', text)
        if ',' in text:
            text = text.replace('.', '').replace(',', '.')
        try:
            return float(text)
        except ValueError:
            return 0.0

    @staticmethod
    def _extract_option_values(product_data, option_names):
        options = product_data.get('options') or []
        position = None
        direct_values = []
        normalized_names = {name.lower() for name in option_names}
        for index, option in enumerate(options, start=1):
            if isinstance(option, dict):
                name = str(option.get('name') or '').strip().lower()
                if name in normalized_names:
                    position = int(option.get('position') or index)
                    direct_values = option.get('values') or []
                    break
            elif str(option).strip().lower() in normalized_names:
                position = index
                break

        values = []
        for value in direct_values:
            value = str(value).strip()
            if value and value not in values:
                values.append(value)

        if position:
            for variant in product_data.get('variants') or []:
                variant_options = variant.get('options') or []
                value = False
                if len(variant_options) >= position:
                    value = variant_options[position - 1]
                if not value:
                    value = variant.get(f'option{position}')
                value = str(value or '').strip()
                if value and value.lower() != 'default title' and value not in values:
                    values.append(value)
        return values

    def _preview_from_ajax(self, source, product_url):
        product_data = self._fetch_shopify_product_payload(source, product_url)
        if not isinstance(product_data, dict) or not product_data.get('title'):
            raise ValueError('El endpoint Ajax de Shopify no devolvió un producto válido.')

        canonical_url = self._absolute_url(product_data.get('url'), product_url) or product_url
        handle = product_data.get('handle') or urlparse(canonical_url).path.rstrip('/').split('/')[-1]
        image_urls = []
        for image_url in product_data.get('images') or []:
            absolute_url = self._absolute_url(image_url, canonical_url)
            if absolute_url and absolute_url not in image_urls:
                image_urls.append(absolute_url)
        featured_image = self._absolute_url(product_data.get('featured_image'), canonical_url)
        if featured_image and featured_image not in image_urls:
            image_urls.insert(0, featured_image)

        colors = self._extract_option_values(product_data, {'color', 'colour'})
        category = str(product_data.get('type') or '').strip()

        return {
            'name': product_data.get('title') or product_url,
            'description': product_data.get('description') or '',
            'price': self._money_from_cents(product_data.get('price')),
            'currency': 'EUR',
            'main_image_url': featured_image or (image_urls[0] if image_urls else False),
            'image_urls': image_urls,
            'canonical_url': canonical_url,
            'style_code': str(handle or '').upper() or False,
            'color_code': ', '.join(colors) if colors else False,
            'ean_variants': self._ean_variants_from_shopify_product(product_data),
            'ean_complete': True,
            'category_path': category,
        }

    @staticmethod
    def _iter_json_nodes(value):
        if isinstance(value, dict):
            yield value
            graph = value.get('@graph')
            if graph:
                yield from SitemapConnectorMiguelBellidoEs._iter_json_nodes(graph)
        elif isinstance(value, list):
            for item in value:
                yield from SitemapConnectorMiguelBellidoEs._iter_json_nodes(item)

    def _find_product_json_ld(self, tree):
        for raw in tree.xpath('//script[@type="application/ld+json"]/text()'):
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                continue
            for node in self._iter_json_nodes(payload):
                node_type = node.get('@type')
                types = node_type if isinstance(node_type, list) else [node_type]
                if any(str(value).lower() == 'product' for value in types if value):
                    return node
        return {}

    @staticmethod
    def _json_ld_images(product_node, base_url):
        raw_images = product_node.get('image') or []
        if isinstance(raw_images, (str, dict)):
            raw_images = [raw_images]
        images = []
        for item in raw_images:
            value = item.get('url') or item.get('contentUrl') if isinstance(item, dict) else item
            absolute_url = SitemapConnectorMiguelBellidoEs._absolute_url(value, base_url)
            if absolute_url and absolute_url not in images:
                images.append(absolute_url)
        return images

    def _preview_from_html(self, source, product_url):
        session = self._get_session(source)
        response = self._http_get(session, product_url, source)
        tree = lxml_html.fromstring(response.content)

        def meta(name):
            values = tree.xpath(f'//meta[@property="{name}"]/@content')
            if not values:
                values = tree.xpath(f'//meta[@name="{name}"]/@content')
            return values[0].strip() if values else False

        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical_url = canonical_values[0].strip() if canonical_values else product_url
        if not urlparse(canonical_url).path.startswith('/products/'):
            raise ValueError(
                'La URL ya no apunta a una ficha de producto; posible redirección o producto descatalogado.')

        product_node = self._find_product_json_ld(tree)
        offers = product_node.get('offers') or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}

        title_values = tree.xpath('//title/text()')
        title = (
            product_node.get('name')
            or meta('og:title')
            or (title_values[0].split('–')[0].split('|')[0].strip() if title_values else product_url)
        )
        description = product_node.get('description') or meta('og:description') or meta('description') or ''
        price = self._parse_display_price(
            offers.get('price') or meta('product:price:amount') or meta('og:price:amount') or '0')
        currency = offers.get('priceCurrency') or meta('product:price:currency') or meta('og:price:currency') or 'EUR'

        image_urls = self._json_ld_images(product_node, canonical_url)
        og_image = self._absolute_url(meta('og:image'), canonical_url)
        if og_image and og_image not in image_urls:
            image_urls.insert(0, og_image)

        page_text = ' '.join(tree.text_content().split())
        color_match = re.search(
            r'\bColor\s+(.+?)(?=\s+(?:Dimensiones|Estilo|Material|Talla|Retiro|Envíos|Devoluciones)\b|$)',
            page_text,
            flags=re.IGNORECASE,
        )
        color_code = color_match.group(1).strip(' ,;') if color_match else False
        handle = urlparse(canonical_url).path.rstrip('/').split('/')[-1]
        category = str(product_node.get('category') or meta('product:type') or '').strip()

        return {
            'name': title or product_url,
            'description': description,
            'price': price,
            'currency': currency,
            'main_image_url': image_urls[0] if image_urls else False,
            'image_urls': image_urls,
            'canonical_url': canonical_url,
            'style_code': str(product_node.get('sku') or handle).upper() or False,
            'color_code': color_code,
            'category_path': category,
        }

    def fetch_preview(self, source, url):
        try:
            return self._preview_from_ajax(source, url)
        except Exception as exc:
            _logger.info(
                'Miguel Bellido: no se pudo usar el endpoint Ajax para %s (%s); se usa HTML.',
                url,
                exc,
            )
            return self._preview_from_html(source, url)
