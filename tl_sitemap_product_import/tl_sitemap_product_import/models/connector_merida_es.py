import gzip
import html
import json
import logging
import re
from collections import deque
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorMeridaEs(models.AbstractModel):
    """Conector para el catálogo español de MERIDA BIKES.

    La web no publica siempre un sitemap de producto estable. Las fichas se
    descubren primero desde robots.txt y los endpoints XML habituales y, si no
    están disponibles, desde el buscador público de bicicletas. Sus URLs usan
    varias formas equivalentes::

        /es-es/bike/5640/
        /es-es/bike/5639/scultura-9000
        /es-es/bike/5639-7796/
        /es-es/bike/4626-6529/eone-sixty-sl-10k

    El primer número identifica el modelo de la ficha y el segundo, cuando
    existe, la versión/artículo seleccionado. Se deduplica por modelo y se
    prefiere la URL más específica. Los GTIN solo se conservan cuando superan
    la validación GS1 común del módulo.
    """

    _name = 'sitemap.connector.merida_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector MERIDA BIKES España'

    _HOSTS = {'www.merida-bikes.com', 'merida-bikes.com'}
    _PRODUCT_PATH_RE = re.compile(
        r'^/es[-_]es/bike/(?P<model_id>\d+)'
        r'(?:-(?P<article_id>\d+))?'
        r'(?:/(?P<slug>[^/?#]+))?/?$',
        re.IGNORECASE,
    )
    _IMAGE_EXT_RE = re.compile(r'\.(?:avif|gif|jpe?g|png|webp)(?:$|\?)', re.IGNORECASE)
    _NON_PRODUCT_IMAGE_RE = re.compile(
        r'(?:logo|favicon|icon|sprite|cookie|newsletter|social|payment|flag|'
        r'loader|placeholder|avatar|footer|header|menu|nav|country|language|'
        r'dealer|storefinder|store-finder|youtube|vimeo|award|badge)',
        re.IGNORECASE,
    )
    _PRICE_RE = re.compile(
        r'(?<!\d)(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2}))\s*€'
    )
    _REFERENCE_RE = re.compile(
        r'(?:n[uú]mero\s+de\s+art[ií]culo|art[ií]culo|article\s*(?:number|no\.?|id)|'
        r'item\s*(?:number|no\.?)|product\s*(?:number|code)|sku|mpn)\s*[:#-]?\s*'
        r'([A-Z0-9][A-Z0-9._/\-]{2,40})',
        re.IGNORECASE,
    )

    _DISCOVERY_PAGES = (
        'https://www.merida-bikes.com/es-es/bikefinder',
        'https://www.merida-bikes.com/es-ES/bikefinder/default/index',
        'https://www.merida-bikes.com/es-es/bikefinder/tag/bikes-83/root/bikes',
    )

    _SPEC_LABELS = (
        'Cuadro', 'Talla', 'Tallas', 'Horquilla', 'Amortiguador', 'Cambio',
        'Desviador', 'Frenos', 'Batería', 'Motor', 'Peso', 'Ruedas',
        'Neumáticos', 'Cassette', 'Cadena', 'Bielas', 'Manillar', 'Potencia',
        'Tija', 'Sillín', 'Color', 'Colores', 'Material', 'Recorrido',
    )

    # ------------------------------------------------------------------
    # Red, URLs y XML
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
        return etree.QName(element).localname.casefold()

    @classmethod
    def _canonical_url(cls, value):
        raw = html.unescape(str(value or '')).strip().replace('\\/', '/')
        if not raw:
            return False
        parts = urlsplit(raw)
        host = parts.netloc.casefold()
        if host == 'merida-bikes.com':
            host = 'www.merida-bikes.com'
        path = re.sub(r'/+', '/', parts.path or '/')
        path = re.sub(r'^/es[-_]es/', '/es-es/', path, flags=re.IGNORECASE)
        if path != '/':
            path = path.rstrip('/')
        return urlunsplit((parts.scheme or 'https', host, path, '', ''))

    @classmethod
    def _product_match(cls, value):
        canonical = cls._canonical_url(value)
        if not canonical:
            return False
        parsed = urlparse(canonical)
        if parsed.netloc.casefold() not in cls._HOSTS:
            return False
        return cls._PRODUCT_PATH_RE.match(parsed.path)

    @classmethod
    def _product_key(cls, value):
        match = cls._product_match(value)
        return match.group('model_id') if match else False

    @classmethod
    def _url_quality(cls, value):
        match = cls._product_match(value)
        if not match:
            return -1
        score = 0
        if match.group('article_id'):
            score += 4
        if match.group('slug'):
            score += 2
        if value.casefold().startswith('https://www.'):
            score += 1
        return score

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
        if cls._NON_PRODUCT_IMAGE_RE.search(absolute):
            return False
        if not cls._IMAGE_EXT_RE.search(parts.path):
            return False
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))

    @staticmethod
    def _robots_sitemaps(text, base_url):
        result = []
        for line in str(text or '').splitlines():
            match = re.match(r'^\s*Sitemap\s*:\s*(\S+)\s*$', line, re.IGNORECASE)
            if match:
                value = urljoin(base_url, match.group(1).strip())
                if value not in result:
                    result.append(value)
        return result

    def _candidate_sitemaps(self, source):
        root = 'https://www.merida-bikes.com/'
        candidates = []
        session = self._get_session(source)
        for url in (
            'https://www.merida-bikes.com/robots.txt',
            source.sitemap_index_url,
        ):
            if not url:
                continue
            try:
                response = session.get(
                    url,
                    timeout=source.request_timeout or 20,
                    allow_redirects=True,
                )
                if response.status_code >= 400:
                    continue
                candidates.extend(self._robots_sitemaps(response.text, response.url))
                payload = response.content.lstrip()
                if payload.startswith((b'<?xml', b'<urlset', b'<sitemapindex')) or payload[:2] == b'\x1f\x8b':
                    candidates.insert(0, response.url)
            except Exception as exc:
                _logger.info('MERIDA: no se pudo consultar %s: %s', url, exc)

        candidates.extend([
            urljoin(root, 'sitemap.xml'),
            urljoin(root, 'sitemap_index.xml'),
            urljoin(root, 'sitemapindex.xml'),
            urljoin(root, 'sitemap/sitemap.xml'),
        ])
        return list(dict.fromkeys(candidates))

    def _iter_sitemap_entries(self, source, sitemap_url, depth=0, visited=None):
        if depth > 10:
            raise ValueError('El sitemap de MERIDA supera diez niveles de índices.')
        visited = visited or set()
        parts = urlsplit(sitemap_url)
        clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))
        if clean_url in visited:
            return
        visited.add(clean_url)

        session = self._get_session(source)
        response = self._http_get(session, clean_url, source)
        root = self._xml_root(response.content)
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
            raise ValueError('El XML de MERIDA no contiene <urlset> ni <sitemapindex>.')

        for url_element in root.xpath('./*[local-name()="url"]'):
            locs = url_element.xpath('./*[local-name()="loc"]/text()')
            alternates = url_element.xpath(
                './*[local-name()="link" and '
                'translate(@hreflang,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")='
                '"es-es"]/@href'
            )
            selected = False
            for candidate in alternates + locs:
                canonical = self._canonical_url(candidate)
                if self._product_match(canonical):
                    selected = canonical
                    break
            if not selected:
                continue
            lastmods = url_element.xpath('./*[local-name()="lastmod"]/text()')
            images = url_element.xpath(
                './*[local-name()="image"]/*[local-name()="loc"]/text()'
            )
            yield {
                'url': selected,
                'lastmod': self._parse_lastmod(lastmods[0] if lastmods else None),
                'images': [item.strip() for item in images if item and item.strip()],
            }

    def _merge_entry(self, entries, images, entry):
        key = self._product_key(entry.get('url'))
        if not key:
            return
        candidate = {
            'url': self._canonical_url(entry['url']),
            'lastmod': entry.get('lastmod') or False,
        }
        current = entries.get(key)
        if not current or self._url_quality(candidate['url']) > self._url_quality(current['url']):
            entries[key] = candidate
        elif candidate['lastmod'] and (
            not current.get('lastmod') or candidate['lastmod'] > current['lastmod']
        ):
            current['lastmod'] = candidate['lastmod']

        target = images.setdefault(key, [])
        for raw in entry.get('images') or []:
            cleaned = self._clean_image_url(raw, candidate['url'])
            if cleaned and cleaned not in target:
                target.append(cleaned)

    def _collect_xml_products(self, source):
        entries = {}
        images = {}
        errors = []
        for sitemap_url in self._candidate_sitemaps(source):
            try:
                found = False
                for entry in self._iter_sitemap_entries(source, sitemap_url):
                    found = True
                    self._merge_entry(entries, images, entry)
                if found and entries:
                    break
            except Exception as exc:
                errors.append(f'{sitemap_url}: {exc}')
                _logger.info('MERIDA: sitemap no utilizable %s: %s', sitemap_url, exc)
        return entries, images, errors

    # ------------------------------------------------------------------
    # Respaldo mediante el bikefinder público
    # ------------------------------------------------------------------
    @classmethod
    def _is_catalog_index_url(cls, value):
        canonical = cls._canonical_url(value)
        if not canonical:
            return False
        parsed = urlparse(canonical)
        if parsed.netloc.casefold() not in cls._HOSTS:
            return False
        path = parsed.path.casefold()
        return path.startswith('/es-es/bikefinder') or path.startswith('/es-es/group/')

    def _fallback_catalog_entries(self, source, max_pages=80):
        session = self._get_session(source)
        entries = {}
        queue = deque(self._DISCOVERY_PAGES)
        visited = set()

        while queue and len(visited) < max_pages:
            page_url = self._canonical_url(queue.popleft())
            if not page_url or page_url in visited:
                continue
            visited.add(page_url)
            try:
                response = self._http_get(session, page_url, source)
                tree = lxml_html.fromstring(response.content)
            except Exception as exc:
                _logger.info('MERIDA: catálogo no accesible %s: %s', page_url, exc)
                continue

            for href in tree.xpath('//a[@href]/@href'):
                absolute = self._canonical_url(urljoin(response.url, href))
                if self._product_match(absolute):
                    self._merge_entry(entries, {}, {'url': absolute, 'lastmod': False})
                elif self._is_catalog_index_url(absolute) and absolute not in visited:
                    queue.append(absolute)

        return entries

    def _collect_products(self, source):
        entries, images, errors = self._collect_xml_products(source)
        if not entries:
            entries = self._fallback_catalog_entries(source)
        return entries, images, errors

    def get_product_entries(self, source, category_filter=None, limit=0):
        entries, images, errors = self._collect_products(source)
        self._merida_entries_cache = entries
        self._merida_images_cache = images
        if not entries:
            detail = ' | '.join(errors[:4])
            raise ValueError(
                'No se localizaron fichas MERIDA bajo /es-es/bike/. '
                'No fue posible procesar un sitemap ni el buscador público.'
                + (f' Intentos: {detail}' if detail else '')
            )

        needle = (category_filter or '').strip().casefold()
        result = []
        for key, entry in sorted(entries.items(), key=lambda item: int(item[0])):
            category = '/'.join(self.parse_category_path(entry['url']))
            haystack = f'{entry["url"]} {key} {category}'.casefold()
            if needle and needle not in haystack:
                continue
            result.append(entry)
            if limit and len(result) >= limit:
                break
        return result

    def get_image_map(self, source):
        entries = getattr(self, '_merida_entries_cache', None)
        images = getattr(self, '_merida_images_cache', None)
        if entries is None or images is None:
            entries, images, _errors = self._collect_products(source)
        return {
            entry['url']: images.get(key, [])
            for key, entry in entries.items()
            if images.get(key)
        }

    # ------------------------------------------------------------------
    # HTML y clasificación
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
    def _json_payloads(cls, tree):
        result = []
        for raw in tree.xpath(
            '//script[@type="application/ld+json" or @type="application/json"]/text()'
        ):
            if not raw or len(raw) > 8_000_000:
                continue
            try:
                result.append(json.loads(raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return result

    @classmethod
    def _product_json(cls, tree):
        found = []

        def walk(value):
            if isinstance(value, list):
                for item in value:
                    walk(item)
                return
            if not isinstance(value, dict):
                return
            types = value.get('@type')
            types = types if isinstance(types, list) else [types]
            if any(str(item).casefold() == 'product' for item in types if item):
                found.append(value)
            for key in ('@graph', 'mainEntity', 'itemListElement', 'hasVariant', 'variants'):
                if key in value:
                    walk(value[key])

        for payload in cls._json_payloads(tree):
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
    def _extract_product_name(cls, tree, product_json, product_url):
        values = tree.xpath('//main//h1[1]//text()') or tree.xpath('//h1[1]//text()')
        name = cls._normalize_text(' '.join(values)) if values else False
        name = name or cls._normalize_text(product_json.get('name'))
        name = name or cls._meta(tree, 'og:title') or cls._meta(tree, 'twitter:title')
        if name:
            name = re.sub(r'\s*[-|]\s*MERIDA(?:\s+BIKES)?.*$', '', name, flags=re.IGNORECASE).strip()
        if not name:
            match = cls._product_match(product_url)
            slug = match.group('slug') if match else ''
            name = re.sub(r'[-_]+', ' ', slug).upper() if slug else f'MERIDA {match.group("model_id")}'
        return name

    @classmethod
    def _description(cls, tree, product_json):
        candidates = []
        for value in (
            product_json.get('description'),
            cls._meta(tree, 'og:description'),
            cls._meta(tree, 'description'),
        ):
            text = cls._normalize_text(value)
            if text and len(text) > 40:
                candidates.append(text)
        for node in tree.xpath('//main//p | //article//p')[:40]:
            text = cls._normalize_text(' '.join(node.itertext()))
            if len(text) > 80 and not any(token in text.casefold() for token in (
                'cookie', 'newsletter', 'privacy', 'política de privacidad', 'all rights reserved',
            )):
                candidates.append(text)
        return max(candidates, key=len) if candidates else ''

    @classmethod
    def _label_values(cls, lines):
        labels = {item.casefold(): item for item in cls._SPEC_LABELS}
        result = {}
        for index, line in enumerate(lines):
            normalized = line.rstrip(':').strip().casefold()
            label = labels.get(normalized)
            inline = False
            if not label:
                for key, original in labels.items():
                    if normalized.startswith(key + ':'):
                        label = original
                        inline = line.split(':', 1)[1].strip()
                        break
            values = []
            if inline:
                values.append(inline)
            elif label:
                for candidate in lines[index + 1:index + 5]:
                    if candidate.rstrip(':').strip().casefold() in labels:
                        break
                    if len(candidate) > 220:
                        break
                    if candidate not in values:
                        values.append(candidate)
                    if len(values) >= 2:
                        break
            if label and values:
                current = result.get(label, [])
                if sum(map(len, values)) > sum(map(len, current)):
                    result[label] = values
        return result

    @classmethod
    def _description_with_specs(cls, description, specs):
        parts = []
        if description:
            parts.append(f'<p>{html.escape(description)}</p>')
        if specs:
            rows = []
            for label, values in specs.items():
                value = ' / '.join(values)
                rows.append(
                    f'<p><strong>{html.escape(label)}:</strong> {html.escape(value)}</p>'
                )
            parts.append(''.join(rows))
        return ''.join(parts) or description or ''

    @classmethod
    def _style_code(cls, product_json, tree, lines, product_url):
        for key in ('sku', 'mpn', 'productID', 'productId', 'model'):
            value = cls._normalize_text(product_json.get(key))
            if value and re.fullmatch(r'[A-Z0-9._/\-]{3,50}', value, re.IGNORECASE):
                return value.upper()
        body_text = cls._normalize_text(' '.join(lines))
        match = cls._REFERENCE_RE.search(body_text)
        if match:
            return match.group(1).upper()
        for attr in ('data-sku', 'data-product-number', 'data-article-number', 'data-product-id'):
            values = tree.xpath(f'//*[@{attr}]/@{attr}')
            for value in values:
                candidate = cls._normalize_text(value)
                if re.fullmatch(r'[A-Z0-9._/\-]{3,50}', candidate, re.IGNORECASE):
                    return candidate.upper()
        match = cls._product_match(product_url)
        identifier = match.group('article_id') or match.group('model_id') if match else False
        return f'MERIDA-{identifier}' if identifier else False

    @classmethod
    def _structured_price(cls, tree, product_json):
        offers = product_json.get('offers') or {}
        offers = offers if isinstance(offers, list) else [offers]
        values = []
        currency = False
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            currency = currency or offer.get('priceCurrency')
            for key in ('price', 'lowPrice', 'salePrice'):
                raw = offer.get(key)
                if raw is None:
                    continue
                try:
                    values.append(float(str(raw).replace(' ', '').replace(',', '.')))
                except (TypeError, ValueError):
                    pass
        if values:
            positive = [value for value in values if value > 0]
            return (min(positive) if positive else 0.0), currency or 'EUR'

        text = cls._normalize_text(' '.join(tree.xpath('//main//text()')))
        candidates = []
        for match in cls._PRICE_RE.finditer(text):
            context = text[max(0, match.start() - 40):match.end() + 40].casefold()
            if any(token in context for token in ('mes', 'month', 'financi', 'cuota', 'desde al mes')):
                continue
            raw = match.group(1).replace(' ', '').replace('.', '').replace(',', '.')
            try:
                value = float(raw)
            except ValueError:
                continue
            if value >= 100:
                candidates.append(value)
        return (min(candidates), 'EUR') if candidates else (0.0, 'EUR')

    @classmethod
    def _json_images(cls, product_json, product_url):
        values = product_json.get('image') or []
        if isinstance(values, (str, dict)):
            values = [values]
        result = []
        for value in values:
            if isinstance(value, dict):
                value = value.get('url') or value.get('contentUrl')
            cleaned = cls._clean_image_url(value, product_url)
            if cleaned and cleaned not in result:
                result.append(cleaned)
        return result

    @classmethod
    def _html_images(cls, tree, product_url):
        result = []
        nodes = tree.xpath('//main//img | //article//img | //*[@data-background-image]')
        for node in nodes:
            candidates = []
            for attr in ('data-src', 'data-lazy-src', 'data-original', 'src', 'data-background-image'):
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
                cleaned = cls._clean_image_url(raw, product_url)
                if cleaned and cleaned not in result:
                    result.append(cleaned)
        return result

    @classmethod
    def _category_from_content(cls, name, lines):
        text = f'{name} {" ".join(lines[:180])}'.casefold()
        electric = any(token in text for token in (
            'motor ', 'batería', 'battery', 'e-bike', 'ebike', 'e-mtb', 'emtb',
            'bosch performance', 'shimano ep', 'mahle x30',
        )) or name.casefold().startswith('e')
        root = 'Bicicletas eléctricas' if electric else 'Bicicletas'

        patterns = (
            (('lithos', 'one-sixty', 'one-eighty', 'enduro'), 'Enduro'),
            (('one-forty', 'one-twenty', 'trail'), 'Trail'),
            (('ninety-six', 'cross country', 'xc '), 'Cross Country'),
            (('big.nine', 'big nine', 'big.seven', 'big seven', 'matts'), 'MTB rígidas'),
            (('silex', 'gravel'), 'Gravel'),
            (('scultura endurance',), 'Carretera / Gran fondo'),
            (('scultura',), 'Carretera / Competición'),
            (('reacto',), 'Carretera / Aero'),
            (('time warp', 'triathlon', 'triatlón'), 'Carretera / Triatlón y contrarreloj'),
            (('speeder', 'fitness'), 'Fitness'),
            (('crossway', 'trekking', 'big.tour', 'big tour'), 'Trekking'),
            (('espresso', 'efloat city', 'urban', 'city'), 'Urbanas'),
            (('junior', 'matts j', 'kids', 'niño'), 'Infantiles'),
        )
        for needles, label in patterns:
            if any(token in text for token in needles):
                return [root] + label.split(' / ')
        return [root]

    @classmethod
    def parse_category_path(cls, product_url):
        return ['Bicicletas'] if cls._product_match(product_url) else []

    def fetch_preview(self, source, url):
        session = self._get_session(source)
        response = self._http_get(session, url, source)
        tree = lxml_html.fromstring(response.content)

        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical = self._canonical_url(
            canonical_values[0] if canonical_values else response.url or url
        )
        if not self._product_match(canonical):
            fallback = self._canonical_url(url)
            if self._product_match(fallback):
                canonical = fallback
            else:
                raise ValueError(
                    'La URL ya no apunta a una ficha española de MERIDA; '
                    'posible redirección o modelo retirado.'
                )

        product_json = self._product_json(tree)
        lines = self._page_lines(tree)
        name = self._extract_product_name(tree, product_json, canonical)
        specs = self._label_values(lines)
        description = self._description_with_specs(
            self._description(tree, product_json), specs
        )
        price, currency = self._structured_price(tree, product_json)

        images = self._json_images(product_json, canonical)
        og_image = self._clean_image_url(self._meta(tree, 'og:image'), canonical)
        if og_image and og_image not in images:
            images.insert(0, og_image)
        for image_url in self._html_images(tree, canonical):
            if image_url not in images:
                images.append(image_url)

        colors = specs.get('Color') or specs.get('Colores') or []
        ean_variants = self._ean_variants_from_html_content(response.content)
        category = self._category_from_content(name, lines)

        return {
            'name': name,
            'description': description,
            'price': price,
            'price_available': bool(price),
            'currency': currency or 'EUR',
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical,
            'style_code': self._style_code(product_json, tree, lines, canonical),
            'color_code': ' / '.join(colors) if colors else False,
            'category_path': ' / '.join(category),
            'ean_variants': self._normalise_ean_variants(ean_variants),
            'ean_complete': False,
        }
