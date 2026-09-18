import html
import logging
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorAraolitEs(models.AbstractModel):
    """Conector para Araolit España (PrestaShop).

    La fuente puede configurarse con ``https://www.araolit.es/robots.txt`` o
    con ``https://www.araolit.es/1_index_sitemap.xml``. ``/sitemap.xml`` no
    existe (404). El conector lee las directivas Sitemap de robots.txt y
    mantiene nombres habituales de Google Sitemap/PrestaShop como respaldo.
    Si el XML no está disponible, descubre fichas desde el mapa del sitio,
    marcas y categorías.

    Delante de PrestaShop hay un WAF que, a clientes sin cookie, responde
    HTTP 202 con una página HTML de espera. Esa página no envía ``Set-Cookie``:
    inyecta ``document.cookie = 'dhd2=...; domain=araolit.es'`` por JavaScript.
    Sin completar ese handshake el importador interpreta el interstitial como
    sitemap y aborta.

    Las categorías de Araolit usan URLs del tipo ``/13-anodos-magnesio`` y las
    fichas de producto PrestaShop terminan en ``.html``; esa diferencia permite
    evitar que una categoría entre por error como producto.
    """

    _name = 'sitemap.connector.araolit_es'
    _inherit = 'sitemap.connector.bicicletasquer_es'
    _description = 'Conector Araolit España'

    _HOSTS = {'araolit.es', 'www.araolit.es'}
    # Araolit usa rutas PrestaShop con uno o varios segmentos de categoria
    # antes del id del producto. No asumimos una profundidad fija.
    _PRODUCT_PATH_RE = re.compile(
        r'^/(?:[^/?#]+/)*(?P<product_id>\d+)(?:-\d+)?-(?P<slug>[^/?#]+)\.html/?$',
        re.IGNORECASE,
    )
    _PRODUCT_PATH_FALLBACK_RE = re.compile(
        r'^/(?:[^/?#]+/)+(?P<product_id>\d+)(?:-\d+)?-(?P<slug>[^/?#]+?)(?:\.html)?/?$',
        re.IGNORECASE,
    )
    _NON_PRODUCT_PREFIXES = (
        '/brand/', '/brands', '/content/', '/module/', '/search', '/stores',
        '/contact', '/login', '/cart', '/order', '/my-account', '/new-products',
        '/best-sales', '/prices-drop', '/mapa-del-sitio', '/sitemap',
    )
    # Las categorías son ``/13-anodos-magnesio`` (sin .html). Si el patrón
    # aceptara ``.html`` también coincidiría con las fichas
    # ``/1-kit-termostato....html`` y el conector las descartaría todas.
    _CATEGORY_PATH_RE = re.compile(
        r'^/(?P<category_id>\d+)-(?P<slug>[^/?#]+?)(?<!\.html)/?$',
        re.IGNORECASE,
    )
    _WAF_COOKIE_RE = re.compile(
        r"document\.cookie\s*=\s*['\"](?P<cookie>[^'\"]+)['\"]",
        re.IGNORECASE,
    )
    _WAF_COOKIE_NAME = 'dhd2'


    def _get_session(self, source):
        """Sesión Araolit con cabeceras de navegador y preferencia XML.

        Araolit responde de forma distinta a clientes identificados como bot en
        sus endpoints ``*.xml``. El importador genérico usa un User-Agent propio
        y el conector PrestaShop heredado prioriza HTML; ambas cosas pueden hacer
        que el servidor entregue una página HTML en lugar del sitemap.
        """
        session = super()._get_session(source)
        configured_ua = (getattr(source, 'user_agent', False) or '').strip()
        if not configured_ua or 'OdooSitemapImporter' in configured_ua:
            session.headers['User-Agent'] = (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/153.0.0.0 Safari/537.36'
            )
        session.headers.update({
            'Accept': (
                'application/xml,text/xml;q=0.9,application/xhtml+xml;q=0.8,'
                'text/html;q=0.7,*/*;q=0.5'
            ),
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.3',
        })
        return session

    @classmethod
    def _waf_challenge_cookie(cls, response):
        """Extrae la cookie JS del interstitial 202 del WAF de Araolit."""
        if response is None:
            return False
        body = response.content or b''
        if cls._WAF_COOKIE_NAME.encode('ascii') not in body and b'document.cookie' not in body:
            return False
        try:
            snippet = body[:8192].decode(response.encoding or 'utf-8', errors='replace')
        except Exception:
            snippet = ''
        match = cls._WAF_COOKIE_RE.search(snippet)
        if not match:
            return False
        name = value = domain = path = None
        for part in match.group('cookie').split(';'):
            item = part.strip()
            if not item or '=' not in item:
                continue
            key, raw = item.split('=', 1)
            key = key.strip()
            raw = raw.strip()
            lowered = key.lower()
            if lowered == 'domain':
                domain = raw.lstrip('.')
            elif lowered == 'path':
                path = raw or '/'
            elif lowered in {'max-age', 'expires', 'samesite', 'secure', 'httponly'}:
                continue
            elif name is None:
                name, value = key, raw
        if not name or value is None:
            return False
        return {
            'name': name,
            'value': value,
            'domain': domain or 'araolit.es',
            'path': path or '/',
        }

    @classmethod
    def _is_waf_challenge(cls, response):
        """Detecta el HTML de espera del WAF (HTTP 202 + cookie JS)."""
        cookie = cls._waf_challenge_cookie(response)
        if not cookie:
            return False
        content_type = (response.headers.get('Content-Type') or '').lower()
        body = response.content or b''
        if response.status_code == 202:
            return True
        if 'html' in content_type and (
            b'http-equiv' in body and b'refresh' in body
        ):
            return True
        return False

    @classmethod
    def _apply_waf_cookie(cls, session, cookie):
        if not cookie:
            return
        for domain in dict.fromkeys((cookie['domain'], 'araolit.es', 'www.araolit.es')):
            if not domain:
                continue
            session.cookies.set(
                cookie['name'], cookie['value'],
                domain=domain, path=cookie['path'],
            )
        _logger.info(
            'Araolit: cookie WAF %s aplicada para el dominio %s',
            cookie['name'], cookie['domain'],
        )

    def _http_get(self, session, url, source):
        """GET que resuelve el desafío JS ``dhd2`` antes de parsear la respuesta.

        ``requests`` no ejecuta JavaScript y el WAF no envía ``Set-Cookie``, así
        que hay que leer el interstitial, guardar la cookie en la sesión y
        repetir la petición. Sin este paso tanto el sitemap como el catálogo
        HTML llegan como la página de puntos suspensivos.
        """
        response = super()._http_get(session, url, source)
        if not self._is_waf_challenge(response):
            return response

        self._apply_waf_cookie(session, self._waf_challenge_cookie(response))
        last_response = response
        for attempt in range(2):
            last_response = super()._http_get(session, url, source)
            if not self._is_waf_challenge(last_response):
                return last_response
            self._apply_waf_cookie(session, self._waf_challenge_cookie(last_response))
        return last_response

    @staticmethod
    def _araolit_xml_root(content):
        """Parsea el sitemap incluso si el servidor antepone HTML/basura.

        En producción se ha observado que el endpoint puede devolver contenido
        que empieza como HTML aunque el navegador termine mostrando el sitemap.
        Primero intentamos XML estricto y después recortamos hasta el comienzo
        real de ``<urlset>``/``<sitemapindex>``. También contemplamos XML
        escapado dentro de HTML.
        """
        raw = content or b''
        if raw[:2] == b'\x1f\x8b':
            import gzip
            raw = gzip.decompress(raw)

        parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
        try:
            return etree.fromstring(raw, parser=parser)
        except etree.XMLSyntaxError as first_exc:
            candidates = [raw]
            try:
                decoded = raw.decode('utf-8', errors='replace')
                unescaped = html.unescape(decoded).encode('utf-8')
                if unescaped != raw:
                    candidates.append(unescaped)
            except Exception:
                pass

            markers = (b'<?xml', b'<urlset', b'<sitemapindex')
            for candidate in candidates:
                starts = [candidate.find(marker) for marker in markers]
                starts = [pos for pos in starts if pos >= 0]
                if not starts:
                    continue
                trimmed = candidate[min(starts):]
                # Si hay contenido HTML después del cierre XML, cortar ahí.
                for closing in (b'</urlset>', b'</sitemapindex>'):
                    end = trimmed.find(closing)
                    if end >= 0:
                        trimmed = trimmed[:end + len(closing)]
                        break
                try:
                    return etree.fromstring(trimmed, parser=parser)
                except etree.XMLSyntaxError:
                    continue
            raise first_exc

    def _iter_sitemap_entries(self, source, sitemap_url, depth=0, visited=None):
        """Iterador específico para los sitemaps de Araolit.

        Sigue las redirecciones (``sitemap.xml`` -> ``1_es_0_sitemap.xml``) y
        conserva como clave visitada la URL final para evitar bucles.
        """
        if depth > 8:
            raise ValueError('El sitemap de Araolit supera ocho niveles de índices.')
        visited = visited or set()
        requested_url = (sitemap_url or '').strip()
        if not requested_url or requested_url in visited:
            return
        visited.add(requested_url)

        session = self._get_session(source)
        response = self._http_get(session, requested_url, source)
        final_url = response.url or requested_url
        if final_url in visited and final_url != requested_url:
            return
        visited.add(final_url)

        try:
            root = self._araolit_xml_root(response.content)
        except etree.XMLSyntaxError as exc:
            # Algunos proxies/WAF entregan el sitemap ya transformado a HTML.
            # En ese caso las entradas siguen siendo enlaces visibles en la
            # página; extraerlos permite trabajar con la misma representación
            # que ve un navegador sin asumir que el XML bruto está disponible.
            try:
                tree = lxml_html.fromstring(response.content)
            except Exception:
                raise exc

            # Si el WAF sustituye el XML por una página PrestaShop, aprovechar
            # directamente sus tarjetas de producto en lugar de abortar.
            card_entries = self._product_card_entries_from_tree(tree, final_url)
            if card_entries:
                for item in card_entries:
                    yield {
                        'url': item['url'],
                        'lastmod': False,
                        'images': [],
                    }
                return

            discovered = []
            for value in tree.xpath('//a[@href]/@href | //a/text()'):
                candidate = self._canonical_url(urljoin(final_url, str(value).strip()))
                if not candidate or candidate in discovered:
                    continue
                parsed = urlparse(candidate)
                if parsed.netloc.lower() not in self._HOSTS:
                    continue
                discovered.append(candidate)

            yielded = False
            for candidate in discovered:
                if self._product_match(candidate):
                    yielded = True
                    yield {'url': candidate, 'lastmod': False, 'images': []}
                elif candidate.lower().endswith('.xml'):
                    yielded = True
                    yield from self._iter_sitemap_entries(
                        source, candidate, depth=depth + 1, visited=visited,
                    )
            if yielded:
                return
            content_type = response.headers.get('Content-Type', '')
            raise ValueError(
                'Araolit devolvió HTML en lugar de XML y no se encontraron '
                'enlaces de producto/sitemap en la representación HTML. '
                f'URL final: {final_url}; Content-Type: {content_type or "desconocido"}. '
                f'Error XML original: {exc}'
            ) from exc

        root_name = etree.QName(root).localname.lower()

        if root_name == 'sitemapindex':
            for child in root.xpath('./*[local-name()="sitemap"]'):
                locs = child.xpath('./*[local-name()="loc"]/text()')
                if not locs or not locs[0].strip():
                    continue
                yield from self._iter_sitemap_entries(
                    source,
                    urljoin(final_url, locs[0].strip()),
                    depth=depth + 1,
                    visited=visited,
                )
            return

        if root_name != 'urlset':
            raise ValueError(
                'El recurso de Araolit no contiene <urlset> ni <sitemapindex> '
                f'(raíz recibida: <{root_name}>).'
            )

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
    def _canonical_url(cls, value):
        parts = urlsplit(html.unescape(str(value or '')).strip())
        host = parts.netloc.lower()
        if host == 'www.araolit.es':
            host = 'araolit.es'
        path = re.sub(r'/+', '/', parts.path)
        return urlunsplit((parts.scheme or 'https', host, path.rstrip('/'), '', ''))

    @classmethod
    def _product_match(cls, value):
        """Reconoce fichas Araolit sin depender de una única forma de URL.

        El patrón clásico PrestaShop termina en ``.html``. Algunas plantillas
        generan rutas localizadas o sin extensión; para esas aceptamos un
        segundo patrón únicamente cuando existe al menos un segmento padre,
        evitando así confundir categorías raíz como ``/88-contacto``.
        """
        parsed = urlparse(value)
        if parsed.netloc.lower() not in cls._HOSTS:
            return False
        path = parsed.path or '/'
        lowered = path.lower()
        if any(lowered.startswith(prefix) for prefix in cls._NON_PRODUCT_PREFIXES):
            return False
        product = cls._PRODUCT_PATH_RE.match(path)
        if product:
            return product
        if cls._CATEGORY_PATH_RE.match(path):
            return False
        return cls._PRODUCT_PATH_FALLBACK_RE.match(path)

    @classmethod
    def _product_key(cls, value):
        match = cls._product_match(value)
        return match.group('product_id') if match else False

    @classmethod
    def _safe_internal_href(cls, href, page_url):
        absolute = cls._canonical_url(urljoin(page_url, href))
        parsed = urlparse(absolute)
        if parsed.netloc.lower() not in cls._HOSTS:
            return False
        lowered = (parsed.path or '/').lower()
        if any(lowered.startswith(prefix) for prefix in cls._NON_PRODUCT_PREFIXES):
            return False
        if cls._CATEGORY_PATH_RE.match(parsed.path):
            return False
        return absolute

    @classmethod
    def _product_card_entries_from_tree(cls, tree, page_url):
        """Obtiene fichas desde miniaturas usando ``data-id-product`` como verdad.

        Esta rutina no exige que el href cumpla un patrón concreto. Araolit es
        PrestaShop y ``data-id-product`` es un identificador mucho más estable
        que la reescritura SEO de la URL.
        """
        result = []
        seen_ids = set()
        cards = tree.xpath('//*[@data-id-product]')
        for card in cards:
            product_id = str(card.get('data-id-product') or '').strip()
            if not product_id.isdigit() or product_id in seen_ids:
                continue
            hrefs = card.xpath(
                './/a[contains(concat(" ", normalize-space(@class), " "), " product-thumbnail ")]/@href | '
                './/*[contains(concat(" ", normalize-space(@class), " "), " product-title ")]//a[@href]/@href | '
                './/a[@href]/@href'
            )
            selected = False
            for href in hrefs:
                absolute = cls._safe_internal_href(href, page_url)
                if not absolute:
                    continue
                # En tarjetas PrestaShop el primer enlace interno no-listado suele
                # ser la ficha. Preferir de todos modos URLs que reconozcamos.
                if cls._product_match(absolute):
                    selected = absolute
                    break
                if not selected:
                    selected = absolute
            if selected:
                seen_ids.add(product_id)
                result.append({
                    'url': selected, 'lastmod': False, 'prestashop_id': product_id,
                })
        return result

    @classmethod
    def _product_links_from_tree(cls, tree, page_url):
        # Compatibilidad con llamadas antiguas del conector.
        return [item['url'] for item in cls._product_card_entries_from_tree(tree, page_url)]

    def _candidate_sitemaps(self, source):
        root = 'https://www.araolit.es/'
        candidates = []
        session = self._get_session(source)
        probes = [
            source.sitemap_index_url,
            urljoin(root, 'robots.txt'),
            urljoin(root, '1_index_sitemap.xml'),
        ]
        for candidate in probes:
            if not candidate or candidate in candidates:
                continue
            try:
                response = self._http_get(session, candidate, source)
                if response.status_code >= 400:
                    continue
                candidates.extend(self._robots_sitemaps(response.text, response.url))
                content = response.content.lstrip()
                if (
                    content.startswith(b'<?xml')
                    or content.startswith(b'<urlset')
                    or content.startswith(b'<sitemapindex')
                    or content[:2] == b'\x1f\x8b'
                ):
                    candidates.insert(0, response.url)
            except Exception as exc:
                _logger.info('Araolit: índice %s no accesible: %s', candidate, exc)

        # ``sitemap.xml`` y ``sitemap_index.xml`` no existen en Araolit (404 HTML).
        # El índice real publicado en robots.txt es ``1_index_sitemap.xml``.
        candidates.extend([
            urljoin(root, '1_index_sitemap.xml'),
            urljoin(root, '1_es_0_sitemap.xml'),
            urljoin(root, '1_es_1_sitemap.xml'),
            urljoin(root, 'sitemap.xml'),
            urljoin(root, 'sitemap_index.xml'),
        ])
        return list(dict.fromkeys(candidates))

    def _fallback_html_entries(self, source, category_filter=None, limit=0):
        """Descubre productos desde listados PrestaShop sin asumir su URL SEO."""
        session = self._get_session(source)
        start_urls = [
            'https://www.araolit.es/brands',
            'https://www.araolit.es/',
            'https://www.araolit.es/mapa-del-sitio',
            'https://www.araolit.es/nuevos-productos',
        ]
        products = {}
        listings = []
        queued = set()

        def add_listing(url):
            absolute = self._canonical_url(url)
            if absolute and absolute not in queued:
                queued.add(absolute)
                listings.append(absolute)

        def absorb_tree(tree, page_url):
            for item in self._product_card_entries_from_tree(tree, page_url):
                key = item.get('prestashop_id') or item['url']
                products.setdefault(key, {'url': item['url'], 'lastmod': False})
            for href in tree.xpath('//a[@href]/@href'):
                absolute = self._canonical_url(urljoin(page_url, href))
                parsed = urlparse(absolute)
                if parsed.netloc.lower() not in self._HOSTS:
                    continue
                path = parsed.path or '/'
                if (
                    self._CATEGORY_PATH_RE.match(path)
                    or re.match(r'^/brand/\d+(?:-[^/?#]+)?/?$', path, re.I)
                ):
                    add_listing(absolute)

        for start_url in start_urls:
            try:
                response = self._http_get(session, start_url, source)
                absorb_tree(lxml_html.fromstring(response.content), response.url)
            except Exception as exc:
                _logger.info('Araolit: respaldo inicial no accesible %s: %s', start_url, exc)

        # Recorre categorías y marcas; la web muestra 30 productos por página.
        index = 0
        max_listings = 500
        while index < len(listings) and index < max_listings:
            base_url = listings[index]
            index += 1
            seen_signatures = set()
            for page in range(1, 100):
                parts = urlsplit(base_url)
                query = dict(parse_qsl(parts.query, keep_blank_values=True))
                if page > 1:
                    query['page'] = str(page)
                page_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))
                try:
                    response = self._http_get(session, page_url, source)
                    tree = lxml_html.fromstring(response.content)
                except Exception as exc:
                    _logger.info('Araolit: listado no accesible %s: %s', page_url, exc)
                    break

                card_entries = self._product_card_entries_from_tree(tree, response.url)
                signature = tuple(sorted(item.get('prestashop_id') for item in card_entries))
                if not card_entries or signature in seen_signatures:
                    break
                seen_signatures.add(signature)
                absorb_tree(tree, response.url)
                if limit and len(products) >= limit:
                    break

                next_links = tree.xpath(
                    '//a[contains(@rel,"next") or contains(concat(" ", normalize-space(@class), " "), " next ")][@href]/@href'
                )
                if not next_links:
                    break
            if limit and len(products) >= limit:
                break

        result = list(products.values())
        if category_filter:
            needle = str(category_filter).casefold()
            result = [item for item in result if needle in item['url'].casefold()]
        result.sort(key=lambda item: item['url'])
        return result[:limit] if limit else result

    def get_product_entries(self, source, category_filter=None, limit=0):
        entries, _image_map, errors = self._collect_products(source)
        html_entries = self._fallback_html_entries(source, category_filter=None, limit=0)
        result = self._merge_discovery_entries(
            'Araolit España',
            [('sitemap', list(entries.values())), ('catalogo_html', html_entries)],
            key_getter=None, category_filter=category_filter, limit=limit,
        )
        if result:
            return result
        raise ValueError(
            'No se pudieron descubrir productos de Araolit ni por los sitemaps '
            'de robots.txt ni recorriendo el catálogo HTML.'
            + (' Intentos: ' + ' | '.join(errors[:4]) if errors else '')
        )

    def get_image_map(self, source):
        entries, image_map, _errors = self._collect_products(source)
        return {
            entry['url']: image_map[key]
            for key, entry in entries.items()
            if image_map.get(key)
        }
