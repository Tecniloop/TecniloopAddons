import gzip
import json
import logging
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorFluchosEs(models.AbstractModel):
    """Conector para fluchos.es (Shopify, catálogo español).

    El sitemap raíz de Shopify es un índice que mezcla productos, colecciones,
    páginas y blog. Se siguen únicamente los ``sitemap_products_*.xml`` y se
    conservan las fichas españolas ``/products/<handle>``.

    La ficha se obtiene primero desde la API Ajax pública de Shopify
    ``/products/<handle>.js``. El HTML se consulta además para obtener la
    referencia comercial de la combinación de color (el valor que Fluchos
    publica en ``MATERIALES / Referencia``), el color visible y la URL canónica.
    """

    _name = 'sitemap.connector.fluchos_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Fluchos España'

    _PRODUCT_PATH_RE = re.compile(r'^/products/[^/]+/?$', re.IGNORECASE)
    _STYLE_RE = re.compile(r'\b([A-Z]{1,3}\d{3,5}|\d{4,5})\b', re.IGNORECASE)
    _REFERENCE_RE = re.compile(
        r'Referencia\s*:?\s*([A-Z0-9][A-Z0-9._/-]{3,20})',
        re.IGNORECASE,
    )

    _TYPE_RULES = (
        (('deportivo', 'deportiva', 'sneaker', 'zapatilla'), 'Deportivos'),
        (('mocasin', 'mocasín', 'loafer'), 'Mocasines'),
        (('slip on', 'slip-on', 'slipon'), 'Slip On'),
        (('nautico', 'náutico'), 'Náuticos'),
        (('sandalia',), 'Sandalias'),
        (('botin', 'botín'), 'Botines'),
        (('bota',), 'Botas'),
        (('salon', 'salón', 'tacon', 'tacón'), 'Zapatos de tacón'),
        (('bailarina',), 'Bailarinas'),
        (('zueco',), 'Zuecos'),
        (('cuña', 'cuna'), 'Cuñas'),
        (('cordon', 'cordón'), 'Zapatos con cordones'),
        (('zapato',), 'Zapatos'),
        (('kit de limpieza', 'crema', 'hidrofugante', 'impermeabilizante'), 'Cuidado del calzado'),
        (('plantilla',), 'Plantillas'),
    )

    _COLOR_NAMES = (
        ('Azul oscuro', ('azul oscuro', 'azul-oscuro')),
        ('Azul marino', ('azul marino', 'marino')),
        ('Marrón claro', ('marrón claro', 'marron claro', 'marron-claro')),
        ('Marrón oscuro', ('marrón oscuro', 'marron oscuro', 'marron-oscuro')),
        ('Verde oscuro', ('verde oscuro', 'verde-oscuro')),
        ('Gris oscuro', ('gris oscuro', 'gris-oscuro')),
        ('Negro', ('negro', 'black')),
        ('Blanco', ('blanco', 'white')),
        ('Marrón', ('marrón', 'marron', 'brown')),
        ('Azul', ('azul', 'blue')),
        ('Verde', ('verde', 'green')),
        ('Taupe', ('taupe',)),
        ('Burdeos', ('burdeos', 'borgona')),
        ('Rojo', ('rojo', 'red')),
        ('Rosa', ('rosa', 'pink')),
        ('Naranja', ('naranja', 'orange')),
        ('Amarillo', ('amarillo', 'yellow')),
        ('Beige', ('beige', 'beig')),
        ('Camel', ('camel',)),
        ('Cuero', ('cuero',)),
        ('Piedra', ('piedra',)),
        ('Arena', ('arena',)),
        ('Dorado', ('dorado', 'oro', 'gold')),
        ('Plata', ('plata', 'silver')),
        ('Gris', ('gris', 'grey', 'gray')),
    )

    # ------------------------------------------------------------------
    # Sitemap
    # ------------------------------------------------------------------
    @classmethod
    def _is_product_url(cls, url):
        parsed = urlparse(url)
        host = parsed.netloc.lower().split(':', 1)[0]
        path = parsed.path or ''
        return (
            host in {'fluchos.es', 'www.fluchos.es', 'fluchos.com', 'www.fluchos.com'}
            and not path.lower().startswith(('/en/', '/pt/', '/fr/', '/de/', '/it/'))
            and bool(cls._PRODUCT_PATH_RE.match(path))
        )

    @staticmethod
    def _clean_product_url(url):
        parts = urlsplit(str(url or '').strip())
        return urlunsplit((parts.scheme or 'https', parts.netloc, parts.path.rstrip('/'), '', ''))

    @staticmethod
    def _xml_root(content):
        payload = content or b''
        if payload[:2] == b'\x1f\x8b':
            payload = gzip.decompress(payload)
        return etree.fromstring(payload)

    def _discover_product_sitemaps(self, source):
        """Devuelve los urlsets de producto desde un índice Shopify.

        También admite que la fuente apunte directamente a un urlset y limita la
        recursión para evitar bucles en índices no estándar.
        """
        session = self._get_session(source)
        pending = [(source.sitemap_index_url, 0)]
        visited = set()
        product_sitemaps = []

        while pending:
            sitemap_url, depth = pending.pop(0)
            if sitemap_url in visited or depth > 3:
                continue
            visited.add(sitemap_url)
            response = self._http_get(session, sitemap_url, source)
            root = self._xml_root(response.content)
            local_name = etree.QName(root).localname.lower()

            if local_name == 'urlset':
                product_sitemaps.append(sitemap_url)
                continue
            if local_name != 'sitemapindex':
                continue

            child_urls = [
                str(value).strip()
                for value in root.xpath('//*[local-name()="sitemap"]/*[local-name()="loc"]/text()')
                if str(value).strip()
            ]
            direct_products = [
                value for value in child_urls if 'sitemap_products_' in value.casefold()
            ]
            if direct_products:
                product_sitemaps.extend(direct_products)
                continue
            for value in child_urls:
                if 'sitemap' in value.casefold():
                    pending.append((value, depth + 1))

        # Conserva el orden y elimina duplicados.
        return list(dict.fromkeys(product_sitemaps))

    def get_product_entries(self, source, category_filter=None, limit=0):
        entries = []
        seen = set()
        for sitemap_url in self._discover_product_sitemaps(source):
            for entry in self._fetch_urlset(source, sitemap_url):
                product_url = self._clean_product_url(entry.get('url'))
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
                    return entries
        return entries

    def get_image_map(self, source):
        image_map = {}
        for sitemap_url in self._discover_product_sitemaps(source):
            raw_map = self._fetch_image_urlset(source, sitemap_url)
            for raw_product_url, raw_images in raw_map.items():
                product_url = self._clean_product_url(raw_product_url)
                if not self._is_product_url(product_url):
                    continue
                images = image_map.setdefault(product_url, [])
                for value in raw_images:
                    image_url = self._high_resolution_shopify_image(
                        self._absolute_url(value, product_url)
                    )
                    if image_url and image_url not in images:
                        images.append(image_url)
        return image_map

    @staticmethod
    def parse_category_path(url):
        # Shopify usa una ruta plana. La categoría se obtiene de la ficha.
        return []

    # ------------------------------------------------------------------
    # Utilidades de ficha Shopify
    # ------------------------------------------------------------------
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

    @staticmethod
    def _tag_strings(product_data):
        tags = product_data.get('tags') or []
        if isinstance(tags, str):
            tags = [part.strip() for part in tags.split(',')]
        return [str(tag).strip() for tag in tags if str(tag).strip()]

    @classmethod
    def _extract_style_code(cls, product_data, title, product_url):
        handle = product_data.get('handle') or urlparse(product_url).path.rstrip('/').split('/')[-1]
        for candidate in (title, product_data.get('title'), handle.replace('-', ' ')):
            match = cls._STYLE_RE.search(str(candidate or '').upper())
            if match:
                return match.group(1).upper()
        return str(handle or '').upper() or False

    @staticmethod
    def _common_variant_sku_prefix(product_data):
        skus = [
            re.sub(r'\s+', '', str(variant.get('sku') or '').strip())
            for variant in product_data.get('variants') or []
            if str(variant.get('sku') or '').strip()
        ]
        if not skus:
            return False
        prefix = skus[0]
        for sku in skus[1:]:
            while prefix and not sku.startswith(prefix):
                prefix = prefix[:-1]
        prefix = prefix.rstrip(' -_/')
        # Evita devolver un prefijo demasiado corto o el propio código de talla.
        return prefix.upper() if len(prefix) >= 4 else False

    @classmethod
    def _extract_title_color(cls, *values):
        text = ' '.join(str(value or '') for value in values).casefold()
        best = False
        best_key = (-1, -1)
        for display, aliases in cls._COLOR_NAMES:
            for alias in aliases:
                for match in re.finditer(rf'(?<!\w){re.escape(alias.casefold())}(?!\w)', text):
                    # Prima la última coincidencia y, si empieza en el mismo lugar,
                    # la expresión más larga ("Marrón claro" antes que "Marrón").
                    key = (match.start(), len(match.group(0)))
                    if key > best_key:
                        best = display
                        best_key = key
        return best

    @classmethod
    def _extract_reference_from_text(cls, text):
        match = cls._REFERENCE_RE.search(str(text or ''))
        return match.group(1).strip(' .,:;').upper() if match else False

    @classmethod
    def _extract_selected_color(cls, tree, page_text, title):
        # Algunos temas publican el valor seleccionado como atributo.
        for xpath in (
            '//*[@data-selected-value]/@data-selected-value',
            '//*[@data-current-value]/@data-current-value',
            '//*[@itemprop="color"]/@content',
            '//*[@itemprop="color"]//text()',
        ):
            for raw in tree.xpath(xpath):
                value = ' '.join(str(raw).split()).strip(' -:')
                color = cls._extract_title_color(value)
                if color:
                    return color

        # Busca un bloque corto cuyo texto comience por "Color". Se limita la
        # longitud para no capturar todos los enlaces a colores alternativos.
        for node in tree.xpath('//*[contains(translate(normalize-space(.), "COLOR", "color"), "color")]'):
            text = ' '.join(node.text_content().split())
            match = re.match(r'^Color\s*:?[ ]*(.{1,30})$', text, flags=re.IGNORECASE)
            if match:
                color = cls._extract_title_color(match.group(1))
                if color:
                    return color

        # Respaldo estable: el nombre y el handle incluyen el color de la ficha.
        return cls._extract_title_color(title)

    @staticmethod
    def _variant_sizes(product_data):
        sizes = []
        for variant in product_data.get('variants') or []:
            raw_values = list(variant.get('options') or [])
            raw_values.extend(
                variant.get(key) for key in ('option1', 'option2', 'option3') if variant.get(key)
            )
            for raw in raw_values:
                match = re.fullmatch(r'\s*(\d{2})(?:[.,]\d)?\s*', str(raw or ''))
                if match:
                    value = int(match.group(1))
                    if 20 <= value <= 55 and value not in sizes:
                        sizes.append(value)
        return sorted(sizes)

    @classmethod
    def _category_path(cls, product_data, product_url, title=''):
        tags = cls._tag_strings(product_data)
        text = ' '.join([
            urlparse(product_url).path.replace('-', ' '),
            str(title or ''),
            str(product_data.get('type') or ''),
            ' '.join(tags),
        ]).casefold()

        gender = False
        if re.search(r'\b(mujer|women|woman|señora|senora)\b', text):
            gender = 'Mujer'
        elif re.search(r'\b(hombre|men|man|caballero)\b', text):
            gender = 'Hombre'
        elif re.search(r'\b(niña|nina|girl)\b', text):
            gender = 'Niña'
        elif re.search(r'\b(niño|nino|boy)\b', text):
            gender = 'Niño'
        else:
            sizes = cls._variant_sizes(product_data)
            if sizes:
                if min(sizes) <= 36 and max(sizes) <= 42:
                    gender = 'Mujer'
                elif min(sizes) >= 38 and max(sizes) >= 43:
                    gender = 'Hombre'

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
                yield from SitemapConnectorFluchosEs._iter_json_nodes(graph)
        elif isinstance(value, list):
            for item in value:
                yield from SitemapConnectorFluchosEs._iter_json_nodes(item)

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
            image_url = cls._high_resolution_shopify_image(cls._absolute_url(value, base_url))
            if image_url and image_url not in images:
                images.append(image_url)
        return images

    @classmethod
    def _html_product_images(cls, tree, base_url, style_code, article_reference):
        images = []
        tokens = [
            re.sub(r'[^A-Z0-9]', '', str(value or '').upper())
            for value in (style_code, article_reference)
            if value
        ]
        for node in tree.xpath('//img'):
            alt = ' '.join(node.xpath('.//@alt')).upper()
            compact_alt = re.sub(r'[^A-Z0-9]', '', alt)
            if tokens and not any(token and token in compact_alt for token in tokens):
                continue
            candidates = []
            for attr in ('src', 'data-src'):
                if node.get(attr):
                    candidates.append(node.get(attr))
            for attr in ('srcset', 'data-srcset'):
                if node.get(attr):
                    candidates.extend(
                        item.strip().split(' ')[0]
                        for item in node.get(attr).split(',')
                        if item.strip()
                    )
            for value in reversed(candidates):
                image_url = cls._high_resolution_shopify_image(cls._absolute_url(value, base_url))
                if image_url and image_url not in images:
                    images.append(image_url)
        return images

    def _fetch_html_context(self, source, product_url):
        session = self._get_session(source)
        response = self._http_get(session, product_url, source)
        tree = lxml_html.fromstring(response.content)
        canonical_url = self._clean_product_url(self._canonical_url(tree, product_url))
        if not self._is_product_url(canonical_url):
            raise ValueError(
                'La URL ya no apunta a una ficha de producto Fluchos; '
                'posible redirección o producto descatalogado.'
            )
        title_nodes = tree.xpath('//h1[1]//text()')
        visible_title = ' '.join(part.strip() for part in title_nodes if part.strip())
        page_text = ' '.join(tree.text_content().split())
        reference = self._extract_reference_from_text(page_text)
        selected_color = self._extract_selected_color(
            tree,
            page_text,
            visible_title or self._meta(tree, 'og:title') or '',
        )
        return {
            'tree': tree,
            'canonical_url': canonical_url,
            'visible_title': visible_title,
            'seo_title': self._meta(tree, 'og:title') or '',
            'page_text': page_text,
            'article_reference': reference,
            'selected_color': selected_color,
        }

    def _preview_from_ajax(self, source, product_url, html_context=None):
        session = self._get_session(source)
        response = self._http_get(session, self._ajax_product_url(product_url), source)
        product_data = response.json()
        if not isinstance(product_data, dict) or not product_data.get('title'):
            raise ValueError('El endpoint Ajax de Shopify no devolvió un producto válido.')

        canonical_url = self._absolute_url(product_data.get('url'), product_url) or product_url
        if html_context:
            canonical_url = html_context.get('canonical_url') or canonical_url
        canonical_url = self._clean_product_url(canonical_url)
        if not self._is_product_url(canonical_url):
            raise ValueError('El endpoint Ajax redirigió a una URL que no es producto Fluchos.')

        images = []
        for item in product_data.get('images') or []:
            if isinstance(item, dict):
                item = item.get('src') or item.get('url')
            image_url = self._high_resolution_shopify_image(
                self._absolute_url(item, canonical_url)
            )
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
        visible_title = html_context.get('visible_title') if html_context else False
        style_code = self._extract_style_code(product_data, visible_title or title, canonical_url)
        article_reference = (
            html_context.get('article_reference') if html_context else False
        ) or self._common_variant_sku_prefix(product_data)
        color = (
            html_context.get('selected_color') if html_context else False
        ) or self._extract_title_color(visible_title, title, canonical_url)
        color_code = ' - '.join(value for value in (article_reference, color) if value) or False
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
            'style_code': style_code,
            'color_code': color_code,
            'ean_variants': self._ean_variants_from_shopify_product(product_data),
            'ean_complete': True,
            'category_path': self._category_path(
                product_data, canonical_url, visible_title or title
            ),
        }

    def _preview_from_html(self, source, product_url, html_context=None):
        context = html_context or self._fetch_html_context(source, product_url)
        tree = context['tree']
        canonical_url = context['canonical_url']
        product_node = self._find_product_json_ld(tree)
        offers = product_node.get('offers') or {}
        if isinstance(offers, list):
            positive_offers = [
                offer for offer in offers
                if isinstance(offer, dict) and self._parse_display_price(offer.get('price')) > 0
            ]
            offers = min(
                positive_offers,
                key=lambda offer: self._parse_display_price(offer.get('price')),
            ) if positive_offers else (offers[0] if offers else {})

        visible_title = context.get('visible_title') or ''
        seo_title = context.get('seo_title') or ''
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

        pseudo_data = {
            'title': name,
            'type': product_node.get('category') or '',
            'tags': [],
            'variants': [],
            'handle': urlparse(canonical_url).path.rstrip('/').split('/')[-1],
        }
        style_code = self._extract_style_code(pseudo_data, name, canonical_url)
        article_reference = context.get('article_reference')
        color = context.get('selected_color') or self._extract_title_color(name, canonical_url)

        images = self._json_ld_images(product_node, canonical_url)
        for image_url in self._html_product_images(
            tree, canonical_url, style_code, article_reference
        ):
            if image_url not in images:
                images.append(image_url)
        og_image = self._high_resolution_shopify_image(
            self._absolute_url(self._meta(tree, 'og:image'), canonical_url)
        )
        if og_image and og_image not in images:
            images.insert(0, og_image)

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
            'color_code': ' - '.join(
                value for value in (article_reference, color) if value
            ) or False,
            'category_path': self._category_path(pseudo_data, canonical_url, name),
        }

    def fetch_preview(self, source, url):
        html_context = None
        try:
            html_context = self._fetch_html_context(source, url)
        except Exception as exc:
            _logger.info('Fluchos: no se pudo enriquecer la ficha HTML %s: %s', url, exc)

        try:
            return self._preview_from_ajax(source, url, html_context=html_context)
        except Exception as exc:
            _logger.info(
                'Fluchos: no se pudo usar el endpoint Ajax para %s (%s); se usa HTML.',
                url,
                exc,
            )
            return self._preview_from_html(source, url, html_context=html_context)
