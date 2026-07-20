import json
import logging
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorGioseppoEs(models.AbstractModel):
    """Conector para Gioseppo España (Shopify con sitemaps en robots.txt).

    Gioseppo publica en ``robots.txt`` los sitemaps de cada mercado. Este
    conector descubre en cada ejecución únicamente las directivas españolas
    ``/es-es/sitemap_products_*.xml``. De este modo no depende de que los
    parámetros ``from``/``to`` de Shopify permanezcan estables y evita mezclar
    colecciones, páginas, blog u otros países.

    Las fichas se leen primero mediante el endpoint Ajax público de Shopify
    ``/es-es/products/<handle>.js``. El HTML se usa para obtener la referencia
    visible ``REF: <estilo>-<color>``, la ruta de migas de pan y para validar
    que la URL canónica siga apuntando a un producto español.
    """

    _name = 'sitemap.connector.gioseppo_es'
    _inherit = 'sitemap.connector.fluchos_es'
    _description = 'Conector Gioseppo España'

    _PRODUCT_PATH_RE = re.compile(r'^/es-es/products/[^/]+/?$', re.IGNORECASE)
    _STYLE_RE = re.compile(r'(?<!\d)(\d{4,6})(?!\d)')
    _REFERENCE_RE = re.compile(
        r'\bREF\s*:\s*([A-Z0-9][A-Z0-9._/-]{2,50})',
        re.IGNORECASE,
    )

    # Ordenadas desde las expresiones más específicas a las genéricas.
    _TYPE_RULES = (
        (('sandalias cangrejeras', 'cangrejera'), 'Sandalias cangrejeras'),
        (('botas de agua', 'bota de agua'), 'Botas de agua'),
        (('zapatillas de casa', 'estar por casa', 'slipper'), 'Zapatillas de casa'),
        (('zapato barefoot escolar',), 'Zapatos barefoot escolares'),
        (('zapatillas barefoot', 'barefoot sneakers'), 'Zapatillas barefoot'),
        (('sandalias barefoot',), 'Sandalias barefoot'),
        (('deportivo', 'deportiva', 'sneaker', 'zapatilla'), 'Zapatillas'),
        (('bailarina', 'mercedita', 'mary-jane', 'mary jane'), 'Bailarinas y merceditas'),
        (('mocasin', 'mocasín', 'loafer'), 'Mocasines'),
        (('nautico', 'náutico'), 'Náuticos'),
        (('alpargata', 'espadrille'), 'Alpargatas'),
        (('sandalia',), 'Sandalias'),
        (('botin', 'botín', 'ankle boot'), 'Botines'),
        (('bota',), 'Botas'),
        (('salon', 'salón', 'tacon', 'tacón', 'pump'), 'Zapatos de tacón'),
        (('colegial', 'school shoe'), 'Zapatos colegiales'),
        (('zapato', 'shoe'), 'Zapatos'),
        (('bolso', 'bandolera', 'shopper', 'mochila', 'bag'), 'Bolsos'),
        (('cartera', 'monedero', 'wallet'), 'Carteras y monederos'),
        (('cinturon', 'cinturón', 'belt'), 'Cinturones'),
        (('calcetin', 'calcetín', 'sock'), 'Calcetines'),
        (('gorra', 'sombrero', 'cap', 'hat'), 'Gorras y sombreros'),
        (('accesorio', 'accessories'), 'Accesorios'),
    )

    _TOP_CATEGORY_MAP = {
        'woman': 'Mujer',
        'women': 'Mujer',
        'mujer': 'Mujer',
        'man': 'Hombre',
        'men': 'Hombre',
        'hombre': 'Hombre',
        'girl': 'Niña',
        'girls': 'Niña',
        'niña': 'Niña',
        'nina': 'Niña',
        'boy': 'Niño',
        'boys': 'Niño',
        'niño': 'Niño',
        'nino': 'Niño',
        'baby': 'Bebé',
        'bebé': 'Bebé',
        'bebe': 'Bebé',
        'kids': 'Niños',
        'niños': 'Niños',
        'ninos': 'Niños',
        'accessories': 'Accesorios',
        'accesorios': 'Accesorios',
    }

    # ------------------------------------------------------------------
    # Descubrimiento a partir de robots.txt
    # ------------------------------------------------------------------
    @classmethod
    def _is_product_url(cls, url):
        parsed = urlparse(url)
        host = parsed.netloc.lower().split(':', 1)[0]
        path = parsed.path or ''
        return (
            host in {'gioseppo.com', 'www.gioseppo.com'}
            and bool(cls._PRODUCT_PATH_RE.match(path))
            and not path.casefold().endswith('-remote')
        )

    def _discover_product_sitemaps(self, source):
        source_url = str(source.sitemap_index_url or '').strip()
        parsed_source = urlparse(source_url)
        if parsed_source.path.rstrip('/').casefold().endswith('/robots.txt'):
            session = self._get_session(source)
            response = self._http_get(session, source_url, source)
            candidates = []
            for match in re.finditer(
                r'(?i)\bSitemap\s*:\s*(https?://\S+)',
                response.text or '',
            ):
                value = match.group(1).strip().rstrip(';,')
                parsed = urlparse(value)
                host = parsed.netloc.lower().split(':', 1)[0]
                path = parsed.path or ''
                if (
                    host in {'gioseppo.com', 'www.gioseppo.com'}
                    and re.fullmatch(
                        r'/es-es/sitemap_products_\d+\.xml',
                        path,
                        flags=re.IGNORECASE,
                    )
                ):
                    candidates.append(value)
            candidates = list(dict.fromkeys(candidates))
            if candidates:
                return candidates
            raise ValueError(
                'robots.txt no contiene directivas Sitemap de productos para el mercado /es-es/.'
            )
        return super()._discover_product_sitemaps(source)

    def get_image_map(self, source):
        # La vista previa ya conserva la galería completa obtenida del endpoint
        # Ajax de Shopify. Evitamos volver a descargar y recorrer los dos
        # sitemaps completos al importar unas pocas filas seleccionadas.
        return {}

    @staticmethod
    def _high_resolution_shopify_image(url):
        """Quita el recorte de miniatura y solicita una anchura máxima de 1600."""
        if not url:
            return False
        parts = urlsplit(url)
        query = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.casefold() not in {'width', 'height', 'crop'}
        ]
        query.append(('width', '1600'))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))

    # ------------------------------------------------------------------
    # Referencia, color y categorías
    # ------------------------------------------------------------------
    @staticmethod
    def _reference_parts(reference):
        reference = str(reference or '').strip().upper()
        if not reference:
            return False, False, False
        match = re.match(r'^(\d{4,6})(?:[-_/](.+))?$', reference)
        if not match:
            return reference, False, False
        style = match.group(1)
        color_code = (match.group(2) or '').strip('-_/') or False
        color_name = color_code
        if color_name:
            # En muchas referencias P es un separador interno, no el color.
            color_name = re.sub(r'^P[-_/]', '', color_name, flags=re.IGNORECASE)
            color_name = color_name.replace('_', ' ').replace('/', ' / ').replace('-', ' ')
            color_name = ' '.join(color_name.split()).title()
        return style, color_code, color_name or False

    @classmethod
    def _extract_style_code(cls, product_data, title, product_url):
        for variant in product_data.get('variants') or []:
            sku = str(variant.get('sku') or '').strip().upper()
            match = re.match(r'^(\d{4,6})(?:[-_/]|$)', sku)
            if match:
                return match.group(1)
        for candidate in (title, product_data.get('title')):
            match = cls._STYLE_RE.search(str(candidate or '').upper())
            if match:
                return match.group(1)
        # Se normaliza posteriormente con la REF visible del HTML.
        return super()._extract_style_code(product_data, title, product_url)

    @classmethod
    def _extract_selected_color(cls, tree, page_text, title):
        reference = cls._extract_reference_from_text(page_text)
        _style, _code, color_name = cls._reference_parts(reference)
        return color_name or super()._extract_selected_color(tree, page_text, title)

    @classmethod
    def _normalise_breadcrumb_segment(cls, value):
        value = ' '.join(str(value or '').split()).strip(' /›>')
        if not value:
            return False
        mapped = cls._TOP_CATEGORY_MAP.get(value.casefold())
        return mapped or value

    @classmethod
    def _iter_json_nodes_local(cls, value):
        if isinstance(value, dict):
            yield value
            if value.get('@graph'):
                yield from cls._iter_json_nodes_local(value['@graph'])
        elif isinstance(value, list):
            for item in value:
                yield from cls._iter_json_nodes_local(item)

    @classmethod
    def _extract_breadcrumb(cls, tree, current_title=''):
        segments = []
        for raw in tree.xpath('//script[@type="application/ld+json"]/text()'):
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                continue
            for node in cls._iter_json_nodes_local(payload):
                node_type = node.get('@type')
                types = node_type if isinstance(node_type, list) else [node_type]
                if not any(str(item).casefold() == 'breadcrumblist' for item in types if item):
                    continue
                ordered = []
                for entry in node.get('itemListElement') or []:
                    if not isinstance(entry, dict):
                        continue
                    item = entry.get('item')
                    name = entry.get('name')
                    if not name and isinstance(item, dict):
                        name = item.get('name')
                    try:
                        position = int(entry.get('position') or 9999)
                    except (TypeError, ValueError):
                        position = 9999
                    if name:
                        ordered.append((position, name))
                if ordered:
                    segments = [name for _position, name in sorted(ordered)]
                    break
            if segments:
                break

        if not segments:
            xpaths = (
                '//*[contains(concat(" ", normalize-space(@class), " "), " breadcrumb ")]//a//text()',
                '//*[contains(@class, "breadcrumbs")]//a//text()',
                '//nav[contains(@aria-label, "readcrumb")]//a//text()',
            )
            for xpath in xpaths:
                values = [' '.join(str(v).split()) for v in tree.xpath(xpath)]
                values = [value for value in values if value]
                if values:
                    segments = values
                    break

        result = []
        current_key = ' '.join(str(current_title or '').split()).casefold()
        for raw in segments:
            segment = cls._normalise_breadcrumb_segment(raw)
            if not segment:
                continue
            key = segment.casefold()
            if key in {'inicio', 'home', 'gioseppo'} or key == current_key:
                continue
            if not result or result[-1].casefold() != key:
                result.append(segment)
        return result

    @classmethod
    def _category_path(cls, product_data, product_url, title=''):
        base = super()._category_path(product_data, product_url, title)
        tags = cls._tag_strings(product_data)
        text = ' '.join([
            str(title or ''),
            str(product_data.get('type') or ''),
            ' '.join(tags),
            urlparse(product_url).path.replace('-', ' '),
        ]).casefold()
        segments = [segment.strip() for segment in str(base or '').split('/') if segment.strip()]

        collection = False
        if 'barefoot' in text:
            collection = 'Barefoot'
        elif 'la siesta' in text or 'la_siesta' in text:
            collection = 'La Siesta'
        elif 'hot potatoes' in text or 'hot_potatoes' in text:
            collection = 'Hot Potatoes'

        if collection and collection.casefold() not in {segment.casefold() for segment in segments}:
            insert_at = 1 if segments and segments[0] in {
                'Mujer', 'Hombre', 'Niña', 'Niño', 'Bebé', 'Niños'
            } else 0
            segments.insert(insert_at, collection)
        return ' / '.join(segments)

    def _fetch_html_context(self, source, product_url):
        context = super()._fetch_html_context(source, product_url)
        context['breadcrumb_segments'] = self._extract_breadcrumb(
            context['tree'], context.get('visible_title') or context.get('seo_title') or ''
        )
        return context

    @classmethod
    def _category_from_context(cls, data, context):
        breadcrumb = list(context.get('breadcrumb_segments') or [])
        fallback = [
            segment.strip()
            for segment in str(data.get('category_path') or '').split('/')
            if segment.strip()
        ]
        if not breadcrumb:
            return ' / '.join(fallback)

        # Muchas fichas solo muestran "Woman"/"Girl" en la miga. En ese caso
        # completamos con el tipo deducido de las etiquetas Shopify.
        existing = {segment.casefold() for segment in breadcrumb}
        for segment in fallback:
            if segment.casefold() not in existing:
                breadcrumb.append(segment)
                existing.add(segment.casefold())
        return ' / '.join(breadcrumb)

    def _normalise_preview(self, data, context):
        reference = context.get('article_reference') or False
        style, color_code, _color_name = self._reference_parts(reference)
        if style:
            data['style_code'] = style
        if color_code:
            data['color_code'] = color_code
        data['category_path'] = self._category_from_context(data, context)
        return data

    def fetch_preview(self, source, url):
        html_context = None
        try:
            html_context = self._fetch_html_context(source, url)
        except Exception as exc:
            _logger.info('Gioseppo: no se pudo enriquecer la ficha HTML %s: %s', url, exc)

        try:
            data = self._preview_from_ajax(source, url, html_context=html_context)
        except Exception as exc:
            _logger.info(
                'Gioseppo: no se pudo usar el endpoint Ajax para %s (%s); se usa HTML.',
                url,
                exc,
            )
            data = self._preview_from_html(source, url, html_context=html_context)

        if html_context:
            data = self._normalise_preview(data, html_context)
        return data
