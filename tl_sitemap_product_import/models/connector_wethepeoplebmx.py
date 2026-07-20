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


class SitemapConnectorWeThePeopleBmx(models.AbstractModel):
    """Conector del catálogo público de WeThePeople BMX.

    El sitio oficial está construido como catálogo de fabricante. El sitemap
    Webflow mezcla páginas editoriales, equipo, noticias, páginas generales y
    fichas de producto. Las fichas válidas se reconocen por su primera carpeta,
    por ejemplo::

        /bikes/prime
        /frames/tomorrow-frame
        /forks/audio-fork-22
        /handlebars/chaos-bar
        /stems-headsets/gooseneck-stem
        /grips-barends/perfect-grips

    El sitio no es la tienda europea (que está enlazada en otro dominio) y, por
    tanto, normalmente no publica precio ni stock. Cuando no existe una oferta
    estructurada se devuelve ``price_available=False`` para que una
    sincronización no borre el precio configurado manualmente en Odoo.
    """

    _name = 'sitemap.connector.wethepeoplebmx'
    _inherit = 'sitemap.import.service'
    _description = 'Conector WeThePeople BMX'

    _HOSTS = {'wethepeoplebmx.de', 'www.wethepeoplebmx.de'}

    # Carpetas de detalle observadas en el catálogo. Se exige siempre un slug
    # adicional, de modo que /bikes o /frames (páginas de índice) no entran.
    _SECTION_LABELS = {
        'bikes': ('Bicicletas BMX',),
        'frames': ('Cuadros BMX',),
        'forks': ('Componentes BMX', 'Horquillas'),
        'handlebars': ('Componentes BMX', 'Manillares'),
        'stems-headsets': ('Componentes BMX', 'Dirección'),
        'grips-barends': ('Componentes BMX', 'Puños y tapones'),
        'pegs-pedals': ('Componentes BMX', 'Pegs y pedales'),
        'cranks-bottom-brackets': ('Componentes BMX', 'Bielas y pedalieres'),
        'sprockets-chains': ('Componentes BMX', 'Platos y cadenas'),
        'hubs-hubguards': ('Componentes BMX', 'Bujes y protectores'),
        'wheels-rims': ('Componentes BMX', 'Ruedas y llantas'),
        'tires': ('Componentes BMX', 'Cubiertas'),
        'seats-seatposts-seatclamps': ('Componentes BMX', 'Sillines y tijas'),
        'misc-parts': ('Componentes BMX', 'Otros componentes'),
    }

    _OVERVIEW_PATHS = (
        '/bikes',
        '/frames',
        '/parts',
        '/forks-ov',
        '/handlebar-ov',
        '/stems-headsets-ov',
        '/grips-barends-ov',
        '/pegs-ov',
        '/cranks-ov',
        '/sprockets-ov',
        '/hub-hubguards-ov',
        '/wheels-rims-ov',
        '/tires-ov',
        '/seats-seatposts-seatclamp-ov',
    )

    _NON_PRODUCT_IMAGE_RE = re.compile(
        r'(?:logo|favicon|icon|sprite|cookie|newsletter|social|payment|flag|'
        r'arrow|loader|placeholder|avatar|team|footer|header|menu|nav|close|'
        r'play-button|youtube|vimeo)',
        re.IGNORECASE,
    )
    _IMAGE_EXT_RE = re.compile(r'\.(?:avif|gif|jpe?g|png|webp)(?:$|\?)', re.IGNORECASE)
    _PRICE_RE = re.compile(
        r'(?<!\d)(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2}))\s*€'
    )

    _SPEC_LABELS = (
        'FRAME', 'FORK', 'BARS', 'GRIPS', 'STEM', 'HEADSET', 'GYRO', 'LEVER',
        'BRAKES', 'CRANKS', 'BB', 'PEDALS', 'CHAIN', 'SPROCKET', 'DRIVER',
        'FRONT HUB', 'REAR HUB', 'HUBGUARDS', 'FRONT RIM', 'REAR RIM', 'SEAT',
        'SEAT POST', 'SEAT CLAMP', 'TIRES', 'PEGS', 'WEIGHT', 'COLORS',
        'MATERIAL', 'SIZE', 'TOP BOLT', 'STEERER LENGTH', 'OFFSET', 'DROPOUTS',
        'BOTTOM BRACKET', 'HEAD TUBE', 'SPECIAL FEATURES', 'TUBING',
    )
    _SECTION_STOPPERS = {
        'SPECIFICATIONS', 'GEOMETRY', 'FEATURES', 'MORE BIKES', 'MORE FRAMES',
        'MORE FORKS', 'MORE PARTS', 'JOIN OUR NEWSLETTER', 'HANDLE BAR',
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
            'Accept-Language': 'en-GB,en;q=0.9,de;q=0.4',
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
        if host == 'wethepeoplebmx.de':
            host = 'www.wethepeoplebmx.de'
        path = re.sub(r'/+', '/', parts.path or '/')
        if path != '/':
            path = path.rstrip('/')
        return urlunsplit((parts.scheme or 'https', host, path, '', ''))

    @classmethod
    def _product_parts(cls, value):
        canonical = cls._canonical_url(value)
        if not canonical:
            return False
        parsed = urlparse(canonical)
        if parsed.netloc.lower() not in cls._HOSTS:
            return False
        segments = [segment for segment in parsed.path.split('/') if segment]
        if len(segments) != 2:
            return False
        section, slug = segments[0].casefold(), segments[1].casefold()
        if section not in cls._SECTION_LABELS:
            return False
        if not slug or slug.endswith('-ov') or slug in {'overview', 'products'}:
            return False
        return section, slug

    @classmethod
    def _product_key(cls, value):
        parts = cls._product_parts(value)
        return f'{parts[0]}/{parts[1]}' if parts else False

    def _iter_sitemap_entries(self, source, sitemap_url, depth=0, visited=None):
        if depth > 8:
            raise ValueError('El sitemap de WeThePeople supera ocho niveles de índices.')
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
                'WeThePeople no devolvió XML válido en '
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
            raise ValueError(
                'El sitemap de WeThePeople no contiene <urlset> ni <sitemapindex>.'
            )

        for url_element in root.xpath('./*[local-name()="url"]'):
            loc_values = url_element.xpath('./*[local-name()="loc"]/text()')
            if not loc_values or not loc_values[0].strip():
                continue
            lastmod_values = url_element.xpath('./*[local-name()="lastmod"]/text()')
            image_values = url_element.xpath(
                './*[local-name()="image"]/*[local-name()="loc"]/text()'
            )
            yield (
                {
                    'url': loc_values[0].strip(),
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
        # srcset puede pasar "url 1200w".
        raw = raw.split()[0]
        absolute = urljoin(page_url, raw)
        parts = urlsplit(absolute)
        if parts.scheme not in ('http', 'https'):
            return False
        if cls._NON_PRODUCT_IMAGE_RE.search(parts.path):
            return False
        if not cls._IMAGE_EXT_RE.search(parts.path):
            return False
        # Webflow sirve la imagen original si se eliminan los parámetros de
        # transformación. En otros hosts se conserva la query porque puede ser
        # necesaria para acceder al recurso.
        query = '' if 'website-files.com' in parts.netloc else parts.query
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ''))

    def _collect_sitemap_products(self, source):
        entries_by_key = {}
        images_by_key = {}
        for entry, image_urls in self._iter_sitemap_entries(
            source, source.sitemap_index_url
        ):
            canonical = self._canonical_url(entry['url'])
            key = self._product_key(canonical)
            if not key:
                continue
            candidate = {
                'url': canonical,
                'lastmod': entry.get('lastmod') or False,
            }
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
        """Respaldo si Webflow entrega temporalmente una página HTML.

        Solo se ejecuta cuando el sitemap no puede leerse. Recorre las páginas
        de índice públicas y vuelve a aplicar el filtro estricto de carpetas.
        """
        session = self._get_session(source)
        entries = {}
        for path in self._OVERVIEW_PATHS:
            page_url = urljoin('https://www.wethepeoplebmx.de/', path)
            try:
                response = self._http_get(session, page_url, source)
                tree = lxml_html.fromstring(response.content)
            except Exception as exc:
                _logger.debug('WeThePeople: no se pudo recorrer %s: %s', page_url, exc)
                continue
            for href in tree.xpath('//a[@href]/@href'):
                canonical = self._canonical_url(urljoin(page_url, href))
                key = self._product_key(canonical)
                if key:
                    entries.setdefault(key, {'url': canonical, 'lastmod': False})
        return entries

    def get_product_entries(self, source, category_filter=None, limit=0):
        try:
            sitemap_entries, _images = self._collect_sitemap_products(source)
        except Exception as exc:
            _logger.warning('WeThePeople: no se pudo procesar el sitemap: %s', exc)
            sitemap_entries = {}
        try:
            catalog_entries = self._fallback_product_entries(source)
        except Exception as exc:
            _logger.warning('WeThePeople: no se pudo recorrer el catálogo alternativo: %s', exc)
            catalog_entries = {}

        result = self._merge_discovery_entries(
            'WeThePeople',
            [
                ('sitemap', list(sitemap_entries.values())),
                ('catalogo_html', list(catalog_entries.values())),
            ],
            key_getter=self._product_key,
            category_filter=category_filter,
            limit=limit,
        )
        if not result:
            raise ValueError('No se localizaron fichas de bicicletas, cuadros o componentes en WeThePeople.')
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
    # Categorías y códigos
    # ------------------------------------------------------------------
    @staticmethod
    def _humanize_slug(value):
        words = re.sub(r'[-_]+', ' ', str(value or '')).split()
        return ' '.join(word.upper() if word.lower() in {'bmx', 'bb'} else word.capitalize()
                        for word in words)

    @classmethod
    def parse_category_path(cls, product_url):
        parts = cls._product_parts(product_url)
        if not parts:
            return []
        section, slug = parts
        path = list(cls._SECTION_LABELS[section])
        text = slug.casefold()

        if section == 'pegs-pedals':
            path[-1] = 'Pedales' if 'pedal' in text else 'Pegs'
        elif section == 'wheels-rims':
            if 'rim' in text:
                path[-1] = 'Llantas'
            elif 'spoke' in text or 'tape' in text:
                path[-1] = 'Radios y fondos de llanta'
            else:
                path[-1] = 'Ruedas'
        elif section == 'stems-headsets':
            if 'stem' in text:
                path[-1] = 'Potencias'
            elif 'gyro' in text:
                path[-1] = 'Rotores y placas'
            else:
                path[-1] = 'Direcciones'
        elif section == 'grips-barends':
            path[-1] = 'Puños' if 'grip' in text else 'Tapones de manillar'
        elif section == 'cranks-bottom-brackets':
            path[-1] = 'Bielas' if 'crank' in text else 'Pedalieres'
        elif section == 'sprockets-chains':
            if 'chain' in text:
                path[-1] = 'Cadenas'
            elif 'guard' in text and 'sprocket' not in text:
                path[-1] = 'Protectores de plato'
            else:
                path[-1] = 'Platos'
        elif section == 'hubs-hubguards':
            path[-1] = 'Protectores de buje' if 'guard' in text else 'Bujes'
        elif section == 'seats-seatposts-seatclamps':
            if 'post' in text:
                path[-1] = 'Tijas'
            elif 'clamp' in text:
                path[-1] = 'Abrazaderas de sillín'
            else:
                path[-1] = 'Sillines'
        return path

    @classmethod
    def _style_code(cls, product_url, lines):
        labels = (
            'SKU', 'ARTICLE', 'ARTICLE NUMBER', 'ITEM NUMBER', 'ITEM NO',
            'PRODUCT CODE', 'MODEL NUMBER', 'ART.-NR', 'ARTIKELNUMMER',
        )
        for index, line in enumerate(lines):
            upper = line.upper().rstrip(':')
            for label in labels:
                if upper == label and index + 1 < len(lines):
                    candidate = re.sub(r'\s+', '', lines[index + 1]).upper()
                    if re.fullmatch(r'[A-Z0-9._/-]{3,40}', candidate):
                        return candidate
                match = re.match(
                    rf'^{re.escape(label)}\s*[:#-]\s*([A-Z0-9._/-]{{3,40}})$',
                    line,
                    flags=re.IGNORECASE,
                )
                if match:
                    return match.group(1).upper()
        # El fabricante no publica siempre un artículo comercial. El slug es
        # estable y sirve como referencia web sin fingir que sea un GTIN.
        parts = cls._product_parts(product_url)
        return parts[1].upper() if parts else False

    # ------------------------------------------------------------------
    # HTML de producto
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
        # ``text_content()`` no inserta necesariamente saltos entre bloques en
        # HTML Webflow. Cada nodo de texto se trata como una línea lógica para
        # conservar pares como ``COLORS:`` / ``Black`` o ``WEIGHT:`` / ``4.8kg``.
        for raw in scope.xpath('.//text()[normalize-space()]'):
            value = cls._normalize_text(raw)
            if value and (not result or result[-1] != value):
                result.append(value)
        return result

    @classmethod
    def _name_from_tree(cls, tree, product_json, page_url):
        values = tree.xpath('//main//h1[1]//text()') or tree.xpath('//h1[1]//text()')
        name = cls._normalize_text(' '.join(values)) if values else False
        name = name or cls._normalize_text(product_json.get('name'))
        name = name or cls._meta(tree, 'og:title') or cls._meta(tree, 'twitter:title')
        if name:
            name = re.sub(
                r'^WETHEPEOPLE\s+BMX\s+', '', name, flags=re.IGNORECASE
            )
            name = re.sub(
                r'\s*[-|]\s*WETHEPEOPLEBMX.*$', '', name, flags=re.IGNORECASE
            ).strip()
        if not name:
            parts = cls._product_parts(page_url)
            name = cls._humanize_slug(parts[1] if parts else page_url)
        return name

    @classmethod
    def _longest_product_paragraph(cls, tree):
        h1_nodes = tree.xpath('//main//h1[1]') or tree.xpath('//h1[1]')
        if not h1_nodes:
            return ''
        candidates = []
        for node in h1_nodes[0].xpath('following::p[position() <= 20]'):
            text = cls._normalize_text(' '.join(node.itertext()))
            if len(text) < 45:
                continue
            lowered = text.casefold()
            if any(token in lowered for token in (
                'cookie', 'privacy', 'newsletter', 'all rights reserved',
                'your browser', 'storage type', 'accept all',
            )):
                continue
            candidates.append(text)
        return max(candidates, key=len) if candidates else ''

    @classmethod
    def _extract_description(cls, tree, product_json):
        description = cls._normalize_text(product_json.get('description'))
        meta_description = cls._meta(tree, 'og:description') or cls._meta(tree, 'description')
        paragraph = cls._longest_product_paragraph(tree)
        candidates = [item for item in (description, meta_description, paragraph) if item]
        return max(candidates, key=len) if candidates else ''

    @classmethod
    def _labelled_blocks(cls, lines):
        labels = {label.upper() for label in cls._SPEC_LABELS}
        stoppers = labels | {item.upper() for item in cls._SECTION_STOPPERS}
        blocks = {}
        for index, line in enumerate(lines):
            normalized = line.upper().rstrip(':').strip()
            if normalized not in labels:
                continue
            values = []
            for candidate in lines[index + 1:index + 10]:
                candidate_norm = candidate.upper().rstrip(':').strip()
                if candidate_norm in stoppers:
                    break
                if candidate in {'/', '-', '–', '—', 'plus'}:
                    continue
                if candidate.casefold() in {'no items found.', 'no items found'}:
                    continue
                if len(candidate) > 1200:
                    candidate = candidate[:1200]
                if candidate and candidate not in values:
                    values.append(candidate)
                if normalized != 'SPECIAL FEATURES' and len(values) >= 4:
                    break
            if values:
                # La página repite algunos bloques. Se conserva la versión con
                # más información, no la última por defecto.
                current = blocks.get(normalized, [])
                if sum(map(len, values)) > sum(map(len, current)):
                    blocks[normalized] = values
        return blocks

    @classmethod
    def _colors_from_blocks(cls, blocks, name=''):
        values = blocks.get('COLORS') or []
        colors = []
        for value in values:
            for part in re.split(r'\s*/\s*|\s*\|\s*|\s*;\s*', value):
                color = cls._normalize_text(part).strip(' -/')
                if not color or color.casefold() == name.casefold():
                    continue
                if color.upper().rstrip(':') in {
                    label.upper() for label in cls._SPEC_LABELS
                }:
                    continue
                if len(color) > 80:
                    continue
                if color.casefold() not in {item.casefold() for item in colors}:
                    colors.append(color)
        return colors

    @classmethod
    def _description_with_specs(cls, description, blocks):
        selected_labels = (
            'MATERIAL', 'SIZE', 'WEIGHT', 'OFFSET', 'FRAME', 'FORK', 'BARS',
            'CRANKS', 'BRAKES', 'TIRES', 'SPECIAL FEATURES',
        )
        items = []
        for label in selected_labels:
            values = blocks.get(label)
            if not values:
                continue
            value = ' / '.join(values)
            if len(value) > 1500:
                value = value[:1497] + '...'
            items.append(
                '<li><strong>%s:</strong> %s</li>' % (
                    html.escape(label.title()), html.escape(value),
                )
            )
        base = f'<p>{html.escape(description)}</p>' if description else ''
        if items:
            base += '<p><strong>Especificaciones publicadas:</strong></p><ul>%s</ul>' % ''.join(items)
        return base or ''

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
    def _structured_price(cls, tree, product_json):
        offers = product_json.get('offers') if isinstance(product_json, dict) else None
        offers = offers if isinstance(offers, list) else [offers]
        values = []
        currency = False
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            currency = currency or offer.get('priceCurrency')
            for field in ('salePrice', 'price', 'lowPrice'):
                parsed = cls._parse_price(offer.get(field))
                if parsed is not False:
                    values.append(parsed)
                    break
        if values:
            return min(values), currency or 'EUR'

        meta_value = cls._meta(tree, 'product:price:amount') or cls._meta(tree, 'og:price:amount')
        parsed = cls._parse_price(meta_value)
        if parsed is not False:
            return parsed, (
                cls._meta(tree, 'product:price:currency')
                or cls._meta(tree, 'og:price:currency')
                or 'EUR'
            )
        return 0.0, 'EUR'

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
            'or contains(translate(@class,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"lightbox") '
            'or contains(translate(@class,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"colour") '
            'or contains(translate(@class,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"color")]'
        )
        nodes = []
        for scope in scopes[:80]:
            nodes.extend(scope.xpath('.//img | .//source | .//a[@href]'))
        if not nodes:
            main = (tree.xpath('//main') or [tree])[0]
            nodes = main.xpath('.//img | .//source | .//a[@href]')

        for node in nodes:
            label = cls._normalize_text(' '.join(filter(None, [
                node.get('alt'), node.get('title'), node.get('aria-label'),
            ])))
            lowered_label = label.casefold()
            # En las galerías Webflow el alt suele ser el nombre del producto;
            # si contiene un nombre de otro artículo se trata de recomendación.
            label_tokens = {
                token for token in re.findall(r'[a-z0-9]+', lowered_label) if len(token) >= 4
            }
            if label_tokens and name_tokens and not (label_tokens & name_tokens):
                if not any(word in lowered_label for word in ('product', 'image', 'colour', 'color')):
                    continue

            candidates = []
            for attr in ('href', 'src', 'data-src', 'data-original', 'data-lazy-src'):
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
                cleaned = cls._clean_image_url(raw, page_url)
                if cleaned and cleaned not in result:
                    result.append(cleaned)
        return result

    @classmethod
    def _category_from_preview(cls, page_url, name, lines):
        path = cls.parse_category_path(page_url)
        parts = cls._product_parts(page_url)
        if not parts:
            return path
        section = parts[0]
        text = f'{name} {" ".join(lines[:80])}'.casefold()

        if section == 'bikes':
            size_match = re.search(r'\b(12|14|16|18|20|22|24|27[.,]5)\s*["“″]', text)
            if size_match:
                path.append(f'{size_match.group(1).replace(",", ".")} pulgadas')
        elif section == 'frames':
            subtype_map = (
                ('flatland', 'Flatland'), ('street', 'Street'), ('park', 'Park'),
                ('trail', 'Trail y transición'), ('transition', 'Trail y transición'),
                ('all-round', 'All-round'), ('allround', 'All-round'),
            )
            for needle, label in subtype_map:
                if needle in text:
                    path.append(label)
                    break
        return path

    def fetch_preview(self, source, url):
        session = self._get_session(source)
        response = self._http_get(session, url, source)
        tree = lxml_html.fromstring(response.content)

        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical = self._canonical_url(
            canonical_values[0] if canonical_values else response.url or url
        )
        if not self._product_parts(canonical):
            fallback = self._canonical_url(url)
            if self._product_parts(fallback):
                canonical = fallback
            else:
                raise ValueError(
                    'La URL ya no apunta a una ficha de producto WeThePeople; '
                    'posible redirección o producto retirado.'
                )

        product_json = self._find_product_json_ld(tree)
        name = self._name_from_tree(tree, product_json, canonical)
        lines = self._page_lines(tree)
        blocks = self._labelled_blocks(lines)
        colors = self._colors_from_blocks(blocks, name)
        description = self._extract_description(tree, product_json)
        description_html = self._description_with_specs(description, blocks)
        price, currency = self._structured_price(tree, product_json)

        images = self._json_ld_images(product_json, canonical)
        og_image = self._clean_image_url(self._meta(tree, 'og:image'), canonical)
        if og_image and og_image not in images:
            images.insert(0, og_image)
        for image_url in self._html_images(tree, canonical, name):
            if image_url not in images:
                images.append(image_url)

        ean_variants = self._ean_variants_from_html_content(response.content)
        category = self._category_from_preview(canonical, name, lines)

        return {
            'name': name,
            'description': description_html,
            'price': price,
            'price_available': bool(price),
            'currency': currency or 'EUR',
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical,
            'style_code': self._style_code(canonical, lines),
            'color_code': ' / '.join(colors) if colors else False,
            'category_path': ' / '.join(category),
            'ean_variants': self._normalise_ean_variants(ean_variants),
            # La web de fabricante no expone un feed completo de variantes.
            # El enriquecedor común puede investigar JSON/endpoints adicionales.
            'ean_complete': False,
        }
