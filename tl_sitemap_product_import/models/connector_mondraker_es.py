import gzip
import html
import json
import logging
import re
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorMondrakerEs(models.AbstractModel):
    """Conector del catálogo español de Mondraker.

    El índice ``https://mondraker.com/sitemapindex.xml`` mezcla mercados,
    páginas editoriales, familias y fichas de producto. Las fichas españolas
    usan rutas bajo ``/es/es/`` y normalmente son planas, por ejemplo::

        /es/es/2025-foxy-carbon-rr
        /es/es/crafty-carbon-rr-s1721822369
        /es/es/handlebar
        /es/es/jersey-forest-l/s-dissolved

    La URL no contiene una referencia comercial inequívoca. Se usa primero el
    SKU/MPN/productID publicado en JSON-LD o HTML y, si no existe, el slug
    canónico como referencia web estable. Los GTIN se recuperan únicamente si
    superan la validación GS1 común del módulo.
    """

    _name = 'sitemap.connector.mondraker_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Mondraker España'

    _HOSTS = {'mondraker.com', 'www.mondraker.com', 'cdn.mondraker.com'}
    _LOCALE_PREFIX = '/es/es/'

    # Rutas editoriales, índices y familias que comparten la misma estructura
    # plana que una ficha de producto.
    _EXCLUDED_FIRST_SEGMENTS = {
        '', 'bikes', 'e-bikes', 'ebikes', 'wear', 'components', 'technology',
        'racing', 'community', 'support', 'news', 'catalogs', 'contact',
        'distributors', 'manuals', 'bike-archive', 'find-your-bike',
        'register-your-bike', 'warranty-conditions', 'professional-zone',
        'faqs', 'preguntas-frecuentes', 'shop-finder', 'buscador-de-tiendas',
        'who-we-are', 'quienes-somos', 'work-with-us', 'trabaja-con-nosotros', 'compare',
        'compare-bike', 'search', 'buscar', 'legal', 'privacy-policy', 'politica-de-privacidad', 'cookies-policy',
        'terms-and-conditions', 'terminos-y-condiciones', 'demo-ride', 'events', 'eventos', 'ambassadors', 'embajadores',
        'eng', 'downloads', 'size-guide', 'dealer-area', 'newsletter',
    }
    _FAMILY_SLUGS = {
        'summum', 'anark', 'foxy', 'raze', 'f-podium', 'podium',
        'arid-carbon', 'arid', 'f-trick', 'dune', 'neat', 'sly', 'zendit',
        'crafty', 'level', 'scree', 'dusty', 'dusty-x', 'f-play', 'mind',
        'downhill', 'bike-park', 'enduro', 'trail', 'dirt-jump',
        'cross-country', 'gravel', 'kids', 'frames', 'light-e-mtb',
        'e-gravel', 'urban-cross', 'outerwear', 'accessories', 'lifestyle',
        'cockpit', 'drivetrain', 'seatpost', 'braking',
    }
    _EDITORIAL_TOKENS = (
        '/technology/', '/community/', '/racing/', '/news/', '/support/',
        '/manuals/', '/catalogs/', '/bike-archive/', '/ambassadors/',
    )

    _NON_PRODUCT_IMAGE_RE = re.compile(
        r'(?:logo|favicon|icon|sprite|cookie|newsletter|social|payment|flag|'
        r'arrow|loader|placeholder|avatar|team|footer|header|menu|nav|close|'
        r'play-button|youtube|vimeo|country|language|dealer|store-locator)',
        re.IGNORECASE,
    )
    _IMAGE_EXT_RE = re.compile(r'\.(?:avif|gif|jpe?g|png|webp)(?:$|\?)', re.IGNORECASE)
    _PRICE_RE = re.compile(
        r'(?<!\d)(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2}))\s*€'
    )

    _CATEGORY_PATTERNS = (
        ('downhill', ('Bicicletas', 'Downhill')),
        ('bike park', ('Bicicletas', 'Bike Park')),
        ('enduro', ('Bicicletas', 'Enduro')),
        ('trail', ('Bicicletas', 'Trail')),
        ('dirt jump', ('Bicicletas', 'Dirt Jump')),
        ('cross country', ('Bicicletas', 'Cross Country')),
        ('gravel', ('Bicicletas', 'Gravel')),
        ('kids', ('Bicicletas', 'Infantil')),
        ('light e-mtb', ('Bicicletas eléctricas', 'Light e-MTB')),
        ('e-gravel', ('Bicicletas eléctricas', 'e-Gravel')),
        ('urban-cross', ('Bicicletas eléctricas', 'Urban-Cross')),
    )
    _WEAR_KEYWORDS = {
        'jersey': 'Maillots', 'bibshort': 'Culottes', 'bib-short': 'Culottes',
        'culotte': 'Culottes', 'short': 'Pantalones y shorts',
        'jacket': 'Chaquetas', 'vest': 'Chalecos', 'glove': 'Guantes',
        'helmet': 'Cascos', 't-shirt': 'Camisetas', 'hoodie': 'Sudaderas',
        'cap': 'Gorras', 'beanie': 'Gorros', 'base-layer': 'Primera capa',
    }
    _COMPONENT_KEYWORDS = {
        'handlebar': 'Manillares', 'stem': 'Potencias', 'headset': 'Direcciones',
        'grip': 'Puños', 'chainguide': 'Guíacadenas', 'chainring': 'Platos',
        'pedal': 'Pedales', 'seatpost': 'Tijas', 'bottle': 'Portabidones',
        'pump': 'Bombas', 'multitool': 'Multiherramientas', 'tubeless': 'Tubeless',
        'disc-rotor': 'Discos de freno', 'bag': 'Bolsas',
    }

    # ------------------------------------------------------------------
    # HTTP y sitemap
    # ------------------------------------------------------------------
    def _get_session(self, source):
        session = super()._get_session(source)
        session.headers.update({
            'Accept': (
                'text/html,application/xhtml+xml,application/xml;q=0.9,'
                'image/avif,image/webp,*/*;q=0.8'
            ),
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.4',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
        })
        return session

    @staticmethod
    def _xml_root(content):
        if content[:2] == b'\x1f\x8b':
            content = gzip.decompress(content)
        parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
        return etree.fromstring(content, parser=parser)

    @staticmethod
    def _local_name(element):
        return etree.QName(element).localname.lower()

    @classmethod
    def _canonical_url(cls, value):
        raw = html.unescape(str(value or '')).strip().replace('\\/', '/')
        if not raw:
            return False
        parts = urlsplit(raw)
        host = parts.netloc.lower()
        if host in {'mondraker.com', 'cdn.mondraker.com'}:
            host = 'www.mondraker.com'
        path = re.sub(r'/+', '/', parts.path or '/')
        path = re.sub(r'^/es[-_]es/', '/es/es/', path, flags=re.IGNORECASE)
        if path != '/':
            path = path.rstrip('/')
        return urlunsplit((parts.scheme or 'https', host, path, '', ''))

    @classmethod
    def _product_parts(cls, value):
        canonical = cls._canonical_url(value)
        if not canonical:
            return False
        parsed = urlparse(canonical)
        if parsed.netloc.lower() not in cls._HOSTS | {'www.mondraker.com'}:
            return False
        path = parsed.path
        if not path.casefold().startswith(cls._LOCALE_PREFIX):
            return False
        lowered = path.casefold()
        if any(token in lowered for token in cls._EDITORIAL_TOKENS):
            return False
        remainder = path[len(cls._LOCALE_PREFIX):].strip('/')
        segments = [segment for segment in remainder.split('/') if segment]
        if not segments or len(segments) > 2:
            return False
        first = segments[0].casefold()
        if len(first) < 3 or not re.search(r'[a-z]', first):
            return False
        if first in cls._EXCLUDED_FIRST_SEGMENTS or first in cls._FAMILY_SLUGS:
            return False
        if first.endswith(('.pdf', '.xml', '.jpg', '.jpeg', '.png', '.webp')):
            return False
        if any(first.startswith(prefix) for prefix in (
            'legal-', 'privacy-', 'cookie-', 'terms-', 'news-', 'event-',
            'ambassador-', 'technology-', 'manual-', 'catalog-',
        )):
            return False
        return segments

    @classmethod
    def _product_key(cls, value):
        parts = cls._product_parts(value)
        return '/'.join(item.casefold() for item in parts) if parts else False

    def _iter_sitemap_entries(self, source, sitemap_url, depth=0, visited=None):
        if depth > 10:
            raise ValueError('El sitemap de Mondraker supera diez niveles de índices.')
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
            content_type = response.headers.get('Content-Type', '')
            raise ValueError(
                'Mondraker no devolvió XML válido en '
                f'{clean_url} (Content-Type: {content_type or "desconocido"}).'
            ) from exc

        root_name = self._local_name(root)
        if root_name == 'sitemapindex':
            for child_url in root.xpath(
                './*[local-name()="sitemap"]/*[local-name()="loc"]/text()'
            ):
                if child_url and child_url.strip():
                    yield from self._iter_sitemap_entries(
                        source,
                        urljoin(clean_url, child_url.strip()),
                        depth=depth + 1,
                        visited=visited,
                    )
            return

        if root_name != 'urlset':
            raise ValueError('El sitemap de Mondraker no contiene <urlset> ni <sitemapindex>.')

        for url_element in root.xpath('./*[local-name()="url"]'):
            loc_values = url_element.xpath('./*[local-name()="loc"]/text()')
            alternate_values = url_element.xpath(
                './*[local-name()="link" and '
                'translate(@hreflang,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")='
                '"es-es"]/@href'
            )
            candidates = alternate_values + loc_values
            loc = False
            for candidate in candidates:
                canonical = self._canonical_url(candidate)
                if self._product_parts(canonical):
                    loc = canonical
                    break
            if not loc:
                continue
            lastmod_values = url_element.xpath('./*[local-name()="lastmod"]/text()')
            image_values = url_element.xpath(
                './*[local-name()="image"]/*[local-name()="loc"]/text()'
            )
            yield (
                {
                    'url': loc,
                    'lastmod': self._parse_lastmod(
                        lastmod_values[0] if lastmod_values else None
                    ),
                },
                [item.strip() for item in image_values if item and item.strip()],
            )

    @classmethod
    def _clean_image_url(cls, value, page_url=''):
        raw = html.unescape(str(value or '')).strip().replace('\\/', '/')
        if not raw or raw.startswith(('data:', 'blob:')):
            return False
        raw = raw.split()[0]
        absolute = urljoin(page_url, raw)
        parts = urlsplit(absolute)
        if parts.scheme not in ('http', 'https'):
            return False
        if cls._NON_PRODUCT_IMAGE_RE.search(parts.path):
            return False
        if not cls._IMAGE_EXT_RE.search(parts.path):
            return False
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))

    def _collect_sitemap_products(self, source):
        entries_by_key = {}
        images_by_key = {}
        for entry, image_urls in self._iter_sitemap_entries(source, source.sitemap_index_url):
            canonical = self._canonical_url(entry['url'])
            key = self._product_key(canonical)
            if not key:
                continue
            candidate = {'url': canonical, 'lastmod': entry.get('lastmod') or False}
            current = entries_by_key.get(key)
            if not current:
                entries_by_key[key] = candidate
            elif candidate['lastmod'] and (
                not current['lastmod'] or candidate['lastmod'] > current['lastmod']
            ):
                current['lastmod'] = candidate['lastmod']

            target = images_by_key.setdefault(key, [])
            for image_url in image_urls:
                cleaned = self._clean_image_url(image_url, canonical)
                if cleaned and cleaned not in target:
                    target.append(cleaned)
        return entries_by_key, images_by_key

    def _fallback_product_entries(self, source):
        session = self._get_session(source)
        entries = {}
        for page_url in (
            'https://www.mondraker.com/es/es',
            'https://www.mondraker.com/es/es/bikes',
            'https://www.mondraker.com/es/es/e-bikes',
            'https://www.mondraker.com/es/es/wear',
            'https://www.mondraker.com/es/es/components',
        ):
            try:
                response = self._http_get(session, page_url, source)
                tree = lxml_html.fromstring(response.content)
            except Exception as exc:
                _logger.debug('Mondraker: no se pudo recorrer %s: %s', page_url, exc)
                continue
            for href in tree.xpath('//a[@href]/@href'):
                canonical = self._canonical_url(urljoin(page_url, href))
                key = self._product_key(canonical)
                if key:
                    entries.setdefault(key, {'url': canonical, 'lastmod': False})
        return entries

    def get_product_entries(self, source, category_filter=None, limit=0):
        try:
            entries_by_key, _images = self._collect_sitemap_products(source)
        except Exception as exc:
            _logger.warning(
                'Mondraker: el sitemap no pudo procesarse; se usa el catálogo como '
                'respaldo: %s', exc,
            )
            entries_by_key = self._fallback_product_entries(source)

        if not entries_by_key:
            raise ValueError('No se localizaron fichas españolas de Mondraker.')

        filter_text = (category_filter or '').strip().casefold()
        result = []
        for key, entry in sorted(entries_by_key.items(), key=lambda item: item[0]):
            category = '/'.join(self.parse_category_path(entry['url']))
            haystack = f'{key} {entry["url"]} {category}'.casefold()
            if filter_text and filter_text not in haystack:
                continue
            result.append(entry)
            if limit and len(result) >= limit:
                break
        return result

    def get_image_map(self, source):
        try:
            entries_by_key, images_by_key = self._collect_sitemap_products(source)
        except Exception:
            return {}
        return {
            entry['url']: images_by_key.get(key, [])
            for key, entry in entries_by_key.items()
            if images_by_key.get(key)
        }

    # ------------------------------------------------------------------
    # Ficha de producto
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_text(value):
        return re.sub(r'\s+', ' ', html.unescape(str(value or ''))).strip()

    @classmethod
    def _meta(cls, tree, name):
        values = tree.xpath(
            f'//meta[@property="{name}" or @name="{name}" or @itemprop="{name}"]/@content'
        )
        return cls._normalize_text(values[0]) if values else False

    @classmethod
    def _json_ld_payloads(cls, tree):
        payloads = []
        for raw in tree.xpath('//script[@type="application/ld+json"]/text()'):
            if not raw or len(raw) > 8_000_000:
                continue
            try:
                payloads.append(json.loads(raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return payloads

    @classmethod
    def _find_product_json_ld(cls, tree):
        found = []

        def walk(value):
            if isinstance(value, list):
                for item in value:
                    walk(item)
                return
            if not isinstance(value, dict):
                return
            item_type = value.get('@type')
            types = item_type if isinstance(item_type, list) else [item_type]
            if any(str(item).casefold() == 'product' for item in types if item):
                found.append(value)
            for key in ('@graph', 'mainEntity', 'itemListElement', 'hasVariant'):
                if key in value:
                    walk(value[key])

        for payload in cls._json_ld_payloads(tree):
            walk(payload)
        return found[0] if found else {}

    @classmethod
    def _page_lines(cls, tree):
        scopes = tree.xpath('//main')
        scope = scopes[0] if scopes else tree
        result = []
        for raw in scope.xpath('.//text()[normalize-space()]'):
            value = cls._normalize_text(raw)
            if value and (not result or result[-1] != value):
                result.append(value)
        return result

    @classmethod
    def _extract_product_name(cls, tree, product_json, canonical):
        values = tree.xpath('//main//h1[1]//text()') or tree.xpath('//h1[1]//text()')
        name = cls._normalize_text(' '.join(values)) if values else False
        name = name or cls._normalize_text(product_json.get('name'))
        name = name or cls._meta(tree, 'og:title') or cls._meta(tree, 'twitter:title')
        if name:
            name = re.sub(r'\s*[-|]\s*MONDRAKER.*$', '', name, flags=re.IGNORECASE).strip()
        if not name:
            parts = cls._product_parts(canonical) or []
            name = ' '.join(parts).replace('-', ' ').title()
        return name

    @staticmethod
    def _parse_price(value):
        text = re.sub(r'[^0-9.,]', '', str(value or ''))
        if not text:
            return False
        if ',' in text and '.' in text:
            if text.rfind(',') > text.rfind('.'):
                text = text.replace('.', '').replace(',', '.')
            else:
                text = text.replace(',', '')
        elif ',' in text:
            text = text.replace('.', '').replace(',', '.')
        try:
            return float(text)
        except ValueError:
            return False

    @classmethod
    def _structured_price(cls, tree, product_json, lines):
        offers = product_json.get('offers') if isinstance(product_json, dict) else None
        offers = offers if isinstance(offers, list) else [offers]
        prices = []
        currency = False
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            currency = currency or offer.get('priceCurrency')
            for field in ('salePrice', 'price', 'lowPrice'):
                parsed = cls._parse_price(offer.get(field))
                if parsed is not False:
                    prices.append(parsed)
                    break
        if prices:
            return min(prices), currency or 'EUR'

        meta_price = cls._meta(tree, 'product:price:amount') or cls._meta(tree, 'og:price:amount')
        parsed = cls._parse_price(meta_price)
        if parsed is not False:
            return parsed, (
                cls._meta(tree, 'product:price:currency')
                or cls._meta(tree, 'og:price:currency')
                or 'EUR'
            )

        # Se limita a las primeras líneas útiles de la ficha para no tomar
        # precios de productos recomendados o financiación del pie.
        candidates = []
        for line in lines[:160]:
            lowered = line.casefold()
            if any(token in lowered for token in ('mes', 'month', 'financi', 'desde ')):
                continue
            for match in cls._PRICE_RE.finditer(line):
                value = cls._parse_price(match.group(1))
                if value is not False and value >= 1:
                    candidates.append(value)
        return (min(candidates), 'EUR') if candidates else (0.0, 'EUR')

    @classmethod
    def _extract_description(cls, tree, product_json):
        candidates = []
        for value in (
            product_json.get('description') if isinstance(product_json, dict) else False,
            cls._meta(tree, 'og:description'),
            cls._meta(tree, 'description'),
        ):
            text = cls._normalize_text(value)
            if text:
                candidates.append(text)
        h1_nodes = tree.xpath('//main//h1[1]') or tree.xpath('//h1[1]')
        if h1_nodes:
            for node in h1_nodes[0].xpath('following::p[position() <= 30]'):
                text = cls._normalize_text(' '.join(node.itertext()))
                lowered = text.casefold()
                if len(text) >= 45 and not any(token in lowered for token in (
                    'cookie', 'privacy', 'newsletter', 'country', 'location', 'postal code',
                )):
                    candidates.append(text)
        return max(candidates, key=len) if candidates else ''

    @classmethod
    def _extract_sizes(cls, lines):
        result = []
        for index, line in enumerate(lines):
            if line.casefold().rstrip(':') not in {'sizes', 'tallas', 'size'}:
                continue
            for candidate in lines[index + 1:index + 8]:
                if len(candidate) > 80:
                    break
                values = re.findall(r'\b(?:XXS|XS|S|M|L|XL|XXL|[0-9]{2,3})\b', candidate, re.I)
                for value in values:
                    value = value.upper()
                    if value not in result:
                        result.append(value)
            if result:
                break
        return result

    @classmethod
    def _extract_colors(cls, tree, lines):
        result = []
        for index, line in enumerate(lines):
            if line.casefold().rstrip(':') not in {'color', 'colors', 'colour', 'colores'}:
                continue
            for candidate in lines[index + 1:index + 5]:
                value = cls._normalize_text(candidate).strip(' /-|')
                if value and len(value) <= 80 and value.casefold() not in {
                    'information', 'components', 'geometry', 'gallery', 'downloads',
                    'información', 'componentes', 'geometría', 'galería', 'descargas',
                }:
                    if value.casefold() not in {item.casefold() for item in result}:
                        result.append(value)
            if result:
                break
        for attr in tree.xpath('//*[@data-color]/@data-color | //*[@data-colour]/@data-colour'):
            value = cls._normalize_text(attr)
            if value and value.casefold() not in {item.casefold() for item in result}:
                result.append(value)
        return result[:8]

    @classmethod
    def _style_code(cls, canonical, product_json, lines):
        if isinstance(product_json, dict):
            for field in ('sku', 'mpn', 'productID', 'productId'):
                candidate = cls._normalize_text(product_json.get(field))
                if candidate and re.fullmatch(r'[A-Z0-9._/-]{3,50}', candidate, re.I):
                    return candidate.upper()
        labels = (
            'SKU', 'REFERENCE', 'REF', 'PRODUCT CODE', 'MODEL CODE',
            'CÓDIGO', 'CÓDIGO DE PRODUCTO', 'REFERENCIA',
        )
        for index, line in enumerate(lines):
            for label in labels:
                match = re.match(
                    rf'^{re.escape(label)}\s*[:#-]\s*([A-Z0-9._/-]{{3,50}})$',
                    line,
                    flags=re.IGNORECASE,
                )
                if match:
                    return match.group(1).upper()
                if line.upper().rstrip(':') == label and index + 1 < len(lines):
                    candidate = re.sub(r'\s+', '', lines[index + 1]).upper()
                    if re.fullmatch(r'[A-Z0-9._/-]{3,50}', candidate):
                        return candidate
        parts = cls._product_parts(canonical) or []
        return '-'.join(parts).upper() if parts else False

    @classmethod
    def _category_path(cls, canonical, name, lines):
        text = (str(name or '') + ' ' + ' '.join(lines[:140])).casefold()
        slug = '/'.join(cls._product_parts(canonical) or []).casefold()

        if 'frameset' in text or 'cuadro' in text and 'bicicleta' not in text:
            return ['Cuadros']
        for keyword, label in cls._WEAR_KEYWORDS.items():
            if keyword in slug or keyword in name.casefold():
                return ['Ropa y equipamiento', label]
        for keyword, label in cls._COMPONENT_KEYWORDS.items():
            if keyword in slug or keyword in name.casefold():
                return ['Componentes', label]

        is_ebike = any(token in text for token in (
            'e-bike', 'e-mtb', 'motor bosch', 'motor shimano', 'motor tq',
            'battery', 'batería', 'wh ', 'drive system',
        ))
        for needle, path in cls._CATEGORY_PATTERNS:
            if needle in text:
                path = list(path)
                if is_ebike and path[0] == 'Bicicletas':
                    path[0] = 'Bicicletas eléctricas'
                # El texto de ficha suele incluir "ENDURO / FOXY".
                family_match = re.search(
                    rf'\b{re.escape(needle)}\s*/\s*([A-Z0-9][A-Z0-9 -]{{2,30}})',
                    ' '.join(lines[:100]),
                    flags=re.IGNORECASE,
                )
                if family_match:
                    family = cls._normalize_text(family_match.group(1)).title()
                    family = re.split(r'\s{2,}|\b(?:sizes?|tallas?)\b', family, maxsplit=1, flags=re.I)[0].strip()
                    if family and family.casefold() != path[-1].casefold():
                        path.append(family)
                return path
        return ['Bicicletas eléctricas' if is_ebike else 'Bicicletas']

    @classmethod
    def parse_category_path(cls, product_url):
        parts = cls._product_parts(product_url)
        if not parts:
            return []
        slug = '/'.join(parts).casefold()
        for keyword, label in cls._WEAR_KEYWORDS.items():
            if keyword in slug:
                return ['Ropa y equipamiento', label]
        for keyword, label in cls._COMPONENT_KEYWORDS.items():
            if keyword in slug:
                return ['Componentes', label]
        if 'frame' in slug or 'frameset' in slug:
            return ['Cuadros']
        return ['Bicicletas']

    @classmethod
    def _json_ld_images(cls, product_json, page_url):
        raw_images = product_json.get('image') if isinstance(product_json, dict) else []
        raw_images = raw_images if isinstance(raw_images, list) else [raw_images]
        result = []
        for item in raw_images:
            if isinstance(item, dict):
                item = item.get('url') or item.get('contentUrl')
            cleaned = cls._clean_image_url(item, page_url)
            if cleaned and cleaned not in result:
                result.append(cleaned)
        return result

    @classmethod
    def _html_images(cls, tree, page_url, name):
        result = []
        name_tokens = {
            token for token in re.findall(r'[a-z0-9]+', name.casefold()) if len(token) >= 4
        }
        scopes = tree.xpath(
            '//main//*[contains(translate(@class,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"gallery") '
            'or contains(translate(@class,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"product") '
            'or contains(translate(@class,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"slider") '
            'or contains(translate(@class,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"carousel")]'
        )
        nodes = []
        for scope in scopes[:100]:
            nodes.extend(scope.xpath('.//img | .//source | .//a[@href]'))
        if not nodes:
            main = (tree.xpath('//main') or [tree])[0]
            nodes = main.xpath('.//img | .//source | .//a[@href]')

        for node in nodes:
            label = cls._normalize_text(' '.join(filter(None, [
                node.get('alt'), node.get('title'), node.get('aria-label'),
            ])))
            label_tokens = {
                token for token in re.findall(r'[a-z0-9]+', label.casefold()) if len(token) >= 4
            }
            if label_tokens and name_tokens and not (label_tokens & name_tokens):
                if not any(word in label.casefold() for word in ('product', 'bike', 'image', 'gallery')):
                    continue
            candidates = []
            for attr in ('href', 'src', 'data-src', 'data-original', 'data-lazy-src'):
                if node.get(attr):
                    candidates.append(node.get(attr))
            for attr in ('srcset', 'data-srcset'):
                if node.get(attr):
                    candidates.extend(
                        item.strip().split(' ')[0]
                        for item in node.get(attr).split(',') if item.strip()
                    )
            for raw in reversed(candidates):
                cleaned = cls._clean_image_url(raw, page_url)
                if cleaned and cleaned not in result:
                    result.append(cleaned)
        return result

    @classmethod
    def _is_product_page(cls, tree, product_json, lines, canonical):
        if not cls._product_parts(canonical):
            return False
        if product_json:
            return True
        text = ' '.join(lines[:220]).casefold()
        markers = (
            'sizes:', 'tallas:', 'size guide', 'guía de tallas',
            'information components geometry gallery downloads',
            'información componentes geometría galería descargas',
            'compare bike', 'comparar bicicleta',
        )
        marker_count = sum(1 for marker in markers if marker in text)
        h1 = tree.xpath('//main//h1 | //h1')
        price = cls._meta(tree, 'product:price:amount') or cls._meta(tree, 'og:price:amount')
        return bool(h1 and (marker_count or price))

    def fetch_preview(self, source, url):
        session = self._get_session(source)
        response = self._http_get(session, url, source)
        tree = lxml_html.fromstring(response.content)

        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical = self._canonical_url(
            canonical_values[0] if canonical_values else response.url or url
        )
        product_json = self._find_product_json_ld(tree)
        lines = self._page_lines(tree)
        if not self._is_product_page(tree, product_json, lines, canonical):
            fallback = self._canonical_url(url)
            if fallback != canonical and self._is_product_page(tree, product_json, lines, fallback):
                canonical = fallback
            else:
                raise ValueError(
                    'La URL no parece una ficha de producto Mondraker; puede ser una '
                    'familia, página editorial o producto retirado.'
                )

        name = self._extract_product_name(tree, product_json, canonical)
        description = self._extract_description(tree, product_json)
        sizes = self._extract_sizes(lines)
        colors = self._extract_colors(tree, lines)
        price, currency = self._structured_price(tree, product_json, lines)
        category = self._category_path(canonical, name, lines)

        description_html = f'<p>{html.escape(description)}</p>' if description else ''
        details = []
        if sizes:
            details.append('<li><strong>Tallas:</strong> %s</li>' % html.escape(' / '.join(sizes)))
        if colors:
            details.append('<li><strong>Colores:</strong> %s</li>' % html.escape(' / '.join(colors)))
        if details:
            description_html += '<p><strong>Opciones publicadas:</strong></p><ul>%s</ul>' % ''.join(details)

        images = self._json_ld_images(product_json, canonical)
        og_image = self._clean_image_url(self._meta(tree, 'og:image'), canonical)
        if og_image and og_image not in images:
            images.insert(0, og_image)
        for image_url in self._html_images(tree, canonical, name):
            if image_url not in images:
                images.append(image_url)

        ean_variants = []
        if product_json:
            ean_variants.extend(self._ean_variants_from_payload(product_json))
        ean_variants.extend(self._ean_variants_from_html_content(response.content))

        return {
            'name': name,
            'description': description_html,
            'price': price,
            'price_available': bool(price),
            'currency': currency or 'EUR',
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical,
            'style_code': self._style_code(canonical, product_json, lines),
            'color_code': ' / '.join(colors) if colors else False,
            'category_path': ' / '.join(category),
            'ean_variants': self._normalise_ean_variants(ean_variants),
            # Puede haber un GTIN distinto por talla; el enriquecedor común
            # seguirá buscando JSON/endpoints de variación descubiertos.
            'ean_complete': False,
        }
