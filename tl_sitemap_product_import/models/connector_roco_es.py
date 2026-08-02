import html
import json
import logging
import re
from urllib.parse import quote, urlencode, urljoin, urlparse, urlsplit, urlunsplit

from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorRocoEs(models.AbstractModel):
    """Conector del catálogo español de ROCO con lectura de fichas en inglés.

    La tienda actual es Magento y publica el catálogo paginado en
    ``/res/productos.html``. Las fichas siguen el patrón
    ``/res/productos/<categorías>/<referencia>-<slug>.html``. Para evitar
    bucles de redirección causados por algunos slugs UTF-8 del escaparate
    español, los datos de producto se descargan siempre desde la ficha
    equivalente inglesa bajo ``/ren/products/``.
    """

    _name = 'sitemap.connector.roco_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector ROCO España'

    _HOSTS = {'roco.cc', 'www.roco.cc'}
    _PRODUCT_RE = re.compile(
        r'^/(?P<locale>res|ren)/(?P<section>productos|products)/'
        r'(?:[^/?#]+/)*(?P<code>\d{5,8})-[^/?#]+\.html/?$',
        re.IGNORECASE,
    )
    _PRICE_RE = re.compile(r'(?P<price>\d{1,5}(?:[.\s]\d{3})*,\d{2})\s*€')
    _SCALE_RE = re.compile(r'(?<!\w)(H0e|H0|TT|N|Z|G)(?!\w)', re.IGNORECASE)
    _ERA_RE = re.compile(r'(?<!\w)(I{1,3}(?:-I{1,3})?|IV|V|VI)(?!\w)', re.IGNORECASE)

    @classmethod
    def _clean(cls, value):
        return re.sub(r'\s+', ' ', html.unescape(str(value or '')).replace('\xa0', ' ')).strip()

    @classmethod
    def _canonical_url(cls, value):
        parts = urlsplit(html.unescape(str(value or '')).strip())
        host = parts.netloc.casefold().removeprefix('www.')
        if host != 'roco.cc':
            return False
        path = re.sub(r'/+', '/', parts.path or '/')
        return urlunsplit(('https', 'www.roco.cc', path.rstrip('/'), '', ''))

    @classmethod
    def _product_match(cls, value):
        canonical = cls._canonical_url(value)
        return cls._PRODUCT_RE.match(urlparse(canonical).path) if canonical else False

    @classmethod
    def _product_key(cls, value):
        match = cls._product_match(value)
        return match.group('code') if match else False

    @classmethod
    def _is_english_product_url(cls, value):
        match = cls._product_match(value)
        return bool(match and match.group('locale').casefold() == 'ren')

    @staticmethod
    def _meta(tree, name):
        values = tree.xpath(
            f'//meta[@property={json.dumps(name)} or @name={json.dumps(name)}]/@content'
        )
        return values[0].strip() if values else False

    @classmethod
    def _product_links(cls, tree, page_url, locale=False):
        links = []
        xpaths = (
            '//li[contains(@class,"product-item")]//a[contains(@class,"product-item-link")]/@href',
            '//*[contains(@class,"products-grid") or contains(@class,"product-items")]//a[@href]/@href',
            '//a[contains(@class,"product-item-photo")]/@href',
        )
        for xpath in xpaths:
            for href in tree.xpath(xpath):
                absolute = cls._canonical_url(urljoin(page_url, href))
                match = cls._product_match(absolute)
                if (
                    match
                    and (not locale or match.group('locale').casefold() == locale.casefold())
                    and absolute not in links
                ):
                    links.append(absolute)
        return links

    def _discover_catalog(self, source, limit=0):
        session = self._get_session(source)
        products = {}
        seen_signatures = set()
        for page in range(1, 1000):
            query = {'product_list_limit': '96'}
            if page > 1:
                query['p'] = str(page)
            page_url = 'https://www.roco.cc/res/productos.html?' + urlencode(query)
            try:
                response = self._http_get(session, page_url, source)
                tree = lxml_html.fromstring(response.content)
            except Exception as exc:
                _logger.info('ROCO: página de catálogo no accesible %s: %s', page_url, exc)
                break
            links = self._product_links(tree, response.url, locale='res')
            signature = tuple(self._product_key(item) for item in links)
            if not signature or signature in seen_signatures:
                break
            seen_signatures.add(signature)
            for product_url in links:
                key = self._product_key(product_url)
                if key and key not in products:
                    products[key] = {'url': product_url, 'lastmod': False}
            if limit and len(products) >= limit:
                break
            next_links = tree.xpath('//a[contains(@class,"action next") or @rel="next"]/@href')
            if not next_links and len(links) < 96:
                break
        result = sorted(products.values(), key=lambda item: item['url'])
        return result[:limit] if limit else result

    def get_product_entries(self, source, category_filter=None, limit=0):
        result = self._discover_catalog(source, limit=limit)
        if category_filter:
            needle = str(category_filter).casefold()
            result = [item for item in result if needle in item['url'].casefold()]
        if not result:
            raise ValueError(
                'No se encontraron fichas ROCO bajo /res/productos.html. '
                'La fuente puede estar bloqueando el catálogo o haber cambiado su estructura.'
            )
        return result[:limit] if limit else result

    def get_image_map(self, source):
        return {}

    @classmethod
    def _json_ld_products(cls, tree):
        products = []
        for raw in tree.xpath('//script[@type="application/ld+json"]/text()'):
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            stack = payload if isinstance(payload, list) else [payload]
            while stack:
                item = stack.pop()
                if isinstance(item, list):
                    stack.extend(item)
                elif isinstance(item, dict):
                    item_type = item.get('@type')
                    if item_type == 'Product' or (isinstance(item_type, list) and 'Product' in item_type):
                        products.append(item)
                    stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
        return products

    @classmethod
    def _price(cls, tree, product):
        offers = product.get('offers') if product else None
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if isinstance(offers, dict):
            raw = offers.get('price') or offers.get('lowPrice')
            try:
                price = float(str(raw).replace(',', '.'))
                if price > 0:
                    return price, offers.get('priceCurrency') or 'EUR'
            except Exception:
                pass
        values = tree.xpath(
            '//*[@data-price-type="finalPrice"]//*[@data-price-amount]/@data-price-amount | '
            '//*[@data-price-amount]/@data-price-amount | //*[@itemprop="price"]/@content'
        )
        for raw in values:
            try:
                price = float(str(raw).replace(',', '.'))
                if price > 0:
                    return price, 'EUR'
            except Exception:
                continue
        text = cls._clean(' '.join(tree.xpath('//*[contains(@class,"price-box")]//text()')))
        match = cls._PRICE_RE.search(text)
        if match:
            return float(match.group('price').replace('.', '').replace(' ', '').replace(',', '.')), 'EUR'
        return 0.0, 'EUR'

    @classmethod
    def _images(cls, tree, product, page_url):
        candidates = []
        image = product.get('image') if product else None
        if isinstance(image, list):
            candidates.extend(image)
        elif image:
            candidates.append(image)
        candidates.extend(tree.xpath(
            '//meta[@property="og:image"]/@content | '
            '//*[@data-gallery-role="gallery-placeholder"]//img/@src | '
            '//*[contains(@class,"fotorama") or contains(@class,"gallery")]//img/@src | '
            '//img[@data-zoom-image]/@data-zoom-image'
        ))
        result = []
        for value in candidates:
            absolute = urljoin(page_url, str(value))
            if absolute.startswith('http') and absolute not in result:
                result.append(absolute)
        return result

    @classmethod
    def _extract_description(cls, tree, product):
        short = cls._clean(product.get('description')) if product else ''
        blocks = []
        for xpath in (
            '//*[@itemprop="description"]',
            '//*[@id="description"]',
            '//*[contains(@class,"product attribute description")]',
            '//*[contains(@class,"product-info-description")]',
        ):
            for node in tree.xpath(xpath):
                text = cls._clean(' '.join(node.xpath('.//text()')))
                if text and text not in blocks:
                    blocks.append(text)
        full = '\n\n'.join(blocks)
        return short or (blocks[0] if blocks else ''), full or short

    @classmethod
    def _attributes(cls, tree, name):
        attrs = {}
        for row in tree.xpath(
            '//table[contains(@class,"additional-attributes")]//tr | '
            '//*[contains(@class,"product-attribute-specs-table")]//tr | '
            '//*[contains(@class,"additional-attributes-wrapper")]//tr'
        ):
            label = cls._clean(' '.join(row.xpath('./th//text() | ./td[1]//text()')))
            value = cls._clean(' '.join(row.xpath('./td[last()]//text()')))
            if label and value and label.casefold() != value.casefold():
                attrs.setdefault(label, [])
                if value not in attrs[label]:
                    attrs[label].append(value)
        focused = cls._clean(' '.join(tree.xpath(
            '//*[contains(@class,"product-info-main") or contains(@class,"product data items")]//text()'
        )))
        scale = cls._SCALE_RE.search(focused + ' ' + name)
        era = cls._ERA_RE.search(focused + ' ' + name)
        if scale:
            attrs.setdefault('Escala ferroviaria', [scale.group(1).upper().replace('H0E', 'H0e')])
        if era:
            attrs.setdefault('Época', [era.group(1).upper()])
        for token, label in (
            ('DCC', 'Sistema digital'), ('Z21', 'Sistema digital'),
            ('sonido', 'Sonido'), ('sound', 'Sonido'),
            ('luz', 'Iluminación'), ('light', 'Iluminación'),
        ):
            if token.casefold() in focused.casefold():
                attrs.setdefault(label, [])
                value = token.upper() if token in {'DCC', 'Z21'} else 'Sí'
                if value not in attrs[label]:
                    attrs[label].append(value)
        return attrs

    @classmethod
    def _breadcrumbs(cls, tree):
        values = []
        for text in tree.xpath(
            '//ul[contains(@class,"breadcrumbs")]//li[not(contains(@class,"home"))]//text() | '
            '//div[contains(@class,"breadcrumbs")]//li//text()'
        ):
            value = cls._clean(text)
            if value and value.casefold() not in {'inicio', 'home', 'productos'} and value not in values:
                values.append(value)
        return values
    @classmethod
    def _english_candidates_from_tree(cls, tree, page_url):
        """Extrae posibles fichas inglesas de una respuesta de búsqueda.

        Magento puede devolver una parrilla de resultados, redirigir
        directamente a la ficha o publicar la URL únicamente en canonical,
        hreflang o JSON-LD. Se contemplan todas esas variantes sin tocar la
        URL española problemática.
        """
        candidates = []

        def add(value):
            canonical = cls._canonical_url(urljoin(page_url, str(value or '')))
            if (
                canonical
                and cls._is_english_product_url(canonical)
                and canonical not in candidates
            ):
                candidates.append(canonical)

        add(page_url)
        for value in tree.xpath(
            '//link[@rel="canonical"]/@href | '
            '//meta[@property="og:url"]/@content | '
            '//link[@rel="alternate" and '
            '(starts-with(translate(@hreflang,"EN","en"),"en") '
            'or contains(translate(@href,"REN","ren"),"/ren/"))]/@href'
        ):
            add(value)
        for value in cls._product_links(tree, page_url, locale='ren'):
            add(value)
        for value in tree.xpath('//a[@href]/@href'):
            add(value)
        for product in cls._json_ld_products(tree):
            for key in ('url', '@id'):
                add(product.get(key))
        return candidates

    def _find_english_product_url(self, source, code):
        """Busca en el escaparate inglés la ficha exacta de una referencia."""
        if not code:
            return False
        session = self._get_session(source)
        session.headers.update({'Accept-Language': 'en-GB,en;q=0.9'})
        search_urls = (
            'https://www.roco.cc/ren/catalogsearch/result/?q=' + quote(str(code)),
            'https://www.roco.cc/ren/products.html?q=' + quote(str(code)),
        )
        for search_url in search_urls:
            try:
                response = self._http_get(session, search_url, source)
                tree = lxml_html.fromstring(response.content)
                links = self._english_candidates_from_tree(tree, response.url)
                exact = [url for url in links if self._product_key(url) == str(code)]
                if exact:
                    return exact[0]
            except Exception as exc:
                _logger.info(
                    'ROCO: búsqueda inglesa de referencia %s falló en %s: %s',
                    code, search_url, exc,
                )
        return False

    def _fetch_product_response(self, source, url):
        session = self._get_session(source)
        session.headers.update({'Accept-Language': 'en-GB,en;q=0.9'})
        failures = []
        code = self._product_key(url)
        if not code:
            raise ValueError('No se pudo identificar la referencia ROCO desde %s.' % url)

        candidates = []
        canonical_input = self._canonical_url(url)
        if self._is_english_product_url(canonical_input):
            candidates.append(canonical_input)

        current = self._find_english_product_url(source, code)
        if current and current not in candidates:
            candidates.insert(0, current)

        if not candidates:
            raise ValueError(
                'No se encontró una ficha inglesa de ROCO para el artículo %s. '
                'No se consulta la ficha española para evitar su bucle de redirecciones.'
                % code
            )

        for candidate in candidates:
            try:
                response = self._http_get(session, candidate, source)
                tree = lxml_html.fromstring(response.content)
                page_text = self._clean(' '.join(tree.xpath('//body//text()')))
                title = self._clean(' '.join(tree.xpath('//h1//text()')))
                response_candidates = self._english_candidates_from_tree(tree, response.url)
                final_url = next(
                    (
                        item for item in response_candidates
                        if self._product_key(item) == str(code)
                    ),
                    False,
                )
                code_is_present = bool(
                    re.search(r'(?<!\d)%s(?!\d)' % re.escape(str(code)), page_text)
                )
                if (
                    response.status_code == 200
                    and title
                    and code_is_present
                    and final_url
                ):
                    return response, tree
                failures.append(
                    '%s -> HTTP %s, url_ingles=%r, h1=%r'
                    % (candidate, response.status_code, final_url, title[:120])
                )
            except Exception as exc:
                failures.append('%s -> %s: %s' % (candidate, exc.__class__.__name__, exc))
        raise ValueError(
            'ROCO no devolvió una ficha inglesa válida para el artículo %s. Intentos: %s'
            % (code or '?', ' | '.join(failures[-8:]))
        )

    def fetch_preview(self, source, url):
        response, tree = self._fetch_product_response(source, url)
        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical = self._canonical_url(canonical_values[0] if canonical_values else response.url)
        match = self._product_match(canonical) or self._product_match(url)
        if not match:
            raise ValueError('La URL de ROCO ya no corresponde a una ficha de producto válida.')
        canonical = canonical if self._product_match(canonical) else self._canonical_url(url)
        products = self._json_ld_products(tree)
        product = products[0] if products else {}
        name = self._clean(product.get('name')) or self._clean(' '.join(tree.xpath('//h1//text()')))
        if not name:
            name = self._clean(self._meta(tree, 'og:title'))
        if not name:
            raise ValueError('La ficha ROCO no publica un nombre reconocible.')
        code = self._clean(product.get('sku')) or self._product_key(canonical)
        price, currency = self._price(tree, product)
        short_description, full_description = self._extract_description(tree, product)
        images = self._images(tree, product, canonical)
        attributes = self._attributes(tree, name)
        breadcrumbs = self._breadcrumbs(tree)
        if not breadcrumbs:
            parts = urlparse(canonical).path.split('/')[3:-1]
            breadcrumbs = ['ROCO'] + [part.replace('-', ' ').title() for part in parts]
        ean_variants = []
        for key in ('gtin13', 'gtin14', 'gtin12', 'gtin8', 'gtin', 'mpn'):
            value = product.get(key)
            normal = self._normalise_gtin(value) if value else False
            if normal:
                ean_variants.append({'ean': normal, 'sku': code, 'label': name, 'external_variant_id': code})
        if not ean_variants:
            page_text = self._clean(' '.join(tree.xpath('//body//text()')))
            ean_match = re.search(r'(?i)\bEAN\s*[:#]?\s*(\d{8,14})\b', page_text)
            if ean_match:
                normal = self._normalise_gtin(ean_match.group(1))
                if normal:
                    ean_variants.append({
                        'ean': normal, 'sku': code, 'label': name,
                        'external_variant_id': code,
                    })
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
            'style_code': code,
            'color_code': False,
            'category_path': ' / '.join(breadcrumbs),
            'ean_variants': ean_variants,
            'ean_complete': True,
        }
