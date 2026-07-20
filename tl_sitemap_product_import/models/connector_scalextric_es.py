import copy
import html
import logging
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorScalextricEs(models.AbstractModel):
    """Conector para la tienda oficial Scalextric España.

    La tienda usa PrestaShop y declara su índice XML desde ``robots.txt``::

        Sitemap: https://scalextric.es/2_index_sitemap.xml

    Las fichas españolas usan normalmente este patrón::

        /<categoria>/<id>-<slug>-<ean13>.html

    Además de los datos comerciales habituales, este conector separa la
    descripción corta de la descripción ampliada y recupera atributos técnicos
    informativos, especialmente la escala (1:32, 1:43, 1:64...). Los atributos
    se crean en Odoo como ``no_variant`` para no generar variantes accidentales.
    """

    _name = 'sitemap.connector.scalextric_es'
    _inherit = 'sitemap.connector.bicicletasquer_es'
    _description = 'Conector Scalextric España'

    _HOSTS = {'scalextric.es', 'www.scalextric.es'}
    _PRODUCT_PATH_RE = re.compile(
        r'^/(?:es/)?(?P<category>[^/?#]+)/(?P<product_id>\d+)'
        r'-(?P<slug>.+?)(?:-(?P<ean>\d{8,14}))?\.html/?$',
        re.IGNORECASE,
    )
    _CATEGORY_PATH_RE = re.compile(
        r'^/(?:es/)?(?P<category_id>\d+)-(?P<slug>[^/?#]+?)/?$',
        re.IGNORECASE,
    )
    _SCALE_RE = re.compile(r'(?<!\d)1\s*[:/]\s*(\d{1,3})(?!\d)', re.IGNORECASE)
    _EAN_URL_RE = re.compile(r'-(\d{8}|\d{12}|\d{13}|\d{14})\.html/?$', re.IGNORECASE)

    @classmethod
    def _canonical_url(cls, value):
        parts = urlsplit(html.unescape(str(value or '')).strip())
        host = parts.netloc.lower()
        if host == 'www.scalextric.es':
            host = 'scalextric.es'
        path = re.sub(r'/+', '/', parts.path)
        # El dominio principal ya sirve el mercado español sin prefijo. Se
        # normaliza un eventual /es/ para no duplicar la misma ficha.
        path = re.sub(r'^/es/', '/', path, flags=re.IGNORECASE)
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

    def _candidate_sitemaps(self, source):
        root = 'https://scalextric.es/'
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
                _logger.info('Scalextric: índice %s no accesible: %s', candidate, exc)

        # El índice actualmente declarado en robots.txt y respaldos habituales
        # del módulo Google Sitemap de PrestaShop.
        candidates.extend([
            urljoin(root, '2_index_sitemap.xml'),
            urljoin(root, 'sitemap.xml'),
            urljoin(root, 'sitemap_index.xml'),
            urljoin(root, '2_es_0_sitemap.xml'),
            urljoin(root, '2_es_1_sitemap.xml'),
        ])
        return list(dict.fromkeys(candidates))

    def _fallback_html_entries(self, source, category_filter=None, limit=0):
        """Descubre fichas desde mapa, portada, marcas y categorías.

        Se usa solo si el XML no resulta accesible. La fuente se configura con
        archivado automático desactivado porque este respaldo puede ser parcial.
        """
        session = self._get_session(source)
        start_urls = [
            'https://scalextric.es/mapa-del-sitio',
            'https://scalextric.es/',
            'https://scalextric.es/brand/2-scalextric',
            'https://scalextric.es/brand/3-scx',
            'https://scalextric.es/10-scalextric-classic',
            'https://scalextric.es/8-scalextric-advance',
            'https://scalextric.es/9-scalextric-compact',
            'https://scalextric.es/5-recambios',
        ]
        products = {}
        category_urls = []

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
                if self._CATEGORY_PATH_RE.match(parsed.path) and absolute not in category_urls:
                    category_urls.append(absolute)

        for start_url in start_urls:
            try:
                response = self._http_get(session, start_url, source)
                add_tree(lxml_html.fromstring(response.content), response.url)
            except Exception as exc:
                _logger.info('Scalextric: respaldo inicial no accesible %s: %s', start_url, exc)
            if limit and len(products) >= limit:
                break

        for category_url in category_urls[:250]:
            seen_signatures = set()
            for page in range(1, 101):
                parts = urlsplit(category_url)
                query = dict(parse_qsl(parts.query, keep_blank_values=True))
                if page > 1:
                    query['page'] = str(page)
                page_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))
                try:
                    response = self._http_get(session, page_url, source)
                    tree = lxml_html.fromstring(response.content)
                except Exception as exc:
                    _logger.info('Scalextric: categoría no accesible %s: %s', page_url, exc)
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
            'No se pudieron descubrir productos de Scalextric España. '
            'El índice declarado en robots.txt no devolvió fichas y el catálogo HTML '
            'de respaldo tampoco resultó utilizable.'
            + (' Intentos: ' + ' | '.join(errors[:4]) if errors else '')
        )

    def get_image_map(self, source):
        entries, image_map, _errors = self._collect_products(source)
        return {
            entry['url']: image_map[key]
            for key, entry in entries.items()
            if image_map.get(key)
        }

    # ------------------------------------------------------------------
    # Descripciones y atributos
    # ------------------------------------------------------------------
    @classmethod
    def _safe_fragment(cls, node):
        clone = copy.deepcopy(node)
        for bad in clone.xpath(
            './/script | .//style | .//noscript | .//form | .//button | '
            './/*[contains(@class,"product-availability-notification")]'
        ):
            bad.drop_tree()
        parts = []
        if clone.text and clone.text.strip():
            parts.append(html.escape(clone.text.strip()))
        for child in clone:
            parts.append(lxml_html.tostring(child, encoding='unicode', method='html'))
        return ''.join(parts).strip()

    @classmethod
    def _short_description(cls, tree, product_json):
        for xpath in (
            '//*[starts-with(@id,"product-description-short")]',
            '//*[contains(concat(" ", normalize-space(@class), " "), " product-description-short ")]',
            '//*[@itemprop="description" and not(ancestor::*[@id="description"])]',
        ):
            nodes = tree.xpath(xpath)
            if nodes:
                fragment = cls._safe_fragment(nodes[0])
                if fragment:
                    return fragment
        value = (product_json or {}).get('description')
        if value:
            return str(value)
        return cls._meta(tree, 'description') or ''

    @classmethod
    def _full_description(cls, tree, short_description=''):
        for xpath in (
            '//*[@id="description"]//*[contains(@class,"product-description")]',
            '//*[@id="description"]',
            '//*[contains(@class,"tab-pane") and @itemprop="description"]',
        ):
            nodes = tree.xpath(xpath)
            if nodes:
                fragment = cls._safe_fragment(nodes[0])
                if fragment:
                    return fragment
        return short_description or ''

    @classmethod
    def _feature_attributes(cls, tree, page_text, breadcrumbs):
        attributes = {}

        def add(name, value):
            name = cls._normalize_text(name).strip(' :')
            value = cls._normalize_text(value).strip(' :')
            if not name or not value:
                return
            if name.casefold() in {
                'referencia', 'reference', 'ref', 'ean', 'ean13', 'gtin',
                'precio', 'price', 'disponibilidad', 'availability',
            }:
                return
            attributes.setdefault(name, [])
            if value not in attributes[name]:
                attributes[name].append(value)

        # Ficha técnica estándar de PrestaShop.
        for dt in tree.xpath('//*[contains(@class,"product-features")]//dt'):
            dd = dt.xpath('following-sibling::dd[1]')
            if dd:
                add(' '.join(dt.xpath('.//text()')), ' '.join(dd[0].xpath('.//text()')))
        for row in tree.xpath(
            '//*[contains(@class,"product-features")]//tr | '
            '//*[contains(@class,"data-sheet")]//tr'
        ):
            names = row.xpath('./th[1]//text() | ./td[1]//text()')
            values = row.xpath('./td[last()]//text()')
            if names and values:
                add(' '.join(names), ' '.join(values))

        # Escala: puede aparecer como valor aislado junto a la referencia o en
        # la descripción larga. Se normaliza siempre como 1:N.
        scales = []
        for denominator in cls._SCALE_RE.findall(page_text or ''):
            value = f'1:{int(denominator)}'
            if value not in scales:
                scales.append(value)
        if scales:
            attributes['Escala'] = scales

        breadcrumb_text = ' / '.join(breadcrumbs or [])
        for label, token in (
            ('Advance', 'advance'),
            ('Classic', 'classic'),
            ('Compact', 'compact'),
            ('My First', 'my first'),
            ('Pull Power', 'pull power'),
        ):
            if token in breadcrumb_text.casefold():
                attributes['Gama'] = [label]
                break

        lowered = (page_text or '').casefold()
        has_digital = 'digital' in lowered
        has_analog = 'analógico' in lowered or 'analogico' in lowered
        if has_digital and not has_analog:
            attributes['Sistema'] = ['Digital']
        elif has_analog and not has_digital:
            attributes['Sistema'] = ['Analógico']
        elif has_digital and has_analog:
            attributes['Compatibilidad de sistema'] = ['Analógico / Digital']

        if re.search(r'\bcon\s+luces\b', lowered):
            attributes['Luces'] = ['Sí']
        elif re.search(r'\bsin\s+luces\b', lowered):
            attributes['Luces'] = ['No']

        return attributes

    @classmethod
    def _reference(cls, tree, product_json, lines, product_url):
        value = super()._reference(tree, product_json, lines, product_url)
        if value:
            return str(value).strip().upper()
        match = cls._product_match(product_url)
        return match.group('product_id') if match else False

    @classmethod
    def _breadcrumbs(cls, tree, product_url, name):
        values = super()._breadcrumbs(tree, product_url, name)
        # Eliminar raíces técnicas o redundantes de PrestaShop.
        excluded = {'raíz', 'inicio', 'home'}
        return [value for value in values if value.casefold() not in excluded]

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
                    'La URL ya no apunta a una ficha de producto de Scalextric España; '
                    'puede tratarse de una redirección o de un artículo retirado.'
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
            raise ValueError('La ficha de Scalextric no publica un nombre reconocible.')

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
        match = self._product_match(canonical)
        url_ean = match.group('ean') if match else False
        if not url_ean:
            suffix = self._EAN_URL_RE.search(urlparse(canonical).path)
            url_ean = suffix.group(1) if suffix else False
        url_item = self._ean_variant(
            url_ean,
            sku=reference,
            label=' / '.join(attributes.get('Escala') or []) or False,
            source_variant_id=match.group('product_id') if match else False,
            available=True,
        )
        if url_item:
            ean_variants.append(url_item)
        ean_variants = self._normalise_ean_variants(ean_variants)

        return {
            'name': name,
            # Compatibilidad con el contrato histórico del módulo.
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
            # El EAN de la URL y los objetos PrestaShop ya se han examinado.
            'ean_complete': True,
        }
