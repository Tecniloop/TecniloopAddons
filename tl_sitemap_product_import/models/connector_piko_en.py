import html
import json
import logging
import re
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorPikoEn(models.AbstractModel):
    """Conector del sitemap y catálogo internacional en inglés de PIKO."""

    _name = 'sitemap.connector.piko_en'
    _inherit = 'sitemap.import.service'
    _description = 'Conector PIKO Europa (inglés)'

    _HOSTS = {'piko-shop.de', 'www.piko-shop.de'}
    _PRODUCT_RE = re.compile(r'^/en/artikel/[^/?#]+-(?P<page_id>\d+)\.html/?$', re.IGNORECASE)
    _PRICE_RE = re.compile(r'(?P<price>\d{1,5}(?:[.\s]\d{3})*,\d{2})\s*€')
    _ITEM_RE = re.compile(r'(?:Item\s*(?:Number|number)|Artikelnummer)\s*:\s*([A-Z0-9._/-]+)', re.I)
    _EAN_RE = re.compile(r'\bEAN\s*:\s*(\d{8}|\d{12}|\d{13}|\d{14})\b', re.I)
    _ERA_RE = re.compile(r'(?<!\w)(I{1,3}(?:\s*[-/]\s*I{1,3})?|IV|V|VI)(?!\w)', re.I)
    _SCALE_RE = re.compile(r'(?<!\w)(H0|TT|N|G)(?:\s+Scale)?(?!\w)', re.I)

    @classmethod
    def _clean(cls, value):
        return re.sub(r'\s+', ' ', html.unescape(str(value or '')).replace('\xa0', ' ')).strip()

    @classmethod
    def _canonical_url(cls, value):
        parts = urlsplit(html.unescape(str(value or '')).strip())
        host = parts.netloc.casefold().removeprefix('www.')
        if host != 'piko-shop.de':
            return False
        path = re.sub(r'/+', '/', parts.path or '/')
        return urlunsplit(('https', 'www.piko-shop.de', path.rstrip('/'), '', ''))

    @classmethod
    def _product_match(cls, value):
        canonical = cls._canonical_url(value)
        return cls._PRODUCT_RE.match(urlparse(canonical).path) if canonical else False

    @staticmethod
    def _meta(tree, name):
        values = tree.xpath(
            f'//meta[@property={json.dumps(name)} or @name={json.dumps(name)}]/@content'
        )
        return values[0].strip() if values else False

    # Catálogos raíz actuales. Se recorren las categorías generales, no todas las
    # subcategorías, porque estas últimas repiten productos y multiplican peticiones.
    _CATALOG_ROOTS = (
        ('G', 'https://www.piko-shop.de/en/warengruppe/g-scale-4.html'),
        ('H0', 'https://www.piko-shop.de/en/warengruppe/h0-scale-20.html'),
        ('TT', 'https://www.piko-shop.de/en/warengruppe/tt-scale-42.html'),
        ('N', 'https://www.piko-shop.de/en/warengruppe/n-scale-50.html'),
    )
    _CATEGORY_RE = re.compile(r'^/en/warengruppe/[^/?#]+-\d+(?:/.*)?\.html/?$', re.I)
    _PAGE_RE = re.compile(r'/p-(?P<page>\d+)\.html/?$', re.I)
    _DEFAULT_PAGE_SIZE = 100
    _MAX_CATEGORY_PAGES = 250

    @classmethod
    def _category_page_url(cls, root_url, page, page_size=None):
        """Build a deterministic PIKO category page URL.

        PIKO uses zero-based ``p-N`` paging. The first plain category page is
        equivalent to page 0, but using the explicit URL makes resume/logging
        predictable and allows requesting 100 products per response.
        """
        page_size = int(page_size or cls._DEFAULT_PAGE_SIZE)
        canonical = cls._canonical_url(root_url)
        if not canonical:
            return False
        path = urlsplit(canonical).path
        path = re.sub(r'/l-\d+/o-[^/]+/p-\d+\.html$', '.html', path, flags=re.I)
        path = re.sub(r'\.html$', '', path, flags=re.I)
        return 'https://www.piko-shop.de%s/l-%d/o-itemnumber/p-%d.html' % (
            path, page_size, int(page),
        )

    @classmethod
    def _listing_product_urls(cls, tree, page_url):
        """Extract only active product cards from a category listing."""
        result = []
        seen = set()
        for href in tree.xpath('//a[contains(@href, "/en/artikel/")]/@href'):
            canonical = cls._canonical_url(urljoin(page_url, href))
            if not cls._product_match(canonical):
                continue
            if canonical in seen:
                continue
            seen.add(canonical)
            result.append(canonical)
        return result

    @classmethod
    def _listing_page_numbers(cls, tree):
        pages = set()
        for href in tree.xpath('//a[contains(@href, "/p-")]/@href'):
            match = cls._PAGE_RE.search(urlsplit(str(href)).path)
            if match:
                pages.add(int(match.group('page')))
        return pages

    def _catalog_roots(self, category_filter=None):
        needle = self._clean(category_filter).casefold()
        if not needle:
            return list(self._CATALOG_ROOTS)
        aliases = {
            'g': {'g', 'g scale', 'scale g'},
            'h0': {'h0', 'ho', 'h0 scale', 'ho scale'},
            'tt': {'tt', 'tt scale'},
            'n': {'n', 'n scale'},
        }
        selected = []
        for code, url in self._CATALOG_ROOTS:
            accepted = aliases.get(code.casefold(), {code.casefold()})
            if needle in accepted or needle in url.casefold():
                selected.append((code, url))
        return selected

    def _fetch_catalog_entries(self, source, category_filter=None, limit=0):
        """Discover current PIKO products from category pages.

        This intentionally avoids the historical sitemap, which contains many
        obsolete product URLs. A category stops when it returns no products,
        repeats an already visited page, or exceeds the last pagination link.
        """
        roots = self._catalog_roots(category_filter)
        if not roots:
            raise ValueError(
                'El filtro PIKO no coincide con los catálogos G, H0, TT o N.'
            )

        session = self._get_session(source)
        products = {}
        for scale, root_url in roots:
            page = 0
            last_page = None
            previous_signature = None
            while page < self._MAX_CATEGORY_PAGES:
                page_url = self._category_page_url(root_url, page)
                response = self._http_get(session, page_url, source)
                tree = lxml_html.fromstring(response.content)
                urls = self._listing_product_urls(tree, response.url or page_url)

                # Some installations may reject l-100. Retry the same page with
                # the site's normal page size before giving up the category.
                if not urls and page == 0:
                    fallback_url = self._category_page_url(root_url, page, page_size=18)
                    response = self._http_get(session, fallback_url, source)
                    tree = lxml_html.fromstring(response.content)
                    urls = self._listing_product_urls(tree, response.url or fallback_url)

                if not urls:
                    break
                signature = tuple(urls)
                if signature == previous_signature:
                    _logger.warning(
                        'PIKO %s: la página %s repite el contenido anterior; se detiene la paginación.',
                        scale, page,
                    )
                    break
                previous_signature = signature

                new_count = 0
                for canonical in urls:
                    if canonical not in products:
                        products[canonical] = {
                            'url': canonical,
                            'lastmod': False,
                            'piko_scale': scale,
                            'piko_listing_url': response.url or page_url,
                        }
                        new_count += 1
                        if limit and len(products) >= limit:
                            return list(products.values())

                page_numbers = self._listing_page_numbers(tree)
                if page_numbers:
                    last_page = max(page_numbers)
                if new_count == 0 or (last_page is not None and page >= last_page):
                    break
                page += 1

        return list(products.values())

    def get_product_entries(self, source, category_filter=None, limit=0):
        products = self._fetch_catalog_entries(
            source, category_filter=category_filter, limit=limit
        )
        if products:
            return products[:limit] if limit else products

        # Compatibility fallback: useful if PIKO temporarily changes or blocks
        # category pages. It is deliberately secondary because the sitemap has
        # historically contained removed products.
        _logger.warning(
            'PIKO: no se encontraron productos activos por categorías; se usa el sitemap como respaldo.'
        )
        entries = self._fetch_urlset(source, source.sitemap_index_url)
        result = []
        seen = set()
        needle = str(category_filter or '').casefold()
        for item in entries:
            canonical = self._canonical_url(item.get('url'))
            if not self._product_match(canonical) or canonical in seen:
                continue
            if needle and needle not in canonical.casefold():
                continue
            seen.add(canonical)
            result.append({'url': canonical, 'lastmod': item.get('lastmod') or False})
            if limit and len(result) >= limit:
                break
        if not result:
            raise ValueError(
                'PIKO no devuelve productos activos en sus categorías ni fichas válidas en el sitemap.'
            )
        return result

    def get_image_map(self, source):
        return {}

    @classmethod
    def _json_ld_products(cls, tree):
        products = []
        for raw in tree.xpath('//script[@type="application/ld+json"]/text()'):
            if not isinstance(raw, (str, bytes, bytearray)) or not raw:
                continue
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
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
            currency = str(offers.get('priceCurrency') or 'EUR').upper()
            try:
                price = float(str(raw).replace(',', '.'))
                if price > 0 and currency in {'EUR', '€'}:
                    return price, 'EUR'
            except Exception:
                pass
        for raw in tree.xpath(
            '//*[@itemprop="price"]/@content | //*[@data-price]/@data-price | '
            '//*[contains(@class,"price")]/@data-price'
        ):
            try:
                price = float(str(raw).replace(',', '.'))
                if price > 0:
                    return price, 'EUR'
            except Exception:
                continue
        text = cls._clean(' '.join(tree.xpath(
            '//*[contains(@class,"price") or contains(@class,"product-price")]//text()'
        )))
        match = cls._PRICE_RE.search(text)
        if match:
            return float(match.group('price').replace('.', '').replace(' ', '').replace(',', '.')), 'EUR'
        return 0.0, 'EUR'

    @classmethod
    def _images(cls, tree, product, page_url):
        """Return the complete PIKO product gallery in page order."""
        candidates = []

        def add(value):
            if isinstance(value, dict):
                value = value.get('url') or value.get('contentUrl')
            if value:
                candidates.append(str(value).strip())

        image = product.get('image') if product else None
        if isinstance(image, list):
            for value in image:
                add(value)
        else:
            add(image)

        for value in tree.xpath(
            '//meta[@property="og:image" or @property="og:image:secure_url"]/@content | '
            '//meta[@name="twitter:image" or @name="twitter:image:src"]/@content | '
            '//link[@rel="preload" and @as="image"]/@href | '
            '//a[contains(@href, "/media/oart_")]/@href | '
            '//img[contains(@src, "/media/oart_")]/@src | '
            '//img[contains(@data-src, "/media/oart_")]/@data-src | '
            '//img[contains(@data-original, "/media/oart_")]/@data-original | '
            '//img[contains(@data-lazy-src, "/media/oart_")]/@data-lazy-src | '
            '//img[contains(@data-zoom-image, "/media/oart_")]/@data-zoom-image | '
            '//img[contains(@data-large, "/media/oart_")]/@data-large'
        ):
            add(value)

        for raw in tree.xpath('//img/@srcset | //img/@data-srcset | //source/@srcset'):
            choices = []
            for part in str(raw).split(','):
                bits = part.strip().split()
                if not bits:
                    continue
                weight = 0
                if len(bits) > 1:
                    token = bits[-1].lower()
                    try:
                        weight = int(float(token[:-1])) if token.endswith(('w', 'x')) else 0
                    except ValueError:
                        weight = 0
                choices.append((weight, bits[0]))
            if choices:
                add(max(choices, key=lambda item: item[0])[1])

        document = '\n'.join(tree.xpath('//script/text() | //style/text() | //@style'))
        media_re = re.compile(
            r"(?P<url>(?:https?:)?//[^\s\"'<>]+/media/oart_[^\s\"'<>]+?\.(?:jpe?g|png|webp)(?:\?[^\s\"'<>]*)?|/media/oart_[^\s\"'<>]+?\.(?:jpe?g|png|webp)(?:\?[^\s\"'<>]*)?)",
            re.IGNORECASE,
        )
        for match in media_re.finditer(html.unescape(document).replace('\\/', '/')):
            add(match.group('url'))

        result = []
        seen = set()
        for value in candidates:
            value = html.unescape(value).replace('\\/', '/')
            absolute = urljoin(page_url, value)
            parts = urlsplit(absolute)
            if parts.scheme not in {'http', 'https'}:
                continue
            if parts.netloc.casefold().removeprefix('www.') != 'piko-shop.de':
                continue
            path = parts.path
            folded = path.casefold()
            if '/media/oart_' not in folded:
                if any(token in folded for token in ('logo', 'icon', 'placeholder', 'spinner')):
                    continue
                if not re.search(r'\.(?:jpe?g|png|webp)$', folded):
                    continue
            normalized = urlunsplit(('https', 'www.piko-shop.de', path, parts.query, ''))
            dedupe_key = urlunsplit(('https', 'www.piko-shop.de', path, '', '')).casefold()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            result.append(normalized)

        gallery = [url for url in result if '/media/oart_' in url.casefold()]
        return gallery or result

    @classmethod
    def _descriptions(cls, tree, product):
        short = cls._clean(product.get('description')) if product else ''
        blocks = []
        for xpath in (
            '//*[@itemprop="description"]',
            '//*[contains(@class,"artikelbeschreibung")]',
            '//*[contains(@class,"product-description")]',
            '//*[contains(@class,"description") and not(self::meta)]',
        ):
            for node in tree.xpath(xpath):
                text = cls._clean(' '.join(node.xpath('.//text()')))
                if len(text) > 20 and text not in blocks:
                    blocks.append(text)
        full = '\n\n'.join(blocks)
        return short or (blocks[0] if blocks else ''), full or short

    @classmethod
    def _breadcrumbs(cls, tree):
        values = []
        for text in tree.xpath(
            '//*[contains(@class,"breadcrumb")]//a//text() | '
            '//*[contains(@class,"breadcrumb")]//*[self::span or self::li]//text()'
        ):
            value = cls._clean(text)
            if value and value.casefold() not in {'home', 'piko webshop'} and value not in values:
                values.append(value)
        return values

    @classmethod
    def _feature_pairs(cls, tree):
        pairs = {}
        for row in tree.xpath('//table//tr'):
            label = cls._clean(' '.join(row.xpath('./th[1]//text() | ./td[1]//text()')))
            value = cls._clean(' '.join(row.xpath('./td[last()]//text()')))
            if label and value and label.casefold() != value.casefold():
                pairs.setdefault(label, [])
                if value not in pairs[label]:
                    pairs[label].append(value)
        for node in tree.xpath('//dl'):
            labels = node.xpath('./dt')
            values = node.xpath('./dd')
            for label_node, value_node in zip(labels, values):
                label = cls._clean(' '.join(label_node.xpath('.//text()')))
                value = cls._clean(' '.join(value_node.xpath('.//text()')))
                if label and value:
                    pairs.setdefault(label, [])
                    if value not in pairs[label]:
                        pairs[label].append(value)
        return pairs

    @classmethod
    def _attributes(cls, tree, name, breadcrumbs):
        attrs = cls._feature_pairs(tree)
        focused = cls._clean(' '.join(tree.xpath(
            '//*[contains(@class,"product") or contains(@class,"artikel") or @id="content"]//text()'
        )))
        feature_text = ' '.join(
            [label for label in attrs] +
            [value for values in attrs.values() for value in values]
        )
        context = ' '.join(breadcrumbs + [name, focused, feature_text])
        scale = cls._SCALE_RE.search(context)
        if scale:
            scale_code = scale.group(1).upper()
            attrs.setdefault('Escala ferroviaria', [scale_code])
            numeric = {'H0': '1:87', 'TT': '1:120', 'N': '1:160', 'G': '1:22,5'}.get(scale_code)
            if numeric:
                attrs.setdefault('Escala', [numeric])
        era = cls._ERA_RE.search(context)
        if era:
            attrs.setdefault('Época', [re.sub(r'\s+', '', era.group(1).upper())])
        token_map = (
            ('Gleichstrom', 'Alimentación', 'DC'), ('direct current', 'Alimentación', 'DC'),
            ('Wechselstrom', 'Alimentación', 'AC'), ('alternating current', 'Alimentación', 'AC'),
            ('DCC', 'Sistema digital', 'DCC'), ('mfx', 'Sistema digital', 'mfx'),
            ('RailCom', 'Sistema digital', 'RailCom'), ('PluX22', 'Interfaz digital', 'PluX22'),
            ('PluX16', 'Interfaz digital', 'PluX16'), ('Next18', 'Interfaz digital', 'Next18'),
            ('NEM 652', 'Interfaz digital', 'NEM 652'), ('sound', 'Sonido', 'Sí'),
            ('Sounddecoder', 'Sonido', 'Sí'), ('LED', 'Iluminación', 'LED'),
        )
        folded = context.casefold()
        for token, label, value in token_map:
            if token.casefold() in folded:
                attrs.setdefault(label, [])
                if value not in attrs[label]:
                    attrs[label].append(value)
        return attrs

    @staticmethod
    def _response_summary(response):
        return 'status=%s requested=%s final=%s content_type=%s bytes=%s' % (
            getattr(response, 'status_code', '?'),
            getattr(getattr(response, 'request', None), 'url', '?'),
            getattr(response, 'url', '?'),
            (getattr(response, 'headers', {}) or {}).get('Content-Type', ''),
            len(getattr(response, 'content', b'') or b''),
        )

    def fetch_preview(self, source, url):
        session = self._get_session(source)
        _logger.info('PIKO preview START url=%s source=%s', url, source.display_name)
        response = self._http_get(session, url, source)
        _logger.info('PIKO preview HTTP %s', self._response_summary(response))
        if not response.content:
            raise ValueError('PIKO devolvió una respuesta vacía. %s' % self._response_summary(response))
        try:
            tree = lxml_html.fromstring(response.content)
        except Exception as exc:
            snippet = (response.text or '')[:1000]
            raise ValueError('PIKO devolvió HTML no analizable. %s | inicio=%r' % (
                self._response_summary(response), snippet)) from exc
        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical = self._canonical_url(canonical_values[0] if canonical_values else response.url)
        if not self._product_match(canonical):
            canonical = self._canonical_url(url)
        if not self._product_match(canonical):
            raise ValueError('La URL de PIKO ya no corresponde a una ficha bajo /en/artikel/. %s' % self._response_summary(response))

        products = self._json_ld_products(tree)
        product = products[0] if products else {}
        name = self._clean(product.get('name')) or self._clean(' '.join(tree.xpath('//h1//text()')))
        if not name:
            name = self._clean(self._meta(tree, 'og:title'))
        if not name:
            raise ValueError('La ficha PIKO no publica un nombre reconocible. %s' % self._response_summary(response))

        page_text = self._clean(' '.join(tree.xpath('//body//text()')))
        code = self._clean(product.get('sku')) if product else ''
        if not code:
            match = self._ITEM_RE.search(page_text)
            code = match.group(1) if match else ''
        if not code:
            raise ValueError('La ficha PIKO no publica un número de artículo reconocible. %s' % self._response_summary(response))

        price, currency = self._price(tree, product)
        short_description, full_description = self._descriptions(tree, product)
        images = self._images(tree, product, canonical)
        breadcrumbs = self._breadcrumbs(tree)
        if not breadcrumbs:
            breadcrumbs = ['PIKO']
        attributes = self._attributes(tree, name, breadcrumbs)

        ean_variants = []
        candidates = []
        for key in ('gtin13', 'gtin14', 'gtin12', 'gtin8', 'gtin', 'ean'):
            if product and product.get(key):
                candidates.append(product.get(key))
        candidates.extend(self._EAN_RE.findall(page_text))
        for candidate in candidates:
            normal = self._normalise_gtin(candidate)
            if normal:
                ean_variants.append({
                    'ean': normal,
                    'sku': code,
                    'label': name,
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
            'category_path': ' / '.join(['PIKO'] + breadcrumbs),
            'ean_variants': ean_variants,
            'ean_complete': True,
        }
