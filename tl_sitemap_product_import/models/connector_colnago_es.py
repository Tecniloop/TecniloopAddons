import gzip
import html
import json
import logging
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorColnagoEs(models.AbstractModel):
    """Conector del mercado español de Colnago.

    Colnago utiliza Shopify para su catálogo comercial, pero combina dos
    clases de ficha:

    * productos Shopify estándar bajo ``/es-es/products/<handle>``;
    * páginas de modelo de gama alta bajo ``/es-es/premium-bikes/<handle>``.

    Las fichas Shopify se consultan primero mediante el endpoint Ajax ``.js``
    para obtener precio, SKU, opciones, imágenes y ``barcode`` por variante.
    Las páginas premium se procesan desde HTML, JSON-LD y JSON incrustado.
    En ambos casos los GTIN solo se aceptan si superan la validación GS1 del
    servicio base y se conservan por montaje/talla cuando hay más de uno.
    """

    _name = 'sitemap.connector.colnago_es'
    _inherit = 'sitemap.connector.fluchos_es'
    _description = 'Conector Colnago España'

    _HOSTS = {'colnago.com', 'www.colnago.com'}
    _PRODUCT_PATH_RE = re.compile(
        r'^/es-es/(?P<section>products|premium-bikes)/(?P<handle>[^/]+)/?$',
        re.IGNORECASE,
    )
    _MODEL_CODE_RE = re.compile(
        r'\b(C72|C68|V5RS|V4RS|V4|Y1RS|G4-X|TT2|TT1|T1RS|MASTER|STEELNOVO)\b',
        re.IGNORECASE,
    )
    _PRICE_RE = re.compile(r'(?<!\d)(\d[\d.,\s]*)\s*€')
    _IMAGE_EXT_RE = re.compile(r'\.(?:avif|gif|jpe?g|png|webp)(?:$|\?)', re.IGNORECASE)
    _NON_PRODUCT_IMAGE_RE = re.compile(
        r'(?:logo|favicon|icon|sprite|cookie|newsletter|social|payment|flag|'
        r'arrow|loader|placeholder|avatar|footer|header|menu|nav|country|'
        r'language|dealer|retailer|store-locator|blog|article|author)',
        re.IGNORECASE,
    )

    _PREMIUM_MODEL_NAMES = {
        'c72-road-bike': 'C72 Road',
        'c68-road-bike': 'C68 Road',
        'c68-allroad-bike': 'C68 Allroad',
        'c68-gravel-bike': 'C68 Gravel',
        'v5rs-bike': 'V5Rs',
        'v4rs-bike': 'V4Rs',
        'y1rs-bike': 'Y1Rs',
    }
    _PRODUCT_MODEL_NAMES = {
        'bicicleta-v4': 'V4',
        'bicicleta-master': 'Master',
        'bicicleta-steelnovo': 'Steelnovo',
        'bicicleta-tt1': 'TT1',
        't1rs-track-bike': 'T1Rs',
        'bicicleta-g4-x': 'G4-X',
        'g4-x': 'G4-X',
        'tt2': 'TT2',
    }

    # ------------------------------------------------------------------
    # HTTP, URL y sitemap
    # ------------------------------------------------------------------
    def _get_session(self, source):
        session = super()._get_session(source)
        session.headers.update({
            'Accept': (
                'text/html,application/xhtml+xml,application/xml;q=0.9,'
                'image/avif,image/webp,*/*;q=0.8'
            ),
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.5',
            'Cache-Control': 'no-cache',
        })
        return session

    @staticmethod
    def _xml_root(content):
        payload = content or b''
        if payload[:2] == b'\x1f\x8b':
            payload = gzip.decompress(payload)
        parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
        return etree.fromstring(payload, parser=parser)

    @classmethod
    def _clean_product_url(cls, value):
        raw = html.unescape(str(value or '')).strip().replace('\\/', '/')
        if not raw:
            return False
        parts = urlsplit(raw)
        host = parts.netloc.lower().split(':', 1)[0]
        if host == 'colnago.com':
            host = 'www.colnago.com'
        path = re.sub(r'/+', '/', parts.path or '/')
        path = re.sub(r'^/es[-_]es/', '/es-es/', path, flags=re.IGNORECASE)
        if path != '/':
            path = path.rstrip('/')
        return urlunsplit((parts.scheme or 'https', host, path, '', ''))

    @classmethod
    def _is_product_url(cls, value):
        canonical = cls._clean_product_url(value)
        if not canonical:
            return False
        parsed = urlparse(canonical)
        return (
            parsed.netloc.lower().split(':', 1)[0] in cls._HOSTS
            and bool(cls._PRODUCT_PATH_RE.match(parsed.path or ''))
        )

    @classmethod
    def _product_parts(cls, value):
        canonical = cls._clean_product_url(value)
        match = cls._PRODUCT_PATH_RE.match(urlparse(canonical or '').path or '')
        if not match:
            return False, False
        return match.group('section').lower(), match.group('handle').lower()

    @staticmethod
    def parse_category_path(url):
        # Las rutas de producto de Shopify son planas. La categoría se obtiene
        # de las migas de pan, el tipo, las etiquetas o el modelo.
        return []

    def _iter_sitemap_entries(self, source, sitemap_url, depth=0, visited=None):
        if depth > 10:
            raise ValueError('El sitemap de Colnago supera diez niveles de índices.')
        visited = visited or set()
        parts = urlsplit(sitemap_url)
        clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))
        if clean_url in visited:
            return
        visited.add(clean_url)

        session = self._get_session(source)
        response = self._http_get(session, clean_url, source)
        try:
            root = self._xml_root(response.content)
        except (OSError, ValueError, etree.XMLSyntaxError) as exc:
            raise ValueError(f'Colnago no devolvió XML válido en {clean_url}.') from exc

        root_name = etree.QName(root).localname.lower()
        if root_name == 'sitemapindex':
            for child_url in root.xpath(
                './*[local-name()="sitemap"]/*[local-name()="loc"]/text()'
            ):
                child_url = str(child_url or '').strip()
                if child_url:
                    yield from self._iter_sitemap_entries(
                        source,
                        urljoin(clean_url, child_url),
                        depth=depth + 1,
                        visited=visited,
                    )
            return

        if root_name != 'urlset':
            raise ValueError('El sitemap de Colnago no contiene <urlset> ni <sitemapindex>.')

        for url_element in root.xpath('./*[local-name()="url"]'):
            alternates = url_element.xpath(
                './*[local-name()="link" and '
                'translate(@hreflang,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")='
                '"es-es"]/@href'
            )
            loc_values = url_element.xpath('./*[local-name()="loc"]/text()')
            product_url = False
            for candidate in [*alternates, *loc_values]:
                canonical = self._clean_product_url(candidate)
                if self._is_product_url(canonical):
                    product_url = canonical
                    break
            if not product_url:
                continue

            lastmod_values = url_element.xpath('./*[local-name()="lastmod"]/text()')
            image_values = url_element.xpath(
                './/*[local-name()="image"]/*[local-name()="loc"]/text()'
            )
            yield {
                'url': product_url,
                'lastmod': self._parse_lastmod(
                    lastmod_values[0].strip() if lastmod_values else False
                ),
            }, [str(value).strip() for value in image_values if str(value).strip()]

    def _collect_sitemap_products(self, source):
        entries = {}
        images = {}
        for entry, raw_images in self._iter_sitemap_entries(
            source, source.sitemap_index_url
        ):
            product_url = self._clean_product_url(entry.get('url'))
            if not self._is_product_url(product_url):
                continue
            current = entries.get(product_url)
            if not current:
                entries[product_url] = {
                    'url': product_url,
                    'lastmod': entry.get('lastmod') or False,
                }
            elif entry.get('lastmod') and (
                not current.get('lastmod') or entry['lastmod'] > current['lastmod']
            ):
                current['lastmod'] = entry['lastmod']

            target = images.setdefault(product_url, [])
            for value in raw_images:
                image_url = self._clean_image_url(value, product_url)
                if image_url and image_url not in target:
                    target.append(image_url)
        return list(entries.values()), images

    def get_product_entries(self, source, category_filter=None, limit=0):
        entries, _images = self._collect_sitemap_products(source)
        needle = str(category_filter or '').strip().casefold()
        result = []
        for entry in entries:
            if needle and needle not in entry['url'].casefold():
                continue
            result.append(entry)
            if limit and len(result) >= limit:
                break
        return result

    def get_image_map(self, source):
        _entries, images = self._collect_sitemap_products(source)
        return images

    # ------------------------------------------------------------------
    # Utilidades de ficha
    # ------------------------------------------------------------------
    @classmethod
    def _clean_image_url(cls, value, page_url=''):
        raw = html.unescape(str(value or '')).strip().replace('\\/', '/')
        if not raw or raw.startswith(('data:', 'blob:')):
            return False
        if raw.startswith('//'):
            raw = f'https:{raw}'
        absolute = urljoin(page_url, raw.split()[0])
        parts = urlsplit(absolute)
        if parts.scheme not in ('http', 'https'):
            return False
        if cls._NON_PRODUCT_IMAGE_RE.search(parts.path):
            return False
        if not cls._IMAGE_EXT_RE.search(parts.path):
            return False

        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        if 'width' in query:
            query['width'] = '1800'
        if 'height' in query and 'width' in query:
            query.pop('height', None)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))

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
        values = []
        for variant in product_data.get('variants') or []:
            raw_values = variant.get('options') or []
            if not isinstance(raw_values, list):
                raw_values = [
                    variant.get('option1'), variant.get('option2'), variant.get('option3')
                ]
            for index in indexes:
                if index >= len(raw_values):
                    continue
                value = ' '.join(str(raw_values[index] or '').split()).strip()
                if value and value.casefold() != 'default title' and value not in values:
                    values.append(value)
        return values

    @classmethod
    def _model_name(cls, product_url, *titles):
        _section, handle = cls._product_parts(product_url)
        if handle in cls._PREMIUM_MODEL_NAMES:
            return cls._PREMIUM_MODEL_NAMES[handle]
        if handle in cls._PRODUCT_MODEL_NAMES:
            return cls._PRODUCT_MODEL_NAMES[handle]

        for raw in titles:
            text = html.unescape(str(raw or ''))
            text = re.sub(r'\s*[|–-]\s*Colnago.*$', '', text, flags=re.IGNORECASE).strip()
            match = cls._MODEL_CODE_RE.search(text)
            if match:
                code = match.group(1).upper()
                return {
                    'V5RS': 'V5Rs', 'V4RS': 'V4Rs', 'Y1RS': 'Y1Rs',
                    'T1RS': 'T1Rs',
                }.get(code, code)

        cleaned = re.sub(
            r'^(?:bicicleta|bike|bicycle|cuadro|frame(?:\s+kit)?)\s+',
            '',
            handle.replace('-', ' '),
            flags=re.IGNORECASE,
        ).strip()
        return cleaned.title() if cleaned else handle.upper()

    @classmethod
    def _style_code(cls, product_data, product_url, model_name=''):
        normalised_model = re.sub(r'[^A-Z0-9]+', '-', str(model_name or '').upper()).strip('-')
        if normalised_model.startswith(('C68-', 'C72-')):
            # C68 Road, C68 Allroad y C68 Gravel son modelos distintos.
            return normalised_model
        model_match = cls._MODEL_CODE_RE.search(str(model_name or ''))
        if model_match:
            return model_match.group(1).upper()

        product_type = str(product_data.get('type') or '').casefold()
        tags = ' '.join(cls._tag_strings(product_data)).casefold()
        title = str(product_data.get('title') or '').casefold()
        bike_context = ' '.join((product_type, tags, title))
        if any(token in bike_context for token in ('bike', 'bici', 'bicicleta', 'frameset', 'frame kit')):
            _section, handle = cls._product_parts(product_url)
            match = cls._MODEL_CODE_RE.search(handle.replace('-', ' '))
            if match:
                return match.group(1).upper()

        prefix = cls._common_variant_sku_prefix(product_data)
        if prefix:
            return prefix
        _section, handle = cls._product_parts(product_url)
        return handle.upper() if handle else False

    @staticmethod
    def _page_lines(tree):
        if tree is None:
            return []
        return [line.strip() for line in tree.text_content().splitlines() if line.strip()]

    @classmethod
    def _colors_from_html(cls, tree):
        colors = []

        def add_candidate(value):
            value = ' '.join(str(value or '').split()).strip(' ,;/')
            if not value or len(value) > 80:
                return False
            if not re.fullmatch(r'[A-Z0-9][A-Z0-9 /,+-]{1,79}', value):
                return False
            for part in re.split(r'\s*/\s*|\s*,\s*|\s*\+\s*', value):
                part = part.strip()
                if part and part not in colors:
                    colors.append(part)
            return bool(colors)

        # En las fichas actuales "Colores" y el código aparecen en nodos
        # contiguos. Se inspecciona el texto directo para no capturar todo el
        # contenido de un contenedor padre.
        for node in tree.xpath('//*'):
            direct = ' '.join(
                str(value).strip() for value in node.xpath('./text()') if str(value).strip()
            )
            match = re.match(r'^(?:Colores?|Colors?)\s*:?[ ]*(.*)$', direct, flags=re.IGNORECASE)
            if not match:
                continue
            if add_candidate(match.group(1)):
                return colors
            siblings = node.xpath('following-sibling::*[1]')
            if siblings and add_candidate(siblings[0].text_content()):
                return colors

        lines = cls._page_lines(tree)
        for index, line in enumerate(lines):
            match = re.match(r'^(?:Colores?|Colors?)\s*:?[ ]*(.*)$', line, flags=re.IGNORECASE)
            if not match:
                continue
            if add_candidate(match.group(1)):
                return colors
            for value in lines[index + 1:index + 6]:
                if add_candidate(value):
                    return colors
        return colors

    @classmethod
    def _breadcrumb_segments(cls, tree, product_title=''):
        segments = []
        for raw in tree.xpath('//script[@type="application/ld+json"]/text()'):
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            for node in cls._iter_json_nodes(payload):
                if not isinstance(node, dict):
                    continue
                node_type = node.get('@type')
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
            for xpath in (
                '//nav[contains(translate(@aria-label,"BREADCRUMB","breadcrumb"),"breadcrumb")]//a//text()',
                '//*[contains(concat(" ", normalize-space(@class), " "), " breadcrumb ")]//a//text()',
                '//*[contains(@class,"breadcrumbs")]//a//text()',
            ):
                values = [' '.join(str(value).split()) for value in tree.xpath(xpath)]
                values = [value for value in values if value]
                if values:
                    segments = values
                    break

        ignored = {
            'home', 'inicio', 'products', 'productos', 'collections', 'colecciones',
            'colnago', 'ver todo', 'all bikes', 'todas las bicicletas',
        }
        title_key = ' '.join(str(product_title or '').split()).casefold()
        result = []
        for segment in segments:
            key = segment.casefold()
            if key in ignored or key == title_key:
                continue
            if segment not in result:
                result.append(segment)
        return result

    @classmethod
    def _category_path(cls, product_data, tree, title, product_url):
        breadcrumb = cls._breadcrumb_segments(tree, title) if tree is not None else []
        text = ' '.join([
            urlparse(product_url).path.replace('-', ' '),
            str(title or ''),
            str(product_data.get('type') or ''),
            ' '.join(cls._tag_strings(product_data)),
            ' '.join(breadcrumb),
        ]).casefold()

        rules = (
            # Componentes, accesorios y ropa se comprueban antes que los
            # modelos: un accesorio puede incluir "C72" o "V4Rs" en el nombre.
            (('portabid', 'bottle cage', 'bidon', 'bottle'), ('Accesorios', 'Portabidones y bidones')),
            (('manillar', 'handlebar'), ('Componentes', 'Manillares')),
            (('potencia', 'stem'), ('Componentes', 'Potencias')),
            (('dirección', 'headset'), ('Componentes', 'Dirección')),
            (('cinta de manillar', 'handlebar tape'), ('Accesorios', 'Cintas de manillar')),
            (('tija', 'seatpost'), ('Componentes', 'Tijas')),
            (('patilla', 'hanger'), ('Componentes', 'Patillas de cambio')),
            (('eje pasante', 'thru axle'), ('Componentes', 'Ejes pasantes')),
            (('maillot', 'jersey', 'cycling apparel'), ('Ropa', 'Ciclismo')),
            (('camiseta', 't shirt', 't-shirt', 'hoodie', 'sudadera'), ('Ropa', 'Casual')),
            (('gravel', 'g4 x'), ('Bicicletas', 'Gravel')),
            (('contrarreloj', 'time trial', 'triathlon', 'tt1', 'tt2'), ('Bicicletas', 'Contrarreloj')),
            (('pista', 'track bike', 't1rs'), ('Bicicletas', 'Pista')),
            (('acero', 'steel', 'master', 'steelnovo'), ('Bicicletas', 'Acero')),
            (('bicicleta', 'bike', 'road bike', 'c72', 'c68', 'v5rs', 'v4rs', 'v4', 'y1rs'), ('Bicicletas', 'Carretera')),
        )
        for tokens, path in rules:
            if any(token in text for token in tokens):
                return ' / '.join(path)

        if breadcrumb:
            return ' / '.join(breadcrumb)
        raw_type = ' '.join(str(product_data.get('type') or '').split()).strip()
        if raw_type and raw_type.casefold() not in {'product', 'producto'}:
            return raw_type
        return 'Catálogo Colnago'

    @staticmethod
    def _parse_colnago_price(value):
        if value in (None, False, ''):
            return 0.0
        text = html.unescape(str(value)).replace('\xa0', '').replace('€', '').strip()
        text = re.sub(r'[^0-9,.-]', '', text)
        if not text:
            return 0.0
        if ',' in text and '.' in text:
            if text.rfind(',') > text.rfind('.'):
                text = text.replace('.', '').replace(',', '.')
            else:
                text = text.replace(',', '')
        elif ',' in text:
            if re.fullmatch(r'-?\d{1,3}(?:,\d{3})+', text):
                text = text.replace(',', '')
            else:
                text = text.replace(',', '.')
        elif '.' in text and re.fullmatch(r'-?\d{1,3}(?:\.\d{3})+', text):
            text = text.replace('.', '')
        try:
            return float(text)
        except ValueError:
            return 0.0

    @classmethod
    def _extract_model_price(cls, tree, model_name=''):
        lines = cls._page_lines(tree)
        text = '\n'.join(lines)
        model = ' '.join(str(model_name or '').split()).strip()
        if model:
            pattern = re.compile(
                rf'{re.escape(model)}[\s\S]{{0,160}}?(?:Desde\s*)?€\s*'
                rf'(\d[\d.,\s]*)',
                re.IGNORECASE,
            )
            matches = pattern.findall(text)
            if matches:
                return cls._parse_colnago_price(matches[-1])

        # En una ficha de producto estándar el precio propio aparece antes de
        # la sección de recomendaciones. Se usa solo como último respaldo.
        for line in lines[:120]:
            match = cls._PRICE_RE.search(line)
            if match:
                return cls._parse_colnago_price(match.group(1))
        return 0.0

    @classmethod
    def _html_images(cls, tree, base_url, model_name=''):
        if tree is None:
            return []
        model_token = re.sub(r'[^a-z0-9]', '', str(model_name or '').casefold())
        preferred = []
        fallback = []
        nodes = tree.xpath('//main//img | //article//img') or tree.xpath('//img')
        for node in nodes:
            raw_candidates = []
            for attr in ('src', 'data-src', 'data-original'):
                if node.get(attr):
                    raw_candidates.append(node.get(attr))
            for attr in ('srcset', 'data-srcset'):
                if node.get(attr):
                    raw_candidates.extend(
                        part.strip().split(' ')[0]
                        for part in node.get(attr).split(',')
                        if part.strip()
                    )
            alt = ' '.join(node.xpath('.//@alt')).strip()
            for raw in reversed(raw_candidates):
                image_url = cls._clean_image_url(raw, base_url)
                if not image_url:
                    continue
                key = re.sub(r'[^a-z0-9]', '', f'{alt} {urlparse(image_url).path}'.casefold())
                target = preferred if model_token and model_token in key else fallback
                if image_url not in preferred and image_url not in fallback:
                    target.append(image_url)
        return preferred + fallback

    @staticmethod
    def _append_features(description, features):
        lines = []
        for label, values in features:
            values = [str(value).strip() for value in values if str(value).strip()]
            if values:
                lines.append(f'<p><strong>{label}:</strong> {", ".join(values)}</p>')
        if not lines:
            return description or ''
        return f'{description or ""}\n{"".join(lines)}'.strip()

    def _fetch_html_context(self, source, product_url):
        session = self._get_session(source)
        response = self._http_get(session, product_url, source)
        tree = lxml_html.fromstring(response.content)
        canonical = self._clean_product_url(self._canonical_url(tree, product_url))
        if not self._is_product_url(canonical):
            fallback = self._clean_product_url(product_url)
            if self._is_product_url(fallback):
                canonical = fallback
            else:
                raise ValueError(
                    'La URL ya no apunta a una ficha española de Colnago; '
                    'posible redirección o producto descatalogado.'
                )
        title_nodes = tree.xpath('//h1[1]//text()')
        visible_title = ' '.join(part.strip() for part in title_nodes if part.strip())
        seo_title = self._meta(tree, 'og:title') or self._meta(tree, 'title') or ''
        model_name = self._model_name(canonical, seo_title, visible_title)
        return {
            'tree': tree,
            'content': response.content,
            'canonical_url': canonical,
            'visible_title': visible_title,
            'seo_title': seo_title,
            'model_name': model_name,
            'colors': self._colors_from_html(tree),
        }

    # ------------------------------------------------------------------
    # Vista previa Shopify / HTML
    # ------------------------------------------------------------------
    def _preview_from_ajax(self, source, product_url, html_context=None):
        section, _handle = self._product_parts(product_url)
        if section != 'products':
            raise ValueError('Las páginas premium de Colnago no exponen el endpoint Ajax Shopify.')

        product_data = self._fetch_shopify_product_payload(source, product_url)
        if not isinstance(product_data, dict) or not product_data.get('title'):
            raise ValueError('El endpoint Ajax de Shopify no devolvió un producto Colnago válido.')

        canonical = self._clean_product_url(product_url)
        if html_context:
            canonical = html_context.get('canonical_url') or canonical
        title = ' '.join(str(product_data.get('title') or '').split()).strip()
        model_name = self._model_name(
            canonical,
            title,
            html_context.get('seo_title') if html_context else '',
        )
        name = title or model_name or canonical
        tree = html_context.get('tree') if html_context else None

        colors = self._option_values(
            product_data, ('color', 'colour', 'colore', 'farbe', 'couleur')
        )
        if html_context:
            for value in html_context.get('colors') or []:
                if value not in colors:
                    colors.append(value)
        sizes = self._option_values(
            product_data, ('size', 'talla', 'taglia', 'taille', 'frame size')
        )
        setups = self._option_values(
            product_data, ('setup', 'montaje', 'configuración', 'configuration', 'grupo')
        )

        description = self._append_features(
            product_data.get('description') or '',
            (
                ('Configuraciones', setups),
                ('Tallas', sizes),
                ('Colores', colors),
            ),
        )
        images = []
        for item in product_data.get('images') or []:
            if isinstance(item, dict):
                item = item.get('src') or item.get('url')
            image_url = self._clean_image_url(item, canonical)
            if image_url and image_url not in images:
                images.append(image_url)
        featured = product_data.get('featured_image')
        if isinstance(featured, dict):
            featured = featured.get('src') or featured.get('url')
        featured = self._clean_image_url(featured, canonical)
        if featured and featured not in images:
            images.insert(0, featured)

        price = self._money_from_cents(product_data.get('price'))
        return {
            'name': name,
            'description': description,
            'price': price,
            'price_available': price > 0,
            'currency': 'EUR',
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical,
            'style_code': self._style_code(product_data, canonical, model_name),
            'color_code': ' / '.join(colors) or False,
            'ean_variants': self._ean_variants_from_shopify_product(product_data),
            'ean_complete': True,
            'category_path': self._category_path(product_data, tree, name, canonical),
        }

    def _preview_from_html(self, source, product_url, html_context=None):
        context = html_context or self._fetch_html_context(source, product_url)
        tree = context['tree']
        canonical = context['canonical_url']
        product_node = self._find_product_json_ld(tree)
        offers = product_node.get('offers') or {}
        if isinstance(offers, list):
            offers = next((item for item in offers if isinstance(item, dict)), {})

        model_name = context.get('model_name') or self._model_name(
            canonical, context.get('seo_title'), context.get('visible_title')
        )
        json_name = ' '.join(str(product_node.get('name') or '').split()).strip()
        visible_title = ' '.join(str(context.get('visible_title') or '').split()).strip()
        # En páginas premium el H1 puede ser un lema ("Built to win") y el
        # nombre estable es el modelo derivado del handle/título SEO.
        section, _handle = self._product_parts(canonical)
        name = json_name or (model_name if section == 'premium-bikes' else visible_title) or model_name
        description = (
            product_node.get('description')
            or self._meta(tree, 'og:description')
            or self._meta(tree, 'description')
            or ''
        )
        price = self._parse_colnago_price(
            offers.get('price')
            or self._meta(tree, 'product:price:amount')
            or self._meta(tree, 'og:price:amount')
            or '0'
        )
        if not price:
            price = self._extract_model_price(tree, model_name)
        currency = (
            offers.get('priceCurrency')
            or self._meta(tree, 'product:price:currency')
            or self._meta(tree, 'og:price:currency')
            or 'EUR'
        )

        colors = list(context.get('colors') or [])
        if product_node.get('color'):
            raw_colors = product_node.get('color')
            if not isinstance(raw_colors, list):
                raw_colors = [raw_colors]
            for value in raw_colors:
                value = ' '.join(str(value or '').split()).strip()
                if value and value not in colors:
                    colors.append(value)

        description = self._append_features(description, (('Colores', colors),))
        images = self._json_ld_images(product_node, canonical)
        for image_url in self._html_images(tree, canonical, model_name):
            if image_url not in images:
                images.append(image_url)
        og_image = self._clean_image_url(self._meta(tree, 'og:image'), canonical)
        if og_image and og_image not in images:
            images.insert(0, og_image)

        pseudo_data = {
            'title': name,
            'type': product_node.get('category') or '',
            'tags': [],
            'variants': [],
            'handle': self._product_parts(canonical)[1],
        }
        return {
            'name': name or canonical,
            'description': description,
            'price': price,
            'price_available': price > 0,
            'currency': currency,
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical,
            'style_code': self._style_code(pseudo_data, canonical, model_name),
            'color_code': ' / '.join(colors) or False,
            'ean_variants': self._ean_variants_from_html_content(context.get('content') or b''),
            'ean_complete': False,
            'category_path': self._category_path(pseudo_data, tree, name, canonical),
        }

    def fetch_preview(self, source, url):
        html_context = None
        try:
            html_context = self._fetch_html_context(source, url)
        except Exception as exc:
            _logger.info('Colnago: no se pudo enriquecer el HTML de %s: %s', url, exc)

        try:
            return self._preview_from_ajax(source, url, html_context=html_context)
        except Exception as exc:
            _logger.info(
                'Colnago: no se pudo usar Shopify Ajax para %s (%s); se usa HTML.',
                url,
                exc,
            )
            return self._preview_from_html(source, url, html_context=html_context)
