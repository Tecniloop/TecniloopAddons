import json
import logging
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorCallaghanEs(models.AbstractModel):
    """Conector para callaghan.es (Shopify, tienda española).

    El sitemap proporcionado por la tienda es un ``urlset`` de productos Shopify
    que ya incluye la imagen principal. Las fichas usan rutas planas
    ``/products/<handle>`` y cada producto agrupa las tallas como variantes.

    La vista previa consume primero la API Ajax pública de Shopify
    ``/products/<handle>.js``. Así se obtienen precio vigente, descripción,
    variantes e imágenes de forma estructurada y no se confunden con precios de
    accesorios, recomendaciones o gastos de envío presentes en el HTML. El HTML
    se consulta para enriquecer color, URL canónica y categoría; si falla el
    endpoint Ajax, JSON-LD/Open Graph actúan como respaldo.
    """

    _name = 'sitemap.connector.callaghan_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Callaghan España'

    _PRODUCT_PATH_RE = re.compile(r'^/products/[^/]+/?$', re.IGNORECASE)
    _STYLE_RE = re.compile(r'^\s*([A-Z0-9][A-Z0-9.-]*)\s*(?:\||$)', re.IGNORECASE)
    _GENDER_WORDS = (
        ('hombre', 'Hombre'),
        ('mujer', 'Mujer'),
        ('nino', 'Niño'),
        ('niño', 'Niño'),
        ('nina', 'Niña'),
        ('niña', 'Niña'),
    )
    _TYPE_RULES = (
        (('mocasin', 'mocasín', 'loafer'), 'Mocasines'),
        (('nautico', 'náutico'), 'Náuticos'),
        (('sneaker', 'deportiv', 'zapatilla'), 'Sneakers'),
        (('sandalia',), 'Sandalias'),
        (('bailarina',), 'Bailarinas'),
        (('botin', 'botín'), 'Botines'),
        (('bota',), 'Botas'),
        (('calcetin', 'calcetín'), 'Calcetines'),
        (('clean', 'care', 'cuidado', 'limpieza'), 'Cuidado del calzado'),
        (('plantilla',), 'Plantillas'),
        (('cinturon', 'cinturón'), 'Cinturones'),
        (('zapato',), 'Zapatos'),
    )

    @classmethod
    def _is_product_url(cls, url):
        parsed = urlparse(url)
        host = parsed.netloc.lower().split(':', 1)[0]
        return host in {'callaghan.es', 'www.callaghan.es'} and bool(
            cls._PRODUCT_PATH_RE.match(parsed.path)
        )

    @staticmethod
    def _clean_product_url(url):
        parts = urlsplit(url)
        return urlunsplit((parts.scheme or 'https', parts.netloc, parts.path.rstrip('/'), '', ''))

    def get_product_entries(self, source, category_filter=None, limit=0):
        entries = []
        seen = set()
        for entry in self._fetch_urlset(source, source.sitemap_index_url):
            product_url = self._clean_product_url(entry.get('url') or '')
            if not self._is_product_url(product_url):
                continue
            if category_filter and category_filter.casefold() not in product_url.casefold():
                continue
            if product_url in seen:
                continue
            seen.add(product_url)
            entries.append({
                'url': product_url,
                'lastmod': entry.get('lastmod') or False,
            })
            if limit and len(entries) >= limit:
                break
        return entries

    def get_image_map(self, source):
        image_map = {}
        raw_map = self._fetch_image_urlset(source, source.sitemap_index_url)
        for raw_product_url, raw_images in raw_map.items():
            product_url = self._clean_product_url(raw_product_url)
            if not self._is_product_url(product_url):
                continue
            images = image_map.setdefault(product_url, [])
            for image_url in raw_images:
                image_url = self._absolute_url(image_url, product_url)
                image_url = self._high_resolution_shopify_image(image_url)
                if image_url and image_url not in images:
                    images.append(image_url)
        return image_map

    @staticmethod
    def parse_category_path(url):
        # El sitemap Shopify usa rutas planas. La categoría se obtiene de la ficha.
        return []

    @staticmethod
    def _ajax_product_url(product_url):
        parts = urlsplit(product_url)
        path = parts.path.rstrip('/')
        if not path.endswith('.js'):
            path = f'{path}.js'
        return urlunsplit((parts.scheme, parts.netloc, path, '', ''))

    @staticmethod
    def _absolute_url(value, base_url):
        if not value:
            return False
        value = str(value).strip()
        if not value:
            return False
        if value.startswith('//'):
            return f'https:{value}'
        return urljoin(base_url, value)

    @staticmethod
    def _high_resolution_shopify_image(url):
        """Conserva la imagen original o eleva el parámetro width hasta 1600."""
        if not url:
            return False
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        if 'width' in query:
            query['width'] = '1600'
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))

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
        text = str(value).replace('\xa0', '').replace('€', '').strip()
        text = re.sub(r'[^0-9,.-]', '', text)
        if ',' in text:
            text = text.replace('.', '').replace(',', '.')
        try:
            return float(text)
        except ValueError:
            return 0.0

    @staticmethod
    def _meta(tree, name):
        values = tree.xpath(f'//meta[@property="{name}"]/@content')
        if not values:
            values = tree.xpath(f'//meta[@name="{name}"]/@content')
        return values[0].strip() if values else False

    @staticmethod
    def _canonical_url(tree, fallback):
        values = tree.xpath('//link[@rel="canonical"]/@href')
        return urljoin(fallback, values[0].strip()) if values else fallback

    @staticmethod
    def _plain_text(value):
        if not value:
            return ''
        try:
            fragment = lxml_html.fromstring(f'<div>{value}</div>')
            return '\n'.join(
                line.strip() for line in fragment.text_content().splitlines() if line.strip()
            )
        except (TypeError, ValueError):
            return str(value).strip()

    @classmethod
    def _extract_style_code(cls, product_data, title, product_url):
        candidates = [title, product_data.get('title')]
        handle = product_data.get('handle') or urlparse(product_url).path.rstrip('/').split('/')[-1]
        candidates.append(handle.replace('-', ' '))
        for candidate in candidates:
            match = cls._STYLE_RE.match(str(candidate or ''))
            if match:
                return match.group(1).upper()

        # Como último respaldo, usa el SKU común de las variantes eliminando
        # sufijos evidentes de talla cuando todos comparten un prefijo estable.
        skus = [
            str(variant.get('sku') or '').strip()
            for variant in product_data.get('variants') or []
            if str(variant.get('sku') or '').strip()
        ]
        if skus:
            prefix = skus[0]
            for sku in skus[1:]:
                while prefix and not sku.startswith(prefix):
                    prefix = prefix[:-1]
            prefix = prefix.rstrip(' -_/')
            if len(prefix) >= 2:
                return prefix.upper()
        return str(handle or '').upper() or False

    @staticmethod
    def _tag_strings(product_data):
        tags = product_data.get('tags') or []
        if isinstance(tags, str):
            tags = [part.strip() for part in tags.split(',')]
        return [str(tag).strip() for tag in tags if str(tag).strip()]

    @classmethod
    def _extract_color(cls, product_data, seo_title='', visible_title=''):
        # El SEO title actual sigue el patrón:
        # "16100 | MATERIAL / NEGRO | PURE CONFORT".
        title = str(seo_title or '')
        title = re.split(r'\s+[–—-]\s+callaghan', title, maxsplit=1, flags=re.IGNORECASE)[0]
        pipe_parts = [part.strip() for part in title.split('|') if part.strip()]
        if len(pipe_parts) >= 3:
            material_color = pipe_parts[-2]
            color = material_color.rsplit('/', 1)[-1].strip(' -/')
            if color:
                return color.title()

        for tag in cls._tag_strings(product_data):
            match = re.match(r'^(?:color|colour)\s*[:_=-]\s*(.+)$', tag, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip().title()

        # Algunas tiendas modelan el color como opción; Callaghan suele usar
        # productos relacionados, pero se admite el caso por robustez.
        options = product_data.get('options') or []
        color_position = None
        for index, option in enumerate(options, start=1):
            option_name = option.get('name') if isinstance(option, dict) else option
            if str(option_name or '').strip().casefold() in {'color', 'colour'}:
                color_position = int(option.get('position') or index) if isinstance(option, dict) else index
                values = option.get('values') or [] if isinstance(option, dict) else []
                if values:
                    return ', '.join(dict.fromkeys(str(value).strip() for value in values if value))
                break
        if color_position:
            values = []
            for variant in product_data.get('variants') or []:
                raw = variant.get(f'option{color_position}')
                if not raw and len(variant.get('options') or []) >= color_position:
                    raw = variant['options'][color_position - 1]
                raw = str(raw or '').strip()
                if raw and raw.casefold() != 'default title' and raw not in values:
                    values.append(raw)
            if values:
                return ', '.join(values)

        # Respaldo prudente para el h1 "16100 | Pure Confort Negro". Solo se
        # usa un color de vocabulario conocido para no confundir el nombre del modelo.
        known_colors = (
            'negro', 'blanco', 'beig', 'beige', 'azul', 'rojo', 'rioja', 'camel',
            'marron', 'marrón', 'gris', 'verde', 'amarillo', 'naranja', 'rosa',
            'piedra', 'taupe', 'marino', 'denim', 'cuero', 'burdeos', 'plata', 'oro',
        )
        visible = str(visible_title or '').casefold()
        found = [color for color in known_colors if re.search(rf'\b{re.escape(color)}\b', visible)]
        return ' '.join(word.title() for word in found) if found else False

    @classmethod
    def _category_path(cls, product_data, product_url, title='', seo_title=''):
        text_parts = [
            urlparse(product_url).path.replace('-', ' '),
            str(title or ''),
            str(seo_title or ''),
            str(product_data.get('type') or ''),
            ' '.join(cls._tag_strings(product_data)),
        ]
        text = ' '.join(text_parts).casefold()

        gender = False
        for token, label in cls._GENDER_WORDS:
            if re.search(rf'\b{re.escape(token)}\b', text):
                gender = label
                break

        product_type = False
        for tokens, label in cls._TYPE_RULES:
            if any(token in text for token in tokens):
                product_type = label
                break
        if not product_type:
            raw_type = str(product_data.get('type') or '').strip()
            if raw_type and raw_type.casefold() not in {'calzado', 'footwear', 'product'}:
                product_type = raw_type.title()

        segments = [segment for segment in (gender, product_type or 'Calzado') if segment]
        return ' / '.join(segments)

    @staticmethod
    def _iter_json_nodes(value):
        if isinstance(value, dict):
            yield value
            graph = value.get('@graph')
            if graph:
                yield from SitemapConnectorCallaghanEs._iter_json_nodes(graph)
        elif isinstance(value, list):
            for item in value:
                yield from SitemapConnectorCallaghanEs._iter_json_nodes(item)

    def _find_product_json_ld(self, tree):
        for raw in tree.xpath('//script[@type="application/ld+json"]/text()'):
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                continue
            for node in self._iter_json_nodes(payload):
                node_type = node.get('@type')
                types = node_type if isinstance(node_type, list) else [node_type]
                if any(str(item).casefold() == 'product' for item in types if item):
                    return node
        return {}

    @classmethod
    def _json_ld_images(cls, product_node, base_url):
        raw_images = product_node.get('image') or []
        if isinstance(raw_images, (str, dict)):
            raw_images = [raw_images]
        images = []
        for item in raw_images:
            value = item.get('url') or item.get('contentUrl') if isinstance(item, dict) else item
            image_url = cls._absolute_url(value, base_url)
            image_url = cls._high_resolution_shopify_image(image_url)
            if image_url and image_url not in images:
                images.append(image_url)
        return images

    def _fetch_html_context(self, source, product_url):
        session = self._get_session(source)
        response = self._http_get(session, product_url, source)
        tree = lxml_html.fromstring(response.content)
        canonical_url = self._canonical_url(tree, product_url)
        if not self._is_product_url(canonical_url):
            raise ValueError(
                'La URL ya no apunta a una ficha de producto Callaghan; '
                'posible redirección o producto descatalogado.'
            )
        title_nodes = tree.xpath('//h1[1]//text()')
        visible_title = ' '.join(part.strip() for part in title_nodes if part.strip())
        return {
            'tree': tree,
            'canonical_url': self._clean_product_url(canonical_url),
            'seo_title': self._meta(tree, 'og:title') or '',
            'visible_title': visible_title,
        }

    def _preview_from_ajax(self, source, product_url, html_context=None):
        product_data = self._fetch_shopify_product_payload(source, product_url)
        if not isinstance(product_data, dict) or not product_data.get('title'):
            raise ValueError('El endpoint Ajax de Shopify no devolvió un producto válido.')

        canonical_url = self._absolute_url(product_data.get('url'), product_url) or product_url
        if html_context:
            canonical_url = html_context.get('canonical_url') or canonical_url
        canonical_url = self._clean_product_url(canonical_url)
        if not self._is_product_url(canonical_url):
            raise ValueError('El endpoint Ajax redirigió a una URL que no es producto Callaghan.')

        images = []
        for item in product_data.get('images') or []:
            if isinstance(item, dict):
                item = item.get('src') or item.get('url')
            image_url = self._absolute_url(item, canonical_url)
            image_url = self._high_resolution_shopify_image(image_url)
            if image_url and image_url not in images:
                images.append(image_url)
        featured = product_data.get('featured_image')
        if isinstance(featured, dict):
            featured = featured.get('src') or featured.get('url')
        featured = self._high_resolution_shopify_image(
            self._absolute_url(featured, canonical_url)
        )
        if featured and featured not in images:
            images.insert(0, featured)

        title = str(product_data.get('title') or '').strip()
        seo_title = html_context.get('seo_title', '') if html_context else ''
        visible_title = html_context.get('visible_title', '') if html_context else ''
        price = self._money_from_cents(product_data.get('price'))
        return {
            'name': visible_title or title or product_url,
            'description': product_data.get('description') or '',
            'price': price,
            'price_available': price > 0,
            'currency': 'EUR',
            'main_image_url': featured or (images[0] if images else False),
            'image_urls': images,
            'canonical_url': canonical_url,
            'style_code': self._extract_style_code(product_data, title, canonical_url),
            'color_code': self._extract_color(product_data, seo_title, visible_title or title),
            'ean_variants': self._ean_variants_from_shopify_product(product_data),
            'ean_complete': True,
            'category_path': self._category_path(
                product_data, canonical_url, visible_title or title, seo_title
            ),
        }

    def _preview_from_html(self, source, product_url, html_context=None):
        context = html_context or self._fetch_html_context(source, product_url)
        tree = context['tree']
        canonical_url = context['canonical_url']
        product_node = self._find_product_json_ld(tree)
        offers = product_node.get('offers') or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}

        visible_title = context.get('visible_title')
        seo_title = context.get('seo_title')
        name = product_node.get('name') or visible_title or seo_title or product_url
        description = (
            product_node.get('description')
            or self._meta(tree, 'og:description')
            or self._meta(tree, 'description')
            or ''
        )
        price = self._parse_display_price(
            offers.get('price')
            or self._meta(tree, 'product:price:amount')
            or self._meta(tree, 'og:price:amount')
            or '0'
        )
        currency = (
            offers.get('priceCurrency')
            or self._meta(tree, 'product:price:currency')
            or self._meta(tree, 'og:price:currency')
            or 'EUR'
        )
        images = self._json_ld_images(product_node, canonical_url)
        og_image = self._high_resolution_shopify_image(
            self._absolute_url(self._meta(tree, 'og:image'), canonical_url)
        )
        if og_image and og_image not in images:
            images.insert(0, og_image)

        pseudo_data = {
            'title': name,
            'type': product_node.get('category') or '',
            'tags': [],
            'variants': [],
            'handle': urlparse(canonical_url).path.rstrip('/').split('/')[-1],
        }
        style_code = self._extract_style_code(pseudo_data, name, canonical_url)
        return {
            'name': name,
            'description': description,
            'price': price,
            'price_available': price > 0,
            'currency': currency,
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical_url,
            'style_code': style_code,
            'color_code': self._extract_color(pseudo_data, seo_title, visible_title or name),
            'category_path': self._category_path(
                pseudo_data, canonical_url, visible_title or name, seo_title
            ),
        }

    def fetch_preview(self, source, url):
        html_context = None
        try:
            html_context = self._fetch_html_context(source, url)
        except Exception as exc:
            _logger.info('Callaghan: no se pudo enriquecer la ficha HTML %s: %s', url, exc)

        try:
            return self._preview_from_ajax(source, url, html_context=html_context)
        except Exception as exc:
            _logger.info(
                'Callaghan: no se pudo usar el endpoint Ajax para %s (%s); se usa HTML.',
                url,
                exc,
            )
            return self._preview_from_html(source, url, html_context=html_context)
