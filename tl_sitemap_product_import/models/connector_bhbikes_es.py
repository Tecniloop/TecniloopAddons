import gzip
import html
import json
import logging
import re
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorBhBikesEs(models.AbstractModel):
    """Conector del mercado español de BH Bikes.

    El índice público ``https://www.bhbikes.com/sitemap.xml`` reparte las URLs
    entre varios ``/cache/sitemap_<hex>.xml``. Esos ficheros mezclan mercados y
    tipos de página, por lo que el conector no depende del nombre del submapa:
    recorre todos los ``urlset`` y aplica un filtro estricto a las fichas bajo
    ``/es_ES/bicicletas/`` y ``/es_ES/equipamiento/`` cuyo último segmento
    termina en una referencia comercial.

    Ejemplos observados::

        /es_ES/bicicletas/.../oxford-lite-te706?c=bbb
        /es_ES/bicicletas/.../expert-junior-26-disc-k2653
        /es_ES/equipamiento/.../xpro-battery-ilynx-sl-387464100

    Una ficha de bicicleta agrupa normalmente varios colores y tallas. Se crea
    un producto simple por referencia de modelo, mientras que los GTIN/EAN que
    la página o sus endpoints públicos expongan se conservan por variante en
    ``sitemap.product.ean``.
    """

    _name = 'sitemap.connector.bhbikes_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector BH Bikes España'

    _HOSTS = {'www.bhbikes.com', 'bhbikes.com'}
    _PRODUCT_PATH_RE = re.compile(
        r'^/es[_-]ES/(?P<section>bicicletas|equipamiento)/(?P<parents>.+?)/'
        r'(?P<slug>[^/]+)-(?P<reference>(?:[A-Z]{1,5}\d{3,10}|\d{5,14}))/?$',
        re.IGNORECASE,
    )
    _IMAGE_EXT_RE = re.compile(r'\.(?:avif|gif|jpe?g|png|webp)(?:$|\?)', re.IGNORECASE)
    _NON_PRODUCT_IMAGE_RE = re.compile(
        r'(?:logo|icon|sprite|favicon|payment|social|newsletter|placeholder|spinner|'
        r'loader|flag|cookie|color\.php|cetelem|paypal)',
        re.IGNORECASE,
    )
    _PRICE_RE = re.compile(r'(?<!\d)(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2}))(?:\s*)€')

    # ------------------------------------------------------------------
    # HTTP y sitemap
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
    def _canonical_product_url(cls, value):
        parts = urlsplit(html.unescape(str(value or '')).strip())
        host = parts.netloc.lower()
        if host == 'bhbikes.com':
            host = 'www.bhbikes.com'
        path = re.sub(r'/+', '/', parts.path)
        path = re.sub(r'^/es[_-]es/', '/es_ES/', path, flags=re.IGNORECASE)
        return urlunsplit((parts.scheme or 'https', host, path.rstrip('/'), '', ''))

    @classmethod
    def _product_match(cls, value):
        parsed = urlparse(value)
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

    def _iter_sitemap_entries(self, source, sitemap_url, depth=0, visited=None):
        if depth > 8:
            raise ValueError('El sitemap de BH Bikes supera ocho niveles de índices.')
        visited = visited or set()
        parts = urlsplit(sitemap_url)
        clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))
        if clean_url in visited:
            return
        visited.add(clean_url)

        session = self._get_session(source)
        response = self._http_get(session, clean_url, source)
        try:
            root = self._xml_root(response.content)
        except (OSError, ValueError, etree.XMLSyntaxError) as exc:
            content_type = response.headers.get('Content-Type', '')
            raise ValueError(
                'BH Bikes no devolvió XML válido en '
                f'{clean_url} (Content-Type: {content_type or "desconocido"}).'
            ) from exc

        root_name = self._local_name(root)
        if root_name == 'sitemapindex':
            child_urls = [
                value.strip()
                for value in root.xpath('./*[local-name()="sitemap"]/*[local-name()="loc"]/text()')
                if value and value.strip()
            ]
            for child_url in child_urls:
                yield from self._iter_sitemap_entries(
                    source,
                    urljoin(clean_url, child_url),
                    depth=depth + 1,
                    visited=visited,
                )
            return

        if root_name != 'urlset':
            raise ValueError('El sitemap de BH Bikes no contiene <urlset> ni <sitemapindex>.')

        for url_element in root.xpath('./*[local-name()="url"]'):
            loc_values = url_element.xpath('./*[local-name()="loc"]/text()')
            if not loc_values or not loc_values[0].strip():
                continue
            lastmod_values = url_element.xpath('./*[local-name()="lastmod"]/text()')
            image_values = url_element.xpath(
                './*[local-name()="image"]/*[local-name()="loc"]/text()'
            )
            yield (
                {
                    'url': loc_values[0].strip(),
                    'lastmod': self._parse_lastmod(
                        lastmod_values[0] if lastmod_values else None
                    ),
                },
                [value.strip() for value in image_values if value and value.strip()],
            )

    @classmethod
    def _clean_image_url(cls, value, page_url=''):
        raw = html.unescape(str(value or '')).strip().replace('\\/', '/')
        if not raw or raw.startswith(('data:', 'blob:')):
            return False
        absolute = urljoin(page_url, raw)
        parts = urlsplit(absolute)
        if parts.scheme not in ('http', 'https'):
            return False
        if cls._NON_PRODUCT_IMAGE_RE.search(absolute):
            return False
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))

    def _collect_sitemap_products(self, source):
        entries_by_key = {}
        image_urls_by_key = {}
        for entry, image_urls in self._iter_sitemap_entries(
            source, source.sitemap_index_url
        ):
            canonical_url = self._canonical_product_url(entry['url'])
            key = self._product_key(canonical_url)
            if not key:
                continue

            candidate = {
                'url': canonical_url,
                'lastmod': entry.get('lastmod') or False,
            }
            current = entries_by_key.get(key)
            if not current:
                entries_by_key[key] = candidate
            elif candidate['lastmod'] and (
                not current['lastmod'] or candidate['lastmod'] > current['lastmod']
            ):
                current['lastmod'] = candidate['lastmod']

            target = image_urls_by_key.setdefault(key, [])
            for image_url in image_urls:
                cleaned = self._clean_image_url(image_url, canonical_url)
                if cleaned and cleaned not in target:
                    target.append(cleaned)

        if not entries_by_key:
            raise ValueError(
                'El sitemap de BH Bikes no contiene fichas españolas con referencia '
                'bajo /es_ES/bicicletas/ o /es_ES/equipamiento/.'
            )
        return entries_by_key, image_urls_by_key

    def get_product_entries(self, source, category_filter=None, limit=0):
        entries_by_key, _images = self._collect_sitemap_products(source)
        filter_text = (category_filter or '').strip().casefold()
        result = []
        for key, entry in sorted(entries_by_key.items(), key=lambda item: item[0]):
            category_path = '/'.join(self.parse_category_path(entry['url']))
            haystack = f'{entry["url"]} {category_path} {key}'.casefold()
            if filter_text and filter_text not in haystack:
                continue
            result.append(entry)
            if limit and len(result) >= limit:
                break
        return result

    def get_image_map(self, source):
        entries_by_key, image_urls_by_key = self._collect_sitemap_products(source)
        return {
            entry['url']: image_urls_by_key.get(key, [])
            for key, entry in entries_by_key.items()
            if image_urls_by_key.get(key)
        }

    # ------------------------------------------------------------------
    # URL, categorías y texto
    # ------------------------------------------------------------------
    @staticmethod
    def _humanize_slug(value):
        text = re.sub(r'[-_]+', ' ', str(value or '')).strip()
        words = []
        for index, word in enumerate(text.split()):
            if word.casefold() in {'y', 'de', 'del', 'para'} and index:
                words.append(word.casefold())
            else:
                words.append(word.capitalize())
        return ' '.join(words)

    @classmethod
    def parse_category_path(cls, product_url):
        match = cls._product_match(product_url)
        if not match:
            return []
        segments = [match.group('section')] + match.group('parents').split('/')
        translated = {
            'bicicletas': 'Bicicletas',
            'equipamiento': 'Equipamiento',
        }
        result = []
        for segment in segments:
            label = translated.get(segment.casefold()) or cls._humanize_slug(segment)
            if label and (not result or result[-1].casefold() != label.casefold()):
                result.append(label)
        return result

    @staticmethod
    def _normalize_text(value):
        return re.sub(r'\s+', ' ', html.unescape(str(value or ''))).strip()

    @classmethod
    def _meta(cls, tree, name):
        values = tree.xpath(
            f'//meta[@property="{name}" or @name="{name}" or @itemprop="{name}"]/@content'
        )
        return cls._normalize_text(values[0]) if values else False

    @classmethod
    def _html_document(cls, content):
        parser = lxml_html.HTMLParser(encoding='utf-8', recover=True)
        return lxml_html.fromstring(content, parser=parser)

    @classmethod
    def _json_ld_values(cls, tree):
        values = []
        for raw in tree.xpath('//script[@type="application/ld+json"]/text()'):
            if not raw or len(raw) > 8_000_000:
                continue
            try:
                values.append(json.loads(raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return values

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
            if any(str(item).casefold() == 'product' for item in types if item):
                found.append(value)
            for key in ('@graph', 'mainEntity', 'itemListElement', 'hasVariant', 'isVariantOf'):
                if key in value:
                    walk(value[key])

        for payload in cls._json_ld_values(tree):
            walk(payload)
        return found[0] if found else {}

    # ------------------------------------------------------------------
    # Precio, color, imágenes y EAN
    # ------------------------------------------------------------------
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
            text = text.replace('.', '').replace(',', '.')
        elif text.count('.') == 1 and len(text.rsplit('.', 1)[1]) == 3:
            text = text.replace('.', '')
        try:
            return float(text)
        except ValueError:
            return False

    @classmethod
    def _offer_price(cls, product_json):
        offers = product_json.get('offers') if isinstance(product_json, dict) else None
        offers = offers if isinstance(offers, list) else [offers]
        values = []
        currency = False
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            currency = currency or offer.get('priceCurrency')
            for field in ('salePrice', 'price', 'lowPrice'):
                parsed = cls._parse_price_number(offer.get(field))
                if parsed is not False:
                    values.append(parsed)
                    break
        return (min(values), currency or 'EUR') if values else (False, currency or 'EUR')

    @classmethod
    def _price_from_text(cls, text):
        normalized = cls._normalize_text(text)
        if re.search(r'\b(?:al mes|/mes|mensual|cuota)\b', normalized, re.IGNORECASE):
            normalized = re.split(r'\bdesde\b', normalized, maxsplit=1, flags=re.IGNORECASE)[0]
        values = [cls._parse_price_number(value) for value in cls._PRICE_RE.findall(normalized)]
        values = [value for value in values if value is not False]
        if not values:
            return False
        return values[-1] if '%' in normalized and len(values) > 1 else values[0]

    @classmethod
    def _extract_price(cls, tree, product_json):
        price, currency = cls._offer_price(product_json)
        if price is not False:
            return price, currency

        meta_price = (
            cls._meta(tree, 'product:price:amount')
            or cls._meta(tree, 'og:price:amount')
        )
        parsed = cls._parse_price_number(meta_price)
        if parsed is not False:
            return parsed, (
                cls._meta(tree, 'product:price:currency')
                or cls._meta(tree, 'og:price:currency')
                or 'EUR'
            )

        main_nodes = tree.xpath('//main')
        scope = main_nodes[0] if main_nodes else tree
        selectors = (
            './/*[contains(translate(@class,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"price")]',
            './/*[@itemprop="price"]',
        )
        for selector in selectors:
            for node in scope.xpath(selector)[:30]:
                text = cls._normalize_text(' '.join(node.itertext()))
                candidate = cls._price_from_text(text)
                if candidate is not False and candidate > 0:
                    return candidate, 'EUR'
        return 0.0, 'EUR'

    @classmethod
    def _extract_color_details(cls, tree, page_url, reference):
        selected = (parse_qs(urlsplit(page_url).query).get('c') or [False])[0]
        reference_lower = reference.lower()
        labels_by_code = {}
        image_re = re.compile(
            rf'(?:^|/){re.escape(reference_lower)}_(?P<code>[a-z0-9]+)_n\d+\.',
            re.IGNORECASE,
        )
        for element in tree.xpath('//img | //source'):
            label = cls._normalize_text(' '.join(filter(None, [
                element.get('alt'), element.get('title'), element.get('aria-label')
            ])))
            for attr in ('src', 'data-src', 'data-original', 'data-lazy-src', 'srcset', 'data-srcset'):
                raw = element.get(attr) or ''
                for token in raw.split(','):
                    value = token.strip().split(' ')[0]
                    match = image_re.search(value)
                    if not match:
                        continue
                    code = match.group('code').upper()
                    if label and label.casefold() not in {'image', 'imagen'}:
                        labels_by_code.setdefault(code, label)
                    else:
                        labels_by_code.setdefault(code, '')
        if selected:
            selected_code = selected.upper()
            label = labels_by_code.get(selected_code)
            return f'{selected_code} - {label}' if label else selected_code
        codes = list(labels_by_code)
        if not codes:
            return False
        if len(codes) == 1:
            label = labels_by_code[codes[0]]
            return f'{codes[0]} - {label}' if label else codes[0]
        value = ' / '.join(codes)
        return value[:250]

    @classmethod
    def _extract_images(cls, tree, product_json, page_url, reference, product_name):
        candidates = []
        json_images = product_json.get('image') if isinstance(product_json, dict) else None
        if json_images:
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
                element.get('alt'), element.get('title'), element.get('aria-label')
            ])))
            for attr in (
                'src', 'data-src', 'data-original', 'data-lazy-src',
                'data-image', 'data-image-url', 'data-zoom-image',
            ):
                image = element.get(attr)
                if image:
                    candidates.append((image, label, False))
            for attr in ('srcset', 'data-srcset'):
                for item in (element.get(attr) or '').split(','):
                    image = item.strip().split(' ')[0]
                    if image:
                        candidates.append((image, label, False))

        ref_lower = reference.casefold()
        name_words = {
            word for word in re.sub(r'[^a-z0-9áéíóúñ]+', ' ', product_name.casefold()).split()
            if len(word) >= 4
        }
        result = []
        seen = set()
        for raw_url, label, trusted in candidates:
            cleaned = cls._clean_image_url(raw_url, page_url)
            if not cleaned or not cls._IMAGE_EXT_RE.search(cleaned):
                continue
            lower = cleaned.casefold()
            label_lower = label.casefold()
            filename = urlsplit(cleaned).path.rsplit('/', 1)[-1].casefold()
            matches_ref = ref_lower in filename or ref_lower in lower
            matches_name = bool(name_words and any(word in label_lower for word in name_words))
            bh_product_cdn = 'bhbikes.b-cdn.net' in urlsplit(cleaned).netloc.casefold() and matches_ref
            if not trusted and not matches_ref and not matches_name and not bh_product_cdn:
                continue
            identity = urlunsplit((
                urlsplit(cleaned).scheme,
                urlsplit(cleaned).netloc,
                urlsplit(cleaned).path,
                '',
                '',
            ))
            if identity in seen:
                continue
            seen.add(identity)
            result.append(cleaned)
        return result

    @classmethod
    def _ean_variants_from_bh_html(cls, tree, content):
        result = []
        marker_re = re.compile(r'(?:gtin|ean|barcode|upc)', re.IGNORECASE)
        main_nodes = tree.xpath('//main')
        scope = main_nodes[0] if main_nodes else tree
        for element in scope.xpath('.//*'):
            label = cls._normalize_text(' / '.join(filter(None, [
                element.get('data-size'), element.get('data-talla'),
                element.get('data-color'), element.get('title'),
            ])))
            sku = (
                element.get('data-sku') or element.get('data-reference')
                or element.get('data-ref') or False
            )
            source_id = element.get('data-id') or element.get('data-variant-id') or False
            for attr_name, attr_value in element.attrib.items():
                if not marker_re.search(attr_name):
                    continue
                item = cls._ean_variant(
                    attr_value,
                    sku=sku,
                    label=label,
                    source_variant_id=source_id,
                    available='disabled' not in (element.get('class') or '').casefold(),
                )
                if item:
                    result.append(item)

        text = content.decode('utf-8', errors='ignore') if isinstance(content, bytes) else str(content)
        for match in re.finditer(
            r'(?:GTIN(?:-?(?:8|12|13|14))?|EAN(?:-?(?:8|12|13|14))?|UPC|BARCODE)'
            r'\s*(?:[:=#]|&quot;\s*:\s*&quot;)?\s*["\']?(\d{8}|\d{12}|\d{13}|\d{14})',
            text,
            flags=re.IGNORECASE,
        ):
            item = cls._ean_variant(match.group(1))
            if item:
                result.append(item)
        return cls._normalise_ean_variants(result)

    @classmethod
    def _color_codes_from_html(cls, tree, reference):
        codes = []
        ref_lower = reference.casefold()
        image_re = re.compile(
            rf'(?:^|/){re.escape(ref_lower)}_(?P<code>[a-z0-9]+)_n\d+\.',
            re.IGNORECASE,
        )
        for href in tree.xpath('//a[contains(@href,"?c=") or contains(@href,"&c=")]/@href'):
            for code in parse_qs(urlsplit(html.unescape(href)).query).get('c', []):
                code = code.strip()
                if code and code not in codes:
                    codes.append(code)
        for value in tree.xpath('//img/@src | //img/@data-src | //source/@srcset | //img/@data-srcset'):
            for token in str(value).split(','):
                match = image_re.search(token.strip().split(' ')[0])
                if match:
                    code = match.group('code')
                    if code not in codes:
                        codes.append(code)
        return codes

    def _fetch_site_ean_variants(self, source, product_url, preview_data):
        variants = super()._fetch_site_ean_variants(source, product_url, preview_data)
        limit = max(int(source.max_ean_requests_per_product or 0), 0)
        if not limit:
            return variants

        session = self._get_session(source)
        try:
            response = self._http_get(session, product_url, source)
            tree = self._html_document(response.content)
        except Exception as exc:
            _logger.debug('BH Bikes: no se pudo revisar variantes de color: %s', exc)
            return self._normalise_ean_variants(variants)

        reference = self._product_reference(product_url)
        color_codes = self._color_codes_from_html(tree, reference) if reference else []
        current_code = (parse_qs(urlsplit(product_url).query).get('c') or [False])[0]
        requests_done = 0
        for color_code in color_codes:
            if requests_done >= limit:
                break
            if current_code and color_code.casefold() == str(current_code).casefold():
                continue
            parts = urlsplit(product_url)
            query = dict(parse_qsl(parts.query, keep_blank_values=True))
            query['c'] = color_code
            color_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))
            try:
                color_response = self._http_get(session, color_url, source)
                color_tree = self._html_document(color_response.content)
                variants.extend(self._ean_variants_from_html_content(color_response.content))
                variants.extend(self._ean_variants_from_bh_html(color_tree, color_response.content))
            except Exception as exc:
                _logger.debug('BH Bikes: variante de color no accesible %s: %s', color_url, exc)
            requests_done += 1
        return self._normalise_ean_variants(variants)

    # ------------------------------------------------------------------
    # Ficha de producto
    # ------------------------------------------------------------------
    def _parse_product_html(self, content, requested_url, final_url=None):
        requested_reference = self._product_reference(requested_url)
        if not requested_reference:
            raise ValueError('La URL solicitada no es una ficha válida de BH Bikes España.')

        tree = self._html_document(content)
        product_json = self._product_json_ld(tree)
        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical_candidate = (
            urljoin(final_url or requested_url, canonical_values[0].strip())
            if canonical_values and canonical_values[0].strip()
            else (final_url or requested_url)
        )
        canonical_url = self._canonical_product_url(canonical_candidate)
        canonical_reference = self._product_reference(canonical_url)
        if not canonical_reference:
            canonical_url = self._canonical_product_url(requested_url)
            canonical_reference = requested_reference
        if canonical_reference != requested_reference:
            raise ValueError(
                'La ficha de BH Bikes ha redirigido a otra referencia; el producto '
                'solicitado puede estar descatalogado.'
            )

        h1_values = tree.xpath('//main//h1//text()') or tree.xpath('//h1//text()')
        name = self._normalize_text(' '.join(h1_values))
        if not name:
            name = self._normalize_text(product_json.get('name') if isinstance(product_json, dict) else '')
        if not name:
            name = self._meta(tree, 'og:title') or self._humanize_slug(
                self._product_match(canonical_url).group('slug')
            )
        name = re.sub(r'\s*[-|]\s*BH Bikes.*$', '', name, flags=re.IGNORECASE).strip()

        description = self._normalize_text(
            (product_json.get('description') if isinstance(product_json, dict) else '')
            or self._meta(tree, 'og:description')
            or self._meta(tree, 'description')
            or ''
        )
        price, currency = self._extract_price(tree, product_json)
        image_urls = self._extract_images(
            tree, product_json, canonical_url, canonical_reference, name
        )
        color_code = self._extract_color_details(tree, requested_url, canonical_reference)

        ean_variants = []
        if isinstance(product_json, dict):
            ean_variants.extend(self._ean_variants_from_payload(product_json))
        ean_variants.extend(self._ean_variants_from_html_content(content))
        ean_variants.extend(self._ean_variants_from_bh_html(tree, content))

        return {
            'name': name or canonical_url,
            'description': description,
            'price': price,
            'price_available': bool(price),
            'currency': currency or 'EUR',
            'category_path': '/'.join(self.parse_category_path(canonical_url)),
            'style_code': canonical_reference,
            'color_code': color_code or False,
            'main_image_url': image_urls[0] if image_urls else False,
            'image_urls': image_urls,
            'canonical_url': canonical_url,
            'ean_variants': self._normalise_ean_variants(ean_variants),
            # No se declara completa: BH puede cargar EAN adicionales al elegir
            # color/talla y enrich_preview_eans debe explorar esos endpoints.
            'ean_complete': False,
        }

    def fetch_preview(self, source, url):
        session = self._get_session(source)
        response = self._http_get(session, url, source)
        return self._parse_product_html(response.content, url, response.url or url)
