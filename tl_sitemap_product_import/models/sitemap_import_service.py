import html
import base64
import hashlib
import mimetypes
import json
import logging
import re
import time
import traceback
from datetime import datetime
from urllib.parse import unquote, urljoin, urlparse

import requests
from psycopg2 import errors as pg_errors
from lxml import etree
from lxml import html as lxml_html

from odoo import fields, models

from .hornby_price_utils import eur_hosts_for_url, eur_product_urls, normalise_host

_logger = logging.getLogger(__name__)

SITEMAP_NS = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
IMAGE_NS = {'image': 'http://www.google.com/schemas/sitemap-image/1.1'}

IMAGE_MARKER = '[Sitemap Import]'

MAERKLIN_ARTICLE_CONNECTORS = frozenset({
    'sitemap.connector.maerklin_en',
    'sitemap.connector.trix_en',
    'sitemap.connector.minitrix_en',
    'sitemap.connector.lgb_en',
})


class SitemapImportService(models.AbstractModel):
    """Modelo base con la mecánica GENÉRICA compartida por todos los conectores: HTTP,
    robots.txt, parseo de XML de sitemaps, extracción de metaetiquetas de una página,
    resolución de categorías de Odoo y creación/actualización de productos.

    A propósito, este modelo NO decide qué sub-sitemaps son "de productos", ni con qué
    expresión regular se extrae el estilo/color, ni qué segmentos de la URL forman la
    categoría: cada sitio tiene su propia estructura y esas decisiones viven en su propio
    conector (sitemap.connector.*, ver models/connector_*.py), no aquí. Así, la estructura
    de un sitio nuevo -por muy distinta que sea- no obliga a retocar un sistema genérico de
    configuración, solo a escribir un conector pequeño y explícito.

    Un conector se registra como un modelo nuevo que hereda de este
    (_name = 'sitemap.connector.xxx', _inherit = 'sitemap.import.service') e implementa:
    - get_product_entries(source, category_filter=None, limit=0) -> [{'url','lastmod'}, ...]
    - get_image_map(source) -> {url_producto: [url_imagen, ...]}
    - fetch_preview(source, url) -> dict con name/description/price/currency/category_path/
      style_code/color_code/main_image_url/canonical_url
    """
    _name = 'sitemap.import.service'
    _description = 'Mecánica compartida de importación por sitemap (base para los conectores)'

    @staticmethod
    def _safe_json_loads(value, default=None):
        """Carga JSON tolerando campos Odoo vacíos o booleanos heredados.

        Los campos ``Text`` vacíos se leen como ``False``. Algunas filas antiguas
        también pueden contener booleanos por escrituras previas. En esos casos no
        se debe llamar a ``json.loads`` porque provoca ``TypeError`` y reintentos
        infinitos de ``queue_job``.
        """
        fallback = default if default is not None else {}
        if value in (None, False, True, ''):
            return fallback
        if isinstance(value, (dict, list, int, float)):
            return value
        if isinstance(value, bytes):
            value = value.decode('utf-8', errors='replace')
        if not isinstance(value, str):
            return fallback
        value = value.strip()
        if not value:
            return fallback
        try:
            return json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return fallback

    @staticmethod
    def _html_to_plain_text(value):
        """Convierte HTML importado en texto seguro para documentos de venta."""
        if not value:
            return ''
        raw = str(value)
        try:
            root = lxml_html.fragment_fromstring(raw, create_parent='div')
            text = ' '.join(root.itertext())
        except (etree.ParserError, TypeError, ValueError):
            text = re.sub(r'<[^>]+>', ' ', raw)
        return re.sub(r'\s+', ' ', text).strip()


    @staticmethod
    def _detect_response_encoding(response):
        """Detecta el charset real sin confiar ciegamente en ISO-8859-1 por defecto.

        Requests usa ISO-8859-1 cuando un ``text/*`` no declara charset. Muchas
        tiendas modernas sirven UTF-8 sin declararlo, lo que produce mojibake
        como ``PortÃ¡til``. Se priorizan BOM, cabecera, declaración XML/HTML y,
        finalmente, UTF-8 cuando los bytes son válidos.
        """
        content = response.content or b''
        if content.startswith(b'\xef\xbb\xbf'):
            return 'utf-8-sig'
        if content.startswith((b'\xff\xfe', b'\xfe\xff')):
            return 'utf-16'
        content_type = response.headers.get('Content-Type', '') or ''
        match = re.search(r'charset\s*=\s*["\']?([^;"\'\s]+)', content_type, re.I)
        if match:
            return match.group(1).strip()
        head = content[:4096]
        match = re.search(
            br'<\?xml[^>]+encoding=["\']\s*([^"\']+)', head, re.I
        ) or re.search(
            br'<meta[^>]+charset=["\']?\s*([^"\'\s/>]+)', head, re.I
        ) or re.search(
            br'<meta[^>]+content=["\'][^"\']*charset=([^;"\'\s>]+)', head, re.I
        )
        if match:
            try:
                return match.group(1).decode('ascii', errors='ignore').strip()
            except Exception:
                pass
        try:
            content.decode('utf-8')
            return 'utf-8'
        except UnicodeDecodeError:
            return response.apparent_encoding or response.encoding or 'utf-8'

    @classmethod
    def _fix_mojibake_text(cls, value):
        """Repara mojibake UTF-8 interpretado como latin-1/cp1252.

        La conversión solo se acepta cuando reduce marcadores típicos de texto
        corrupto, para no modificar palabras correctamente escritas. También se
        aplica a fragmentos HTML sin alterar sus etiquetas.
        """
        if value is None or not isinstance(value, str):
            return value
        text = value
        markers = ('Ã', 'Â', 'â€', 'â€™', 'â€œ', 'â€', 'â€“', 'â€”', 'ðŸ', 'ï»¿', '\ufffd')

        def score(candidate):
            return sum(candidate.count(marker) for marker in markers)

        for _index in range(3):
            before = score(text)
            if not before:
                break
            candidates = []
            for codec in ('latin-1', 'cp1252'):
                try:
                    candidates.append(text.encode(codec).decode('utf-8'))
                except (UnicodeEncodeError, UnicodeDecodeError):
                    continue
            if not candidates:
                break
            best = min(candidates, key=score)
            if score(best) >= before:
                break
            text = best
        return text.lstrip('\ufeff')

    @classmethod
    def _normalise_extracted_charset(cls, value):
        """Normaliza recursivamente cadenas recuperadas por cualquier conector."""
        if isinstance(value, str):
            return cls._fix_mojibake_text(value)
        if isinstance(value, list):
            return [cls._normalise_extracted_charset(item) for item in value]
        if isinstance(value, tuple):
            return tuple(cls._normalise_extracted_charset(item) for item in value)
        if isinstance(value, dict):
            return {
                cls._normalise_extracted_charset(key): cls._normalise_extracted_charset(item)
                for key, item in value.items()
            }
        return value

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    def _get_session(self, source):
        session = requests.Session()
        session.headers.update({
            'User-Agent': source.user_agent or 'Mozilla/5.0 (compatible; OdooSitemapImporter/1.0)',
            'Accept-Language': 'es-ES,es;q=0.9',
        })
        return session

    def _http_get(self, session, url, source):
        """GET resiliente compartido por Shopify, PrestaShop y el resto de conectores.

        Reintenta únicamente errores transitorios: límites 429, respuestas 5xx y
        fallos de red/timeout. Los 4xx funcionales se propagan inmediatamente para
        no ocultar URLs inválidas. Respeta ``Retry-After`` cuando el servidor lo
        publica y aplica espera exponencial configurable entre intentos.
        """
        max_retries = max(int(getattr(source, 'http_retry_count', 3) or 0), 0)
        backoff = max(float(getattr(source, 'http_retry_backoff', 1.5) or 0.0), 0.0)
        retry_statuses = {429, 500, 502, 503, 504}
        last_exc = None

        for attempt in range(max_retries + 1):
            try:
                _logger.debug(
                    'Sitemap import: GET %s (intento %s/%s)',
                    url, attempt + 1, max_retries + 1,
                )
                response = session.get(url, timeout=source.request_timeout or 20)
                if response.status_code not in retry_statuses:
                    response.raise_for_status()
                    detected_encoding = self._detect_response_encoding(response)
                    if detected_encoding:
                        response.encoding = detected_encoding
                    if source.request_delay:
                        time.sleep(source.request_delay)
                    return response

                last_exc = requests.HTTPError(
                    'HTTP %s al consultar %s' % (response.status_code, url),
                    response=response,
                )
                if attempt >= max_retries:
                    response.raise_for_status()

                retry_after = response.headers.get('Retry-After', '').strip()
                try:
                    wait_seconds = float(retry_after) if retry_after else backoff * (2 ** attempt)
                except ValueError:
                    wait_seconds = backoff * (2 ** attempt)
                wait_seconds = min(max(wait_seconds, 0.0), 120.0)
                _logger.warning(
                    'Sitemap import: HTTP %s temporal en %s; reintento %s/%s en %.2f s',
                    response.status_code, url, attempt + 1, max_retries, wait_seconds,
                )
                if wait_seconds:
                    time.sleep(wait_seconds)
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = exc
                if attempt >= max_retries:
                    raise
                wait_seconds = min(backoff * (2 ** attempt), 120.0)
                _logger.warning(
                    'Sitemap import: error de red temporal en %s (%s); '
                    'reintento %s/%s en %.2f s',
                    url, exc, attempt + 1, max_retries, wait_seconds,
                )
                if wait_seconds:
                    time.sleep(wait_seconds)

        if last_exc:
            raise last_exc
        raise requests.RequestException('No se pudo consultar %s' % url)

    def _hornby_official_eur_price(
        self, source, session, product_url, expected_code, price_parser,
        code_getter=None, eur_hosts=None, existing_response=None, brand_name='Hornby',
    ):
        """Lee el precio comercial oficial en EUR de una ficha Hornby.

        No convierte divisas. Si la ficha de origen ya pertenece a un mercado
        EUR, puede reutilizarse mediante ``existing_response``. En otro caso se
        consulta la misma ruta en el escaparate europeo oficial de la marca.

        ``price_parser`` recibe ``(tree, lines, product_node, product_name)`` y
        debe devolver ``(precio, moneda, disponible)``. ``code_getter`` valida
        que una redirección siga apuntando exactamente a la misma referencia.
        """
        target_hosts = eur_hosts_for_url(product_url, explicit_hosts=eur_hosts)
        if not target_hosts:
            _logger.info(
                '%s: no hay un escaparate oficial EUR configurado para %s',
                brand_name, product_url,
            )
            return 0.0, 'EUR', False

        responses = []
        if existing_response is not None:
            response_host = normalise_host(urlparse(existing_response.url).netloc)
            if response_host in target_hosts:
                responses.append(existing_response)

        used_urls = {getattr(item, 'url', '') for item in responses}
        for candidate in eur_product_urls(product_url, explicit_hosts=target_hosts):
            if candidate in used_urls:
                continue
            try:
                responses.append(self._http_get(session, candidate, source))
                used_urls.add(candidate)
            except Exception as exc:
                _logger.info(
                    '%s: no se pudo consultar el precio oficial EUR en %s: %s',
                    brand_name, candidate, exc,
                )

        for response in responses:
            response_host = normalise_host(urlparse(response.url).netloc)
            if response_host not in target_hosts:
                _logger.info(
                    '%s: la ficha EUR redirigió a un dominio no autorizado: %s',
                    brand_name, response.url,
                )
                continue

            if code_getter:
                response_code = code_getter(response.url)
                if not response_code:
                    _logger.info(
                        '%s: no se pudo validar la referencia de %s',
                        brand_name, response.url,
                    )
                    continue
                if expected_code and str(response_code).upper() != str(expected_code).upper():
                    _logger.info(
                        '%s: la ficha EUR %s corresponde a %s, no a %s',
                        brand_name, response.url, response_code, expected_code,
                    )
                    continue

            try:
                page_markup = getattr(response, 'text', None) or response.content
                tree = lxml_html.fromstring(page_markup)
                lines = self._visible_lines(tree)
                payloads = self._json_payloads(tree)
                product_node = self._product_json_node(payloads)
                product_name = (
                    self._normalise_text(product_node.get('name'))
                    if isinstance(product_node, dict) else ''
                )
                if not product_name:
                    product_name = self._normalise_text(' '.join(tree.xpath('//h1//text()')))
                price, currency, available = price_parser(
                    tree, lines, product_node, product_name,
                )
            except Exception as exc:
                _logger.info(
                    '%s: no se pudo interpretar el precio EUR de %s: %s',
                    brand_name, response.url, exc,
                )
                continue

            currency_code = self._normalise_text(currency).upper()
            if currency_code not in {'EUR', '€'}:
                _logger.info(
                    '%s: la ficha oficial %s devolvió moneda %s, no EUR',
                    brand_name, response.url, currency,
                )
                continue
            if available and price and price > 0:
                return price, 'EUR', True

        return 0.0, 'EUR', False

    # ------------------------------------------------------------------
    # robots.txt (parser propio: la librería estándar de Python no
    # interpreta correctamente los comodines "*" habituales en robots.txt,
    # p. ej. "Disallow: /carrito*" -> comprobado contra robots.txt reales)
    # ------------------------------------------------------------------
    def check_robots(self, source, sample_url):
        if not source.respect_robots_txt:
            return True
        parsed = urlparse(sample_url)
        robots_url = f'{parsed.scheme}://{parsed.netloc}/robots.txt'
        try:
            session = self._get_session(source)
            response = session.get(robots_url, timeout=source.request_timeout or 20)
            if response.status_code >= 400:
                return True  # sin robots.txt publicado -> se asume permitido
            allowed = self._robots_allowed(response.text, source.user_agent, sample_url)
            if not allowed:
                _logger.warning('Sitemap import: robots.txt no permite el acceso a %s', sample_url)
            return allowed
        except Exception as exc:
            _logger.warning('Sitemap import: no se pudo leer robots.txt (%s); se continúa por defecto', exc)
            return True

    @staticmethod
    def _robots_pattern_to_regex(pattern):
        import re
        end_anchor = pattern.endswith('$')
        if end_anchor:
            pattern = pattern[:-1]
        parts = []
        for token in re.split(r'(\*)', pattern):
            if token == '*':
                parts.append('.*')
            elif token:
                parts.append(re.escape(token))
        regex = '^' + ''.join(parts) + ('$' if end_anchor else '')
        return re.compile(regex)

    @staticmethod
    def _parse_robots(text):
        groups = []
        current_agents, current_rules = [], []
        seen_rule_in_group = False
        for raw_line in text.splitlines():
            line = raw_line.split('#', 1)[0].strip()
            if not line or ':' not in line:
                continue
            field, _, value = line.partition(':')
            field, value = field.strip().lower(), value.strip()
            if field == 'user-agent':
                if seen_rule_in_group:
                    groups.append((current_agents, current_rules))
                    current_agents, current_rules = [], []
                    seen_rule_in_group = False
                current_agents.append(value.lower())
            elif field in ('allow', 'disallow'):
                current_rules.append((field, value or None))
                seen_rule_in_group = True
        if current_agents:
            groups.append((current_agents, current_rules))
        return groups

    def _robots_allowed(self, robots_text, user_agent, url):
        groups = self._parse_robots(robots_text)
        ua = (user_agent or '*').lower()
        rules = None
        for agents, group_rules in groups:
            if any(a != '*' and a in ua for a in agents):
                rules = group_rules
                break
        if rules is None:
            for agents, group_rules in groups:
                if '*' in agents:
                    rules = group_rules
                    break
        if not rules:
            return True
        parsed = urlparse(url)
        path = parsed.path or '/'
        if parsed.query:
            path = f'{path}?{parsed.query}'
        best_len, best_allow = -1, True
        for rule_type, pattern in rules:
            if pattern is None:
                if rule_type == 'disallow' and 0 > best_len:
                    best_len, best_allow = 0, True
                continue
            if self._robots_pattern_to_regex(pattern).match(path):
                if len(pattern) > best_len:
                    best_len, best_allow = len(pattern), (rule_type == 'allow')
        return best_allow

    # ------------------------------------------------------------------
    # Mecánica XML genérica de sitemaps (sin decisiones específicas de sitio:
    # qué ficheros combinar lo decide cada conector, esto solo sabe leer UN
    # fichero de índice o UN urlset dado su URL)
    # ------------------------------------------------------------------
    def _fetch_sitemap_index_locs(self, source, index_url):
        """Dado un sitemap_index.xml, devuelve la lista de <loc> de sus sub-sitemaps."""
        session = self._get_session(source)
        response = self._http_get(session, index_url, source)
        root = etree.fromstring(response.content)
        return [el.text.strip() for el in root.findall('.//sm:sitemap/sm:loc', SITEMAP_NS) if el.text]

    def _fetch_urlset(self, source, sitemap_url):
        """Dado UN sitemap de URLs (urlset), devuelve sus entradas {'url','lastmod'}."""
        session = self._get_session(source)
        response = self._http_get(session, sitemap_url, source)
        root = etree.fromstring(response.content)
        entries = []
        for url_el in root.findall('.//sm:url', SITEMAP_NS):
            loc_el = url_el.find('sm:loc', SITEMAP_NS)
            if loc_el is None or not loc_el.text:
                continue
            lastmod_el = url_el.find('sm:lastmod', SITEMAP_NS)
            entries.append({
                'url': loc_el.text.strip(),
                'lastmod': self._parse_lastmod(lastmod_el.text if lastmod_el is not None else None),
            })
        return entries

    def _fetch_image_urlset(self, source, sitemap_url):
        """Dado UN sitemap de imágenes, devuelve {url_producto: [url_imagen, ...]}."""
        session = self._get_session(source)
        response = self._http_get(session, sitemap_url, source)
        root = etree.fromstring(response.content)
        image_map = {}
        for url_el in root.findall('.//sm:url', SITEMAP_NS):
            loc_el = url_el.find('sm:loc', SITEMAP_NS)
            if loc_el is None or not loc_el.text:
                continue
            loc = loc_el.text.strip()
            images = []
            for img_el in url_el.findall('image:image', IMAGE_NS):
                loc_img = img_el.find('image:loc', IMAGE_NS)
                if loc_img is not None and loc_img.text:
                    images.append(loc_img.text.strip())
            if images:
                image_map[loc] = images
        return image_map

    @staticmethod
    def _parse_lastmod(value):
        if not value:
            return False
        try:
            return datetime.strptime(value[:19], '%Y-%m-%dT%H:%M:%S')
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # Descubrimiento multifuente
    # ------------------------------------------------------------------
    def _merge_discovery_entries(
        self, source_name, entry_groups, key_getter=None,
        category_filter=None, limit=0,
    ):
        """Fusiona inventarios parciales sin considerar completa una sola fuente.

        ``entry_groups`` es una secuencia ``[(nombre, entradas), ...]``. La
        deduplicación se realiza por ``key_getter(url)`` o, por defecto, por URL
        canónica sin query ni fragmento. Una entrada posterior puede aportar un
        ``lastmod`` más reciente, pero no elimina productos hallados por otra vía.
        El límite se aplica únicamente después de fusionar todas las fuentes.
        """
        def default_key(url):
            parts = urlparse(str(url or '').strip())
            path = re.sub(r'/+', '/', parts.path or '/').rstrip('/') or '/'
            return f'{parts.scheme.lower()}://{parts.netloc.lower()}{path}'

        key_getter = key_getter or default_key
        merged = {}
        counts = {}
        needle = str(category_filter or '').strip().casefold()
        for group_name, raw_entries in entry_groups:
            local_keys = set()
            for raw in raw_entries or []:
                if not isinstance(raw, dict):
                    continue
                url = str(raw.get('url') or '').strip()
                if not url or (needle and needle not in url.casefold()):
                    continue
                key = key_getter(url)
                if not key:
                    continue
                local_keys.add(key)
                candidate = {
                    'url': url,
                    'lastmod': raw.get('lastmod') or False,
                }
                current = merged.get(key)
                if not current:
                    merged[key] = candidate
                elif candidate['lastmod'] and (
                    not current.get('lastmod') or candidate['lastmod'] > current['lastmod']
                ):
                    merged[key] = candidate
            counts[group_name] = len(local_keys)

        result = sorted(merged.values(), key=lambda item: item['url'])
        _logger.info(
            '%s: descubrimiento multifuente %s; %s productos únicos',
            source_name,
            ', '.join(f'{name}={count}' for name, count in counts.items()),
            len(result),
        )
        non_empty = [count for count in counts.values() if count]
        if len(non_empty) > 1 and max(non_empty) >= (min(non_empty) * 1.25):
            _logger.warning(
                '%s: las fuentes de descubrimiento difieren de forma significativa: %s',
                source_name, counts,
            )
        return result[:limit] if limit else result

    def _discover_html_product_entries(
        self, source, start_urls, is_product_url, is_category_url=None,
        canonicalize=None, max_pages=300,
    ):
        """Rastrea categorías HTML como inventario complementario y acotado.

        El conector conserva el control de qué constituye una ficha o categoría.
        Esto evita filtros globales por nombres como ``bikes`` o ``shoes`` que
        excluyen accesorios. Solo se siguen URLs aceptadas por el conector.
        """
        canonicalize = canonicalize or (lambda value: value)
        session = self._get_session(source)
        queue = list(start_urls or [])
        queued = set(queue)
        visited = set()
        products = {}
        while queue and len(visited) < max_pages:
            requested = queue.pop(0)
            try:
                response = self._http_get(session, requested, source)
                page_url = canonicalize(response.url)
                if page_url in visited:
                    continue
                visited.add(page_url)
                tree = lxml_html.fromstring(response.content)
            except Exception as exc:
                _logger.info('Descubrimiento HTML: no se pudo leer %s: %s', requested, exc)
                continue
            for href in tree.xpath('//a[@href]/@href'):
                absolute = canonicalize(urljoin(response.url, href))
                if not absolute:
                    continue
                if is_product_url(absolute):
                    products.setdefault(absolute, {'url': absolute, 'lastmod': False})
                elif is_category_url and is_category_url(absolute):
                    if absolute not in queued and absolute not in visited:
                        queue.append(absolute)
                        queued.add(absolute)
        return list(products.values())

    # ------------------------------------------------------------------
    # Mecánica genérica de ficha de producto: SOLO extrae metaetiquetas
    # (Open Graph / Twitter Card), sin interpretar estilo/color/categoría
    # -eso es cada conector quien lo decide en su propio fetch_preview-.
    # ------------------------------------------------------------------
    def _fetch_og_meta(self, source, url):
        session = self._get_session(source)
        response = self._http_get(session, url, source)
        tree = lxml_html.fromstring(response.content)

        def meta(prop):
            values = tree.xpath(f'//meta[@property="{prop}"]/@content')
            if not values:
                values = tree.xpath(f'//meta[@name="{prop}"]/@content')
            return values[0].strip() if values else False

        canonical_els = tree.xpath('//link[@rel="canonical"]/@href')
        canonical_url = canonical_els[0].strip() if canonical_els else url

        title = meta('og:title')
        if not title:
            title_els = tree.xpath('//title/text()')
            title = title_els[0].split('|')[0].strip() if title_els else url

        description = meta('og:description') or meta('description') or ''
        price_str = meta('product:price:amount') or meta('og:price:amount') or '0'
        currency = meta('product:price:currency') or meta('og:price:currency') or 'EUR'
        image_url = meta('og:image')

        try:
            price = float(price_str)
        except (TypeError, ValueError):
            price = 0.0

        return {
            'name': title or url,
            'description': description,
            'price': price,
            'currency': currency,
            'main_image_url': image_url or False,
            'canonical_url': canonical_url,
        }


    # ------------------------------------------------------------------
    # EAN / GTIN (común a todos los conectores)
    # ------------------------------------------------------------------
    _GTIN_FIELDS = {
        'gtin', 'gtin8', 'gtin12', 'gtin13', 'gtin14',
        'ean', 'ean8', 'ean12', 'ean13', 'ean14', 'barcode', 'upc', 'upca',
    }

    @staticmethod
    def _gtin_type(value):
        return {
            8: 'gtin8',
            12: 'gtin12',
            13: 'gtin13',
            14: 'gtin14',
        }.get(len(value))

    @classmethod
    def _normalise_gtin(cls, value):
        """Devuelve un GTIN numérico válido o False.

        Se aceptan GTIN-8, UPC-A/GTIN-12, EAN-13 y GTIN-14. Se valida el
        dígito de control para no confundir SKU, referencias internas o IDs
        de variante con un EAN.
        """
        if value is None or isinstance(value, bool):
            return False
        text = str(value).strip()
        if not text:
            return False

        # GS1 Digital Link y notación humana (01)0950...
        digital = re.search(r'(?:/01/|\(01\)|\b01)(\d{14})(?:\D|$)', text)
        if digital:
            text = digital.group(1)
        else:
            text = re.sub(r'[\s.-]', '', text)
            if not text.isdigit():
                match = re.fullmatch(r'[^0-9]*(\d{8}|\d{12}|\d{13}|\d{14})[^0-9]*', text)
                if not match:
                    return False
                text = match.group(1)

        if len(text) not in (8, 12, 13, 14):
            return False
        digits = [int(char) for char in text]
        check = digits[-1]
        body = digits[:-1]
        total = 0
        # GS1: desde la derecha del cuerpo, peso 3,1,3,1...
        for index, digit in enumerate(reversed(body)):
            total += digit * (3 if index % 2 == 0 else 1)
        expected = (10 - (total % 10)) % 10
        return text if check == expected else False

    @classmethod
    def _ean_variant(cls, ean=False, sku=False, label=False, source_variant_id=False, available=True):
        """Normaliza una variante, incluso si la tienda todavía no publica GTIN."""
        label = str(label or '').strip() or False
        ean = cls._normalise_gtin(ean) if ean else False
        if not ean and not label:
            return False
        return {
            'ean': ean,
            'gtin_type': cls._gtin_type(ean) if ean else False,
            'sku': str(sku or '').strip() or False,
            'variant_label': label,
            'source_variant_id': str(source_variant_id or '').strip() or False,
            'available': bool(available),
        }

    @classmethod
    def _normalise_ean_variants(cls, variants):
        """Deduplica por GTIN y conserva opciones sin GTIN por ID o etiqueta."""
        by_key = {}
        order = []
        for item in variants or []:
            if isinstance(item, str):
                item = {'ean': item}
            if not isinstance(item, dict):
                continue
            normalised = cls._ean_variant(
                item.get('ean') or item.get('gtin') or item.get('barcode'),
                sku=item.get('sku'),
                label=item.get('variant_label') or item.get('label') or item.get('title'),
                source_variant_id=item.get('source_variant_id') or item.get('id'),
                available=item.get('available', True),
            )
            if not normalised:
                continue
            if normalised.get('ean'):
                key = ('ean', normalised['ean'])
            elif normalised.get('source_variant_id'):
                key = ('id', normalised['source_variant_id'])
            else:
                key = ('label', normalised['variant_label'].casefold())
            if key not in by_key:
                by_key[key] = normalised
                order.append(key)
                continue
            current = by_key[key]
            for field in ('ean', 'gtin_type', 'sku', 'variant_label', 'source_variant_id'):
                if not current.get(field) and normalised.get(field):
                    current[field] = normalised[field]
            current['available'] = current.get('available', True) or normalised.get('available', True)
        return [by_key[key] for key in order]

    @classmethod
    def _ean_variants_from_shopify_product(cls, product_data):
        """Extrae barcode/SKU/opciones de la respuesta Ajax de Shopify."""
        if not isinstance(product_data, dict):
            return []
        option_names = []
        for option in product_data.get('options') or []:
            if isinstance(option, dict):
                option_names.append(str(option.get('name') or '').strip())
            else:
                option_names.append(str(option or '').strip())

        result = []
        for variant in product_data.get('variants') or []:
            if not isinstance(variant, dict):
                continue
            values = variant.get('options') or []
            labels = []
            if isinstance(values, list):
                for index, value in enumerate(values):
                    value = str(value or '').strip()
                    if not value or value.casefold() == 'default title':
                        continue
                    name = option_names[index] if index < len(option_names) else ''
                    labels.append(f'{name}: {value}' if name else value)
            label = ' / '.join(labels)
            if not label:
                title = str(variant.get('title') or '').strip()
                label = False if title.casefold() == 'default title' else title
            item = cls._ean_variant(
                variant.get('barcode'),
                sku=variant.get('sku'),
                label=label,
                source_variant_id=variant.get('id'),
                available=variant.get('available', True),
            )
            if item:
                result.append(item)

        # Algunas tiendas publican el GTIN a nivel de producto simple.
        direct = cls._ean_variant(
            product_data.get('barcode') or product_data.get('gtin'),
            sku=product_data.get('sku'),
            label=product_data.get('title'),
            source_variant_id=product_data.get('id'),
        )
        if direct:
            result.append(direct)
        return cls._normalise_ean_variants(result)

    @classmethod
    def _payload_available(cls, node):
        value = node.get('available')
        if value is None:
            value = node.get('inStock')
        if value is None:
            value = node.get('availability')
        if isinstance(value, str):
            lowered = value.casefold()
            if any(token in lowered for token in ('outofstock', 'out_of_stock', 'agotado', 'soldout')):
                return False
            if any(token in lowered for token in ('instock', 'in_stock', 'disponible')):
                return True
        return True if value is None else bool(value)

    @classmethod
    def _selected_variant_label(cls, node):
        parts = []
        selected_options = node.get('selectedOptions') or node.get('selected_options') or []
        if isinstance(selected_options, dict):
            selected_options = list(selected_options.values())
        for option in selected_options if isinstance(selected_options, list) else []:
            if not isinstance(option, dict):
                continue
            name = option.get('name') or option.get('id') or option.get('attributeId')
            value = option.get('value') or option.get('displayValue')
            if value:
                parts.append(f'{name}: {value}' if name else str(value))

        attributes = node.get('variationAttributes') or node.get('variationAttrs') or []
        if isinstance(attributes, dict):
            attributes = list(attributes.values())
        for attribute in attributes if isinstance(attributes, list) else []:
            if not isinstance(attribute, dict):
                continue
            name = (
                attribute.get('displayName') or attribute.get('name')
                or attribute.get('id') or attribute.get('attributeId')
            )
            selected = attribute.get('selectedValue') or attribute.get('selected')
            value = False
            if isinstance(selected, dict):
                value = selected.get('displayValue') or selected.get('name') or selected.get('value')
            elif isinstance(selected, str):
                value = selected
            if not value:
                for option in attribute.get('values') or []:
                    if isinstance(option, dict) and option.get('selected'):
                        value = option.get('displayValue') or option.get('name') or option.get('value')
                        break
            if value:
                part = f'{name}: {value}' if name else str(value)
                if part not in parts:
                    parts.append(part)
        return ' / '.join(str(part).strip() for part in parts if str(part).strip()) or False

    @classmethod
    def _ean_variants_from_payload(cls, payload):
        """Recorre JSON-LD/JSON de cualquier plataforma y recupera GTIN publicados."""
        result = []
        visited = set()

        def walk(value, inherited_label=False, inherited_sku=False):
            if id(value) in visited:
                return
            if isinstance(value, (dict, list)):
                visited.add(id(value))
            if isinstance(value, list):
                for child in value:
                    walk(child, inherited_label, inherited_sku)
                return
            if not isinstance(value, dict):
                return

            lower = {str(key).casefold(): val for key, val in value.items()}
            label = (
                cls._selected_variant_label(value)
                or value.get('variant_label') or value.get('title') or value.get('name')
                or value.get('displayValue') or value.get('size') or inherited_label
            )
            sku = (
                value.get('sku') or value.get('manufacturerSKU') or value.get('mpn')
                or value.get('productID') or inherited_sku
            )
            source_id = value.get('variantId') or value.get('productId') or value.get('id') or value.get('@id')

            for field in cls._GTIN_FIELDS:
                raw = lower.get(field)
                if isinstance(raw, (str, int)):
                    item = cls._ean_variant(
                        raw, sku=sku, label=label, source_variant_id=source_id,
                        available=cls._payload_available(value),
                    )
                    if item:
                        result.append(item)

            # Schema.org PropertyValue: {propertyID: "GTIN", value: "..."}
            property_name = str(
                value.get('propertyID') or value.get('propertyId') or value.get('name') or ''
            ).casefold()
            if any(token in property_name for token in ('gtin', 'ean', 'barcode')):
                item = cls._ean_variant(
                    value.get('value'), sku=sku, label=label, source_variant_id=source_id,
                    available=cls._payload_available(value),
                )
                if item:
                    result.append(item)

            for child in value.values():
                walk(child, label, sku)

        walk(payload)
        return cls._normalise_ean_variants(result)

    def _ean_variants_from_html_content(self, content):
        result = []
        try:
            tree = lxml_html.fromstring(content)
        except (ValueError, etree.ParserError):
            tree = None
        if tree is not None:
            for raw in tree.xpath('//script[@type="application/ld+json" or @type="application/json"]/text()'):
                if not raw or len(raw) > 8_000_000:
                    continue
                try:
                    result.extend(self._ean_variants_from_payload(json.loads(raw)))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue

        text = content.decode('utf-8', errors='ignore') if isinstance(content, bytes) else str(content)
        # Respaldo para objetos JavaScript no estrictamente JSON.
        pattern = re.compile(
            r'["\'](?:gtin(?:8|12|13|14)?|ean(?:8|12|13|14)?|EAN(?:8|12|13|14)?|barcode|upc|upca)["\']\s*:\s*["\'](\d{8}|\d{12}|\d{13}|\d{14})["\']'
        )
        existing_eans = {item.get('ean') for item in result if isinstance(item, dict)}
        for match in pattern.finditer(text):
            item = self._ean_variant(match.group(1))
            if item and item['ean'] not in existing_eans:
                result.append(item)
                existing_eans.add(item['ean'])
        return self._normalise_ean_variants(result)

    def _shopify_product_endpoint_urls(self, product_url, include_js=True):
        """Return locale-preserving Shopify JSON endpoints in priority order.

        ``include_js`` lets a source permanently skip the lightweight ``.js``
        endpoint after the shop has answered 404 once. The ``.json`` and
        ``products.json`` fallbacks remain available.
        """
        parsed = urlparse(product_url)
        path = parsed.path.rstrip('/')
        suffixes = ('.js', '.json') if include_js else ('.json',)
        for suffix in suffixes:
            endpoint_path = path if path.endswith(suffix) else path + suffix
            yield parsed._replace(path=endpoint_path, query='', fragment='').geturl()

    @staticmethod
    def _shopify_js_should_be_used(source):
        mode = getattr(source, 'shopify_js_mode', 'auto') or 'auto'
        status = getattr(source, 'shopify_js_status', 'unknown') or 'unknown'
        if mode == 'disabled':
            return False
        if mode == 'enabled':
            return True
        return status != 'unsupported'

    @staticmethod
    def _set_shopify_js_status(source, status):
        if not source or getattr(source, 'shopify_js_mode', 'auto') != 'auto':
            return
        if getattr(source, 'shopify_js_status', 'unknown') == status:
            return
        try:
            source.sudo().write({
                'shopify_js_status': status,
                'shopify_js_checked_at': fields.Datetime.now(),
            })
        except Exception:
            _logger.debug(
                'Shopify: no se pudo guardar el estado .js de la fuente %s',
                getattr(source, 'display_name', source), exc_info=True,
            )

    @staticmethod
    def _shopify_product_handle(product_url):
        """Return the stable Shopify handle from a localized product URL."""
        path = urlparse(product_url).path.rstrip('/')
        match = re.search(r'/products/([^/]+?)(?:\.js|\.json)?$', path, flags=re.IGNORECASE)
        return match.group(1) if match else False

    @staticmethod
    def _normalise_shopify_product_payload(payload):
        """Normalize direct, wrapped and catalogue Shopify product payloads."""
        if not isinstance(payload, dict):
            return {}
        product = payload.get('product')
        if isinstance(product, dict):
            return product
        if any(payload.get(field) for field in ('title', 'name', 'handle')):
            return payload
        return {}

    def _fetch_shopify_catalog_product(self, source, product_url, max_pages=100):
        """Find one product by handle in Shopify's paginated public catalogue.

        Some shops allow ``products.json`` while blocking or customising the
        per-product ``.js``/``.json`` endpoints.  The catalogue contains the
        same core data needed by the import: title, variants, price and images.
        """
        handle = self._shopify_product_handle(product_url)
        if not handle:
            return {}
        parsed = urlparse(product_url)
        base_url = f'{parsed.scheme}://{parsed.netloc}'
        session = self._get_session(source)
        for page in range(1, max_pages + 1):
            endpoint = f'{base_url}/products.json?limit=250&page={page}'
            try:
                response = self._http_get(session, endpoint, source)
                payload = response.json()
            except Exception:  # catalogue may be disabled; caller has other fallbacks
                return {}
            products = payload.get('products') if isinstance(payload, dict) else None
            if not isinstance(products, list) or not products:
                return {}
            for product in products:
                if not isinstance(product, dict):
                    continue
                if str(product.get('handle') or '').casefold() == handle.casefold():
                    return product
            if len(products) < 250:
                return {}
        return {}

    def _fetch_shopify_product_payload(self, source, product_url):
        """Fetch and normalize a Shopify product independently of the theme.

        Priority: localized ``.js`` when enabled/supported, localized ``.json``
        and finally the paginated public catalogue. A 404 from ``.js`` in auto
        mode is an expected capability result: it is stored once on the source
        and not logged as a product error on subsequent requests.
        """
        session = self._get_session(source)
        errors = []
        include_js = self._shopify_js_should_be_used(source)
        for endpoint in self._shopify_product_endpoint_urls(product_url, include_js=include_js):
            is_js = urlparse(endpoint).path.endswith('.js')
            try:
                response = self._http_get(session, endpoint, source)
                payload = response.json()
            except requests.HTTPError as exc:
                status_code = getattr(getattr(exc, 'response', None), 'status_code', None)
                if is_js and status_code in {404, 405, 410}:
                    self._set_shopify_js_status(source, 'unsupported')
                    _logger.debug(
                        'Shopify .js no disponible para la fuente %s (%s); se omite en adelante.',
                        source.display_name, status_code,
                    )
                    continue
                errors.append(str(exc))
                continue
            except Exception as exc:  # JSON inválido o endpoint personalizado
                errors.append(str(exc))
                continue
            product = self._normalise_shopify_product_payload(payload)
            if product:
                if is_js:
                    self._set_shopify_js_status(source, 'supported')
                return product

        product = self._fetch_shopify_catalog_product(source, product_url)
        if product:
            return product

        detail = '; '.join(errors[-2:]) if errors else 'sin detalle HTTP'
        raise ValueError(
            'Shopify no devolvió un producto válido mediante .js, .json ni products.json '
            f'para {product_url} ({detail}).'
        )

    def _shopify_ajax_product_url(self, product_url):
        parsed = urlparse(product_url)
        path = parsed.path.rstrip('/')
        if not path.endswith('.js'):
            path += '.js'
        return parsed._replace(path=path, query='', fragment='').geturl()

    def _fetch_shopify_ean_variants(self, source, product_url):
        if '/products/' not in urlparse(product_url).path.casefold():
            return []
        product = self._fetch_shopify_product_payload(source, product_url)
        return self._ean_variants_from_shopify_product(product)

    def _fetch_generic_ean_variants(self, source, product_url):
        session = self._get_session(source)
        response = self._http_get(session, product_url, source)
        return self._ean_variants_from_html_content(response.content)

    def _fetch_site_ean_variants(self, source, product_url, preview_data):
        """Busca GTIN en la página y en endpoints públicos de variación.

        Es el respaldo común para Salesforce Commerce Cloud y otras tiendas que
        cargan el EAN al seleccionar talla/color. Los conectores pueden
        sobrescribirlo si conocen un endpoint más preciso.
        """
        session = self._get_session(source)
        response = self._http_get(session, product_url, source)
        variants = self._ean_variants_from_html_content(response.content)
        limit = max(int(source.max_ean_requests_per_product or 0), 0)
        if not limit:
            return variants

        text = response.text
        candidates = []
        # URLs en atributos HTML y objetos JS. Se restringen a términos de
        # variación para no seguir recomendaciones, carrito o analítica.
        patterns = (
            r"[\"']([^\"']*(?:Product-Variation|product/variation|product-variation|variation\?)[^\"']*)[\"']",
            r"[\"']([^\"']*dwvar_[^\"']*(?:size|talla|color)[^\"']*)[\"']",
        )
        for pattern in patterns:
            for raw in re.findall(pattern, text, flags=re.IGNORECASE):
                value = unquote(
                    raw.replace('\\/', '/').replace('&amp;', '&')
                    .replace('\\u0026', '&').replace('\\x26', '&')
                )
                endpoint = urljoin(product_url, value)
                if endpoint not in candidates:
                    candidates.append(endpoint)
                if len(candidates) >= limit:
                    break
            if len(candidates) >= limit:
                break

        for endpoint in candidates[:limit]:
            try:
                variant_response = self._http_get(session, endpoint, source)
                try:
                    payload = variant_response.json()
                except (TypeError, ValueError, json.JSONDecodeError):
                    payload = None
                if payload is not None:
                    variants.extend(self._ean_variants_from_payload(payload))
                else:
                    variants.extend(self._ean_variants_from_html_content(variant_response.content))
            except Exception as exc:
                _logger.debug('EAN: endpoint de variación no accesible %s: %s', endpoint, exc)
        return self._normalise_ean_variants(variants)

    def enrich_preview_eans(self, source, product_url, preview_data):
        data = dict(preview_data or {})
        if not source.import_eans:
            data.update({'ean_variants': [], 'ean': False, 'ean_count': 0, 'ean_checked': False})
            return data

        variants = self._normalise_ean_variants(data.get('ean_variants') or [])
        complete = bool(data.get('ean_complete'))
        checked = complete

        # Los conectores Shopify normalmente incorporan ya todos los códigos
        # desde la respuesta Ajax usada para la ficha. Si no, se consulta aquí.
        if not complete and not variants and '/products/' in urlparse(product_url).path.casefold():
            try:
                shopify_variants = self._fetch_shopify_ean_variants(source, product_url)
                variants.extend(shopify_variants)
                complete = True  # el endpoint devuelve la lista completa de variantes
                checked = True
            except Exception as exc:
                _logger.debug('EAN: Shopify estructurado no disponible para %s: %s', product_url, exc)

        # JSON-LD puede contener solo el producto principal. Mientras el conector
        # no declare la lista completa, se buscan además endpoints de talla/color.
        if not complete:
            try:
                variants.extend(self._fetch_site_ean_variants(source, product_url, data))
                checked = True
            except Exception as exc:
                _logger.info('EAN: el endpoint específico falló para %s: %s', product_url, exc)

        variants = self._normalise_ean_variants(variants)
        unique_eans = list(dict.fromkeys(item.get('ean') for item in variants if item.get('ean')))
        data['ean_variants'] = variants
        data['ean_count'] = len(unique_eans)
        data['ean'] = unique_eans[0] if len(unique_eans) == 1 else False
        data['ean_checked'] = checked
        return data

    @staticmethod
    def _variant_label_parts(label):
        """Convierte etiquetas como ``Talla: 36 / Color: Negro`` en pares.

        Se admiten separadores habituales de Shopify y PrestaShop. Si una
        etiqueta no declara el nombre del atributo, se conserva bajo
        ``Variante`` para no perder el valor ni impedir la generación.
        """
        text = str(label or '').strip()
        if not text:
            return []
        import re
        chunks = [part.strip() for part in re.split(r'\s*(?:/|\||;)\s*', text) if part.strip()]
        result = []
        for chunk in chunks:
            if ':' in chunk:
                name, value = chunk.split(':', 1)
            elif '=' in chunk:
                name, value = chunk.split('=', 1)
            else:
                name, value = 'Variante', chunk
            name, value = name.strip(), value.strip()
            if name and value:
                result.append((name, value))
        return result

    def _variant_attribute(self, name):
        Attribute = self.env['product.attribute']
        attribute = Attribute.search([('name', '=ilike', name)], limit=1)
        if not attribute:
            attribute = Attribute.create({'name': name, 'create_variant': 'always'})
        elif attribute.create_variant == 'no_variant':
            # Un atributo detectado en variantes debe generar product.product.
            # La conversión es deliberada: mantenerlo como informativo impediría
            # crear las tallas/colores publicadas por la fuente.
            attribute.write({'create_variant': 'always'})
        return attribute

    @staticmethod
    def _variant_attribute_names(variants):
        names = set()
        for item in variants or []:
            label = item.get('variant_label') if isinstance(item, dict) else False
            for name, _value in SitemapImportService._variant_label_parts(label):
                names.add(name.strip().casefold())
        return names

    def _remove_duplicate_variant_informational_attributes(self, product_tmpl, variants):
        """Elimina líneas informativas que duplican atributos de variante.

        Históricamente Munich enviaba ``Talla`` tanto en ``attributes`` como en
        ``variant_label``. El primer canal generaba ``Talla (informativo)`` y el
        segundo ``Talla``. Se conserva únicamente el atributo generador.
        """
        variant_names = self._variant_attribute_names(variants)
        if not variant_names:
            return
        suffix_re = re.compile(r'\s*\((?:informativo|informativa)\)\s*$', re.I)
        lines = product_tmpl.attribute_line_ids.filtered(
            lambda line: line.attribute_id.create_variant == 'no_variant'
        )
        to_remove = self.env['product.template.attribute.line']
        for line in lines:
            base_name = suffix_re.sub('', line.attribute_id.name or '').strip().casefold()
            if base_name in variant_names:
                to_remove |= line
        if to_remove:
            to_remove.unlink()

    def _sync_product_variants(self, product_tmpl, variants):
        variants = self._normalise_ean_variants(variants)
        parsed = []
        attribute_values = {}
        for item in variants:
            parts = self._variant_label_parts(item.get('variant_label'))
            if not parts:
                continue
            parsed.append((item, parts))
            for attribute_name, value_name in parts:
                attribute_values.setdefault(attribute_name, [])
                if value_name not in attribute_values[attribute_name]:
                    attribute_values[attribute_name].append(value_name)
        if not parsed:
            return

        Value = self.env['product.attribute.value']
        Line = self.env['product.template.attribute.line']
        value_by_key = {}
        for attribute_name, names in attribute_values.items():
            attribute = self._variant_attribute(attribute_name)
            values = Value.browse([])
            for value_name in names:
                value = Value.search([
                    ('attribute_id', '=', attribute.id),
                    ('name', '=ilike', value_name),
                ], limit=1)
                if not value:
                    value = Value.create({'attribute_id': attribute.id, 'name': value_name})
                values |= value
                value_by_key[(attribute_name.casefold(), value_name.casefold())] = value
            line = Line.search([
                ('product_tmpl_id', '=', product_tmpl.id),
                ('attribute_id', '=', attribute.id),
            ], limit=1)
            if line:
                missing = values - line.value_ids
                if missing:
                    line.write({'value_ids': [(4, value.id) for value in missing]})
            else:
                Line.create({
                    'product_tmpl_id': product_tmpl.id,
                    'attribute_id': attribute.id,
                    'value_ids': [(6, 0, values.ids)],
                })

        # Odoo suele generar las variantes al escribir las líneas. La llamada
        # explícita cubre importaciones, contextos y versiones donde se difiere.
        if hasattr(product_tmpl, '_create_variant_ids'):
            product_tmpl._create_variant_ids()
        product_tmpl.invalidate_recordset(['product_variant_ids'])

        Product = self.env['product.product'].with_context(active_test=False)
        for item, parts in parsed:
            expected_ids = {
                value_by_key[(name.casefold(), value.casefold())].id
                for name, value in parts
                if (name.casefold(), value.casefold()) in value_by_key
            }
            matched = Product.browse([])
            for candidate in product_tmpl.product_variant_ids.with_context(active_test=False):
                candidate_ids = set(candidate.product_template_attribute_value_ids.product_attribute_value_id.ids)
                if expected_ids and expected_ids.issubset(candidate_ids):
                    matched = candidate
                    break
            if not matched:
                _logger.warning(
                    'Sitemap import: no se encontró la variante Odoo para %s (%s).',
                    product_tmpl.display_name, item.get('variant_label'),
                )
                continue
            vals = {
                'sitemap_source_variant_id': item.get('source_variant_id') or False,
                'sitemap_variant_available': item.get('available', True),
            }
            sku = str(item.get('sku') or '').strip()
            if sku:
                vals['default_code'] = sku
            ean = str(item.get('ean') or '').strip()
            if ean:
                conflict = Product.search([('barcode', '=', ean), ('id', '!=', matched.id)], limit=1)
                if conflict:
                    _logger.warning(
                        'EAN %s no asignado a %s: ya pertenece a %s.',
                        ean, matched.display_name, conflict.display_name,
                    )
                else:
                    vals['barcode'] = ean
            vals = {key: value for key, value in vals.items() if key in Product._fields}
            try:
                with self.env.cr.savepoint():
                    matched.write(vals)
            except Exception as exc:
                _logger.exception(
                    'Sitemap import: error actualizando la variante %s de %s: %s',
                    item.get('variant_label'), product_tmpl.display_name, exc,
                )

    def _sync_product_eans(self, product_tmpl, source, variants):
        if not source.import_eans:
            return
        variants = self._normalise_ean_variants(variants)
        unique_eans = list(dict.fromkeys(item.get('ean') for item in variants if item.get('ean')))
        old_single = product_tmpl.sitemap_single_ean

        product_tmpl.sitemap_ean_ids.unlink()
        for item in variants:
            if not item.get('ean'):
                continue
            self.env['sitemap.product.ean'].create({
                'product_tmpl_id': product_tmpl.id,
                'ean': item['ean'],
                'gtin_type': item['gtin_type'],
                'sku': item.get('sku'),
                'variant_label': item.get('variant_label'),
                'source_variant_id': item.get('source_variant_id'),
                'available': item.get('available', True),
            })

        single = unique_eans[0] if len(unique_eans) == 1 else False
        product_tmpl.write({
            'sitemap_single_ean': single,
            'sitemap_ean_count': len(unique_eans),
        })

        labelled = [item for item in variants if self._variant_label_parts(item.get('variant_label'))]
        if labelled:
            self._sync_product_variants(product_tmpl, labelled)
            self._remove_duplicate_variant_informational_attributes(product_tmpl, labelled)
            return

        variants_odoo = product_tmpl.product_variant_ids
        if len(variants_odoo) != 1:
            return
        product_variant = variants_odoo[0]
        if single:
            conflict = self.env['product.product'].with_context(active_test=False).search([
                ('barcode', '=', single),
                ('id', '!=', product_variant.id),
            ], limit=1)
            if conflict:
                _logger.warning(
                    'EAN %s no asignado a %s: ya pertenece a %s.',
                    single, product_tmpl.display_name, conflict.display_name,
                )
                return
            if not product_variant.barcode or product_variant.barcode == old_single:
                product_variant.barcode = single
        elif old_single and product_variant.barcode == old_single:
            product_variant.barcode = False

    # ------------------------------------------------------------------
    # Ganchos que CADA CONECTOR debe implementar (aquí solo hay una
    # implementación de respaldo que no rompe la importación, pero deja
    # estilo/color/categoría vacíos y avisa en el log).
    # ------------------------------------------------------------------
    def get_product_entries(self, source, category_filter=None, limit=0):
        _logger.warning(
            'Sitemap import: get_product_entries no implementado por el conector de "%s"', source.name)
        return []

    def get_image_map(self, source):
        _logger.warning('Sitemap import: get_image_map no implementado por el conector de "%s"', source.name)
        return {}

    def parse_category_path(self, url):
        # Respaldo para conectores con URL plana (p. ej. Shopify). Los conectores
        # cuya categoría sí está codificada en la URL pueden sobrescribirlo.
        return []

    def fetch_preview(self, source, url):
        _logger.warning('Sitemap import: fetch_preview no implementado por el conector de "%s"', source.name)
        data = self._fetch_og_meta(source, url)
        data.update({'category_path': '', 'style_code': False, 'color_code': False})
        return data

    # ------------------------------------------------------------------
    # Categorías (genérico: resuelve contra los modelos de Odoo y los
    # mapeos manuales de la fuente; no depende de la estructura del sitio)
    # ------------------------------------------------------------------
    def _get_root_category(self, source, category_field='internal'):
        if category_field == 'internal':
            Model = self.env['product.category']
            configured_root = source.root_category_id
        else:
            Model = self.env['product.public.category']
            configured_root = source.public_root_category_id
        if configured_root:
            return configured_root
        root = Model.search([('name', '=', source.name), ('parent_id', '=', False)], limit=1)
        return root or Model.create({'name': source.name})

    def _find_category_mapping(self, category_segments, category_field, source):
        target_field = 'product_category_id' if category_field == 'internal' else 'public_category_id'
        mappings = self.env['sitemap.category.mapping'].search([
            (target_field, '!=', False),
            ('source_id', '=', source.id),
        ])
        lower_segments = [s.lower() for s in category_segments]
        best_len, best_target = 0, None
        for mapping in mappings:
            mapping_segments = [s.strip() for s in (mapping.category_path or '').split('/') if s.strip()]
            n = len(mapping_segments)
            if not n or n > len(lower_segments):
                continue
            if [s.lower() for s in mapping_segments] == lower_segments[:n] and n > best_len:
                best_len, best_target = n, mapping[target_field]
        return best_target, best_len

    @staticmethod
    def _category_token(value):
        value = html.unescape(str(value or '')).casefold()
        value = re.sub(r'[^a-z0-9]+', ' ', value)
        return re.sub(r'\s+', ' ', value).strip()

    def _sanitize_product_category_segments(self, segments, product_name=False, style_code=False, url=False):
        """Elimina hojas que en realidad son el producto o su slug.

        Muchas plataformas usan rutas como ``/products/<slug>`` y algunos
        breadcrumbs incluyen la ficha como último elemento. Ese último elemento
        no debe crear una categoría distinta para cada producto.
        """
        clean = []
        for segment in segments or []:
            text = re.sub(r'\s+', ' ', str(segment or '')).strip(' /')
            if text and (not clean or text.casefold() != clean[-1].casefold()):
                clean.append(text)
        if not clean:
            return []

        product_tokens = set()
        for candidate in (product_name, style_code):
            token = self._category_token(candidate)
            if token:
                product_tokens.add(token)
        combined = self._category_token(' '.join(filter(None, [style_code, product_name])))
        if combined:
            product_tokens.add(combined)
        if url:
            slug = unquote(urlparse(url).path.rstrip('/').rsplit('/', 1)[-1])
            slug_token = self._category_token(slug)
            if slug_token:
                product_tokens.add(slug_token)

        while clean:
            leaf = self._category_token(clean[-1])
            is_product_leaf = leaf in product_tokens
            if style_code:
                code = self._category_token(style_code)
                is_product_leaf = is_product_leaf or bool(code and code in leaf and (
                    self._category_token(product_name) in leaf or len(clean) > 1
                ))
            if not is_product_leaf:
                break
            clean.pop()
        return clean

    def _resolve_category_chain(self, category_segments, source, category_field='internal'):
        Model = self.env['product.category'] if category_field == 'internal' else self.env['product.public.category']
        mapped_target, consumed = self._find_category_mapping(category_segments, category_field, source)
        if mapped_target:
            parent, remaining = mapped_target, category_segments[consumed:]
        else:
            parent, remaining = self._get_root_category(source, category_field), category_segments
        for segment in remaining:
            existing = Model.search([('name', '=', segment), ('parent_id', '=', parent.id)], limit=1)
            parent = existing or Model.create({'name': segment, 'parent_id': parent.id})
        return parent

    # ------------------------------------------------------------------
    # Atributos técnicos informativos (genérico)
    # ------------------------------------------------------------------
    @staticmethod
    def _normalise_product_attributes(attributes):
        """Normaliza atributos como ``{nombre: [valores...]}``.

        Los conectores pueden devolver un diccionario, una lista de pares o una
        lista de objetos ``{'name': ..., 'value': ...}``. Se eliminan vacíos y
        duplicados preservando el orden.
        """
        result = {}
        if isinstance(attributes, dict):
            items = attributes.items()
        elif isinstance(attributes, list):
            items = []
            for item in attributes:
                if isinstance(item, dict):
                    items.append((item.get('name'), item.get('values') or item.get('value')))
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    items.append((item[0], item[1]))
        else:
            items = []

        for raw_name, raw_values in items:
            name = re.sub(r'\s+', ' ', str(raw_name or '')).strip(' :')
            if not name:
                continue
            values = raw_values if isinstance(raw_values, (list, tuple, set)) else [raw_values]
            clean_values = []
            for raw_value in values:
                value = re.sub(r'\s+', ' ', str(raw_value or '')).strip(' :')
                if value and value not in clean_values:
                    clean_values.append(value)
            if clean_values:
                result[name] = clean_values
        return result

    @staticmethod
    def _dimension_number(value):
        match = re.search(r'(?<!\d)(\d+(?:[.,]\d+)?)', str(value or ''))
        return float(match.group(1).replace(',', '.')) if match else 0.0

    @staticmethod
    def _dimension_unit(value, label=''):
        text = f'{label} {value}'.casefold()
        if re.search(r'\bmm\b|millimet', text):
            return 'mm'
        if re.search(r'\bcm\b|centimet', text):
            return 'cm'
        if re.search(r'(?<![a-z])m(?![a-z])|meter|metre', text):
            return 'm'
        return False

    @classmethod
    def _normalise_dimensions(cls, data):
        """Devuelve dimensiones de producto compatibles con OCA product_dimension.

        Se ignoran expresamente dimensiones de caja/embalaje. Todas las medidas se
        convierten a milímetros para poder usar una única UdM dimensional.
        """
        direct = {key: data.get(key) for key in ('product_length', 'product_height', 'product_width')}
        direct_unit = data.get('dimensional_uom_name') or data.get('dimensional_uom')
        if any(direct.values()):
            unit = str(direct_unit or 'mm').strip().casefold()
            factor = {'m': 1000.0, 'cm': 10.0, 'mm': 1.0}.get(unit, 1.0)
            return {
                key: (float(value) * factor if value not in (False, None, '') else 0.0)
                for key, value in direct.items()
            } | {'dimensional_uom_name': 'mm'}

        attrs = cls._normalise_product_attributes(data.get('attributes') or {})
        result = {'product_length': 0.0, 'product_height': 0.0, 'product_width': 0.0}
        explicit = {
            'product_length': ('longitud entre topes', 'longitud sin embalaje', 'longitud', 'länge', 'length'),
            'product_height': ('altura sin embalaje', 'altura', 'höhe', 'height'),
            'product_width': ('anchura sin embalaje', 'anchura', 'ancho', 'breite', 'width'),
        }
        def to_mm(number, unit):
            return number * {'m': 1000.0, 'cm': 10.0, 'mm': 1.0}.get(unit or 'mm', 1.0)
        for field, labels in explicit.items():
            for name, values in attrs.items():
                folded = name.casefold()
                is_without_packaging = ('sin embalaje' in folded or 'without packaging' in folded)
                if not is_without_packaging and (
                        'embalaj' in folded or 'packag' in folded or 'box' in folded):
                    continue
                if folded in labels or any(folded.startswith(label + ' ') for label in labels):
                    value = values[0] if values else ''
                    number = cls._dimension_number(value)
                    if number:
                        result[field] = to_mm(number, cls._dimension_unit(value, name))
                        break

        if not any(result.values()):
            for name, values in attrs.items():
                folded = name.casefold()
                if folded not in {'dimensiones', 'dimensiones del producto', 'dimensions', 'product size'}:
                    continue
                value = values[0] if values else ''
                numbers = [float(v.replace(',', '.')) for v in re.findall(r'\d+(?:[.,]\d+)?', str(value))]
                if len(numbers) >= 2:
                    unit = cls._dimension_unit(value, name) or 'mm'
                    result['product_length'] = to_mm(numbers[0], unit)
                    result['product_width'] = to_mm(numbers[1], unit)
                    if len(numbers) >= 3:
                        result['product_height'] = to_mm(numbers[2], unit)
                    break
        if not any(result.values()):
            return {}
        result['dimensional_uom_name'] = 'mm'
        return result

    @classmethod
    def _normalise_packaging_dimensions(cls, data):
        """Normaliza medidas de caja a mm y peso de caja a kg."""
        attrs = cls._normalise_product_attributes(data.get('attributes') or {})
        result = {}

        def to_mm(number, unit):
            return number * {'m': 1000.0, 'cm': 10.0, 'mm': 1.0}.get(unit or 'mm', 1.0)

        labels = {
            'packaging_length': ('longitud del embalaje', 'largo del embalaje', 'package length', 'packaging length', 'box length'),
            'packaging_height': ('altura del embalaje', 'package height', 'packaging height', 'box height'),
            'packaging_width': ('anchura del embalaje', 'ancho del embalaje', 'package width', 'packaging width', 'box width'),
        }
        for field, accepted in labels.items():
            for name, values in attrs.items():
                folded = name.casefold().strip()
                if 'sin embalaje' in folded or 'without packaging' in folded:
                    continue
                if folded in accepted or any(folded.startswith(label + ' ') for label in accepted):
                    value = values[0] if values else ''
                    number = cls._dimension_number(value)
                    if number:
                        result[field] = to_mm(number, cls._dimension_unit(value, name))
                        break

        if not any(result.get(k) for k in ('packaging_length', 'packaging_height', 'packaging_width')):
            accepted = {
                'dimensiones del embalaje', 'medidas del embalaje', 'package dimensions',
                'packaging dimensions', 'box dimensions', 'package size', 'packaging size',
            }
            for name, values in attrs.items():
                folded = name.casefold().strip()
                if folded not in accepted:
                    continue
                value = values[0] if values else ''
                numbers = [float(v.replace(',', '.')) for v in re.findall(r'\d+(?:[.,]\d+)?', str(value))]
                if len(numbers) >= 2:
                    unit = cls._dimension_unit(value, name) or 'mm'
                    result['packaging_length'] = to_mm(numbers[0], unit)
                    result['packaging_width'] = to_mm(numbers[1], unit)
                    if len(numbers) >= 3:
                        result['packaging_height'] = to_mm(numbers[2], unit)
                    break

        for name, values in attrs.items():
            folded = name.casefold().strip()
            if 'sin embalaje' in folded or 'without packaging' in folded:
                continue
            if folded in {'peso del embalaje', 'peso embalaje', 'package weight', 'packaging weight', 'box weight'}:
                value = values[0] if values else ''
                number = cls._dimension_number(value)
                if number:
                    text = f'{name} {value}'.casefold()
                    if re.search(r'\bmg\b', text):
                        number /= 1000000.0
                    elif re.search(r'\bg\b', text) and not re.search(r'\bkg\b', text):
                        number /= 1000.0
                    result['packaging_weight'] = number
                break

        if not any(result.values()):
            return {}
        result['packaging_dimensional_uom_name'] = 'mm'
        result['packaging_weight_uom_name'] = 'kg'
        return result

    def _weight_uom(self, name):
        Uom = self.env['uom.uom']
        for candidate in ('kg', 'Kilograms', 'Kilogram'):
            uom = Uom.search([('name', '=ilike', candidate)], limit=1)
            if uom:
                return uom
        return self.env.ref('uom.product_uom_kgm')

    def _sync_manufacturer_package_dimensions(self, product_tmpl, staging_row):
        """Update physical packaging data on the product template.

        These values describe the manufacturer's outer package and are not a
        commercial ``product.packaging`` format. Missing source values never
        erase dimensions maintained manually in Odoo.
        """
        vals = {}
        if staging_row.packaging_length:
            vals['package_length'] = staging_row.packaging_length
        if staging_row.packaging_width:
            vals['package_width'] = staging_row.packaging_width
        if staging_row.packaging_height:
            vals['package_height'] = staging_row.packaging_height
        if any((
            staging_row.packaging_length,
            staging_row.packaging_width,
            staging_row.packaging_height,
        )):
            vals['package_dimensional_uom_id'] = self._dimension_uom(
                staging_row.packaging_dimensional_uom_name or 'mm'
            ).id
        if staging_row.packaging_weight:
            vals.update({
                'package_weight': staging_row.packaging_weight,
                'package_weight_uom_id': self._weight_uom(
                    staging_row.packaging_weight_uom_name or 'kg'
                ).id,
            })
        if vals:
            product_tmpl.write(vals)

    def _dimension_uom(self, name):
        name = (name or 'mm').strip().casefold()
        aliases = {'mm': ('mm', 'Millimeters', 'Millimetres'), 'cm': ('cm', 'Centimeters', 'Centimetres'), 'm': ('m', 'Meters', 'Metres')}
        Uom = self.env['uom.uom']
        for candidate in aliases.get(name, (name,)):
            uom = Uom.search([('name', '=ilike', candidate)], limit=1)
            if uom:
                return uom
        return self.env.ref('uom.product_uom_meter')

    def _informational_attribute(self, name):
        Attribute = self.env['product.attribute']
        attribute = Attribute.search([('name', '=ilike', name)], limit=1)
        if attribute and attribute.create_variant != 'no_variant':
            safe_name = f'{name} (informativo)'
            attribute = Attribute.search([('name', '=ilike', safe_name)], limit=1)
            if not attribute:
                attribute = Attribute.create({
                    'name': safe_name,
                    'create_variant': 'no_variant',
                })
        elif not attribute:
            attribute = Attribute.create({
                'name': name,
                'create_variant': 'no_variant',
            })
        return attribute

    def _sync_product_attributes(self, product_tmpl, attributes):
        """Crea/actualiza líneas de atributo sin generar variantes.

        Solo se sustituyen los valores de atributos que el propio importador ya
        gestionaba. Si el usuario tenía previamente una línea manual con el mismo
        atributo, los valores recuperados se añaden sin borrar los existentes.
        """
        attributes = self._normalise_product_attributes(attributes)
        if not attributes:
            return
        try:
            previous = self._safe_json_loads(product_tmpl.sitemap_attributes_json, {})
            previous = self._normalise_product_attributes(previous)
        except (TypeError, ValueError, json.JSONDecodeError):
            previous = {}

        Value = self.env['product.attribute.value']
        Line = self.env['product.template.attribute.line']
        stored = {}
        for requested_name, values in attributes.items():
            attribute = self._informational_attribute(requested_name)
            value_records = Value.browse([])
            for value_name in values:
                value = Value.search([
                    ('attribute_id', '=', attribute.id),
                    ('name', '=ilike', value_name),
                ], limit=1)
                if not value:
                    value = Value.create({
                        'attribute_id': attribute.id,
                        'name': value_name,
                    })
                value_records |= value

            line = Line.search([
                ('product_tmpl_id', '=', product_tmpl.id),
                ('attribute_id', '=', attribute.id),
            ], limit=1)
            was_managed = requested_name in previous or attribute.name in previous
            if line:
                if was_managed:
                    line.write({'value_ids': [(6, 0, value_records.ids)]})
                else:
                    line.write({'value_ids': [(4, value.id) for value in value_records]})
            else:
                Line.create({
                    'product_tmpl_id': product_tmpl.id,
                    'attribute_id': attribute.id,
                    'value_ids': [(6, 0, value_records.ids)],
                })
            stored[attribute.name] = values

        product_tmpl.sitemap_attributes_json = json.dumps(
            stored, ensure_ascii=False, sort_keys=True)

    # ------------------------------------------------------------------
    # Documentos adjuntos (genérico, compatible con Community)
    # ------------------------------------------------------------------
    _DOCUMENT_EXTENSIONS = {
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.zip', '.rar', '.7z',
        '.txt', '.csv', '.stl', '.dxf', '.dwg', '.step', '.stp',
    }

    @classmethod
    def _normalise_attachments(cls, values, base_url=False):
        result = []
        seen = set()
        for item in values or []:
            if isinstance(item, str):
                item = {'url': item}
            if not isinstance(item, dict):
                continue
            url = urljoin(base_url or '', str(item.get('url') or '').strip())
            if not url or url in seen or not url.lower().startswith(('http://', 'https://')):
                continue
            seen.add(url)
            name = cls._html_to_plain_text(item.get('name') or '')
            if not name:
                name = unquote(urlparse(url).path.rsplit('/', 1)[-1]) or 'Documento'
            result.append({
                'url': url,
                'name': name[:255],
                'document_type': item.get('document_type') or cls._guess_document_type(name, url),
                'language_code': item.get('language_code') or False,
            })
        return result

    @staticmethod
    def _guess_document_type(name, url=''):
        text = f'{name} {url}'.casefold()
        if any(token in text for token in ('spare', 'ersatz', 'exploded', 'despiece', 'repuesto')):
            return 'spare_parts'
        if any(token in text for token in ('manual', 'instruction', 'anleitung', 'instruccion')):
            return 'manual'
        if any(token in text for token in ('technical', 'datasheet', 'data-sheet', 'ficha tecnica')):
            return 'technical'
        if any(token in text for token in ('certificate', 'certificat', 'certificado', 'declaration')):
            return 'certificate'
        if any(token in text for token in ('catalog', 'catalogue', 'brochure', 'prospekt', 'folleto')):
            return 'catalog'
        if any(token in text for token in ('warranty', 'garantie', 'garantia')):
            return 'warranty'
        if any(token in text for token in ('firmware', 'software', 'driver')):
            return 'software'
        return 'other'

    def _download_attachment(self, source, document):
        session = self._get_session(source)
        response = self._http_get(session, document['url'], source)
        content_type = (response.headers.get('Content-Type') or '').split(';', 1)[0].strip()
        return response.content, content_type

    def _sync_website_attachments(
        self, product_tmpl, documents, source, replace_imported=False,
    ):
        """Descarga documentos y los enlaza al producto.

        ``replace_imported`` se usa en las acciones de reparación. En ese modo
        se sustituyen solamente las relaciones con adjuntos marcados como
        importados por sitemap y se conservan todos los documentos manuales.
        Si falla alguna descarga no se eliminan adjuntos históricos, evitando
        perder documentos por un error temporal de red.
        """
        documents = self._normalise_attachments(
            documents, product_tmpl.sitemap_source_url,
        )
        Attachment = self.env['ir.attachment'].sudo()
        current_imported = product_tmpl.website_attachment_ids.filtered(
            lambda attachment: attachment.sitemap_imported
        )

        if not documents:
            if replace_imported and current_imported:
                product_tmpl.write({
                    'website_attachment_ids': [
                        (3, attachment_id, 0)
                        for attachment_id in current_imported.ids
                    ],
                })
            return Attachment.browse()

        limit = max(int(source.max_attachments_per_product or 20), 1)
        linked = Attachment.browse()
        failed_downloads = 0
        for document in documents[:limit]:
            try:
                content, content_type = self._download_attachment(source, document)
                if not content:
                    failed_downloads += 1
                    continue
                digest = hashlib.sha256(content).hexdigest()
                attachment = Attachment.search([
                    ('sitemap_imported', '=', True),
                    ('sitemap_sha256', '=', digest),
                ], limit=1)
                filename = unquote(urlparse(document['url']).path.rsplit('/', 1)[-1])
                if not filename or '.' not in filename:
                    extension = mimetypes.guess_extension(content_type or '') or ''
                    filename = f"{document['name']}{extension}"
                vals = {
                    'name': filename[:255],
                    'website_name': document['name'][:255],
                    'public': True,
                    'sitemap_source_url': document['url'],
                    'sitemap_sha256': digest,
                    'sitemap_document_type': document.get('document_type') or 'other',
                    'sitemap_imported': True,
                }
                if attachment:
                    update_vals = {
                        key: value for key, value in vals.items()
                        if attachment[key] != value
                    }
                    if update_vals:
                        attachment.write(update_vals)
                else:
                    vals.update({
                        'datas': base64.b64encode(content),
                        'mimetype': content_type or mimetypes.guess_type(filename)[0],
                    })
                    attachment = Attachment.create(vals)
                linked |= attachment
            except Exception as exc:
                failed_downloads += 1
                _logger.warning(
                    'Sitemap import: no se pudo importar el documento %s: %s',
                    document.get('url'), exc,
                )

        commands = [
            (4, attachment_id, 0)
            for attachment_id in linked.ids
            if attachment_id not in product_tmpl.website_attachment_ids.ids
        ]
        # Solo se eliminan relaciones obsoletas cuando todas las descargas de
        # la ficha han terminado correctamente. Así un fallo temporal no borra
        # documentos válidos que ya estaban asociados al producto.
        if replace_imported and not failed_downloads:
            stale = current_imported - linked
            commands.extend((3, attachment_id, 0) for attachment_id in stale.ids)
        if commands:
            product_tmpl.write({'website_attachment_ids': commands})
        return linked

    # ------------------------------------------------------------------
    # Imágenes (genérico)
    # ------------------------------------------------------------------
    def _download_image(self, source, image_url):
        session = self._get_session(source)
        response = self._http_get(session, image_url, source)
        return response.content

    def _merge_import_image_urls(self, discovered_urls, extracted_urls):
        """Combina imágenes del sitemap y de la ficha manteniendo el orden.

        Los conectores pueden especializar este método cuando la galería de la
        ficha sea una fuente más fiable que el sitemap de imágenes.
        """
        merged = []
        for image_url in list(discovered_urls or []) + list(extracted_urls or []):
            if image_url and image_url not in merged:
                merged.append(image_url)
        return merged

    def _import_images(self, product_tmpl, data, image_urls, source):
        urls = list(image_urls) if image_urls else []
        main_url = data.get('main_image_url')
        if main_url and main_url not in urls:
            urls.insert(0, main_url)
        if not urls:
            return
        urls = urls[:max(source.max_images_per_product, 1)]

        try:
            main_bytes = self._download_image(source, urls[0])
            product_tmpl.image_1920 = base64.b64encode(main_bytes)
        except Exception as exc:
            _logger.warning('Sitemap import: no se pudo descargar la imagen principal %s: %s', urls[0], exc)

        Image = self.env['product.image']
        old_images = Image.search([
            ('product_tmpl_id', '=', product_tmpl.id),
            '|',
            ('is_sitemap_import_image', '=', True),
            ('name', 'like', IMAGE_MARKER),
        ])
        old_images.unlink()

        for index, extra_url in enumerate(urls[1:], start=1):
            try:
                img_bytes = self._download_image(source, extra_url)
                Image.create({
                    'product_tmpl_id': product_tmpl.id,
                    # Se crean todos los medios, pero sin mostrar el marcador
                    # técnico ``[Sitemap Import]`` en el comercio electrónico.
                    'name': f'{product_tmpl.name} ({index})',
                    'image_1920': base64.b64encode(img_bytes),
                    'is_sitemap_import_image': True,
                    'sitemap_source_url': extra_url,
                })
            except Exception as exc:
                _logger.warning('Sitemap import: no se pudo descargar la imagen %s: %s', extra_url, exc)

    # ------------------------------------------------------------------
    # Orquestación (genérica: solo llama a los ganchos de arriba, así que
    # sirve igual para cualquier conector sin cambios)
    # ------------------------------------------------------------------
    def refresh_staging_row(self, staging_row, source, image_map=None, force=False):
        """Obtiene los datos LIGEROS de vista previa (nunca imágenes) para una fila de
        staging, usando el conector de 'source'.
        - Si la URL ya corresponde a un producto de Odoo (aprobada e importada antes -en OTRO
          lote, o en este mismo-), se aplica la actualización completa de inmediato -incluidas
          imágenes, vía import_staging_row- porque esa decisión ya se tomó.
        - Si no, se guardan solo los datos de vista previa (estado 'preview_ready') a la espera
          de selección manual."""
        if not staging_row.product_tmpl_id:
            linked = self.env['product.template'].search([('sitemap_source_url', '=', staging_row.url)], limit=1)
            if linked:
                staging_row.product_tmpl_id = linked.id

        if not force and staging_row.product_tmpl_id and staging_row.product_tmpl_id.sitemap_lastmod \
                and staging_row.sitemap_lastmod \
                and staging_row.product_tmpl_id.sitemap_lastmod >= staging_row.sitemap_lastmod:
            staging_row.write({'state': 'skipped', 'preview_date': fields.Datetime.now()})
            return True

        staging_row.write({
            'preview_attempt_count': staging_row.preview_attempt_count + 1,
            'last_attempt_date': fields.Datetime.now(),
        })
        try:
            data = self.fetch_preview(source, staging_row.url)
            data = self._normalise_extracted_charset(data)
            data = self.enrich_preview_eans(source, staging_row.url, data)
            data = self._normalise_extracted_charset(data)
            extracted_name = str((data or {}).get('name') or '').strip()
            normalized_name = extracted_name.rstrip('/').casefold()
            normalized_url = staging_row.url.strip().rstrip('/').casefold()
            if not extracted_name or normalized_name == normalized_url or normalized_name.startswith(('http://', 'https://')):
                raise ValueError(
                    'La ficha no devolvió un nombre de producto válido; se cancela la importación '
                    'para evitar crear un producto cuyo nombre sea únicamente la URL.'
                )
        except Exception as exc:
            connector_name = source.connector_model or self._name
            response = getattr(exc, 'response', None)
            status_code = getattr(response, 'status_code', None)
            diagnostic = '%s: %s' % (exc.__class__.__name__, exc)
            if status_code:
                diagnostic = 'HTTP %s | %s' % (status_code, diagnostic)
            diagnostic = '[%s] %s' % (connector_name, diagnostic)
            _logger.exception(
                'Sitemap import: error aislado obteniendo vista previa de %s con %s',
                staging_row.url, connector_name,
            )
            staging_row.write({
                'state': 'error',
                'error_message': diagnostic[:4000],
                'preview_date': fields.Datetime.now(),
            })
            return False

        dimensions = self._normalise_dimensions(data)
        packaging_dimensions = self._normalise_packaging_dimensions(data)
        staging_row.write({
            'name': data['name'],
            'list_price': data['price'],
            'price_available': data.get('price_available', True),
            'currency_name': data['currency'],
            'category_path': data.get('category_path') or '',
            'shopify_blog_articles_json': json.dumps(
                data.get('shopify_blog_articles') or [], ensure_ascii=False
            ),
            'style_code': data.get('style_code') or False,
            'color_code': data.get('color_code') or False,
            'description_preview': data.get('full_description') or data.get('description') or '',
            'short_description_preview': data.get('short_description') or data.get('description') or '',
            'full_description_preview': data.get('full_description') or data.get('description') or '',
            'product_length': dimensions.get('product_length', 0.0),
            'product_height': dimensions.get('product_height', 0.0),
            'product_width': dimensions.get('product_width', 0.0),
            'dimensional_uom_name': dimensions.get('dimensional_uom_name') or False,
            'packaging_length': packaging_dimensions.get('packaging_length', 0.0),
            'packaging_height': packaging_dimensions.get('packaging_height', 0.0),
            'packaging_width': packaging_dimensions.get('packaging_width', 0.0),
            'packaging_weight': packaging_dimensions.get('packaging_weight', 0.0),
            'packaging_dimensional_uom_name': packaging_dimensions.get('packaging_dimensional_uom_name') or False,
            'packaging_weight_uom_name': packaging_dimensions.get('packaging_weight_uom_name') or False,
            'attributes_json': (
                json.dumps(
                    self._normalise_product_attributes(data.get('attributes') or {}),
                    ensure_ascii=False, indent=2,
                ) if self._normalise_product_attributes(data.get('attributes') or {}) else False
            ),
            'main_image_url': data['main_image_url'] or False,
            'image_urls_json': json.dumps(data.get('image_urls') or [], ensure_ascii=False),
            'attachment_urls_json': json.dumps(
                self._normalise_attachments(data.get('attachments') or [], staging_row.url),
                ensure_ascii=False,
            ),
            'attachment_count': len(self._normalise_attachments(
                data.get('attachments') or [], staging_row.url)),
            'ean': data.get('ean') or False,
            'ean_count': data.get('ean_count', 0),
            'ean_checked': data.get('ean_checked', False),
            'ean_variants_json': json.dumps(
                data.get('ean_variants') or [], ensure_ascii=False, indent=2),
            'preview_date': fields.Datetime.now(),
            'error_message': False,
        })

        if staging_row.product_tmpl_id:
            self.import_staging_row(staging_row, source, (image_map or {}).get(staging_row.url, []))
        else:
            staging_row.write({'state': 'preview_ready'})
        return staging_row.state in ('preview_ready', 'imported', 'updated', 'skipped')

    def _import_staging_row_inner(self, staging_row, source, image_urls):
        """Crea o actualiza el product.template a partir de los datos YA guardados en la fila
        de staging -no vuelve a descargar la ficha-. Es genérico: por este punto, todo lo que
        necesita ya es un simple diccionario de datos, sin decisiones específicas del sitio.
        Devuelve 'created', 'updated' o 'error'."""
        Product = self.env['product.template']

        # La URL de origen es la identidad funcional del producto importado.
        # Debe tener prioridad sobre un product_tmpl_id antiguo o incorrecto de
        # la fila de staging. De lo contrario, al escribir la URL sobre ese
        # producto enlazado se produce una UniqueViolation si otro producto ya
        # es el propietario legítimo de la URL.
        url_owner = Product.search(
            [('sitemap_source_url', '=', staging_row.url)], limit=1)
        linked_product = staging_row.product_tmpl_id
        if url_owner:
            existing = url_owner
            if linked_product != url_owner:
                staging_row.product_tmpl_id = url_owner.id
        elif linked_product and (
            not linked_product.sitemap_source_url
            or linked_product.sitemap_source_url == staging_row.url
        ):
            existing = linked_product
        else:
            # No se reutiliza un producto enlazado que pertenece a otra URL.
            # Se crea uno nuevo para no secuestrar ni corromper otra ficha.
            existing = Product.browse()

        try:
            raw_segments = staging_row.category_path.split('/') if staging_row.category_path else []
            segments = self._sanitize_product_category_segments(
                raw_segments,
                product_name=staging_row.name,
                style_code=staging_row.style_code,
                url=staging_row.url,
            )
            category = self._resolve_category_chain(segments, source, 'internal')

            full_description = (
                staging_row.full_description_preview
                or staging_row.description_preview
                or ''
            )
            short_description = (
                staging_row.short_description_preview
                or self._html_to_plain_text(staging_row.description_preview)
                or self._html_to_plain_text(full_description)
                or ''
            )
            valid_name = str(staging_row.name or '').strip()
            if not valid_name or valid_name.rstrip('/').casefold() == staging_row.url.rstrip('/').casefold() \
                    or valid_name.casefold().startswith(('http://', 'https://')):
                raise ValueError(
                    'No se puede importar el producto porque el nombre extraído está vacío o es una URL.'
                )

            vals = {
                'name': valid_name,
                'categ_id': category.id,
                'sitemap_source_id': source.id,
                'sitemap_source_url': staging_row.url,
                'sitemap_style_code': staging_row.style_code,
                'sitemap_color_code': staging_row.color_code,
                'sitemap_lastmod': staging_row.sitemap_lastmod,
                'sitemap_last_sync': fields.Datetime.now(),
                'is_sitemap_import_product': True,
                'sale_ok': source.sale_ok,
                'purchase_ok': source.purchase_ok,
                'active': True,
            }
            if source.brand_id and 'brand_id' in Product._fields:
                vals['brand_id'] = source.brand_id.id

            # En el grupo Märklin el número de artículo es también la referencia
            # interna comercial. Se aplica tanto al crear como al actualizar el
            # producto desde staging.
            if source.connector_model in MAERKLIN_ARTICLE_CONNECTORS:
                article_reference = str(staging_row.style_code or '').strip()
                if article_reference:
                    vals['default_code'] = article_reference

            # La descripción recuperada es contenido para e-commerce. Se prioriza
            # el HTML ampliado del registro importado y se guarda únicamente en
            # ``public_description``. Los campos de venta y los campos web
            # alternativos se vacían para no crear textos en presupuestos ni un
            # segundo bloque sin márgenes en la página del producto.
            imported_description = (
                staging_row.full_description_preview
                or staging_row.description_preview
                or staging_row.short_description_preview
                or ''
            )
            vals.update(Product._sitemap_description_cleanup_vals(imported_description))

            if staging_row.dimensional_uom_name and (
                    staging_row.product_length or staging_row.product_height or staging_row.product_width):
                vals.update({
                    'product_length': staging_row.product_length,
                    'product_height': staging_row.product_height,
                    'product_width': staging_row.product_width,
                    'dimensional_uom_id': self._dimension_uom(staging_row.dimensional_uom_name).id,
                })

            # Algunas fuentes son catálogos sin precio público. En una creación
            # se mantiene 0,00, pero una sincronización posterior no debe borrar
            # un precio introducido manualmente o calculado mediante tarifas.
            if not existing or staging_row.price_available:
                vals['list_price'] = staging_row.list_price
            if source.product_tag_ids:
                vals['product_tag_ids'] = [(6, 0, source.product_tag_ids.ids)]

            if source.import_public_categories:
                public_category = self._resolve_category_chain(segments, source, 'public')
                previous_public = existing.sitemap_public_categ_id if existing else False
                commands = [(4, public_category.id, 0)]
                if previous_public and previous_public.id != public_category.id:
                    commands.insert(0, (3, previous_public.id, 0))
                vals['public_categ_ids'] = commands
                vals['sitemap_public_categ_id'] = public_category.id

                # Shopify Collections representan agrupaciones navegables y un
                # producto puede pertenecer a varias. Se sincronizan aparte de
                # la categoría principal para no eliminar categorías manuales.
                resolver = getattr(self, 'resolve_product_collection_categories', None)
                if resolver and 'sitemap_collection_categ_ids' in Product._fields:
                    raw_collections = self._safe_json_loads(
                        staging_row.shopify_collections_json, []
                    )
                    if not isinstance(raw_collections, list):
                        raw_collections = []
                    collection_categories = resolver(source, raw_collections)
                    previous_collections = (
                        existing.sitemap_collection_categ_ids
                        if existing else self.env['product.public.category']
                    )
                    collection_commands = [
                        (3, category.id, 0)
                        for category in previous_collections - collection_categories
                    ] + [
                        (4, category.id, 0)
                        for category in collection_categories - previous_collections
                    ]
                    vals['public_categ_ids'] += collection_commands
                    vals['sitemap_collection_categ_ids'] = [
                        (6, 0, collection_categories.ids)
                    ]

            # Defensa adicional frente a dependencias opcionales o campos
            # renombrados: nunca enviar al ORM claves que no existan en el modelo
            # product.template de la instalación actual.
            unknown_fields = sorted(set(vals) - set(Product._fields))
            if unknown_fields:
                _logger.warning(
                    'Sitemap import: se omiten campos no disponibles en product.template: %s',
                    ', '.join(unknown_fields),
                )
                vals = {key: value for key, value in vals.items() if key in Product._fields}

            # La creación/actualización queda dentro de un savepoint. Si una
            # columna o restricción SQL falla, PostgreSQL revierte esta operación
            # antes de que el bloque exterior intente registrar el error.
            if existing:
                with self.env.cr.savepoint():
                    existing.write(vals)
                product_tmpl = existing
                result = 'updated'
            else:
                try:
                    with self.env.cr.savepoint():
                        product_tmpl = Product.create(vals)
                    result = 'created'
                except pg_errors.UniqueViolation:
                    # Otro trabajo pudo crear la misma URL entre el search y el
                    # create. El savepoint ya ha limpiado la transacción; se
                    # recupera el registro ganador y se actualiza en vez de
                    # convertir la condición de carrera en un error funcional.
                    product_tmpl = Product.search(
                        [('sitemap_source_url', '=', staging_row.url)], limit=1,
                    )
                    if not product_tmpl:
                        raise
                    with self.env.cr.savepoint():
                        product_tmpl.write(vals)
                    result = 'updated'

            staged_eans = []
            if staging_row.ean_variants_json:
                try:
                    loaded_eans = self._safe_json_loads(staging_row.ean_variants_json, [])
                    if isinstance(loaded_eans, list):
                        staged_eans = loaded_eans
                except (TypeError, ValueError, json.JSONDecodeError):
                    _logger.warning(
                        'Sitemap import: JSON de EAN inválido para la fila %s',
                        staging_row.id,
                    )
            if staging_row.ean_checked:
                self._sync_product_eans(product_tmpl, source, staged_eans)

            self._sync_manufacturer_package_dimensions(product_tmpl, staging_row)

            staged_attributes = {}
            if staging_row.attributes_json:
                try:
                    loaded_attributes = self._safe_json_loads(staging_row.attributes_json, {})
                    staged_attributes = self._normalise_product_attributes(loaded_attributes)
                except (TypeError, ValueError, json.JSONDecodeError):
                    _logger.warning(
                        'Sitemap import: JSON de atributos inválido para la fila %s',
                        staging_row.id,
                    )
            if staged_attributes:
                variant_names = self._variant_attribute_names(staged_eans)
                if variant_names:
                    staged_attributes = {
                        name: values for name, values in staged_attributes.items()
                        if name.strip().casefold() not in variant_names
                    }
                self._remove_duplicate_variant_informational_attributes(
                    product_tmpl, staged_eans,
                )
                if staged_attributes:
                    self._sync_product_attributes(product_tmpl, staged_attributes)

            if source.import_images:
                staged_image_urls = []
                if staging_row.image_urls_json:
                    try:
                        loaded_urls = self._safe_json_loads(staging_row.image_urls_json, [])
                        if isinstance(loaded_urls, list):
                            staged_image_urls = loaded_urls
                    except (TypeError, ValueError):
                        _logger.warning(
                            'Sitemap import: JSON de imagenes invalido para la fila %s',
                            staging_row.id,
                        )
                merged_image_urls = self._merge_import_image_urls(
                    image_urls, staged_image_urls,
                )
                image_data = {'main_image_url': staging_row.main_image_url}
                self._import_images(product_tmpl, image_data, merged_image_urls, source)

            if staging_row.shopify_blog_articles_json and hasattr(product_tmpl, '_sitemap_sync_blog_articles'):
                try:
                    blog_articles = self._safe_json_loads(staging_row.shopify_blog_articles_json, [])
                except (TypeError, ValueError, json.JSONDecodeError):
                    blog_articles = []
                if blog_articles:
                    product_tmpl._sitemap_sync_blog_articles(
                        self, source, blog_articles, imported_description
                    )

            if source.import_attachments and staging_row.attachment_urls_json:
                try:
                    documents = self._safe_json_loads(staging_row.attachment_urls_json, [])
                except (TypeError, ValueError, json.JSONDecodeError):
                    documents = []
                    _logger.warning(
                        'Sitemap import: JSON de documentos inválido para la fila %s',
                        staging_row.id,
                    )
                self._sync_website_attachments(product_tmpl, documents, source)

            staging_row.write({
                'state': 'imported',
                'result': result,
                'product_tmpl_id': product_tmpl.id,
                'imported_date': fields.Datetime.now(),
                'error_message': False,
            })
            return result
        except Exception:
            raise

    def import_staging_row(self, staging_row, source, image_urls):
        """Importa una fila dentro de un savepoint integral."""
        try:
            with self.env.cr.savepoint():
                return self._import_staging_row_inner(staging_row, source, image_urls)
        except Exception as exc:
            _logger.exception('Sitemap import: error aislado importando %s', staging_row.url)
            trace_lines = traceback.format_exc().strip().splitlines()
            trace_tail = ' | '.join(trace_lines[-6:])
            diagnostic = '%s: %s' % (exc.__class__.__name__, exc)
            if trace_tail:
                diagnostic = '%s | %s' % (diagnostic, trace_tail)
            staging_row.write({
                'state': 'error',
                'error_message': diagnostic[:4000],
            })
            return 'error'
