import gzip
import html
import json
import logging
import re
from datetime import datetime
from urllib.parse import unquote, urljoin, urlparse, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorRidleyEs(models.AbstractModel):
    """Conector del catálogo español de Ridley Bikes.

    ``robots.txt`` declara un ``sitemap_index.xml`` relativo. Las fichas de
    bicicletas y e-bikes del mercado español se publican bajo::

        /es_ES/bikes/<referencia>

    Ejemplos observados::

        /es_ES/bikes/SBIEGCRID002
        /es_ES/bikes/SBIFRSRID212
        /es_ES/bikes/FFSARSRID006

    Cada URL representa una configuración concreta (montaje/diseño/talla), no
    solo una familia genérica. La referencia de la URL se conserva como código
    estable. Los GTIN que Ridley publique en JSON-LD, estado JavaScript,
    atributos HTML o endpoints de variación se guardan mediante el flujo común
    de ``sitemap.product.ean``.
    """

    _name = 'sitemap.connector.ridley_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Ridley Bikes España'

    _HOSTS = {'ridley-bikes.com', 'www.ridley-bikes.com'}
    _PRODUCT_PATH_RE = re.compile(
        r'^/(?:es|en)[_-]ES/bikes/(?P<reference>[A-Z0-9]{8,24})/?$',
        re.IGNORECASE,
    )
    _PRICE_RE = re.compile(
        r'(?:€\s*(\d[\d.,\s]*\d|\d)|'
        r'(\d[\d.,\s]*\d|\d)\s*€)',
        re.IGNORECASE,
    )
    _NON_PRODUCT_IMAGE_RE = re.compile(
        r'(?:logo|favicon|icon|sprite|cookie|newsletter|social|payment|flag|'
        r'arrow|loader|placeholder|avatar|dealer|retailer|country|language|'
        r'youtube|vimeo|review|article|blog|team|athlete|footer|header|menu)',
        re.IGNORECASE,
    )
    _IMAGE_EXT_RE = re.compile(
        r'\.(?:avif|gif|jpe?g|png|webp)(?:$|[?#])', re.IGNORECASE
    )
    _DESIGN_SIZE_RE = re.compile(
        r'\b(?P<design>[A-Z][A-Z0-9]{4,11}[A-Za-z]?)\s*'
        r'\((?P<size>XXS|XS|S|M|L|XL|XXL|\d{2,3})\)\s*$',
        re.IGNORECASE,
    )

    # ------------------------------------------------------------------
    # HTTP, URL y XML
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

    @staticmethod
    def _parse_sitemap_lastmod(value):
        if not value:
            return False
        value = str(value).strip()
        for fmt, length in (
            ('%Y-%m-%dT%H:%M:%S', 19),
            ('%Y-%m-%d', 10),
        ):
            try:
                return datetime.strptime(value[:length], fmt)
            except ValueError:
                continue
        return False

    @classmethod
    def _canonical_url(cls, value):
        raw = html.unescape(str(value or '')).strip().replace('\\/', '/')
        if not raw:
            return False
        parts = urlsplit(raw)
        host = parts.netloc.lower()
        if host == 'ridley-bikes.com':
            host = 'www.ridley-bikes.com'
        path = re.sub(r'/+', '/', unquote(parts.path or '/'))
        # El mercado ES se publica en español (/es_ES) y en inglés (/en_ES).
        # Se normaliza siempre al idioma español para evitar duplicados.
        path = re.sub(r'^/(?:es|en)[_-]es/', '/es_ES/', path, flags=re.IGNORECASE)
        if path != '/':
            path = path.rstrip('/')
        return urlunsplit((parts.scheme or 'https', host, path, '', ''))

    @classmethod
    def _product_match(cls, value):
        canonical = cls._canonical_url(value)
        if not canonical:
            return False
        parsed = urlparse(canonical)
        if parsed.netloc.lower() not in cls._HOSTS:
            return False
        return cls._PRODUCT_PATH_RE.match(parsed.path)

    @classmethod
    def _product_reference(cls, value):
        match = cls._product_match(value)
        return match.group('reference').upper() if match else False

    @classmethod
    def _product_key(cls, value):
        return cls._product_reference(value) or False

    @staticmethod
    def _robots_sitemaps(text, base_url):
        result = []
        for raw_line in (text or '').splitlines():
            line = raw_line.split('#', 1)[0].strip()
            if ':' not in line:
                continue
            field, _, value = line.partition(':')
            if field.strip().casefold() != 'sitemap':
                continue
            value = value.strip()
            if not value:
                continue
            absolute = urljoin(base_url, value)
            if absolute not in result:
                result.append(absolute)
        return result

    def _candidate_sitemaps(self, source):
        configured = (source.sitemap_index_url or '').strip()
        root = 'https://www.ridley-bikes.com/'
        candidates = []
        session = self._get_session(source)

        if configured.casefold().endswith('/robots.txt'):
            try:
                response = self._http_get(session, configured, source)
                candidates.extend(self._robots_sitemaps(response.text, response.url))
            except Exception as exc:
                _logger.info(
                    'Ridley: robots.txt no accesible (%s); se prueba el índice conocido.',
                    exc,
                )
        elif configured:
            candidates.append(configured)

        # robots.txt declara actualmente sitemap_index.xml de forma relativa.
        candidates.extend([
            urljoin(root, 'sitemap_index.xml'),
            urljoin(root, 'sitemap.xml'),
        ])
        return list(dict.fromkeys(item for item in candidates if item))

    @classmethod
    def _spanish_product_url_from_node(cls, node):
        candidates = []
        # Se priorizan alternates del mercado español, si el sitemap los publica.
        for element in node.xpath('./*[local-name()="link"]'):
            hreflang = (element.get('hreflang') or '').replace('_', '-').casefold()
            href = element.get('href')
            if href and hreflang in {'es-es', 'es'}:
                candidates.append(href)
        candidates.extend(node.xpath('./*[local-name()="loc"]/text()'))

        for candidate in candidates:
            canonical = cls._canonical_url(candidate)
            if cls._product_match(canonical):
                return canonical
        return False

    def _iter_sitemap_entries(self, source, sitemap_url, depth=0, visited=None):
        if depth > 10:
            raise ValueError('El sitemap de Ridley supera diez niveles de índices.')
        visited = visited or set()
        clean_url = str(sitemap_url or '').strip()
        if not clean_url or clean_url in visited:
            return
        visited.add(clean_url)

        session = self._get_session(source)
        response = self._http_get(session, clean_url, source)
        root = self._xml_root(response.content)
        root_name = self._local_name(root)

        if root_name == 'sitemapindex':
            for child in root.xpath('./*[local-name()="sitemap"]'):
                locs = child.xpath('./*[local-name()="loc"]/text()')
                if not locs or not locs[0].strip():
                    continue
                yield from self._iter_sitemap_entries(
                    source,
                    urljoin(response.url or clean_url, locs[0].strip()),
                    depth=depth + 1,
                    visited=visited,
                )
            return

        if root_name != 'urlset':
            raise ValueError('El recurso de Ridley no contiene <urlset> ni <sitemapindex>.')

        for node in root.xpath('./*[local-name()="url"]'):
            product_url = self._spanish_product_url_from_node(node)
            if not product_url:
                continue
            lastmods = node.xpath('./*[local-name()="lastmod"]/text()')
            images = node.xpath(
                './*[local-name()="image"]/*[local-name()="loc"]/text()'
            )
            yield {
                'url': product_url,
                'lastmod': self._parse_sitemap_lastmod(
                    lastmods[0] if lastmods else False
                ),
                'images': [item.strip() for item in images if item and item.strip()],
            }

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
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))

    def _collect_sitemap_products(self, source):
        entries = {}
        images = {}
        errors = []
        for candidate in self._candidate_sitemaps(source):
            try:
                found = False
                for item in self._iter_sitemap_entries(source, candidate):
                    found = True
                    key = self._product_key(item['url'])
                    if not key:
                        continue
                    current = entries.get(key)
                    if not current:
                        entries[key] = {
                            'url': item['url'],
                            'lastmod': item.get('lastmod') or False,
                        }
                    elif item.get('lastmod') and (
                        not current.get('lastmod')
                        or item['lastmod'] > current['lastmod']
                    ):
                        current['lastmod'] = item['lastmod']

                    target = images.setdefault(key, [])
                    for image_url in item.get('images') or []:
                        cleaned = self._clean_image_url(image_url, item['url'])
                        if cleaned and cleaned not in target:
                            target.append(cleaned)
                if found and entries:
                    break
            except Exception as exc:
                errors.append(f'{candidate}: {exc}')
                _logger.info('Ridley: sitemap no utilizable %s: %s', candidate, exc)

        if not entries:
            fallback = self._discover_from_catalog(source)
            for url in fallback:
                key = self._product_key(url)
                entries[key] = {'url': url, 'lastmod': False}

        if not entries:
            detail = '; '.join(errors[-3:])
            raise ValueError(
                'No se localizaron fichas Ridley españolas en el sitemap.'
                + (f' Detalle: {detail}' if detail else '')
            )
        return entries, images

    def _discover_from_catalog(self, source):
        """Respaldo acotado si el índice XML cambia temporalmente."""
        seeds = [
            'https://www.ridley-bikes.com/es_ES/bikes',
            'https://www.ridley-bikes.com/es_ES/ebikes',
            'https://www.ridley-bikes.com/es_ES/bikes/categories/road',
            'https://www.ridley-bikes.com/es_ES/bikes/categories/gravel',
            'https://www.ridley-bikes.com/es_ES/bikes/categories/mtb',
            'https://www.ridley-bikes.com/es_ES/bikes/categories/cyclocross',
        ]
        session = self._get_session(source)
        queue = list(seeds)
        visited = set()
        products = []
        while queue and len(visited) < 30:
            page_url = queue.pop(0)
            if page_url in visited:
                continue
            visited.add(page_url)
            try:
                response = self._http_get(session, page_url, source)
                tree = self._html_document(response.content)
            except Exception as exc:
                _logger.debug('Ridley: página de catálogo no accesible %s: %s', page_url, exc)
                continue
            for href in tree.xpath('//a[@href]/@href'):
                absolute = self._canonical_url(urljoin(response.url or page_url, href))
                if self._product_match(absolute):
                    if absolute not in products:
                        products.append(absolute)
                    continue
                parsed = urlparse(absolute)
                if parsed.netloc.lower() not in self._HOSTS:
                    continue
                path = parsed.path.casefold()
                if (
                    path.startswith('/es_es/bikes/categories/')
                    or path.startswith('/es_es/bikes/platform/')
                ) and absolute not in visited and absolute not in queue:
                    queue.append(absolute)
        return products

    def get_product_entries(self, source, category_filter=None, limit=0):
        entries, _images = self._collect_sitemap_products(source)
        filter_text = (category_filter or '').strip().casefold()
        result = []
        for key, entry in sorted(entries.items(), key=lambda item: item[0]):
            haystack = f'{key} {entry["url"]}'.casefold()
            if filter_text and filter_text not in haystack:
                continue
            result.append(entry)
            if limit and len(result) >= limit:
                break
        return result

    def get_image_map(self, source):
        entries, images = self._collect_sitemap_products(source)
        return {
            entry['url']: images.get(key, [])
            for key, entry in entries.items()
            if images.get(key)
        }

    def parse_category_path(self, product_url):
        # Las URLs de ficha son planas. La categoría definitiva se obtiene de
        # breadcrumb/JSON-LD al procesar la ficha.
        return ['Bicicletas'] if self._product_match(product_url) else []

    # ------------------------------------------------------------------
    # HTML, JSON-LD y contenido de ficha
    # ------------------------------------------------------------------
    @staticmethod
    def _html_document(content):
        parser = lxml_html.HTMLParser(encoding='utf-8', recover=True)
        return lxml_html.fromstring(content, parser=parser)

    @staticmethod
    def _normalize_text(value):
        return re.sub(r'\s+', ' ', html.unescape(str(value or ''))).strip()

    @classmethod
    def _meta(cls, tree, name):
        values = tree.xpath(
            f'//meta[@property={json.dumps(name)}]/@content | '
            f'//meta[@name={json.dumps(name)}]/@content'
        )
        return cls._normalize_text(values[0]) if values else False

    @classmethod
    def _json_payloads(cls, tree):
        payloads = []
        for raw in tree.xpath('//script/text()'):
            raw = (raw or '').strip()
            if not raw or len(raw) > 12_000_000:
                continue
            if raw.startswith(('window.__', 'self.__')) and '=' in raw:
                raw = raw.split('=', 1)[1].strip().rstrip(';')
            if not raw.startswith(('{', '[')):
                continue
            try:
                payloads.append(json.loads(raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return payloads

    @classmethod
    def _product_json_ld(cls, tree):
        found = []

        def walk(value):
            if isinstance(value, list):
                for child in value:
                    walk(child)
                return
            if not isinstance(value, dict):
                return
            item_type = value.get('@type')
            types = item_type if isinstance(item_type, list) else [item_type]
            if any(str(item).casefold() in {'product', 'individualproduct'} for item in types if item):
                found.append(value)
            for key in ('@graph', 'mainEntity', 'itemListElement', 'hasVariant', 'isVariantOf'):
                if key in value:
                    walk(value[key])

        for payload in cls._json_payloads(tree):
            walk(payload)
        return found[0] if found else {}

    @staticmethod
    def _parse_price_number(value):
        if value is None or isinstance(value, bool):
            return False
        text = re.sub(r'[^0-9.,]', '', str(value))
        if not text:
            return False
        if ',' in text and '.' in text:
            if text.rfind(',') > text.rfind('.'):
                text = text.replace('.', '').replace(',', '.')
            else:
                text = text.replace(',', '')
        elif ',' in text:
            decimals = len(text.rsplit(',', 1)[1])
            text = text.replace('.', '')
            text = text.replace(',', '.') if decimals == 2 else text.replace(',', '')
        elif '.' in text:
            decimals = len(text.rsplit('.', 1)[1])
            if decimals != 2:
                text = text.replace('.', '')
        try:
            return float(text)
        except ValueError:
            return False

    @classmethod
    def _price_from_product_json(cls, product_json):
        offers = product_json.get('offers') if isinstance(product_json, dict) else None
        offers = offers if isinstance(offers, list) else [offers]
        candidates = []
        currency = False
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            currency = currency or offer.get('priceCurrency')
            for field in ('salePrice', 'price', 'lowPrice'):
                price = cls._parse_price_number(offer.get(field))
                if price is not False and price > 0:
                    candidates.append(price)
                    break
        return (candidates[0], currency or 'EUR') if candidates else (False, currency or 'EUR')

    @classmethod
    def _extract_price(cls, tree, product_json):
        price, currency = cls._price_from_product_json(product_json)
        if price is not False:
            return price, currency

        for meta_name in ('product:price:amount', 'og:price:amount'):
            price = cls._parse_price_number(cls._meta(tree, meta_name))
            if price is not False and price > 0:
                return price, (
                    cls._meta(tree, 'product:price:currency')
                    or cls._meta(tree, 'og:price:currency')
                    or 'EUR'
                )

        main_nodes = tree.xpath('//main')
        scope = main_nodes[0] if main_nodes else tree
        selectors = (
            './/*[@itemprop="price"]/@content',
            './/*[@data-price]/@data-price',
            './/*[contains(translate(@class,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"price")]//text()',
        )
        for selector in selectors:
            for raw in scope.xpath(selector)[:80]:
                text = cls._normalize_text(raw)
                matches = cls._PRICE_RE.findall(text)
                for left, right in matches:
                    price = cls._parse_price_number(left or right)
                    if price is not False and price > 0:
                        return price, 'EUR'
                direct = cls._parse_price_number(text)
                if direct is not False and direct > 0 and ('€' in text or selector.endswith('@data-price')):
                    return direct, 'EUR'

        # Último respaldo: se limita al bloque inicial de la ficha para no
        # capturar precios de configuraciones recomendadas al final de página.
        text = cls._normalize_text(' '.join(scope.xpath('.//text()[normalize-space()]')[:350]))
        for left, right in cls._PRICE_RE.findall(text):
            price = cls._parse_price_number(left or right)
            if price is not False and price > 0:
                return price, 'EUR'
        return 0.0, 'EUR'

    @classmethod
    def _breadcrumb_items(cls, tree):
        result = []

        def add(value):
            text = cls._normalize_text(value)
            if not text:
                return
            lowered = text.casefold()
            if lowered in {'home', 'inicio', 'ridley', 'bicicletas', 'bikes'}:
                return
            if text not in result:
                result.append(text)

        for payload in cls._json_payloads(tree):
            stack = [payload]
            while stack:
                value = stack.pop()
                if isinstance(value, list):
                    stack.extend(reversed(value))
                    continue
                if not isinstance(value, dict):
                    continue
                item_type = value.get('@type')
                types = item_type if isinstance(item_type, list) else [item_type]
                if any(str(item).casefold() == 'breadcrumblist' for item in types if item):
                    elements = value.get('itemListElement') or []
                    elements = sorted(
                        [item for item in elements if isinstance(item, dict)],
                        key=lambda item: item.get('position') or 0,
                    )
                    for element in elements:
                        item = element.get('item')
                        add(element.get('name') or (item.get('name') if isinstance(item, dict) else False))
                stack.extend(value.values())

        selectors = (
            '//*[@aria-label and contains(translate(@aria-label,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"breadcrumb")]//a//text()',
            '//*[contains(translate(@class,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"breadcrumb")]//a//text()',
        )
        for selector in selectors:
            for value in tree.xpath(selector):
                add(value)
        return result

    @classmethod
    def _category_path(cls, tree, name, description):
        breadcrumbs = cls._breadcrumb_items(tree)
        # El último breadcrumb suele ser el nombre de la configuración.
        if breadcrumbs and name and breadcrumbs[-1].casefold() in name.casefold():
            breadcrumbs.pop()
        if breadcrumbs:
            return '/'.join(['Bicicletas'] + breadcrumbs[-4:])

        text = f'{name} {description} {cls._normalize_text(" ".join(tree.xpath("//main//text()")[:500]))}'.casefold()
        discipline = False
        if any(token in text for token in ('gravel', 'allroad', 'all-road')):
            discipline = 'Gravel'
        elif any(token in text for token in ('mountainbike', 'mountain bike', 'montaña', 'mtb', 'hardtail', 'full suspension')):
            discipline = 'Montaña'
        elif any(token in text for token in ('cyclo-cross', 'cyclocross', 'ciclocross')):
            discipline = 'Ciclocross'
        elif any(token in text for token in ('triathlon', 'triatlón', 'time trial', 'contrarreloj', 'track', 'pista')):
            discipline = 'Triatlón, contrarreloj y pista'
        elif any(token in text for token in ('kids', 'niño', 'niña', 'junior')):
            discipline = 'Infantil'
        elif any(token in text for token in ('road', 'carretera', 'aero-to-', 'endurance')):
            discipline = 'Carretera'

        electric = any(token in text for token in ('e-bike', 'e-bike', 'ebike', 'eléctrica', 'motor ', 'batería '))
        root = 'Bicicletas eléctricas' if electric else 'Bicicletas'
        return '/'.join([root, discipline]) if discipline else root

    @classmethod
    def _extract_design_and_size(cls, name, tree):
        match = cls._DESIGN_SIZE_RE.search(name or '')
        design = match.group('design').upper() if match else False
        size = match.group('size').upper() if match else False

        if not size:
            selected = tree.xpath(
                '//*[@aria-selected="true" or contains(concat(" ",normalize-space(@class)," ")," selected ") or @data-selected="true"]'
                '[contains(translate(@data-attribute,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"size") '
                'or contains(translate(@name,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"size") '
                'or contains(translate(@class,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"size")]//text()'
            )
            for value in selected:
                candidate = cls._normalize_text(value).upper()
                if re.fullmatch(r'(?:XXS|XS|S|M|L|XL|XXL|\d{2,3})', candidate):
                    size = candidate
                    break
        color_code = design or False
        if size:
            color_code = f'{design} / Talla {size}' if design else f'Talla {size}'
        return design, size, color_code

    @classmethod
    def _extract_images(cls, tree, product_json, page_url, reference, name):
        candidates = []
        json_images = product_json.get('image') if isinstance(product_json, dict) else None
        json_images = json_images if isinstance(json_images, list) else [json_images]
        for image in json_images:
            if isinstance(image, dict):
                image = image.get('url') or image.get('contentUrl')
            if image:
                candidates.append((image, '', True))
        for meta_name in ('og:image', 'og:image:secure_url', 'twitter:image'):
            image = cls._meta(tree, meta_name)
            if image:
                candidates.append((image, '', True))

        main_nodes = tree.xpath('//main')
        scope = main_nodes[0] if main_nodes else tree
        for element in scope.xpath('.//img | .//source'):
            label = cls._normalize_text(' '.join(filter(None, [
                element.get('alt'), element.get('title'), element.get('aria-label'),
            ])))
            for attr in (
                'src', 'data-src', 'data-original', 'data-lazy-src',
                'data-image', 'data-image-url', 'data-zoom-image',
            ):
                value = element.get(attr)
                if value:
                    candidates.append((value, label, False))
            for attr in ('srcset', 'data-srcset'):
                for item in (element.get(attr) or '').split(','):
                    value = item.strip().split(' ')[0]
                    if value:
                        candidates.append((value, label, False))

        significant = {
            word for word in re.sub(r'[^a-z0-9áéíóúñ]+', ' ', (name or '').casefold()).split()
            if len(word) >= 4 and word not in {'ridley', 'series', 'shimano', 'sram'}
        }
        ref = (reference or '').casefold()
        result = []
        identities = set()
        for raw, label, trusted in candidates:
            cleaned = cls._clean_image_url(raw, page_url)
            if not cleaned:
                continue
            lower = cleaned.casefold()
            label_lower = label.casefold()
            likely = (
                trusted
                or ref in lower
                or any(word in label_lower for word in significant)
                or any(word in lower for word in significant)
            )
            if not likely:
                continue
            if not cls._IMAGE_EXT_RE.search(cleaned) and not trusted:
                continue
            parts = urlsplit(cleaned)
            identity = urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
            if identity in identities:
                continue
            identities.add(identity)
            result.append(cleaned)
        return result


    def _parse_product_html(self, content, requested_url, final_url=None):
        requested_reference = self._product_reference(requested_url)
        if not requested_reference:
            raise ValueError('La URL solicitada no es una ficha válida de Ridley España.')

        tree = self._html_document(content)
        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical_candidate = (
            urljoin(final_url or requested_url, canonical_values[0].strip())
            if canonical_values and canonical_values[0].strip()
            else (final_url or requested_url)
        )
        canonical_url = self._canonical_url(canonical_candidate)
        canonical_reference = self._product_reference(canonical_url)
        if not canonical_reference:
            canonical_url = self._canonical_url(requested_url)
            canonical_reference = requested_reference
        if canonical_reference != requested_reference:
            raise ValueError(
                'Ridley ha redirigido la ficha a otra referencia; la configuración '
                'solicitada puede estar descatalogada.'
            )

        product_json = self._product_json_ld(tree)
        h1_values = tree.xpath('//main//h1//text()') or tree.xpath('//h1//text()')
        name = self._normalize_text(' '.join(h1_values))
        if not name and isinstance(product_json, dict):
            name = self._normalize_text(product_json.get('name'))
        name = name or self._meta(tree, 'og:title') or canonical_reference
        name = re.sub(r'\s*[|–-]\s*Ridley(?: Bikes)?\s*$', '', name, flags=re.IGNORECASE).strip()

        description = self._normalize_text(
            (product_json.get('description') if isinstance(product_json, dict) else False)
            or self._meta(tree, 'og:description')
            or self._meta(tree, 'description')
            or ''
        )
        price, currency = self._extract_price(tree, product_json)
        _design, size, color_code = self._extract_design_and_size(name, tree)
        category_path = self._category_path(tree, name, description)
        image_urls = self._extract_images(
            tree, product_json, canonical_url, canonical_reference, name
        )

        ean_variants = []
        if isinstance(product_json, dict):
            ean_variants.extend(self._ean_variants_from_payload(product_json))
        ean_variants.extend(self._ean_variants_from_html_content(content))
        for payload in self._json_payloads(tree):
            ean_variants.extend(self._ean_variants_from_payload(payload))
        # Completa la etiqueta de códigos sin metadata con la talla visible.
        if size:
            for item in ean_variants:
                if isinstance(item, dict) and not item.get('variant_label'):
                    item['variant_label'] = f'Talla {size}'
                if isinstance(item, dict) and not item.get('sku'):
                    item['sku'] = canonical_reference

        return {
            'name': name,
            'description': description,
            'price': price,
            'price_available': bool(price),
            'currency': currency or 'EUR',
            'category_path': category_path,
            'style_code': canonical_reference,
            'color_code': color_code or False,
            'main_image_url': image_urls[0] if image_urls else False,
            'image_urls': image_urls,
            'canonical_url': canonical_url,
            'ean_variants': self._normalise_ean_variants(ean_variants),
            # Puede haber códigos adicionales cargados al seleccionar montaje,
            # diseño o talla. El flujo común explorará endpoints públicos.
            'ean_complete': False,
        }

    def fetch_preview(self, source, url):
        session = self._get_session(source)
        response = self._http_get(session, url, source)
        return self._parse_product_html(response.content, url, response.url or url)
