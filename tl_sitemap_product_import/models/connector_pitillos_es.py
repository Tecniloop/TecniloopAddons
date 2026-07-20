import logging
import re
from urllib.parse import urljoin, urlparse

from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorPitillosEs(models.AbstractModel):
    """Connector for calzadospitillos.com (Spanish Shopify catalogue).

    The Shopify sitemap is traversed through the Fluchos connector implementation,
    but this connector applies Pitillos-specific host validation, model parsing,
    category rules and product characteristics.
    """

    _name = 'sitemap.connector.pitillos_es'
    _inherit = 'sitemap.connector.fluchos_es'
    _description = 'Conector Pitillos Espa\u00f1a'

    _PRODUCT_PATH_RE = re.compile(r'^/products/[^/]+/?$', re.IGNORECASE)
    _STYLE_RE = re.compile(r'\b(\d{4,5})\b')
    _REFERENCE_RE = re.compile(
        r'Modelo\s*:\s*([A-Z0-9][A-Z0-9._/-]{2,40})',
        re.IGNORECASE,
    )

    _TYPE_RULES = (
        (('deportivo', 'deportiva', 'sneaker', 'zapatilla', 'basket'), 'Deportivos y zapatillas'),
        (('mocasin', 'mocas\u00edn', 'loafer'), 'Mocasines y n\u00e1uticos'),
        (('nautico', 'n\u00e1utico'), 'Mocasines y n\u00e1uticos'),
        (('oxford', 'blucher', 'cordon', 'cordones'), 'Bluchers y zapatos con cordones'),
        (('sandalia',), 'Sandalias'),
        (('alpargata',), 'Alpargatas'),
        (('bailarina', 'manoletina'), 'Bailarinas'),
        (('mercedita', 'mercedes'), 'Merceditas'),
        (('salon', 'sal\u00f3n', 'tacon', 'tac\u00f3n'), 'Zapatos con tac\u00f3n'),
        (('botin', 'bot\u00edn'), 'Botines'),
        (('bota',), 'Botas'),
        (('zueco',), 'Zuecos'),
        (('slip on', 'slip-on', 'slipon'), 'Slip on'),
        (('bolso', 'neceser'), 'Accesorios'),
        (('plantilla',), 'Plantillas'),
        (('zapato',), 'Zapatos'),
    )

    _COLOR_NAMES = (
        ('Blanco/Plata', ('blanco/plata', 'blanco plata')),
        ('Marino/Plata', ('marino/plata', 'marino plata')),
        ('Negro/Glacial', ('negro/glacial', 'negro glacial')),
        ('Negro/Nude', ('negro/nude', 'negro nude')),
        ('Nude/Oro', ('nude/oro', 'nude oro')),
        ('Taupe/Crema', ('taupe/crema', 'taupe crema')),
        ('Metales/Blanco', ('metales/blanco', 'metales blanco')),
        ('Plata vieja', ('plata vieja', 'plata viej')),
        ('Multimetal', ('multimetal',)),
        ('Azul marino', ('azul marino', 'marino')),
        ('Marr\u00f3n', ('marron', 'marr\u00f3n')),
        ('Negro', ('negro', 'black')),
        ('Blanco', ('blanco', 'white')),
        ('Crema', ('crema', 'cream')),
        ('Glacial', ('glacial',)),
        ('Hielo', ('hielo',)),
        ('Arena', ('arena',)),
        ('Camel', ('camel',)),
        ('Cuero', ('cuero',)),
        ('Nude', ('nude',)),
        ('Oro', ('oro', 'dorado', 'gold')),
        ('Plata', ('plata', 'silver')),
        ('Bronce', ('bronce', 'bronze')),
        ('Burdeos', ('burdeos', 'borgona')),
        ('L\u00edbano', ('libano', 'l\u00edbano')),
        ('Oliva', ('oliva',)),
        ('Kaki', ('kaki', 'khaki')),
        ('Piedra', ('piedra',)),
        ('Taupe', ('taupe',)),
        ('Natural', ('natural',)),
        ('Jeans', ('jeans', 'denim')),
        ('Celeste', ('celeste',)),
        ('Turquesa', ('turquesa',)),
        ('Fuxia', ('fuxia', 'fucsia')),
        ('Rojo', ('rojo', 'red')),
        ('Naranja', ('naranja', 'orange')),
        ('Mostaza', ('mostaza',)),
        ('Ma\u00edz', ('maiz', 'ma\u00edz')),
        ('Verde', ('verde', 'green')),
        ('Azul', ('azul', 'blue')),
        ('Gris', ('gris', 'grey', 'gray')),
    )

    _CHARACTERISTIC_LABELS = (
        'Altura cu\u00f1a',
        'Etiqueta composici\u00f3n',
        'G\u00e9nero',
        'Altura del piso',
        'Cremallera',
        'Velcro',
        'Cordones',
        'Color',
        'Tipo de piso',
        'Altura tac\u00f3n',
        'Plantilla',
        'Plantilla extra\u00edble',
        'Forro',
        'Suela',
        'Material',
    )

    @classmethod
    def _is_product_url(cls, url):
        parsed = urlparse(url)
        host = parsed.netloc.lower().split(':', 1)[0]
        path = parsed.path or ''
        return (
            host in {'calzadospitillos.com', 'www.calzadospitillos.com'}
            and not path.lower().startswith(('/en/', '/it/', '/fr/'))
            and bool(cls._PRODUCT_PATH_RE.match(path))
        )

    @classmethod
    def _extract_style_code(cls, product_data, title, product_url):
        sku_prefix = cls._common_variant_sku_prefix(product_data)
        if sku_prefix:
            style, _color = cls._model_parts(sku_prefix)
            if style:
                return style
        for candidate in (title, product_data.get('title')):
            match = cls._STYLE_RE.search(str(candidate or '').upper())
            if match:
                return match.group(1).upper()
        handle = product_data.get('handle') or urlparse(product_url).path.rstrip('/').split('/')[-1]
        return str(handle or '').upper() or False

    @classmethod
    def _extract_characteristics(cls, page_text):
        text = ' '.join(str(page_text or '').split())
        marker = re.search(r'Caracter(?:\u00ed|i)sticas', text, flags=re.IGNORECASE)
        if marker:
            text = text[marker.end():]
        end = re.search(r'M\u00e1s detalles|Mi cesta', text, flags=re.IGNORECASE)
        if end:
            text = text[:end.start()]

        escaped = '|'.join(
            sorted((re.escape(label) for label in cls._CHARACTERISTIC_LABELS), key=len, reverse=True)
        )
        pattern = re.compile(
            rf'(?P<label>{escaped})\s*:\s*(?P<value>.*?)(?=(?:{escaped})\s*:|$)',
            flags=re.IGNORECASE,
        )
        result = {}
        canonical = {label.casefold(): label for label in cls._CHARACTERISTIC_LABELS}
        for match in pattern.finditer(text):
            label = canonical.get(match.group('label').casefold(), match.group('label'))
            value = ' '.join(match.group('value').split()).strip(' -:;,.')
            if value and len(value) <= 500:
                result[label] = value
        return result

    @staticmethod
    def _model_parts(reference, selected_color=False):
        reference = str(reference or '').strip().upper()
        style = False
        suffix = False
        if reference:
            match = re.match(r'^([A-Z0-9]+?)[-_/]([A-Z0-9][A-Z0-9._/-]*)$', reference)
            if match:
                style, suffix = match.group(1), match.group(2)
            else:
                style = reference
        color = str(selected_color or suffix or '').strip().upper() or False
        return style or False, color

    @classmethod
    def _characteristic_value(cls, characteristics, label):
        wanted = label.casefold()
        for key, value in (characteristics or {}).items():
            if str(key).casefold() == wanted:
                return value
        return False

    @classmethod
    def _category_from_context(cls, data, context):
        title = str(data.get('name') or context.get('visible_title') or '')
        characteristics = context.get('characteristics') or {}
        gender = cls._characteristic_value(characteristics, 'G\u00e9nero')
        if gender:
            gender = str(gender).strip().title()

        text = ' '.join((title, str(data.get('category_path') or ''))).casefold()
        product_type = False
        for tokens, label in cls._TYPE_RULES:
            if any(token in text for token in tokens):
                product_type = label
                break

        old_segments = [segment.strip() for segment in str(data.get('category_path') or '').split('/') if segment.strip()]
        if not gender:
            for segment in old_segments:
                if segment.casefold() in {'mujer', 'hombre', 'nina', 'ni\u00f1a', 'nino', 'ni\u00f1o'}:
                    gender = segment
                    break
        if not product_type:
            for segment in reversed(old_segments):
                if not gender or segment.casefold() != gender.casefold():
                    product_type = segment
                    break

        return '/'.join(value for value in (gender, product_type or 'Calzado') if value)

    @classmethod
    def _description_with_characteristics(cls, description, characteristics):
        items = []
        for label in cls._CHARACTERISTIC_LABELS:
            value = cls._characteristic_value(characteristics, label)
            if value:
                items.append(f'<li><strong>{label}:</strong> {value}</li>')
        if not items:
            return description or ''
        block = '<p><strong>Caracter\u00edsticas</strong></p><ul>%s</ul>' % ''.join(items)
        return '%s%s' % (description or '', block)

    def _fetch_html_context(self, source, product_url):
        session = self._get_session(source)
        response = self._http_get(session, product_url, source)
        tree = lxml_html.fromstring(response.content)
        canonical_url = self._clean_product_url(self._canonical_url(tree, product_url))
        if not self._is_product_url(canonical_url):
            raise ValueError(
                'La URL ya no apunta a una ficha de producto Pitillos; '
                'posible redirecci\u00f3n o producto descatalogado.'
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
        characteristics = self._extract_characteristics(page_text)
        characteristics.setdefault('Color', selected_color or '')
        return {
            'tree': tree,
            'canonical_url': canonical_url,
            'visible_title': visible_title,
            'seo_title': self._meta(tree, 'og:title') or '',
            'page_text': page_text,
            'article_reference': reference,
            'selected_color': selected_color,
            'characteristics': characteristics,
        }

    def _normalise_preview(self, data, context):
        reference = context.get('article_reference') or False
        characteristics = context.get('characteristics') or {}
        selected_color = (
            context.get('selected_color')
            or self._characteristic_value(characteristics, 'Color')
            or data.get('color_code')
        )
        style, color = self._model_parts(reference, selected_color)
        if style:
            data['style_code'] = style
        if color:
            data['color_code'] = color
        data['category_path'] = self._category_from_context(data, context)
        data['description'] = self._description_with_characteristics(
            data.get('description'), characteristics
        )
        return data

    def fetch_preview(self, source, url):
        html_context = None
        try:
            html_context = self._fetch_html_context(source, url)
        except Exception as exc:
            _logger.info('Pitillos: no se pudo enriquecer la ficha HTML %s: %s', url, exc)

        try:
            data = self._preview_from_ajax(source, url, html_context=html_context)
        except Exception as exc:
            _logger.info(
                'Pitillos: no se pudo usar el endpoint Ajax para %s (%s); se usa HTML.',
                url,
                exc,
            )
            data = self._preview_from_html(source, url, html_context=html_context)

        if html_context:
            data = self._normalise_preview(data, html_context)
        return data
