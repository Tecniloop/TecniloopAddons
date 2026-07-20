import gzip
import html
import json
import logging
import re
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorBicicletasQuerEs(models.AbstractModel):
    """Conector para el B2B español de Bicicletas Quer.

    La tienda usa PrestaShop y publica fichas con el patrón::

        /es/<categoria>/<id_producto>-<slug>.html

    La fuente se configura con ``robots.txt`` porque el módulo Google Sitemap
    de PrestaShop suele declarar allí uno o varios ficheros XML. Como algunos
    WAF devuelven 403 específicamente para robots.txt, el conector prueba además
    los nombres habituales de PrestaShop y, como último respaldo, descubre
    productos desde el mapa HTML español y sus categorías.

    Cada ficha puede contener combinaciones por talla/color. El conector extrae
    los GTIN desde JSON-LD, objetos JavaScript ``combinations`` y respuestas de
    combinaciones; los conserva en ``sitemap.product.ean`` sin asignar uno de
    forma arbitraria al producto simple.
    """

    _name = 'sitemap.connector.bicicletasquer_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Bicicletas Quer B2B España'

    _HOSTS = {'b2b.bicicletasquer.com', 'www.b2b.bicicletasquer.com'}
    _PRODUCT_PATH_RE = re.compile(
        r'^/es/(?P<category>[^/?#]+)/(?P<product_id>\d{5,})-(?P<slug>[^/?#]+)\.html/?$',
        re.IGNORECASE,
    )
    _CATEGORY_PATH_RE = re.compile(r'^/es/(?P<category_id>\d+)-(?P<slug>[^/?#]+?)/?$', re.IGNORECASE)
    _IMAGE_EXT_RE = re.compile(r'\.(?:avif|gif|jpe?g|png|webp)(?:$|\?)', re.IGNORECASE)
    _NON_PRODUCT_IMAGE_RE = re.compile(
        r'(?:logo|icon|sprite|favicon|payment|social|newsletter|placeholder|spinner|loader|flag|cookie)',
        re.IGNORECASE,
    )
    _PRICE_RE = re.compile(
        r'(?<!\d)(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2}))(?:\s*)€'
    )
    _REFERENCE_RE = re.compile(
        r'(?:Referencia|Reference|R[eé]f(?:erencia)?\.?)[\s:#-]*([A-Z0-9][A-Z0-9._/\-]{2,})',
        re.IGNORECASE,
    )

    # ------------------------------------------------------------------
    # HTTP y normalización
    # ------------------------------------------------------------------
    def _get_session(self, source):
        session = super()._get_session(source)
        session.headers.update({
            'Accept': (
                'text/html,application/xhtml+xml,application/xml;q=0.9,'
                'image/avif,image/webp,*/*;q=0.8'
            ),
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.3',
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
        parts = urlsplit(html.unescape(str(value or '')).strip())
        host = parts.netloc.lower()
        if host == 'www.b2b.bicicletasquer.com':
            host = 'b2b.bicicletasquer.com'
        path = re.sub(r'/+', '/', parts.path)
        path = re.sub(r'^/(?:en|gb|fr|ca)/', '/es/', path, flags=re.IGNORECASE)
        return urlunsplit((parts.scheme or 'https', host, path.rstrip('/'), '', ''))

    @classmethod
    def _product_match(cls, value):
        parsed = urlparse(value)
        if parsed.netloc.lower() not in cls._HOSTS:
            return False
        return cls._PRODUCT_PATH_RE.match(parsed.path)

    @classmethod
    def _product_key(cls, value):
        match = cls._product_match(value)
        return match.group('product_id') if match else False

    @staticmethod
    def _parse_sitemap_lastmod(value):
        if not value:
            return False
        value = str(value).strip()
        for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
            try:
                return datetime.strptime(value[:19] if 'T' in value else value[:10], fmt)
            except ValueError:
                continue
        return False

    # ------------------------------------------------------------------
    # Sitemap / robots / descubrimiento
    # ------------------------------------------------------------------
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
        root = 'https://b2b.bicicletasquer.com/'
        candidates = []
        session = self._get_session(source)
        try:
            response = session.get(
                source.sitemap_index_url,
                timeout=source.request_timeout or 20,
                allow_redirects=True,
            )
            if response.status_code < 400:
                candidates.extend(self._robots_sitemaps(response.text, response.url))
                content = response.content.lstrip()
                if content.startswith(b'<?xml') or content.startswith(b'<urlset') or content.startswith(b'<sitemapindex') or content[:2] == b'\x1f\x8b':
                    candidates.insert(0, response.url)
        except Exception as exc:
            _logger.info('Bicicletas Quer: robots.txt no accesible (%s); se prueban rutas conocidas.', exc)

        # Nombres usados por el módulo Google Sitemap de PrestaShop, además de
        # los endpoints genéricos que algunas instalaciones redirigen al índice.
        candidates.extend([
            urljoin(root, 'sitemap.xml'),
            urljoin(root, 'sitemap_index.xml'),
            urljoin(root, '1_es_0_sitemap.xml'),
            urljoin(root, '1_es_1_sitemap.xml'),
        ])
        return list(dict.fromkeys(candidates))

    def _iter_sitemap_entries(self, source, sitemap_url, depth=0, visited=None):
        if depth > 8:
            raise ValueError('El sitemap de Bicicletas Quer supera ocho niveles de índices.')
        visited = visited or set()
        clean_url = sitemap_url.strip()
        if clean_url in visited:
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
                    urljoin(clean_url, locs[0].strip()),
                    depth=depth + 1,
                    visited=visited,
                )
            return

        if root_name != 'urlset':
            raise ValueError('El recurso no contiene <urlset> ni <sitemapindex>.')

        for node in root.xpath('./*[local-name()="url"]'):
            locs = node.xpath('./*[local-name()="loc"]/text()')
            if not locs or not locs[0].strip():
                continue
            lastmods = node.xpath('./*[local-name()="lastmod"]/text()')
            images = node.xpath('./*[local-name()="image"]/*[local-name()="loc"]/text()')
            yield {
                'url': locs[0].strip(),
                'lastmod': self._parse_sitemap_lastmod(lastmods[0] if lastmods else None),
                'images': [value.strip() for value in images if value and value.strip()],
            }

    @classmethod
    def _product_links_from_tree(cls, tree, page_url):
        result = []
        for href in tree.xpath('//a[@href]/@href'):
            absolute = cls._canonical_url(urljoin(page_url, href))
            if cls._product_match(absolute) and absolute not in result:
                result.append(absolute)
        return result

    @classmethod
    def _category_links_from_tree(cls, tree, page_url):
        result = []
        for href in tree.xpath('//a[@href]/@href'):
            absolute = cls._canonical_url(urljoin(page_url, href))
            parsed = urlparse(absolute)
            if parsed.netloc.lower() not in cls._HOSTS:
                continue
            if cls._CATEGORY_PATH_RE.match(parsed.path) and absolute not in result:
                result.append(absolute)
        return result

    def _fallback_html_entries(self, source, category_filter=None, limit=0):
        """Descubrimiento de respaldo desde el mapa HTML y categorías.

        Se usa únicamente cuando robots.txt y los nombres estándar de sitemap
        no devuelven XML. No se marca nunca una colección como completa para
        archivado automático: la fuente se crea con auto_archive desactivado.
        """
        session = self._get_session(source)
        start_urls = [
            'https://b2b.bicicletasquer.com/es/mapa-del-sitio',
            'https://b2b.bicicletasquer.com/es/nuevos-productos',
        ]
        products = {}
        categories = []
        for start_url in start_urls:
            try:
                response = self._http_get(session, start_url, source)
                tree = lxml_html.fromstring(response.content)
            except Exception as exc:
                _logger.info('Bicicletas Quer: respaldo HTML no accesible %s: %s', start_url, exc)
                continue
            for product_url in self._product_links_from_tree(tree, response.url):
                products.setdefault(self._product_key(product_url), {'url': product_url, 'lastmod': False})
            for category_url in self._category_links_from_tree(tree, response.url):
                if category_url not in categories:
                    categories.append(category_url)

        for category_url in categories:
            page = 1
            seen_page_products = set()
            while page <= 200:
                parts = urlsplit(category_url)
                query = dict(parse_qsl(parts.query, keep_blank_values=True))
                if page > 1:
                    query['page'] = str(page)
                page_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))
                try:
                    response = self._http_get(session, page_url, source)
                    tree = lxml_html.fromstring(response.content)
                except Exception:
                    break
                page_links = self._product_links_from_tree(tree, response.url)
                new_keys = []
                for product_url in page_links:
                    key = self._product_key(product_url)
                    if key and key not in products:
                        products[key] = {'url': product_url, 'lastmod': False}
                        new_keys.append(key)
                signature = tuple(sorted(self._product_key(url) for url in page_links if self._product_key(url)))
                if not page_links or signature in seen_page_products:
                    break
                seen_page_products.add(signature)
                if limit and len(products) >= limit:
                    break
                # Si no existe enlace de siguiente página, no se inventan más.
                next_links = tree.xpath(
                    '//a[contains(@rel,"next") or contains(@class,"next") or '
                    'contains(@class,"js-search-link")][@href]/@href'
                )
                if not next_links and not new_keys:
                    break
                page += 1
            if limit and len(products) >= limit:
                break

        entries = list(products.values())
        if category_filter:
            needle = str(category_filter).casefold()
            entries = [item for item in entries if needle in item['url'].casefold()]
        entries.sort(key=lambda item: item['url'])
        return entries[:limit] if limit else entries

    def _collect_products(self, source):
        entries = {}
        images = {}
        errors = []
        for sitemap_url in self._candidate_sitemaps(source):
            try:
                local_count = 0
                for item in self._iter_sitemap_entries(source, sitemap_url):
                    product_url = self._canonical_url(item['url'])
                    key = self._product_key(product_url)
                    if not key:
                        continue
                    local_count += 1
                    current = entries.get(key)
                    candidate = {'url': product_url, 'lastmod': item.get('lastmod') or False}
                    if not current:
                        entries[key] = candidate
                    elif candidate['lastmod'] and (
                        not current['lastmod'] or candidate['lastmod'] > current['lastmod']
                    ):
                        entries[key] = candidate
                    for image_url in item.get('images') or []:
                        cleaned = self._clean_image_url(image_url, product_url)
                        if cleaned and cleaned not in images.setdefault(key, []):
                            images[key].append(cleaned)
                if local_count:
                    break
            except Exception as exc:
                errors.append(f'{sitemap_url}: {exc}')
                continue
        return entries, images, errors

    def get_product_entries(self, source, category_filter=None, limit=0):
        entries, image_map, errors = self._collect_products(source)
        self._quer_entries_cache = entries
        self._quer_image_map_cache = image_map
        if entries:
            result = list(entries.values())
            if category_filter:
                needle = str(category_filter).casefold()
                result = [item for item in result if needle in item['url'].casefold()]
            result.sort(key=lambda item: item['url'])
            return result[:limit] if limit else result

        fallback = self._fallback_html_entries(source, category_filter=category_filter, limit=limit)
        if fallback:
            return fallback
        raise ValueError(
            'No se pudieron descubrir productos de Bicicletas Quer. '
            'robots.txt no publicó un sitemap XML accesible y el mapa HTML no devolvió fichas. '
            + (' Intentos: ' + ' | '.join(errors[:4]) if errors else '')
        )

    def get_image_map(self, source):
        entries = getattr(self, '_quer_entries_cache', None)
        image_map = getattr(self, '_quer_image_map_cache', None)
        if entries is None or image_map is None:
            entries, image_map, _ = self._collect_products(source)
            self._quer_entries_cache = entries
            self._quer_image_map_cache = image_map
        result = {}
        # El servicio espera mapa por URL; reconstruimos a partir de las
        # entradas para no depender de URLs con parámetros o alias.
        for key, entry in entries.items():
            if image_map.get(key):
                result[entry['url']] = image_map[key]
        return result

    # ------------------------------------------------------------------
    # Datos de ficha
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

    @staticmethod
    def _json_ld_payloads(tree):
        result = []
        for raw in tree.xpath('//script[@type="application/ld+json"]/text()'):
            if not raw or len(raw) > 8_000_000:
                continue
            try:
                result.append(json.loads(raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return result

    @classmethod
    def _find_product_json(cls, payload):
        if isinstance(payload, list):
            for child in payload:
                found = cls._find_product_json(child)
                if found:
                    return found
            return False
        if not isinstance(payload, dict):
            return False
        kind = payload.get('@type')
        kinds = kind if isinstance(kind, list) else [kind]
        if any(str(value).casefold() == 'product' for value in kinds if value):
            return payload
        graph = payload.get('@graph')
        if graph:
            return cls._find_product_json(graph)
        return False

    @classmethod
    def _page_lines(cls, tree):
        return [
            cls._normalize_text(value)
            for value in tree.xpath('//body//*[not(self::script or self::style or self::noscript)]/text()')
            if cls._normalize_text(value)
        ]

    @staticmethod
    def _parse_price(value):
        if value in (None, False, ''):
            return 0.0
        text = re.sub(r'[^0-9,.-]', '', str(value)).strip()
        if not text:
            return 0.0
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
            return 0.0

    @classmethod
    def _offer_price(cls, product_json):
        offers = product_json.get('offers') if isinstance(product_json, dict) else False
        if isinstance(offers, list):
            candidates = []
            currency = False
            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                price = cls._parse_price(offer.get('price') or offer.get('lowPrice'))
                if price:
                    candidates.append(price)
                currency = currency or offer.get('priceCurrency')
            return (min(candidates) if candidates else 0.0), currency
        if isinstance(offers, dict):
            return cls._parse_price(offers.get('price') or offers.get('lowPrice')), offers.get('priceCurrency')
        return 0.0, False

    @classmethod
    def _extract_price(cls, tree, product_json, lines):
        price, currency = cls._offer_price(product_json or {})
        if price:
            return price, currency or 'EUR'
        candidates = []
        for value in tree.xpath(
            '//meta[@property="product:price:amount" or @property="og:price:amount" or '
            '@itemprop="price"]/@content | //*[@itemprop="price"]/@content | '
            '//*[contains(@class,"current-price") or contains(@class,"product-price")]/@content | '
            '//*[contains(@class,"current-price") or contains(@class,"product-price")]/@data-price-amount'
        ):
            parsed = cls._parse_price(value)
            if parsed:
                candidates.append(parsed)
        if not candidates:
            focused = tree.xpath(
                '//*[contains(@class,"product-prices") or contains(@class,"current-price") or '
                'contains(@class,"product-price")]/descendant-or-self::*/text()'
            )
            for value in focused:
                match = cls._PRICE_RE.search(cls._normalize_text(value))
                if match:
                    parsed = cls._parse_price(match.group(1))
                    if parsed:
                        candidates.append(parsed)
        return (candidates[0] if candidates else 0.0), (
            cls._meta(tree, 'product:price:currency') or 'EUR'
        )

    @classmethod
    def _extract_description(cls, tree, product_json):
        value = (product_json or {}).get('description')
        if value:
            return str(value)
        for xpath in (
            '//*[@id="description"]',
            '//*[contains(@class,"product-description")]',
            '//*[contains(@class,"product-information")]',
        ):
            nodes = tree.xpath(xpath)
            if nodes:
                fragments = [lxml_html.tostring(node, encoding='unicode', method='html') for node in nodes[:2]]
                return ''.join(fragments)
        return cls._meta(tree, 'description') or ''

    @classmethod
    def _reference(cls, tree, product_json, lines, product_url):
        for value in (
            (product_json or {}).get('sku'),
            (product_json or {}).get('mpn'),
            cls._meta(tree, 'sku'),
        ):
            value = cls._normalize_text(value)
            if value:
                return value.upper()
        for value in tree.xpath(
            '//*[@itemprop="sku"]/@content | //*[@itemprop="sku"]/text() | '
            '//*[contains(@class,"product-reference") or contains(@class,"reference")]/descendant-or-self::*/text()'
        ):
            match = cls._REFERENCE_RE.search('Referencia ' + cls._normalize_text(value))
            if match:
                return match.group(1).upper()
        for line in lines:
            match = cls._REFERENCE_RE.search(line)
            if match:
                return match.group(1).upper()
        match = cls._product_match(product_url)
        return match.group('product_id') if match else False

    @classmethod
    def _breadcrumbs(cls, tree, product_url, name):
        values = []
        xpaths = (
            '//*[contains(@class,"breadcrumb")]//a//text()',
            '//*[@itemtype="https://schema.org/BreadcrumbList" or '
            '@itemtype="http://schema.org/BreadcrumbList"]//*[@itemprop="name"]/text()',
        )
        for xpath in xpaths:
            for value in tree.xpath(xpath):
                text = cls._normalize_text(value)
                if not text or text.casefold() in {'inicio', 'home', name.casefold()}:
                    continue
                if text not in values:
                    values.append(text)
        if values:
            return values
        match = cls._product_match(product_url)
        if not match:
            return ['Bicicletas Quer']
        category = match.group('category').replace('-', ' ').replace('_', ' ').strip().title()
        return [category] if category else ['Bicicletas Quer']

    @classmethod
    def _colors_and_sizes(cls, tree, lines):
        colors = []
        sizes = []
        for node in tree.xpath('//*[contains(@class,"product-variants-item") or contains(@class,"product-variants")]'):
            text = cls._normalize_text(' '.join(node.xpath('.//text()')))
            lowered = text.casefold()
            values = [
                cls._normalize_text(value)
                for value in node.xpath('.//option[not(@disabled)]/text() | .//*[@title]/@title | .//*[@data-value]/@data-value')
                if cls._normalize_text(value)
            ]
            target = colors if any(token in lowered for token in ('color', 'colores', 'colour')) else sizes if any(token in lowered for token in ('talla', 'size', 'tamaño', 'rueda')) else None
            if target is not None:
                for value in values:
                    if value.casefold() not in {'elige una opción', 'seleccionar', 'choose an option'} and value not in target:
                        target.append(value)
        # Respaldo para texto plano indexable.
        for line in lines:
            match = re.match(r'^(?:Colores?|Colour)\s*:\s*(.+)$', line, re.IGNORECASE)
            if match:
                for value in re.split(r'\s*[/,|]\s*', match.group(1)):
                    value = cls._normalize_text(value)
                    if value and value not in colors:
                        colors.append(value)
            match = re.match(r'^(?:Talla|Tallas|Size|talla rueda)\s*:\s*(.+)$', line, re.IGNORECASE)
            if match:
                for value in re.split(r'\s*[/,|]\s*', match.group(1)):
                    value = cls._normalize_text(value)
                    if value and value not in sizes:
                        sizes.append(value)
        return colors, sizes

    @classmethod
    def _clean_image_url(cls, value, page_url=''):
        if not value:
            return False
        url = urljoin(page_url, html.unescape(str(value)).replace('\\/', '/').strip())
        if not url.startswith(('http://', 'https://')) or cls._NON_PRODUCT_IMAGE_RE.search(url):
            return False
        # PrestaShop puede entregar miniaturas con sufijos de tipo -home_default.
        url = re.sub(r'-(?:small|medium|large|home|cart|product)_[a-z0-9_-]+(?=\.(?:jpe?g|png|webp))', '', url, flags=re.IGNORECASE)
        return url

    @classmethod
    def _images(cls, tree, product_json, page_url):
        result = []

        def add(value):
            if isinstance(value, dict):
                value = value.get('url') or value.get('contentUrl')
            cleaned = cls._clean_image_url(value, page_url)
            if cleaned and cleaned not in result:
                result.append(cleaned)

        image_data = (product_json or {}).get('image')
        for value in image_data if isinstance(image_data, list) else [image_data]:
            add(value)
        add(cls._meta(tree, 'og:image'))
        for value in tree.xpath(
            '//*[@data-image-large-src]/@data-image-large-src | '
            '//*[contains(@class,"product-cover")]//img/@src | '
            '//*[contains(@class,"product-images")]//img/@data-image-large-src | '
            '//*[contains(@class,"product-images")]//img/@src | '
            '//img[@itemprop="image"]/@src'
        ):
            add(value)
        return result

    @staticmethod
    def _extract_balanced_json(text, start):
        while start < len(text) and text[start].isspace():
            start += 1
        if start >= len(text) or text[start] not in '[{':
            return False
        opening = text[start]
        closing = '}' if opening == '{' else ']'
        depth = 0
        quote = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if quote:
                if escaped:
                    escaped = False
                elif char == '\\':
                    escaped = True
                elif char == quote:
                    quote = False
                continue
            if char in ('"', "'"):
                quote = char
                continue
            if char == opening:
                depth += 1
            elif char == closing:
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]
        return False

    def _prestashop_payloads(self, content):
        text = content.decode('utf-8', errors='ignore') if isinstance(content, bytes) else str(content)
        payloads = []
        try:
            tree = lxml_html.fromstring(content)
        except (ValueError, etree.ParserError):
            tree = None
        if tree is not None:
            for raw in tree.xpath('//*[@data-product]/@data-product | //*[@data-product-info]/@data-product-info'):
                raw = html.unescape(raw)
                try:
                    payloads.append(json.loads(raw))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
        markers = (
            r'\bcombinations\s*=\s*',
            r'\bproductCombinations\s*=\s*',
            r'\bproduct\s*=\s*',
            r'"combinations"\s*:\s*',
        )
        for marker in markers:
            for match in re.finditer(marker, text, flags=re.IGNORECASE):
                raw = self._extract_balanced_json(text, match.end())
                if not raw or len(raw) > 8_000_000:
                    continue
                try:
                    payload = json.loads(raw)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                payloads.append(payload)
        return payloads

    def _prestashop_ean_variants(self, content):
        variants = self._ean_variants_from_html_content(content)
        for payload in self._prestashop_payloads(content):
            variants.extend(self._ean_variants_from_payload(payload))
            if isinstance(payload, dict):
                nodes = list(payload.items())
            elif isinstance(payload, list):
                nodes = [(False, node) for node in payload]
            else:
                nodes = []
            for node_key, node in nodes:
                if not isinstance(node, dict):
                    continue
                ean = node.get('ean13') or node.get('ean') or node.get('gtin13') or node.get('upc')
                attributes = node.get('attributes_values') or node.get('attributes') or {}
                if isinstance(attributes, dict):
                    label = ' / '.join(self._normalize_text(value) for value in attributes.values() if self._normalize_text(value))
                elif isinstance(attributes, list):
                    label = ' / '.join(self._normalize_text(value) for value in attributes if self._normalize_text(value))
                else:
                    label = False
                item = self._ean_variant(
                    ean,
                    sku=node.get('reference') or node.get('sku'),
                    label=label,
                    source_variant_id=node.get('id_product_attribute') or node.get('id') or node_key,
                    available=(node.get('quantity', 1) or 0) > 0,
                )
                if item:
                    variants.append(item)
        return self._normalise_ean_variants(variants)

    def _fetch_site_ean_variants(self, source, product_url, preview_data):
        session = self._get_session(source)
        response = self._http_get(session, product_url, source)
        variants = self._prestashop_ean_variants(response.content)

        limit = max(int(source.max_ean_requests_per_product or 0), 0)
        if not limit:
            return variants
        text = response.text
        attribute_ids = []
        for pattern in (
            r'["\']id_product_attribute["\']\s*[:=]\s*["\']?(\d+)',
            r'data-id-product-attribute=["\'](\d+)',
            r'[?&]id_product_attribute=(\d+)',
        ):
            for value in re.findall(pattern, text, flags=re.IGNORECASE):
                if value != '0' and value not in attribute_ids:
                    attribute_ids.append(value)
                if len(attribute_ids) >= limit:
                    break
            if len(attribute_ids) >= limit:
                break

        for attribute_id in attribute_ids[:limit]:
            parts = urlsplit(product_url)
            query = dict(parse_qsl(parts.query, keep_blank_values=True))
            query['id_product_attribute'] = attribute_id
            variant_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))
            try:
                variant_response = self._http_get(session, variant_url, source)
                extracted = self._prestashop_ean_variants(variant_response.content)
                for item in extracted:
                    if not item.get('source_variant_id'):
                        item['source_variant_id'] = attribute_id
                variants.extend(extracted)
            except Exception as exc:
                _logger.debug('Bicicletas Quer: combinación %s no accesible: %s', attribute_id, exc)
        return self._normalise_ean_variants(variants)

    def fetch_preview(self, source, url):
        session = self._get_session(source)
        response = self._http_get(session, url, source)
        tree = lxml_html.fromstring(response.content)

        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical = self._canonical_url(canonical_values[0] if canonical_values else response.url or url)
        if not self._product_match(canonical):
            fallback = self._canonical_url(url)
            if self._product_match(fallback):
                canonical = fallback
            else:
                raise ValueError(
                    'La URL ya no apunta a una ficha española de Bicicletas Quer; '
                    'posible redirección, autenticación o producto retirado.'
                )

        product_json = False
        for payload in self._json_ld_payloads(tree):
            product_json = self._find_product_json(payload)
            if product_json:
                break

        name = self._normalize_text((product_json or {}).get('name'))
        if not name:
            values = tree.xpath('//h1[1]//text()')
            name = self._normalize_text(' '.join(values)) if values else self._meta(tree, 'og:title')
        if not name:
            raise ValueError('La ficha no publica un nombre de producto reconocible.')

        lines = self._page_lines(tree)
        price, currency = self._extract_price(tree, product_json, lines)
        colors, sizes = self._colors_and_sizes(tree, lines)
        description = self._extract_description(tree, product_json)
        details = []
        if colors:
            details.append('<p><strong>Colores:</strong> %s</p>' % html.escape(' / '.join(colors)))
        if sizes:
            details.append('<p><strong>Tallas/variantes:</strong> %s</p>' % html.escape(' / '.join(sizes)))
        if details:
            description = (description or '') + ''.join(details)

        images = self._images(tree, product_json, canonical)
        reference = self._reference(tree, product_json, lines, canonical)
        categories = self._breadcrumbs(tree, canonical, name)
        ean_variants = self._prestashop_ean_variants(response.content)

        return {
            'name': name,
            'description': description,
            'price': price,
            'price_available': bool(price),
            'currency': currency or 'EUR',
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical,
            'style_code': reference,
            'color_code': ' / '.join(colors) if colors else False,
            'category_path': ' / '.join(categories),
            'ean_variants': ean_variants,
            # PrestaShop puede cargar combinaciones adicionales por AJAX; el
            # enriquecedor común invocará _fetch_site_ean_variants.
            'ean_complete': False,
        }
