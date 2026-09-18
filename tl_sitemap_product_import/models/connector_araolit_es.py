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

    La fuente se configura con https://www.araolit.es/robots.txt. El conector
    lee de robots.txt las directivas Sitemap y mantiene varios nombres
    habituales de Google Sitemap/PrestaShop como respaldo. Si el XML no está
    disponible, descubre fichas desde el mapa del sitio, marcas y categorías.

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
    _CATEGORY_PATH_RE = re.compile(
        r'^/(?P<category_id>\d+)-(?P<slug>[^/?#]+?)/?$', re.IGNORECASE,
    )


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
        parsed = urlparse(value)
        if parsed.netloc.lower() not in cls._HOSTS:
            return False
        return cls._PRODUCT_PATH_RE.match(parsed.path)

    @classmethod
    def _product_key(cls, value):
        match = cls._product_match(value)
        return match.group('product_id') if match else False

    @classmethod
    def _product_links_from_tree(cls, tree, page_url):
        """Extrae enlaces desde las tarjetas PrestaShop y como respaldo desde todo el DOM.

        Araolit renderiza listados con miniaturas PrestaShop. Priorizar esos
        nodos evita depender de clases concretas del tema para descubrir fichas.
        """
        result = []
        seen = set()
        xpaths = [
            '//*[@data-id-product]//a[@href]/@href',
            '//*[contains(concat(" ", normalize-space(@class), " "), " product-miniature ")]//a[@href]/@href',
            '//article[contains(@class,"product")]//a[@href]/@href',
            '//a[@href]/@href',
        ]
        for xpath in xpaths:
            for href in tree.xpath(xpath):
                absolute = cls._canonical_url(urljoin(page_url, href))
                if absolute in seen or not cls._product_match(absolute):
                    continue
                seen.add(absolute)
                result.append(absolute)
        return result

    def _candidate_sitemaps(self, source):
        root = 'https://www.araolit.es/'
        candidates = []
        session = self._get_session(source)
        for candidate in (source.sitemap_index_url, urljoin(root, 'robots.txt')):
            if not candidate or candidate in candidates:
                continue
            try:
                response = session.get(
                    candidate,
                    timeout=source.request_timeout or 20,
                    allow_redirects=True,
                )
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

        candidates.extend([
            urljoin(root, 'sitemap.xml'),
            urljoin(root, 'sitemap_index.xml'),
            urljoin(root, '1_index_sitemap.xml'),
            urljoin(root, '1_es_0_sitemap.xml'),
            urljoin(root, '1_es_1_sitemap.xml'),
        ])
        return list(dict.fromkeys(candidates))

    def _fallback_html_entries(self, source, category_filter=None, limit=0):
        session = self._get_session(source)
        start_urls = [
            'https://www.araolit.es/mapa-del-sitio',
            'https://www.araolit.es/',
            'https://www.araolit.es/brands',
            'https://www.araolit.es/nuevos-productos',
        ]
        products = {}
        categories = []

        def add_tree(tree, page_url):
            for product_url in self._product_links_from_tree(tree, page_url):
                key = self._product_key(product_url)
                if key and key not in products:
                    products[key] = {'url': product_url, 'lastmod': False}
            for href in tree.xpath('//a[@href]/@href'):
                absolute = self._canonical_url(urljoin(page_url, href))
                parsed = urlparse(absolute)
                if parsed.netloc.lower() not in self._HOSTS:
                    continue
                if self._CATEGORY_PATH_RE.match(parsed.path) and absolute not in categories:
                    categories.append(absolute)

        for start_url in start_urls:
            try:
                response = self._http_get(session, start_url, source)
                add_tree(lxml_html.fromstring(response.content), response.url)
            except Exception as exc:
                _logger.info('Araolit: respaldo inicial no accesible %s: %s', start_url, exc)
            if limit and len(products) >= limit:
                break

        # Las categorías PrestaShop de Araolit muestran 30 productos por página.
        for category_url in categories[:300]:
            seen_signatures = set()
            for page in range(1, 100):
                parts = urlsplit(category_url)
                query = dict(parse_qsl(parts.query, keep_blank_values=True))
                if page > 1:
                    query['page'] = str(page)
                page_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))
                try:
                    response = self._http_get(session, page_url, source)
                    tree = lxml_html.fromstring(response.content)
                except Exception as exc:
                    _logger.info('Araolit: categoría no accesible %s: %s', page_url, exc)
                    break
                links = self._product_links_from_tree(tree, response.url)
                signature = tuple(sorted(self._product_key(url) for url in links if self._product_key(url)))
                if not links or not signature or signature in seen_signatures:
                    break
                seen_signatures.add(signature)
                for product_url in links:
                    key = self._product_key(product_url)
                    if key and key not in products:
                        products[key] = {'url': product_url, 'lastmod': False}
                if limit and len(products) >= limit:
                    break
                if not tree.xpath('//a[contains(@rel,"next") or contains(@class,"next")][@href]'):
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
        result = self._prestashop_merge_discovery(
            'Araolit España', sitemap_entries=list(entries.values()),
            category_entries=html_entries, category_filter=category_filter, limit=limit,
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
