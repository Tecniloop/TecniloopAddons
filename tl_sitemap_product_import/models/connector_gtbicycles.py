import logging
import re
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorGtBicycles(models.AbstractModel):
    """Conector del catálogo oficial de GT Bicycles.

    GT Bicycles usa Shopify. ``robots.txt`` declara el sitemap raíz y este
    enlaza los mapas de productos, colecciones, páginas y blog. Solo se siguen
    los mapas ``sitemap_products_*.xml`` y las fichas ``/products/<handle>``.

    El endpoint Ajax público ``/products/<handle>.js`` contiene opciones,
    variantes, SKU, disponibilidad, imágenes y ``barcode``. El catálogo oficial
    muestra muchos modelos únicamente con "Find a dealer"; cuando Shopify no
    publica un precio positivo se marca ``price_available=False`` para no borrar
    un precio introducido manualmente en Odoo.
    """

    _name = 'sitemap.connector.gtbicycles'
    _inherit = 'sitemap.connector.fluchos_es'
    _description = 'Conector GT Bicycles'

    _HOSTS = {'gtbicycles.com', 'www.gtbicycles.com'}
    _PRODUCT_PATH_RE = re.compile(r'^/products/(?P<handle>[^/]+)/?$', re.IGNORECASE)

    _BIKE_RULES = (
        (('electric', 'e-bike', 'ebike', 'egrade'), ('Bicicletas eléctricas',)),
        (('youth', 'kids', 'kid', 'stomper', 'sidewalk'), ('Bicicletas infantiles',)),
        (('downhill', 'fury'), ('Bicicletas', 'Montaña', 'Downhill')),
        (('enduro', 'force carbon'), ('Bicicletas', 'Montaña', 'Enduro')),
        (('trail', 'sensor', 'zaskar lt'), ('Bicicletas', 'Montaña', 'Trail')),
        (('dirt jump', 'labomba'), ('Bicicletas', 'Montaña', 'Dirt Jump')),
        (('hardtail', 'avalanche', 'aggressor', 'zaskar'), ('Bicicletas', 'Montaña', 'Hardtail')),
        (('mountain', 'mtb'), ('Bicicletas', 'Montaña')),
        (('bmx race', 'race bmx'), ('Bicicletas BMX', 'Race')),
        (('bmx freestyle', 'freestyle bmx'), ('Bicicletas BMX', 'Freestyle')),
        (('big wheel', 'bikelife', 'pro series 29', 'performer 29'), ('Bicicletas BMX', 'Big Wheel')),
        (('bmx', 'performer'), ('Bicicletas BMX',)),
        (('frameset', 'frame set'), ('Cuadros',)),
        (('gravel', 'grade'), ('Bicicletas', 'Gravel')),
    )

    _PART_RULES = (
        (('crank', 'bottom bracket', 'cranks/bb'), 'Bielas y pedalieres'),
        (('grip', 'barend', 'bar end'), 'Puños y tapones'),
        (('handlebar', 'bar '), 'Manillares'),
        (('hub', 'hubguard'), 'Bujes y protectores'),
        (('pad set', 'pads'), 'Protectores'),
        (('peg',), 'Pegs'),
        (('pedal',), 'Pedales'),
        (('saddle', 'seat '), 'Sillines'),
        (('seatpost', 'seat post'), 'Tijas'),
        (('sprocket',), 'Platos'),
        (('stem',), 'Potencias'),
        (('tire', 'tyre'), 'Neumáticos'),
        (('wheel', 'rim'), 'Ruedas y llantas'),
        (('apparel', 'shirt', 'jersey', 'hoodie', 'hat', 'cap'), 'Ropa'),
    )

    # ------------------------------------------------------------------
    # Sitemap y URL
    # ------------------------------------------------------------------
    @classmethod
    def _is_product_url(cls, url):
        parsed = urlparse(str(url or ''))
        host = parsed.netloc.lower().split(':', 1)[0]
        return host in cls._HOSTS and bool(cls._PRODUCT_PATH_RE.match(parsed.path or ''))

    @staticmethod
    def _clean_product_url(url):
        parts = urlsplit(str(url or '').strip())
        host = parts.netloc.lower().split(':', 1)[0]
        if host == 'www.gtbicycles.com':
            host = 'gtbicycles.com'
        path = re.sub(r'/+', '/', parts.path or '/').rstrip('/')
        return urlunsplit((parts.scheme or 'https', host, path, '', ''))

    @staticmethod
    def parse_category_path(url):
        return []

    @staticmethod
    def _robots_sitemaps(text, base_url):
        result = []
        for match in re.finditer(r'(?im)^\s*Sitemap\s*:\s*(\S+)', text or ''):
            value = match.group(1).strip().rstrip(';,')
            absolute = urljoin(base_url, value)
            if absolute not in result:
                result.append(absolute)
        # Algunos robots generados por Shopify pueden llegar sin saltos de línea.
        if not result:
            for match in re.finditer(r'(?i)\bSitemap\s*:\s*(https?://\S+)', text or ''):
                value = match.group(1).strip().rstrip(';,')
                if value not in result:
                    result.append(value)
        return result

    def _discover_product_sitemaps(self, source):
        configured = str(source.sitemap_index_url or '').strip()
        session = self._get_session(source)
        candidates = []
        if configured.casefold().endswith('/robots.txt'):
            response = self._http_get(session, configured, source)
            candidates.extend(self._robots_sitemaps(response.text, response.url))
        elif configured:
            candidates.append(configured)

        candidates.extend([
            'https://gtbicycles.com/sitemap.xml',
            'https://www.gtbicycles.com/sitemap.xml',
        ])
        pending = [(value, 0) for value in dict.fromkeys(candidates) if value]
        visited = set()
        result = []

        while pending:
            sitemap_url, depth = pending.pop(0)
            if sitemap_url in visited or depth > 5:
                continue
            visited.add(sitemap_url)
            try:
                response = self._http_get(session, sitemap_url, source)
                root = self._xml_root(response.content)
            except Exception as exc:
                _logger.info('GT Bicycles: sitemap no accesible %s: %s', sitemap_url, exc)
                continue

            local_name = root.tag.rsplit('}', 1)[-1].casefold()
            if local_name == 'urlset':
                result.append(sitemap_url)
                continue
            if local_name != 'sitemapindex':
                continue

            children = [
                str(value).strip()
                for value in root.xpath(
                    './*[local-name()="sitemap"]/*[local-name()="loc"]/text()'
                )
                if str(value).strip()
            ]
            product_maps = [
                value for value in children
                if 'sitemap_products_' in value.casefold()
            ]
            if product_maps:
                result.extend(product_maps)
            else:
                pending.extend(
                    (urljoin(sitemap_url, value), depth + 1)
                    for value in children
                    if 'sitemap' in value.casefold()
                )

        result = list(dict.fromkeys(result))
        if not result:
            raise ValueError('No se encontraron sitemaps de producto de GT Bicycles.')
        return result

    # ------------------------------------------------------------------
    # Referencias, opciones y categorías
    # ------------------------------------------------------------------
    @classmethod
    def _extract_style_code(cls, product_data, title, product_url):
        prefix = cls._common_variant_sku_prefix(product_data)
        if prefix:
            return prefix
        skus = [
            str(variant.get('sku') or '').strip().upper()
            for variant in product_data.get('variants') or []
            if str(variant.get('sku') or '').strip()
        ]
        if len(set(skus)) == 1:
            return skus[0]
        handle = product_data.get('handle') or urlparse(product_url).path.rstrip('/').split('/')[-1]
        return str(handle or '').strip().upper() or False

    @classmethod
    def _extract_reference_from_text(cls, text):
        # Las menciones "Part #" de las fichas suelen corresponder a recambios
        # recomendados (p. ej. una patilla), no a la bicicleta mostrada.
        return False

    @staticmethod
    def _option_names(product_data):
        names = []
        for option in product_data.get('options') or []:
            if isinstance(option, dict):
                names.append(str(option.get('name') or '').strip())
            else:
                names.append(str(option or '').strip())
        return names

    @classmethod
    def _option_values(cls, product_data, aliases):
        names = cls._option_names(product_data)
        indexes = [
            index for index, name in enumerate(names)
            if any(alias in name.casefold() for alias in aliases)
        ]
        result = []
        for variant in product_data.get('variants') or []:
            values = variant.get('options') or []
            if not isinstance(values, list):
                values = [variant.get('option1'), variant.get('option2'), variant.get('option3')]
            for index in indexes:
                if index >= len(values):
                    continue
                value = str(values[index] or '').strip()
                if value and value.casefold() != 'default title' and value not in result:
                    result.append(value)
        return result

    @classmethod
    def _category_path(cls, product_data, product_url, title=''):
        tags = cls._tag_strings(product_data)
        product_type = str(product_data.get('type') or '').strip()
        text = ' '.join([
            str(title or ''),
            product_type,
            ' '.join(tags),
            urlparse(product_url).path.replace('-', ' '),
        ]).casefold()

        for tokens, path in cls._BIKE_RULES:
            if any(token in text for token in tokens):
                segments = list(path)
                if segments == ['Bicicletas eléctricas']:
                    if any(token in text for token in ('gravel', 'grade')):
                        segments.append('Gravel')
                    elif any(token in text for token in ('mountain', 'sensor', 'force', 'avalanche')):
                        segments.append('Montaña')
                return ' / '.join(segments)

        for tokens, label in cls._PART_RULES:
            if any(token in text for token in tokens):
                root = 'Equipamiento' if label == 'Ropa' else 'Componentes'
                return f'{root} / {label}'

        if any(token in text for token in ('part', 'gear', 'component', 'accessor')):
            return 'Componentes'
        if product_type and product_type.casefold() not in {'product', 'bike', 'bikes'}:
            return f'Catálogo GT / {product_type}'
        return 'Bicicletas'

    # ------------------------------------------------------------------
    # Vista previa Shopify
    # ------------------------------------------------------------------
    def _preview_from_ajax(self, source, product_url, html_context=None):
        product_data = self._fetch_shopify_product_payload(source, product_url)
        if not isinstance(product_data, dict) or not product_data.get('title'):
            raise ValueError('El endpoint Ajax de Shopify no devolvió un producto GT válido.')

        canonical_url = self._absolute_url(product_data.get('url'), product_url) or product_url
        if html_context:
            canonical_url = html_context.get('canonical_url') or canonical_url
        canonical_url = self._clean_product_url(canonical_url)
        if not self._is_product_url(canonical_url):
            raise ValueError('El endpoint Ajax redirigió a una URL que no es producto GT.')

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
        colors = self._option_values(product_data, ('color', 'colour'))
        sizes = self._option_values(product_data, ('size', 'talla', 'frame size'))
        style_code = self._extract_style_code(
            product_data, visible_title or title, canonical_url
        )
        price = self._money_from_cents(product_data.get('price'))
        currency = str(product_data.get('currency') or '').strip().upper()
        if not currency and html_context:
            tree = html_context.get('tree')
            if tree is not None:
                currency = (
                    self._meta(tree, 'product:price:currency')
                    or self._meta(tree, 'og:price:currency')
                    or ''
                ).strip().upper()
        currency = currency or 'USD'

        description = product_data.get('description') or ''
        extra = []
        if colors:
            extra.append('<p><strong>Colores:</strong> %s</p>' % ', '.join(colors))
        if sizes:
            extra.append('<p><strong>Tallas:</strong> %s</p>' % ', '.join(sizes))
        if extra:
            description = f'{description}{"".join(extra)}'

        return {
            'name': visible_title or title or product_url,
            'description': description,
            'price': price,
            'price_available': price > 0,
            'currency': currency,
            'main_image_url': featured or (images[0] if images else False),
            'image_urls': images,
            'canonical_url': canonical_url,
            'style_code': style_code,
            'color_code': ' / '.join(colors) or False,
            'ean_variants': self._ean_variants_from_shopify_product(product_data),
            'ean_complete': True,
            'category_path': self._category_path(
                product_data, canonical_url, visible_title or title
            ),
        }

    def fetch_preview(self, source, url):
        html_context = None
        try:
            html_context = self._fetch_html_context(source, url)
        except Exception as exc:
            _logger.info('GT Bicycles: no se pudo enriquecer el HTML %s: %s', url, exc)

        try:
            return self._preview_from_ajax(source, url, html_context=html_context)
        except Exception as exc:
            _logger.info(
                'GT Bicycles: Ajax no disponible para %s (%s); se usa HTML.',
                url,
                exc,
            )
            data = self._preview_from_html(source, url, html_context=html_context)
            # El catálogo oficial puede no publicar precio y limitarse a localizar
            # distribuidores. El flujo base conservará cualquier precio manual.
            if not data.get('price'):
                data['price_available'] = False
            data['currency'] = data.get('currency') or 'USD'
            data['category_path'] = self._category_path(
                {
                    'title': data.get('name'),
                    'type': '',
                    'tags': [],
                    'variants': [],
                },
                data.get('canonical_url') or url,
                data.get('name'),
            )
            return data
