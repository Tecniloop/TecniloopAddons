import gzip
import html
import json
import logging
import re
from urllib.parse import parse_qsl, unquote_plus, urljoin, urlparse, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorBlendCompanyEu(models.AbstractModel):
    """Conector para el catálogo europeo público de Blend.

    Las fichas del mercado ``en-eu`` usan una referencia estable al final de
    la URL::

        /en-eu/<slug>--20712999-200297

    El primer bloque numérico es el estilo y el segundo el color. El sitio
    publica alias de URL para una misma combinación estilo-color (por ejemplo,
    con prefijos ``global`` o de otros mercados), de modo que el sitemap se
    deduplica por esa referencia y no por la cadena completa de la URL.

    Las fichas publican nombre, precio, color y galería en HTML/JSON-LD. El
    conector prioriza JSON-LD y Open Graph y usa el texto visible como respaldo.
    Las tallas y longitudes se mantienen fuera del alcance de esta versión,
    porque el importador crea todavía un producto simple por estilo-color.
    """

    _name = 'sitemap.connector.blendcompany_eu'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Blend Europa'

    _HOSTS = {'www.blendcompany.com', 'blendcompany.com'}
    _PRODUCT_PATH_RE = re.compile(
        r'^/en-eu/(?P<slug>.+?)--(?P<style>\d{8})-(?P<color>\d{5,6})/?$',
        re.IGNORECASE,
    )
    _ALIAS_PREFIX_RE = re.compile(
        r'^(?:(?:global)|(?:[a-z]{2}-[a-z]{2}))+',
        re.IGNORECASE,
    )
    _IMAGE_EXT_RE = re.compile(r'\.(?:avif|gif|jpe?g|png|webp)(?:$|\?)', re.IGNORECASE)
    _NON_PRODUCT_IMAGE_RE = re.compile(
        r'(?:logo|icon|flag|sprite|favicon|payment|social|newsletter|placeholder|spinner)',
        re.IGNORECASE,
    )

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
            'Accept-Language': 'en-GB,en;q=0.9,es;q=0.5',
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

    @staticmethod
    def _without_query_fragment(value):
        parts = urlsplit(value)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))

    @classmethod
    def _canonical_product_url(cls, value):
        parts = urlsplit(cls._without_query_fragment(value))
        host = parts.netloc.lower()
        if host == 'blendcompany.com':
            host = 'www.blendcompany.com'
        path = parts.path.rstrip('/')
        return urlunsplit((parts.scheme or 'https', host, path, '', ''))

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
        return match.group('style'), match.group('color')

    @classmethod
    def _style_from_url(cls, value):
        key = cls._product_key(value)
        return key[0] if key else False

    @classmethod
    def _numeric_color_from_url(cls, value):
        key = cls._product_key(value)
        return key[1] if key else False

    @classmethod
    def _slug_from_url(cls, value):
        match = cls._product_match(value)
        return match.group('slug') if match else ''

    @classmethod
    def _clean_slug(cls, value):
        value = unquote_plus(value or '').strip('-_ ')
        previous = None
        while value and value != previous:
            previous = value
            value = cls._ALIAS_PREFIX_RE.sub('', value, count=1).strip('-_ ')
        return value

    @classmethod
    def _entry_priority(cls, value):
        """Prioriza una URL sin prefijo de alias y después la más descriptiva."""
        raw_slug = cls._slug_from_url(value)
        clean_slug = cls._clean_slug(raw_slug)
        has_alias = int(raw_slug.lower() != clean_slug.lower())
        # Entre dos URLs equivalentes, una descripción algo más larga suele ser
        # preferible a alias genéricos como ``jeans`` o ``shoe``.
        return has_alias, -len(clean_slug), len(value), value

    def _iter_sitemap_entries(self, source, sitemap_url, depth=0, visited=None):
        """Lee urlset o sitemapindex, incluidos índices anidados y XML gzip."""
        if depth > 4:
            raise ValueError('El sitemap de Blend supera cuatro niveles de índices.')
        visited = visited or set()
        sitemap_url = self._without_query_fragment(sitemap_url)
        if sitemap_url in visited:
            return
        visited.add(sitemap_url)

        session = self._get_session(source)
        response = self._http_get(session, sitemap_url, source)
        try:
            root = self._xml_root(response.content)
        except (OSError, ValueError, etree.XMLSyntaxError) as exc:
            content_type = response.headers.get('Content-Type', '')
            raise ValueError(
                'Blend no devolvió un sitemap XML válido en '
                f'{sitemap_url} (Content-Type: {content_type or "desconocido"}).'
            ) from exc

        root_name = self._local_name(root)
        if root_name == 'sitemapindex':
            child_urls = [
                value.strip()
                for value in root.xpath(
                    './*[local-name()="sitemap"]/*[local-name()="loc"]/text()'
                )
                if value and value.strip()
            ]
            product_named = [
                value for value in child_urls
                if any(token in value.lower() for token in ('product', 'products', 'pdp'))
            ]
            if product_named:
                child_urls = product_named
            for child_url in child_urls:
                yield from self._iter_sitemap_entries(
                    source,
                    urljoin(sitemap_url, child_url),
                    depth=depth + 1,
                    visited=visited,
                )
            return

        if root_name != 'urlset':
            raise ValueError(
                'El sitemap de Blend no contiene <urlset> ni <sitemapindex>.'
            )

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

    def _collect_sitemap_products(self, source):
        """Devuelve una sola entrada y una galería por estilo-color."""
        best_entries = {}
        image_urls_by_key = {}

        for entry, image_urls in self._iter_sitemap_entries(
            source, source.sitemap_index_url
        ):
            product_url = self._canonical_product_url(entry['url'])
            key = self._product_key(product_url)
            if not key:
                continue

            current = best_entries.get(key)
            candidate = {
                'url': product_url,
                'lastmod': entry.get('lastmod') or False,
            }
            if not current:
                best_entries[key] = candidate
            elif self._entry_priority(product_url) < self._entry_priority(current['url']):
                newest_lastmod = current['lastmod']
                if candidate['lastmod'] and (
                    not newest_lastmod or candidate['lastmod'] > newest_lastmod
                ):
                    newest_lastmod = candidate['lastmod']
                candidate['lastmod'] = newest_lastmod
                best_entries[key] = candidate
            elif (
                candidate['lastmod']
                and (not current['lastmod'] or candidate['lastmod'] > current['lastmod'])
            ):
                # Conserva la URL preferida, pero no pierde la fecha más reciente
                # publicada por otro alias de la misma ficha.
                current['lastmod'] = candidate['lastmod']

            target_images = image_urls_by_key.setdefault(key, [])
            for image_url in image_urls:
                absolute_url = urljoin(product_url, html.unescape(image_url))
                if absolute_url not in target_images:
                    target_images.append(absolute_url)

        return best_entries, image_urls_by_key

    def get_product_entries(self, source, category_filter=None, limit=0):
        best_entries, _image_urls_by_key = self._collect_sitemap_products(source)
        filter_text = (category_filter or '').strip().lower()
        result = []

        for key, entry in sorted(
            best_entries.items(),
            key=lambda item: (self._entry_priority(item[1]['url']), item[0]),
        ):
            category_path = '/'.join(self.parse_category_path(entry['url']))
            haystack = f"{entry['url']} {category_path} {key[0]} {key[1]}".lower()
            if filter_text and filter_text not in haystack:
                continue
            result.append(entry)
            if limit and len(result) >= limit:
                break
        return result

    def get_image_map(self, source):
        best_entries, image_urls_by_key = self._collect_sitemap_products(source)
        image_map = {}
        for key, entry in best_entries.items():
            images = image_urls_by_key.get(key) or []
            if images:
                image_map[entry['url']] = images
        return image_map

    # ------------------------------------------------------------------
    # Clasificación de respaldo para el explorador de categorías
    # ------------------------------------------------------------------
    @staticmethod
    def _humanize_slug(value):
        value = unquote_plus(value or '').replace('_', ' ').replace('-', ' ')
        return re.sub(r'\s+', ' ', value).strip().title()

    @classmethod
    def parse_category_path(cls, url):
        slug = cls._clean_slug(cls._slug_from_url(url)).lower()
        if not slug:
            return []

        if re.search(r'\b(?:jeans?|denim)\b', slug):
            family = 'Jeans'
        elif re.search(r'\b(?:pants?|trousers?|chinos?)\b', slug):
            family = 'Trousers'
        elif re.search(r'\bshorts?\b', slug):
            family = 'Shorts'
        elif re.search(r'\b(?:jacket|coat|parka|overshirt|waistcoat|vest)\b', slug):
            family = 'Outerwear'
        elif re.search(r'\b(?:hoodie|sweatshirt|sweat)\b', slug):
            family = 'Sweatshirts and Hoodies'
        elif re.search(r'\b(?:pullover|jumper|knit|knitted|cardigan|sweater)\b', slug):
            family = 'Knitwear'
        elif re.search(r'\bpolo(?:[-\s]*shirt)?\b', slug):
            family = 'Polo Shirts'
        elif re.search(r'\b(?:t[-\s]*shirt|tee)\b', slug):
            family = 'T-Shirts'
        elif re.search(r'\bshirt\b', slug):
            family = 'Shirts'
        elif re.search(r'\b(?:shoe|footwear|sneaker|boot)\b', slug):
            family = 'Footwear'
        elif re.search(r'\b(?:belt|cap|hat|scarf|bag|wallet|accessor)\w*\b', slug):
            family = 'Accessories'
        else:
            family = 'Other Products'
        return [family]

    # ------------------------------------------------------------------
    # HTML y JSON-LD
    # ------------------------------------------------------------------
    @staticmethod
    def _html_document(content):
        if isinstance(content, (bytes, bytearray)):
            content = bytes(content).decode('utf-8', errors='replace')
        return lxml_html.fromstring(content)

    @staticmethod
    def _normalize_text(value):
        return re.sub(r'\s+', ' ', html.unescape(value or '')).strip()

    @staticmethod
    def _meta(tree, name):
        values = tree.xpath(f'//meta[@property="{name}"]/@content')
        if not values:
            values = tree.xpath(f'//meta[@name="{name}"]/@content')
        return values[0].strip() if values and values[0].strip() else False

    @classmethod
    def _iter_json_nodes(cls, value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from cls._iter_json_nodes(child)
        elif isinstance(value, list):
            for child in value:
                yield from cls._iter_json_nodes(child)

    @classmethod
    def _json_ld_nodes(cls, tree):
        nodes = []
        for raw_value in tree.xpath('//script[@type="application/ld+json"]/text()'):
            try:
                payload = json.loads(raw_value)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            nodes.extend(cls._iter_json_nodes(payload))
        return nodes

    @classmethod
    def _product_json_ld(cls, tree):
        for node in cls._json_ld_nodes(tree):
            node_type = node.get('@type') if isinstance(node, dict) else None
            node_types = node_type if isinstance(node_type, list) else [node_type]
            if any(
                str(value).lower() == 'product'
                or str(value).lower().rstrip('/').endswith('/product')
                for value in node_types if value
            ):
                return node
        return {}

    @staticmethod
    def _first_scalar(value):
        if isinstance(value, list):
            for item in value:
                result = SitemapConnectorBlendCompanyEu._first_scalar(item)
                if result not in (None, False, ''):
                    return result
            return False
        if isinstance(value, dict):
            for key in ('url', 'contentUrl', 'value', 'name'):
                if key in value:
                    result = SitemapConnectorBlendCompanyEu._first_scalar(value[key])
                    if result not in (None, False, ''):
                        return result
            return False
        return value

    @staticmethod
    def _parse_price(value):
        if value in (None, False, ''):
            return 0.0
        text = html.unescape(str(value)).replace('\xa0', ' ')
        text = re.sub(r'[^0-9,.-]', '', text)
        if not text:
            return 0.0
        if ',' in text:
            text = text.replace('.', '').replace(',', '.')
        elif text.count('.') > 1:
            text = text.replace('.', '')
        try:
            return float(text)
        except ValueError:
            return 0.0

    @classmethod
    def _extract_offer(cls, product_json, tree, main_text):
        offers = product_json.get('offers') if isinstance(product_json, dict) else None
        offer_nodes = offers if isinstance(offers, list) else [offers]
        for offer in offer_nodes:
            if not isinstance(offer, dict):
                continue
            price = cls._parse_price(
                offer.get('price') or offer.get('lowPrice') or offer.get('salePrice')
            )
            if price:
                return price, offer.get('priceCurrency') or 'EUR'

        for meta_name in (
            'product:price:amount', 'og:price:amount', 'twitter:data1'
        ):
            price = cls._parse_price(cls._meta(tree, meta_name))
            if price:
                currency = (
                    cls._meta(tree, 'product:price:currency')
                    or cls._meta(tree, 'og:price:currency')
                    or 'EUR'
                )
                return price, currency

        # En rebajas la ficha puede mostrar primero el precio vigente y después
        # el original, incluso sin espacio entre ambos. Se usa el primer importe
        # visible con dos decimales y símbolo EUR.
        match = re.search(
            r'(?:€\s*([0-9]{1,5}[,.][0-9]{2})|'
            r'([0-9]{1,5}[,.][0-9]{2})\s*(?:€|EUR))',
            main_text,
            flags=re.IGNORECASE,
        )
        if match:
            return cls._parse_price(match.group(1) or match.group(2)), 'EUR'
        return 0.0, 'EUR'

    @classmethod
    def _extract_breadcrumb(cls, tree, product_name=''):
        values = []
        for node in cls._json_ld_nodes(tree):
            node_type = node.get('@type') if isinstance(node, dict) else None
            if str(node_type).lower() != 'breadcrumblist':
                continue
            elements = node.get('itemListElement') or []
            if not isinstance(elements, list):
                elements = [elements]
            ordered = []
            for index, element in enumerate(elements):
                if not isinstance(element, dict):
                    continue
                item = element.get('item')
                name = element.get('name')
                if not name and isinstance(item, dict):
                    name = item.get('name')
                try:
                    position = int(element.get('position') or index + 1)
                except (TypeError, ValueError):
                    position = index + 1
                if name:
                    ordered.append((position, cls._normalize_text(str(name))))
            values = [name for _position, name in sorted(ordered)]
            if values:
                break

        if not values:
            selectors = (
                '//*[contains(translate(@class, "BREADCRUMB", "breadcrumb"), "breadcrumb")]//a//text()',
                '//nav[contains(translate(@aria-label, "BREADCRUMB", "breadcrumb"), "breadcrumb")]//a//text()',
                '//*[@itemtype and contains(@itemtype, "BreadcrumbList")]//*[self::a or @itemprop="name"]//text()',
            )
            for selector in selectors:
                values = [cls._normalize_text(value) for value in tree.xpath(selector)]
                values = [value for value in values if value]
                if values:
                    break

        ignored = {
            'home', 'frontpage', 'blend', 'blend official brandsite',
            'shop', 'products', 'all products', 'new arrivals',
        }
        normalized_product_name = cls._normalize_text(product_name).lower()
        result = []
        for value in values:
            normalized = cls._normalize_text(value)
            if not normalized:
                continue
            lower_value = normalized.lower()
            if lower_value in ignored or lower_value == normalized_product_name:
                continue
            if normalized not in result:
                result.append(normalized)
        return result

    @classmethod
    def _extract_color_name(cls, product_json, tree, main_text):
        if isinstance(product_json, dict):
            color = cls._first_scalar(product_json.get('color'))
            if color:
                return cls._normalize_text(str(color))

        candidates = []
        for element in tree.xpath(
            '//*[contains(normalize-space(.), "Colour:") or '
            'contains(normalize-space(.), "Color:")]'
        ):
            text = cls._normalize_text(element.text_content())
            if len(text) <= 180:
                candidates.append(text)
        candidates.sort(key=len)

        pattern = (
            r'\b(?:Colour|Color)\s*:\s*(.+?)'
            r'(?=\s+(?:In stock|Sizes?|Lengths?|Size guide|Add to basket|'
            r'About the product|Preferred fibres|Payment|Care)\b|$)'
        )
        for text in candidates + [main_text]:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                color = cls._normalize_text(match.group(1)).strip(' ,;|-')
                if color:
                    return color
        return False

    @classmethod
    def _extract_about_product(cls, tree):
        for heading in tree.xpath('//h2 | //h3 | //button'):
            heading_text = cls._normalize_text(heading.text_content()).lower()
            if heading_text != 'about the product':
                continue

            controlled_id = heading.get('aria-controls')
            if controlled_id:
                targets = tree.xpath('//*[@id=$target]', target=controlled_id)
                if targets:
                    value = cls._normalize_text(targets[0].text_content())
                    if value and value.lower() != 'about the product':
                        return value

            sibling = heading.getnext()
            if sibling is not None:
                value = cls._normalize_text(sibling.text_content())
                if value and value.lower() != 'about the product':
                    return value
        return ''

    @classmethod
    def _extract_description(cls, product_json, tree):
        if isinstance(product_json, dict):
            description = cls._normalize_text(str(product_json.get('description') or ''))
            if description:
                return description
        description = cls._extract_about_product(tree)
        if description:
            return description
        return (
            cls._meta(tree, 'og:description')
            or cls._meta(tree, 'description')
            or ''
        )

    @staticmethod
    def _image_identity(value):
        parts = urlsplit(value)
        query = [
            (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in {
                'w', 'h', 'width', 'height', 'quality', 'format', 'rendition',
                'crop', 'fit', 'dpr', 'scale', 'cache', 'cb', 'q',
            }
        ]
        return parts.netloc.lower(), parts.path, tuple(query)

    @staticmethod
    def _image_score(url, descriptor=''):
        score = 0
        descriptor_match = re.search(r'(\d+)(?:w|x)?$', (descriptor or '').strip())
        if descriptor_match:
            score = int(descriptor_match.group(1))
        query = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
        for key in ('w', 'h', 'width', 'height', 'wid', 'hei'):
            try:
                score = max(score, int(query.get(key) or 0))
            except (TypeError, ValueError):
                pass
        return score

    @classmethod
    def _extract_images(cls, tree, product_json, page_url, reference, product_name):
        candidates = []

        json_images = product_json.get('image') if isinstance(product_json, dict) else None
        if json_images:
            json_images = json_images if isinstance(json_images, list) else [json_images]
            for value in json_images:
                image_url = cls._first_scalar(value)
                if image_url:
                    candidates.append((str(image_url), product_name, '', True))

        for meta_name in ('og:image', 'og:image:secure_url', 'twitter:image'):
            image_url = cls._meta(tree, meta_name)
            if image_url:
                candidates.append((image_url, product_name, '', True))

        for element in tree.xpath('//img | //source'):
            label = ' '.join(filter(None, [
                element.get('alt'), element.get('title'), element.get('aria-label')
            ]))
            for attribute in (
                'src', 'data-src', 'data-original', 'data-lazy-src',
                'data-image-url', 'data-zoom-image',
            ):
                image_url = element.get(attribute)
                if image_url:
                    candidates.append((image_url, label, '', False))
            for attribute in ('srcset', 'data-srcset'):
                for item in (element.get(attribute) or '').split(','):
                    pieces = item.strip().rsplit(None, 1)
                    if pieces and pieces[0]:
                        candidates.append((
                            pieces[0], label, pieces[1] if len(pieces) == 2 else '', False
                        ))

        reference_upper = (reference or '').upper()
        reference_compact = re.sub(r'[^A-Za-z0-9]', '', reference_upper)
        normalized_name = re.sub(r'[^a-z0-9]+', ' ', product_name.lower()).strip()
        best_by_identity = {}
        order = 0
        for raw_url, label, descriptor, trusted in candidates:
            raw_url = html.unescape(str(raw_url)).strip()
            if not raw_url or raw_url.startswith(('data:', 'blob:')):
                continue
            absolute_url = urljoin(page_url, raw_url)
            parsed = urlsplit(absolute_url)
            if parsed.scheme not in ('http', 'https'):
                continue
            lower_url = absolute_url.lower()
            if cls._NON_PRODUCT_IMAGE_RE.search(lower_url):
                continue
            if not trusted and not cls._IMAGE_EXT_RE.search(lower_url):
                # Se admiten endpoints de transformación de imágenes aunque no
                # terminen en extensión, siempre que identifiquen la referencia.
                if not reference_upper or reference_upper not in absolute_url.upper():
                    continue

            upper_url = absolute_url.upper()
            upper_label = (label or '').upper()
            compact_haystack = re.sub(r'[^A-Za-z0-9]', '', upper_url + ' ' + upper_label)
            matches_reference = bool(
                reference_upper
                and (
                    reference_upper in upper_url
                    or reference_upper in upper_label
                    or reference_compact in compact_haystack
                )
            )
            normalized_label = re.sub(r'[^a-z0-9]+', ' ', (label or '').lower()).strip()
            matches_name = bool(
                normalized_name
                and normalized_label
                and (
                    normalized_name in normalized_label
                    or normalized_label in normalized_name
                )
            )
            if not trusted and not matches_reference and not matches_name:
                continue

            identity = cls._image_identity(absolute_url)
            score = cls._image_score(absolute_url, descriptor)
            previous = best_by_identity.get(identity)
            if not previous or score > previous[0]:
                best_by_identity[identity] = (score, order, absolute_url)
            order += 1

        return [
            value[2]
            for value in sorted(best_by_identity.values(), key=lambda item: item[1])
        ]

    # ------------------------------------------------------------------
    # Ficha
    # ------------------------------------------------------------------
    def _parse_product_html(self, content, requested_url):
        requested_url = self._canonical_product_url(requested_url)
        requested_key = self._product_key(requested_url)
        if not requested_key:
            raise ValueError('La URL solicitada no es una ficha válida de Blend Europa.')

        tree = self._html_document(content)
        product_json = self._product_json_ld(tree)

        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical_candidate = (
            urljoin(requested_url, canonical_values[0].strip())
            if canonical_values and canonical_values[0].strip()
            else requested_url
        )
        canonical_url = self._canonical_product_url(canonical_candidate)
        canonical_key = self._product_key(canonical_url)
        if not canonical_key:
            canonical_url = requested_url
            canonical_key = requested_key
        if canonical_key != requested_key:
            raise ValueError(
                'La ficha de Blend ha redirigido a otra referencia; el producto '
                'solicitado puede estar descatalogado.'
            )

        main_nodes = tree.xpath('//main')
        main_node = main_nodes[0] if main_nodes else tree
        main_text = self._normalize_text(' '.join(main_node.itertext()))

        heading_values = tree.xpath('//main//h1//text()') or tree.xpath('//h1//text()')
        name = self._normalize_text(' '.join(heading_values))
        if not name:
            name = self._normalize_text(str(product_json.get('name') or ''))
        if not name:
            name = (
                self._meta(tree, 'og:title')
                or self._meta(tree, 'twitter:title')
                or self._humanize_slug(self._clean_slug(self._slug_from_url(canonical_url)))
            )
        name = re.sub(
            r'\s*[|–-]\s*Blend(?:\s+Official\s+Brandsite)?\s*$',
            '',
            name,
            flags=re.IGNORECASE,
        ).strip()

        style_code, numeric_color = requested_key
        reference = f'{style_code}-{numeric_color}'
        color_name = self._extract_color_name(product_json, tree, main_text)
        color_value = (
            f'{numeric_color} - {color_name}' if color_name else numeric_color
        )

        price, currency = self._extract_offer(product_json, tree, main_text)
        image_urls = self._extract_images(
            tree, product_json, canonical_url, reference, name
        )
        main_image_url = image_urls[0] if image_urls else False

        fallback_category = self.parse_category_path(canonical_url)
        breadcrumb = self._extract_breadcrumb(tree, product_name=name)
        # Migas demasiado genéricas no sustituyen la clasificación deducida de
        # la propia ficha. Cuando aportan una familia real, se prefieren.
        useful_breadcrumb = [
            value for value in breadcrumb
            if value.lower() not in {'men', 'man', 'clothing', 'apparel'}
        ]
        category_path = breadcrumb if useful_breadcrumb else fallback_category

        return {
            'name': name or canonical_url,
            'description': self._extract_description(product_json, tree),
            'price': price,
            'price_available': bool(price),
            'currency': currency or 'EUR',
            'main_image_url': main_image_url,
            'image_urls': image_urls,
            'canonical_url': canonical_url,
            'style_code': style_code,
            'color_code': color_value,
            'ean_variants': self._ean_variants_from_payload(product_json),
            'category_path': '/'.join(category_path),
        }

    def fetch_preview(self, source, url):
        session = self._get_session(source)
        response = self._http_get(session, url, source)
        return self._parse_product_html(response.content, response.url or url)
