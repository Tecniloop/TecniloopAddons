import html
import logging
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorNincoEs(models.AbstractModel):
    """Conector para el catálogo español de NINCO.

    NINCO usa PrestaShop y declara desde ``robots.txt`` el índice::

        https://www.ninco.com/1_index_sitemap.xml

    Las fichas actuales se publican normalmente como::

        /es/<id_producto>-<slug>.html

    La misma forma de URL también se usa en algunas categorías antiguas. Para
    no importar páginas de listado, el conector aplica tres filtros: IDs de
    producto actuales, enlaces situados en tarjetas de producto y validación de
    marcadores propios de una ficha PrestaShop antes de crear la vista previa.
    """

    _name = 'sitemap.connector.ninco_es'
    _inherit = 'sitemap.connector.scalextric_es'
    _description = 'Conector NINCO España'

    _HOSTS = {'ninco.com', 'www.ninco.com'}
    _PRODUCT_PATH_RE = re.compile(
        r'^/es/(?P<product_id>\d+)-(?P<slug>[^/?#]+)\.html/?$',
        re.IGNORECASE,
    )
    _CATEGORY_PATH_RE = re.compile(
        r'^/es/(?P<category_id>\d+)-(?P<slug>[^/?#]+?)(?:\.html)?/?$',
        re.IGNORECASE,
    )
    _MIN_PRODUCT_ID = 3000

    @classmethod
    def _canonical_url(cls, value):
        parts = urlsplit(html.unescape(str(value or '')).strip())
        host = parts.netloc.lower()
        if host == 'ninco.com':
            host = 'www.ninco.com'
        path = re.sub(r'/+', '/', parts.path)
        return urlunsplit((parts.scheme or 'https', host, path.rstrip('/'), '', ''))

    @classmethod
    def _product_match(cls, value):
        parsed = urlparse(value)
        if parsed.netloc.lower() not in cls._HOSTS:
            return False
        match = cls._PRODUCT_PATH_RE.match(parsed.path)
        if not match:
            return False
        # Las categorías y páginas CMS históricas usan el mismo patrón pero sus
        # IDs públicos están muy por debajo del rango de producto activo actual.
        if int(match.group('product_id')) < cls._MIN_PRODUCT_ID:
            return False
        return match

    def _candidate_sitemaps(self, source):
        root = 'https://www.ninco.com/'
        candidates = []
        session = self._get_session(source)
        for candidate in (
            source.sitemap_index_url,
            urljoin(root, 'robots.txt'),
        ):
            if not candidate or candidate in candidates:
                continue
            try:
                response = session.get(
                    candidate,
                    timeout=source.request_timeout or 30,
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
                _logger.info('NINCO: índice %s no accesible: %s', candidate, exc)

        candidates.extend([
            urljoin(root, '1_index_sitemap.xml'),
            urljoin(root, 'sitemap.xml'),
            urljoin(root, 'sitemap_index.xml'),
            urljoin(root, '1_es_0_sitemap.xml'),
            urljoin(root, '1_es_1_sitemap.xml'),
        ])
        return list(dict.fromkeys(candidates))

    @classmethod
    def _product_links_from_tree(cls, tree, page_url):
        """Extrae enlaces solo desde tarjetas o bloques de producto.

        No se recogen todos los enlaces ``/<id>-<slug>.html`` porque NINCO usa
        esa misma forma para categorías y páginas antiguas.
        """
        xpaths = (
            '//article[contains(@class,"product-miniature")]//a[@href]/@href',
            '//*[@data-id-product]//a[@href]/@href',
            '//*[contains(@class,"product-title")]//a[@href]/@href',
            '//*[contains(@class,"product-name")]//a[@href]/@href',
            '//*[contains(@class,"product-container")]//a[@href]/@href',
            '//*[contains(@class,"ajax_block_product")]//a[@href]/@href',
        )
        result = []
        for xpath in xpaths:
            for href in tree.xpath(xpath):
                absolute = cls._canonical_url(urljoin(page_url, href))
                if cls._product_match(absolute) and absolute not in result:
                    result.append(absolute)
        return result

    @classmethod
    def _category_links_from_tree(cls, tree, page_url):
        result = []
        for href in tree.xpath(
            '//nav//a[@href]/@href | '
            '//*[contains(@class,"category") or contains(@class,"menu") or '
            'contains(@class,"facet") or contains(@class,"block-categories")]//a[@href]/@href'
        ):
            absolute = cls._canonical_url(urljoin(page_url, href))
            parsed = urlparse(absolute)
            if parsed.netloc.lower() not in cls._HOSTS:
                continue
            if re.match(r'^/es/marca/\d+-[^/?#]+/?$', parsed.path, re.IGNORECASE):
                if absolute not in result:
                    result.append(absolute)
                continue
            match = cls._CATEGORY_PATH_RE.match(parsed.path)
            if match and int(match.group('category_id')) < cls._MIN_PRODUCT_ID:
                if absolute not in result:
                    result.append(absolute)
        return result

    def _fallback_html_entries(self, source, category_filter=None, limit=0):
        session = self._get_session(source)
        start_urls = [
            'https://www.ninco.com/es/mapa-del-sitio',
            'https://www.ninco.com/es/',
            'https://www.ninco.com/es/2059-juguete.html',
            'https://www.ninco.com/es/2205-coches',
            'https://www.ninco.com/es/2051-circuitos',
            'https://www.ninco.com/es/2053-recambios',
            'https://www.ninco.com/es/1698-coches-rc',
            'https://www.ninco.com/es/2117-nincoracers',
            'https://www.ninco.com/es/marca/1-ninco',
            'https://www.ninco.com/es/nuevos-productos',
        ]
        products = {}
        categories = []

        def add_tree(tree, page_url):
            for product_url in self._product_links_from_tree(tree, page_url):
                key = self._product_key(product_url)
                if key and key not in products:
                    products[key] = {'url': product_url, 'lastmod': False}
            for category_url in self._category_links_from_tree(tree, page_url):
                if category_url not in categories:
                    categories.append(category_url)

        for start_url in start_urls:
            try:
                response = self._http_get(session, start_url, source)
                add_tree(lxml_html.fromstring(response.content), response.url)
            except Exception as exc:
                _logger.info('NINCO: respaldo inicial no accesible %s: %s', start_url, exc)
            if limit and len(products) >= limit:
                break

        for category_url in categories[:300]:
            seen_signatures = set()
            for page in range(1, 151):
                parts = urlsplit(category_url)
                query = dict(parse_qsl(parts.query, keep_blank_values=True))
                if page > 1:
                    query['page'] = str(page)
                page_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))
                try:
                    response = self._http_get(session, page_url, source)
                    tree = lxml_html.fromstring(response.content)
                except Exception as exc:
                    _logger.info('NINCO: categoría no accesible %s: %s', page_url, exc)
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
                next_links = tree.xpath(
                    '//a[contains(@rel,"next") or contains(@class,"next") or '
                    'contains(@class,"js-search-link")][@href]/@href'
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
        entries, image_map, errors = self._collect_products(source)
        self._ninco_entries_cache = entries
        self._ninco_image_map_cache = image_map
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
            'No se pudieron descubrir productos de NINCO España. '
            'El índice declarado en robots.txt no devolvió fichas y el catálogo HTML '
            'de respaldo tampoco resultó utilizable.'
            + (' Intentos: ' + ' | '.join(errors[:4]) if errors else '')
        )

    def get_image_map(self, source):
        entries = getattr(self, '_ninco_entries_cache', None)
        image_map = getattr(self, '_ninco_image_map_cache', None)
        if entries is None or image_map is None:
            entries, image_map, _errors = self._collect_products(source)
            self._ninco_entries_cache = entries
            self._ninco_image_map_cache = image_map
        return {
            entry['url']: image_map[key]
            for key, entry in entries.items()
            if image_map.get(key)
        }

    @classmethod
    def _breadcrumbs(cls, tree, product_url, name):
        values = super()._breadcrumbs(tree, product_url, name)
        excluded = {
            'raíz', 'inicio', 'home', 'productos', 'product', 'products',
        }
        cleaned = []
        for value in values:
            if value.casefold() in excluded:
                continue
            if value not in cleaned:
                cleaned.append(value)
        return cleaned or ['NINCO']

    @classmethod
    def _feature_attributes(cls, tree, page_text, breadcrumbs):
        raw = super()._feature_attributes(tree, page_text, breadcrumbs)
        attributes = {}
        name_map = {
            'escala (1/n)': 'Escala',
            'escala': 'Escala',
            'motor rc': 'Motor RC',
            'tipo vehiculo rc': 'Tipo de vehículo RC',
            'tipo vehículo rc': 'Tipo de vehículo RC',
            'tracción': 'Tracción',
            'batería (v) (ma)': 'Batería',
            'bateria (v) (ma)': 'Batería',
            'incluye cargador': 'Incluye cargador',
            'tipo emisora': 'Tipo de emisora',
            'acabado rc': 'Acabado RC',
            'velocidad máx (km/h)': 'Velocidad máxima',
            'velocidad max (km/h)': 'Velocidad máxima',
            'tipo coche slot': 'Tipo de coche slot',
            'configuración motor': 'Configuración del motor',
            'configuracion motor': 'Configuración del motor',
            'pilas': 'Pilas',
        }

        def add(name, value):
            name = cls._normalize_text(name).strip(' :')
            value = cls._normalize_text(value).strip(' :')
            if not name or not value:
                return
            attributes.setdefault(name, [])
            if value not in attributes[name]:
                attributes[name].append(value)

        for name, values in (raw or {}).items():
            target = name_map.get(cls._normalize_text(name).casefold(), cls._normalize_text(name).title())
            for value in values or []:
                if target == 'Escala':
                    match = cls._SCALE_RE.search(str(value))
                    if match:
                        value = f'1:{int(match.group(1))}'
                add(target, value)

        text = cls._normalize_text(page_text)
        for label, pattern in (
            ('Dimensiones del producto', r'Product\s+size\s*[:\-]?\s*([0-9][0-9.,x×\s]{2,})'),
            ('Dimensiones del embalaje', r'(?:Box|Packaging)\s+size\s*[:\-]?\s*([0-9][0-9.,x×\s]{2,})'),
        ):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = re.sub(r'\s+', '', match.group(1)).strip('.,;')
                add(label, value)

        age = re.search(r'\+\s*(\d{1,2})\s*años', text, re.IGNORECASE)
        if not age:
            age = re.search(r'a\s+partir\s+de\s+(\d{1,2})\s*años', text, re.IGNORECASE)
        if age:
            add('Edad recomendada', f'A partir de {age.group(1)} años')

        return attributes

    @classmethod
    def _is_product_page(cls, tree, product_json):
        if product_json:
            return True
        body_ids = [value.casefold() for value in tree.xpath('//body/@id') if value]
        if 'product' in body_ids:
            return True
        if tree.xpath('//meta[@property="og:type" and translate(@content,"PRODUCT","product")="product"]'):
            return True
        if tree.xpath('//*[@itemtype="https://schema.org/Product" or @itemtype="http://schema.org/Product"]'):
            return True
        has_detail = bool(tree.xpath(
            '//*[contains(@class,"product-information") or '
            'contains(@class,"product-reference") or '
            'contains(@class,"product-features") or @id="product-details"]'
        ))
        has_reference = bool(tree.xpath('//*[@itemprop="sku"] | //*[@data-product]'))
        return has_detail and has_reference

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
                    'La URL ya no apunta a una ficha española de NINCO; '
                    'puede tratarse de una categoría, una redirección o un artículo retirado.'
                )

        product_json = False
        for payload in self._json_ld_payloads(tree):
            product_json = self._find_product_json(payload)
            if product_json:
                break
        if not self._is_product_page(tree, product_json):
            raise ValueError(
                'La URL coincide con el formato histórico de NINCO, pero la página no '
                'contiene marcadores de ficha de producto. Se descarta para no importar '
                'una categoría o página editorial.'
            )

        name = self._normalize_text((product_json or {}).get('name'))
        if not name:
            values = tree.xpath('//h1[1]//text()')
            name = self._normalize_text(' '.join(values)) if values else self._meta(tree, 'og:title')
        if not name:
            raise ValueError('La ficha de NINCO no publica un nombre reconocible.')

        lines = self._page_lines(tree)
        price, currency = self._extract_price(tree, product_json, lines)
        reference = self._reference(tree, product_json, lines, canonical)
        breadcrumbs = self._breadcrumbs(tree, canonical, name)
        short_description = self._short_description(tree, product_json)
        full_description = self._full_description(tree, short_description)
        images = self._images(tree, product_json, canonical)

        focused_text = self._normalize_text(' '.join(tree.xpath(
            '//*[contains(@class,"product-information") or '
            'contains(@class,"product-features") or @id="description" or '
            'starts-with(@id,"product-description-short")]//text()'
        )))
        if not focused_text:
            focused_text = self._normalize_text(
                re.sub(r'<[^>]+>', ' ', (short_description or '') + ' ' + (full_description or ''))
            )
        attributes = self._feature_attributes(tree, focused_text, breadcrumbs)

        ean_variants = self._prestashop_ean_variants(response.content)
        ean_variants = self._normalise_ean_variants(ean_variants)

        return {
            'name': name,
            'description': full_description or short_description,
            'short_description': short_description,
            'full_description': full_description,
            'attributes': attributes,
            'price': price,
            'price_available': bool(price),
            'currency': currency or 'EUR',
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical,
            'style_code': reference,
            'color_code': False,
            'category_path': ' / '.join(breadcrumbs),
            'ean_variants': ean_variants,
            # PrestaShop puede exponer combinaciones por AJAX; el enriquecedor
            # común hará las consultas adicionales configuradas en la fuente.
            'ean_complete': False,
        }
