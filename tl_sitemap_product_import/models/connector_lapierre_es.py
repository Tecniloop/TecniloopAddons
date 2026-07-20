import json
import logging
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorLapierreEs(models.AbstractModel):
    """Conector del mercado español de Lapierre Bikes.

    Lapierre usa Shopify y publica el catálogo localizado bajo
    ``/es-es/products/<handle>``. El sitemap raíz es un índice Shopify; se
    siguen únicamente sus mapas de producto y se descartan colecciones,
    páginas, blog y otros mercados.

    La ficha se consulta primero mediante el endpoint Ajax localizado
    ``/es-es/products/<handle>.js``. Ese JSON contiene precio, opciones,
    variantes, SKU, barcode y galería. El HTML se usa para validar la URL
    canónica y completar migas de pan o el color visible.

    Cada URL representa un modelo de bicicleta que puede contener varios
    tamaños de cuadro y, a veces, varios colores. El producto se mantiene
    simple en Odoo y todos los GTIN/EAN se conservan por variante externa.
    """

    _name = 'sitemap.connector.lapierre_es'
    _inherit = 'sitemap.connector.fluchos_es'
    _description = 'Conector Lapierre Bikes España'

    _HOSTS = {'lapierrebikes.com', 'www.lapierrebikes.com'}
    _PRODUCT_PATH_RE = re.compile(r'^/es-es/products/(?P<handle>[^/]+)/?$', re.IGNORECASE)
    _HANDLE_STYLE_RE = re.compile(r'-([a-z]{4,8})$', re.IGNORECASE)
    _SKU_STYLE_RE = re.compile(r'^([A-Z]{4,8})(?=\d)', re.IGNORECASE)

    _CATEGORY_TRANSLATIONS = (
        (('electric all mountain', 'e-all mountain'), ('Bicicletas eléctricas', 'All-Mountain')),
        (('electric enduro', 'e-enduro'), ('Bicicletas eléctricas', 'Enduro')),
        (('electric trail', 'e-trail'), ('Bicicletas eléctricas', 'Trail')),
        (('electric mountain', 'e-mtb'), ('Bicicletas eléctricas', 'Montaña')),
        (('e-trekking', 'electric trekking'), ('Bicicletas eléctricas', 'Trekking')),
        (('performance road',), ('Bicicletas de carretera', 'Rendimiento')),
        (('endurance road',), ('Bicicletas de carretera', 'Resistencia')),
        (('sport road',), ('Bicicletas de carretera', 'Sport')),
        (('time trial', 'contrarreloj'), ('Bicicletas de carretera', 'Contrarreloj')),
        (('gravel',), ('Bicicletas de gravel',)),
        (('cross-country', 'cross country', 'x-country'), ('Bicicletas de montaña', 'Cross-country')),
        (('all-mountain', 'all mountain'), ('Bicicletas de montaña', 'All-Mountain')),
        (('trail mountain', 'trail bikes'), ('Bicicletas de montaña', 'Trail')),
        (('enduro',), ('Bicicletas de montaña', 'Enduro')),
        (('frame kit', 'frameset'), ('Cuadros',)),
    )

    # ------------------------------------------------------------------
    # URLs y sitemap Shopify
    # ------------------------------------------------------------------
    @classmethod
    def _is_product_url(cls, url):
        parsed = urlparse(str(url or ''))
        host = parsed.netloc.lower().split(':', 1)[0]
        return host in cls._HOSTS and bool(cls._PRODUCT_PATH_RE.match(parsed.path or ''))

    @classmethod
    def _clean_product_url(cls, url):
        parts = urlsplit(str(url or '').strip())
        host = parts.netloc.lower().split(':', 1)[0]
        if host == 'www.lapierrebikes.com':
            host = 'lapierrebikes.com'
        path = re.sub(r'/+', '/', parts.path or '')
        path = re.sub(r'^/es[-_]es/', '/es-es/', path, flags=re.IGNORECASE)
        return urlunsplit((parts.scheme or 'https', host, path.rstrip('/'), '', ''))

    @staticmethod
    def parse_category_path(url):
        # La categoría no está codificada en la URL plana de Shopify.
        return []

    def _iter_localized_product_entries(self, source):
        """Lee los loc principales y los alternates hreflang del sitemap.

        Shopify Markets puede publicar como ``loc`` el mercado principal y
        colocar ``/es-es/`` en un ``xhtml:link`` alternativo. El lector
        genérico de urlsets solo conserva ``loc``; por eso este conector revisa
        también todos los atributos ``href`` del elemento ``url``.
        """
        session = self._get_session(source)
        for sitemap_url in self._discover_product_sitemaps(source):
            response = self._http_get(session, sitemap_url, source)
            root = self._xml_root(response.content)
            for url_element in root.xpath('./*[local-name()="url"]'):
                candidates = [
                    str(value).strip()
                    for value in url_element.xpath(
                        './*[local-name()="loc"]/text() | .//*[@href]/@href'
                    )
                    if str(value).strip()
                ]
                product_url = next(
                    (self._clean_product_url(value) for value in candidates
                     if self._is_product_url(value)),
                    False,
                )
                if not product_url:
                    continue
                lastmod_values = url_element.xpath('./*[local-name()="lastmod"]/text()')
                image_values = url_element.xpath(
                    './*[local-name()="image"]/*[local-name()="loc"]/text()'
                )
                yield {
                    'url': product_url,
                    'lastmod': self._parse_lastmod(
                        lastmod_values[0] if lastmod_values else None
                    ),
                }, [
                    self._high_resolution_shopify_image(
                        self._absolute_url(value, product_url)
                    )
                    for value in image_values
                    if str(value).strip()
                ]

    def get_product_entries(self, source, category_filter=None, limit=0):
        entries = []
        seen = set()
        filter_text = str(category_filter or '').strip().casefold()
        for entry, _images in self._iter_localized_product_entries(source):
            product_url = entry['url']
            if filter_text and filter_text not in product_url.casefold():
                continue
            if product_url in seen:
                continue
            seen.add(product_url)
            entries.append(entry)
            if limit and len(entries) >= limit:
                break
        return entries

    def get_image_map(self, source):
        image_map = {}
        for entry, raw_images in self._iter_localized_product_entries(source):
            images = image_map.setdefault(entry['url'], [])
            for image_url in raw_images:
                if image_url and image_url not in images:
                    images.append(image_url)
        return image_map

    # ------------------------------------------------------------------
    # Datos de producto
    # ------------------------------------------------------------------
    @classmethod
    def _style_code(cls, product_data, product_url):
        handle = str(product_data.get('handle') or '').strip()
        if not handle:
            match = cls._PRODUCT_PATH_RE.match(urlparse(product_url).path or '')
            handle = match.group('handle') if match else ''
        match = cls._HANDLE_STYLE_RE.search(handle)
        if match:
            return match.group(1).upper()

        prefixes = []
        for variant in product_data.get('variants') or []:
            sku = str(variant.get('sku') or '').strip().upper()
            sku_match = cls._SKU_STYLE_RE.match(sku)
            if sku_match:
                prefixes.append(sku_match.group(1).upper())
        if prefixes and len(set(prefixes)) == 1:
            return prefixes[0]

        prefix = cls._common_variant_sku_prefix(product_data)
        if prefix:
            alpha = re.match(r'^([A-Z]{4,8})', prefix)
            return alpha.group(1) if alpha else prefix
        return handle.upper() or False

    @staticmethod
    def _option_names(product_data):
        result = []
        for option in product_data.get('options') or []:
            if isinstance(option, dict):
                result.append(str(option.get('name') or '').strip())
            else:
                result.append(str(option or '').strip())
        return result

    @classmethod
    def _option_values(cls, product_data, aliases):
        names = cls._option_names(product_data)
        indexes = [
            index for index, name in enumerate(names)
            if any(alias in name.casefold() for alias in aliases)
        ]
        values = []
        for variant in product_data.get('variants') or []:
            raw_values = variant.get('options') or []
            if not isinstance(raw_values, list):
                continue
            for index in indexes:
                if index >= len(raw_values):
                    continue
                value = str(raw_values[index] or '').strip()
                if value and value.casefold() != 'default title' and value not in values:
                    values.append(value)
        return values

    @classmethod
    def _colors_from_product(cls, product_data):
        return cls._option_values(product_data, ('color', 'colour', 'farbe', 'couleur'))

    @classmethod
    def _frame_sizes_from_product(cls, product_data):
        return cls._option_values(
            product_data,
            ('tamaño del cuadro', 'frame size', 'taille du cadre', 'rahmengröße'),
        )

    @staticmethod
    def _iter_json_nodes(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                if isinstance(child, (dict, list)):
                    yield from SitemapConnectorLapierreEs._iter_json_nodes(child)
        elif isinstance(value, list):
            for item in value:
                yield from SitemapConnectorLapierreEs._iter_json_nodes(item)

    @classmethod
    def _breadcrumb_segments(cls, tree, product_title=''):
        segments = []
        for raw in tree.xpath('//script[@type="application/ld+json"]/text()'):
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                continue
            for node in cls._iter_json_nodes(payload):
                node_type = node.get('@type') if isinstance(node, dict) else False
                types = node_type if isinstance(node_type, list) else [node_type]
                if not any(str(item).casefold() == 'breadcrumblist' for item in types if item):
                    continue
                for element in node.get('itemListElement') or []:
                    if not isinstance(element, dict):
                        continue
                    item = element.get('item')
                    name = element.get('name')
                    if not name and isinstance(item, dict):
                        name = item.get('name')
                    name = ' '.join(str(name or '').split()).strip()
                    if name and name not in segments:
                        segments.append(name)

        if not segments:
            xpaths = (
                '//nav[contains(translate(@aria-label,"BREADCRUMB","breadcrumb"),"breadcrumb")]//a//text()',
                '//*[contains(concat(" ", normalize-space(@class), " "), " breadcrumb ")]//a//text()',
                '//*[contains(@class,"breadcrumbs")]//a//text()',
            )
            for xpath in xpaths:
                values = [' '.join(str(value).split()) for value in tree.xpath(xpath)]
                values = [value for value in values if value]
                if values:
                    segments = values
                    break

        ignored = {
            'home', 'hogar', 'products', 'productos', 'collections', 'colecciones',
            'collection', 'recopilación', 'recopilacion', 'lapierre',
        }
        title_key = ' '.join(str(product_title or '').split()).casefold()
        cleaned = []
        for value in segments:
            key = value.casefold()
            if key in ignored or key == title_key:
                continue
            if value not in cleaned:
                cleaned.append(value)
        return cleaned

    @classmethod
    def _translated_category(cls, values, product_data, title, product_url):
        text = ' '.join(
            [
                *(str(value or '') for value in values),
                str(product_data.get('type') or ''),
                ' '.join(cls._tag_strings(product_data)),
                str(title or ''),
                urlparse(product_url).path.replace('-', ' '),
            ]
        ).casefold()
        for needles, path in cls._CATEGORY_TRANSLATIONS:
            if any(needle in text for needle in needles):
                return list(path)

        product_type = ' '.join(str(product_data.get('type') or '').split()).strip()
        if product_type and product_type.casefold() not in {'product', 'producto'}:
            return [product_type]

        if any(token in text for token in ('overvolt', 'e-explorer', 'electric', 'e-bike')):
            return ['Bicicletas eléctricas']
        return ['Bicicletas']

    @classmethod
    def _category_path(cls, product_data, tree, title, product_url):
        breadcrumb = cls._breadcrumb_segments(tree, title) if tree is not None else []
        translated = cls._translated_category(breadcrumb, product_data, title, product_url)
        # Las traducciones conocidas son más consistentes que una miga de pan
        # que puede estar en inglés incluso dentro del mercado español.
        return ' / '.join(translated or breadcrumb or ['Bicicletas'])

    @staticmethod
    def _selected_color_from_html(tree):
        if tree is None:
            return False
        page_text = '\n'.join(
            line.strip() for line in tree.text_content().splitlines() if line.strip()
        )
        patterns = (
            r'(?:Color|Colour)\s*:\s*([^\n]{1,80})',
            r'(?:Color|Colour)\s+([^\n]{1,80})',
        )
        for pattern in patterns:
            match = re.search(pattern, page_text, flags=re.IGNORECASE)
            if not match:
                continue
            value = match.group(1).strip(' -:')
            value = re.split(
                r'\s{2,}|\b(?:Precio|Price|Tipo de marco|Frame shape|Tamaño|Size|Cantidad)\b',
                value,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip(' -:')
            if value:
                return value
        return False

    @classmethod
    def _shopify_images(cls, product_data, base_url):
        images = []
        for item in product_data.get('images') or []:
            if isinstance(item, dict):
                item = item.get('src') or item.get('url')
            image_url = cls._high_resolution_shopify_image(cls._absolute_url(item, base_url))
            if image_url and image_url not in images:
                images.append(image_url)
        featured = product_data.get('featured_image')
        if isinstance(featured, dict):
            featured = featured.get('src') or featured.get('url')
        featured = cls._high_resolution_shopify_image(cls._absolute_url(featured, base_url))
        if featured and featured not in images:
            images.insert(0, featured)
        return images

    @classmethod
    def _html_product_images(cls, tree, base_url):
        if tree is None:
            return []
        images = []
        nodes = tree.xpath(
            '//*[contains(@id,"MediaGallery") or contains(@id,"ProductGallery") '
            'or contains(@class,"product__media") or contains(@class,"product-media") '
            'or contains(@class,"product-gallery")]//img'
        )
        for node in nodes:
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
            for raw in reversed(candidates):
                image_url = cls._high_resolution_shopify_image(cls._absolute_url(raw, base_url))
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
                'La URL ya no apunta a una ficha española de Lapierre; '
                'posible redirección o producto descatalogado.'
            )
        title_nodes = tree.xpath('//h1[1]//text()')
        visible_title = ' '.join(part.strip() for part in title_nodes if part.strip())
        return {
            'tree': tree,
            'content': response.content,
            'canonical_url': canonical_url,
            'visible_title': visible_title,
            'seo_title': self._meta(tree, 'og:title') or '',
            'selected_color': self._selected_color_from_html(tree),
        }

    def _preview_from_ajax(self, source, product_url, html_context=None):
        product_data = self._fetch_shopify_product_payload(source, product_url)
        if not isinstance(product_data, dict) or not product_data.get('title'):
            raise ValueError('El endpoint Ajax de Shopify no devolvió un producto Lapierre válido.')

        canonical_url = self._absolute_url(product_data.get('url'), product_url) or product_url
        if html_context:
            canonical_url = html_context.get('canonical_url') or canonical_url
        canonical_url = self._clean_product_url(canonical_url)
        # Algunos temas Shopify devuelven ``/products/<handle>`` aunque el
        # endpoint consultado esté localizado. Se conserva la URL española de
        # origen en ese caso para no rechazar una respuesta válida.
        if not self._is_product_url(canonical_url):
            fallback_url = self._clean_product_url(product_url)
            if self._is_product_url(fallback_url):
                canonical_url = fallback_url
            else:
                raise ValueError(
                    'El endpoint Ajax devolvió una URL que no es producto Lapierre España.'
                )

        title = str(product_data.get('title') or '').strip()
        visible_title = html_context.get('visible_title') if html_context else False
        name = visible_title or title or canonical_url
        tree = html_context.get('tree') if html_context else None
        colors = self._colors_from_product(product_data)
        if not colors and html_context and html_context.get('selected_color'):
            colors = [html_context['selected_color']]
        style_code = self._style_code(product_data, canonical_url)
        images = self._shopify_images(product_data, canonical_url)
        price = self._money_from_cents(product_data.get('price'))

        description = product_data.get('description') or ''
        frame_sizes = self._frame_sizes_from_product(product_data)
        if frame_sizes and 'Tamaños de cuadro:' not in self._plain_text(description):
            description = (
                f'{description}\n<p><strong>Tamaños de cuadro:</strong> '
                f'{", ".join(frame_sizes)}</p>'
            ).strip()

        return {
            'name': name,
            'description': description,
            'price': price,
            'price_available': price > 0,
            'currency': 'EUR',
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical_url,
            'style_code': style_code,
            'color_code': ' / '.join(colors) or False,
            'ean_variants': self._ean_variants_from_shopify_product(product_data),
            'ean_complete': True,
            'category_path': self._category_path(product_data, tree, name, canonical_url),
        }

    def _preview_from_html(self, source, product_url, html_context=None):
        context = html_context or self._fetch_html_context(source, product_url)
        tree = context['tree']
        canonical_url = context['canonical_url']
        product_node = self._find_product_json_ld(tree)
        offers = product_node.get('offers') or {}
        if isinstance(offers, list):
            offers = next((item for item in offers if isinstance(item, dict)), {})

        name = (
            product_node.get('name')
            or context.get('visible_title')
            or context.get('seo_title')
            or product_url
        )
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
        style_code = self._style_code(pseudo_data, canonical_url)
        color = product_node.get('color') or context.get('selected_color')

        images = self._json_ld_images(product_node, canonical_url)
        for image_url in self._html_product_images(tree, canonical_url):
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
            'color_code': color or False,
            'ean_variants': self._ean_variants_from_html_content(context.get('content') or b''),
            'ean_complete': False,
            'category_path': self._category_path(pseudo_data, tree, name, canonical_url),
        }

    def fetch_preview(self, source, url):
        html_context = None
        try:
            html_context = self._fetch_html_context(source, url)
        except Exception as exc:
            _logger.info('Lapierre: no se pudo enriquecer la ficha HTML %s: %s', url, exc)

        try:
            return self._preview_from_ajax(source, url, html_context=html_context)
        except Exception as exc:
            _logger.info(
                'Lapierre: no se pudo usar el endpoint Ajax para %s (%s); se usa HTML.',
                url,
                exc,
            )
            return self._preview_from_html(source, url, html_context=html_context)
