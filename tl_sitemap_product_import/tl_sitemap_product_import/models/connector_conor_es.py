import html
import logging
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorConorEs(models.AbstractModel):
    """Conector para el catalogo espanol de Conor Bikes.

    Conor utiliza PrestaShop. Sus fichas publicas siguen normalmente el
    patron::

        /es/<categoria>/<id_producto>-<id_combinacion>-<slug>-<ean13>.html

    El EAN de la combinacion seleccionada aparece en la URL y en el contenido
    de la ficha. Las combinaciones restantes pueden aparecer en JSON/JavaScript
    de PrestaShop y se conservan como EAN externos por talla y color.

    El sitio no ofrece siempre un sitemap XML estable o facilmente accesible.
    Por ello se prueban robots.txt y los nombres habituales de PrestaShop y, si
    no se obtiene un XML util, se recorre de forma acotada la categoria general
    ``/es/2-inicio`` que pagina todo el catalogo publico.
    """

    _name = 'sitemap.connector.conor_es'
    _inherit = 'sitemap.connector.bicicletasquer_es'
    _description = 'Conector Conor Bikes Espana'

    _HOSTS = {'conorbikes.com', 'www.conorbikes.com'}
    _PRODUCT_PATH_RE = re.compile(
        r'^/es/(?P<category>[^/?#]+)/(?P<product_id>\d+)'
        r'(?:-(?P<attribute_id>\d+))?'
        r'-(?P<slug>.+?)'
        r'(?:-(?P<ean>\d{8,14}))?\.html/?$',
        re.IGNORECASE,
    )
    _ARTICLE_RE = re.compile(
        r'(?:Numero|N[uú]mero)\s+de\s+art[ií]culo\s*[:#-]?\s*\.?\s*'
        r'([A-Z0-9][A-Z0-9._/\-]{2,})',
        re.IGNORECASE,
    )

    @classmethod
    def _canonical_url(cls, value):
        parts = urlsplit(html.unescape(str(value or '')).strip())
        host = parts.netloc.lower()
        if host == 'www.conorbikes.com':
            host = 'conorbikes.com'
        path = re.sub(r'/+', '/', parts.path)
        path = re.sub(r'^/(?:gb|en|it|fr)/', '/es/', path, flags=re.IGNORECASE)
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
        if not match:
            return False
        # Una ficha agrupa colores y tallas. Se deduplica por producto maestro
        # y se conservan los EAN de todas las combinaciones en la tabla auxiliar.
        return match.group('product_id')

    def _candidate_sitemaps(self, source):
        root = 'https://conorbikes.com/'
        candidates = []
        session = self._get_session(source)

        for candidate in (
            'https://conorbikes.com/robots.txt',
            source.sitemap_index_url,
        ):
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
                _logger.info('Conor: indice %s no accesible: %s', candidate, exc)

        # Rutas frecuentes del modulo Google Sitemap de PrestaShop y variantes
        # usadas por instalaciones con varios idiomas/tiendas.
        candidates.extend([
            urljoin(root, 'sitemap.xml'),
            urljoin(root, 'sitemap_index.xml'),
            urljoin(root, '1_es_0_sitemap.xml'),
            urljoin(root, '1_es_1_sitemap.xml'),
            urljoin(root, 'es/sitemap.xml'),
        ])
        return list(dict.fromkeys(candidates))

    def _fallback_html_entries(self, source, category_filter=None, limit=0):
        """Descubre el catalogo completo desde la paginacion publica."""
        session = self._get_session(source)
        products = {}
        seen_signatures = set()

        # /es/2-inicio enumera todo el catalogo publico; el mapa HTML sirve como
        # segunda puerta de entrada si cambia el identificador de esa categoria.
        start_urls = [
            'https://conorbikes.com/es/2-inicio',
            'https://conorbikes.com/es/mapa%20del%20sitio',
            'https://conorbikes.com/es/4-bicicletas-conor-wrcline',
        ]

        for start_url in start_urls:
            page = 1
            while page <= 250:
                parts = urlsplit(start_url)
                query = dict(parse_qsl(parts.query, keep_blank_values=True))
                if page > 1:
                    query['page'] = str(page)
                page_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))
                try:
                    response = self._http_get(session, page_url, source)
                    tree = lxml_html.fromstring(response.content)
                except Exception as exc:
                    _logger.info('Conor: respaldo HTML no accesible %s: %s', page_url, exc)
                    break

                page_links = self._product_links_from_tree(tree, response.url)
                signature = tuple(sorted(
                    self._product_key(product_url)
                    for product_url in page_links
                    if self._product_key(product_url)
                ))
                if not page_links or not signature or signature in seen_signatures:
                    break
                seen_signatures.add(signature)

                for product_url in page_links:
                    key = self._product_key(product_url)
                    if key and key not in products:
                        products[key] = {'url': product_url, 'lastmod': False}

                if limit and len(products) >= limit:
                    break

                next_links = tree.xpath(
                    '//a[contains(@rel,"next") or contains(@class,"next") or '
                    'contains(@class,"js-search-link")][@href]/@href'
                )
                if not next_links:
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

    def get_product_entries(self, source, category_filter=None, limit=0):
        entries, image_map, errors = self._collect_products(source)
        self._conor_entries_cache = entries
        self._conor_image_map_cache = image_map
        if entries:
            result = list(entries.values())
            if category_filter:
                needle = str(category_filter).casefold()
                result = [item for item in result if needle in item['url'].casefold()]
            result.sort(key=lambda item: item['url'])
            return result[:limit] if limit else result

        fallback = self._fallback_html_entries(
            source,
            category_filter=category_filter,
            limit=limit,
        )
        if fallback:
            return fallback
        raise ValueError(
            'No se pudieron descubrir productos de Conor Bikes. '
            'No se obtuvo un sitemap XML util y la paginacion publica no devolvio fichas.'
            + (' Intentos: ' + ' | '.join(errors[:4]) if errors else '')
        )

    def get_image_map(self, source):
        entries = getattr(self, '_conor_entries_cache', None)
        image_map = getattr(self, '_conor_image_map_cache', None)
        if entries is None or image_map is None:
            entries, image_map, _errors = self._collect_products(source)
            self._conor_entries_cache = entries
            self._conor_image_map_cache = image_map
        result = {}
        for key, entry in entries.items():
            if image_map.get(key):
                result[entry['url']] = image_map[key]
        return result

    @classmethod
    def _reference(cls, tree, product_json, lines, product_url):
        value = super()._reference(tree, product_json, lines, product_url)
        if value and not str(value).isdigit():
            return str(value).lstrip('.').upper()

        for line in lines:
            match = cls._ARTICLE_RE.search(line)
            if match:
                return match.group(1).lstrip('.').upper()

        # Algunas plantillas separan la etiqueta y el valor en nodos distintos.
        text = cls._normalize_text(' '.join(tree.xpath('//body//text()')))
        match = cls._ARTICLE_RE.search(text)
        if match:
            return match.group(1).lstrip('.').upper()

        return str(value).lstrip('.').upper() if value else False

    @classmethod
    def _breadcrumbs(cls, tree, product_url, name):
        values = super()._breadcrumbs(tree, product_url, name)
        if values == ['Bicicletas Quer']:
            return ['Conor Bikes']
        return values

    def fetch_preview(self, source, url):
        data = super().fetch_preview(source, url)
        match = self._product_match(data.get('canonical_url') or url)
        if not match:
            return data

        # Garantiza el EAN seleccionado aunque el JavaScript de combinaciones
        # cambie. El codigo ya se valida por el normalizador GS1 comun.
        url_ean = match.groupdict().get('ean')
        if url_ean:
            variants = list(data.get('ean_variants') or [])
            selected = self._ean_variant(
                url_ean,
                sku=data.get('style_code'),
                label=False,
                source_variant_id=match.groupdict().get('attribute_id') or False,
                available=True,
            )
            if selected:
                variants.append(selected)
            data['ean_variants'] = self._normalise_ean_variants(variants)

        category_path = data.get('category_path') or ''
        if category_path.casefold() == 'bicicletas quer':
            data['category_path'] = 'Conor Bikes'
        return data
