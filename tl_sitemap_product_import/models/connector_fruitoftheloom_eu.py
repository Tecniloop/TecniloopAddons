import html
import json
import logging
import re
from urllib.parse import parse_qsl, unquote_plus, urljoin, urlparse, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorFruitOfTheLoomEu(models.AbstractModel):
    """Conector para el catálogo europeo público de Fruit of the Loom.

    El sitio es una Salesforce Experience Cloud. El sitemap facilitado es un
    ``sitemap-view-N.xml`` estándar y las fichas actuales tienen la forma::

        https://www.fruitoftheloom.eu/shop/p/valueweight-t/0610360

    La referencia estable es el último segmento (``0610360``). La consulta
    ``?color=...`` selecciona un color dentro de la misma ficha y no representa
    un producto independiente en esta versión del importador, que todavía crea
    productos simples. Por eso las URLs se deduplican sin query string.

    Fruit of the Loom funciona como catálogo para distribuidores y normalmente
    no publica un precio de venta en la ficha. El conector intenta leer JSON-LD,
    Open Graph y el HTML visible, pero devuelve 0.0 cuando no existe un precio
    público, sin inferirlo ni inventarlo.
    """

    _name = 'sitemap.connector.fruitoftheloom_eu'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Fruit of the Loom Europa'

    _HOSTS = {'www.fruitoftheloom.eu', 'fruitoftheloom.eu'}
    _PRODUCT_PATH_RE = re.compile(
        r'^/shop/p/(?P<slug>[^/?#]+)/(?P<style>[A-Za-z0-9][A-Za-z0-9-]*)/?$',
        re.IGNORECASE,
    )
    _IMAGE_EXT_RE = re.compile(r'\.(?:avif|gif|jpe?g|png|webp)(?:$|\?)', re.IGNORECASE)
    _NON_PRODUCT_IMAGE_RE = re.compile(
        r'(?:logo|icon|flag|sprite|favicon|payment|social|newsletter|placeholder|spinner)',
        re.IGNORECASE,
    )
    _CATALOG_URL = 'https://www.fruitoftheloom.eu/shop/c/Fruit-Europe'

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
            'Accept-Language': 'es-ES,es;q=0.9,en-GB;q=0.6,en;q=0.4',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
        })
        return session

    @staticmethod
    def _xml_root(content):
        parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
        return etree.fromstring(content, parser=parser)

    @staticmethod
    def _local_name(element):
        return etree.QName(element).localname.lower()

    def _read_sitemap(self, source, sitemap_url, depth=0, visited=None):
        """Lee urlset o sitemapindex usando local-name para tolerar namespaces.

        Devuelve pares ``(entry, image_urls)``. Experience Cloud genera un
        ``urlset`` normal, pero se admite también un índice por si Salesforce
        divide el sitemap en el futuro.
        """
        if depth > 3:
            raise ValueError(
                'El sitemap de Fruit of the Loom supera tres niveles de índices.'
            )
        visited = visited or set()
        sitemap_url = self._without_query_fragment(sitemap_url)
        if sitemap_url in visited:
            return
        visited.add(sitemap_url)

        session = self._get_session(source)
        response = self._http_get(session, sitemap_url, source)
        try:
            root = self._xml_root(response.content)
        except (ValueError, etree.XMLSyntaxError) as exc:
            content_type = response.headers.get('Content-Type', '')
            raise ValueError(
                'Fruit of the Loom no devolvió un sitemap XML válido en '
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
            for child_url in child_urls:
                yield from self._read_sitemap(
                    source,
                    urljoin(sitemap_url, child_url),
                    depth=depth + 1,
                    visited=visited,
                )
            return

        if root_name != 'urlset':
            raise ValueError(
                'El sitemap de Fruit of the Loom no contiene <urlset> ni '
                '<sitemapindex>.'
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

    @staticmethod
    def _without_query_fragment(value):
        parts = urlsplit(value)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))

    @classmethod
    def _product_match(cls, value):
        parsed = urlparse(value)
        if parsed.netloc.lower() not in cls._HOSTS:
            return False
        return cls._PRODUCT_PATH_RE.match(parsed.path)

    @classmethod
    def _canonical_product_url(cls, value):
        value = cls._without_query_fragment(value)
        parsed = urlsplit(value)
        host = parsed.netloc.lower()
        if host == 'fruitoftheloom.eu':
            host = 'www.fruitoftheloom.eu'
        path = parsed.path.rstrip('/')
        return urlunsplit((parsed.scheme or 'https', host, path, '', ''))

    @classmethod
    def _product_urls_from_catalog_html(cls, content, page_url):
        tree = cls._html_document(content)
        urls = []
        seen = set()
        for href in tree.xpath('//a[@href]/@href'):
            product_url = cls._canonical_product_url(urljoin(page_url, href))
            if not cls._product_match(product_url) or product_url in seen:
                continue
            seen.add(product_url)
            urls.append(product_url)
        return urls

    @classmethod
    def _next_catalog_page_url(cls, content, current_url):
        tree = cls._html_document(content)
        current_parts = urlsplit(current_url)
        current_query = dict(parse_qsl(current_parts.query, keep_blank_values=True))
        try:
            current_page = int(current_query.get('page') or -1)
        except (TypeError, ValueError):
            current_page = -1

        candidates = []
        for href in tree.xpath('//a[@href]/@href'):
            absolute = urljoin(current_url, href)
            parts = urlsplit(absolute)
            if parts.netloc.lower() not in cls._HOSTS:
                continue
            if parts.path.rstrip('/').lower() != current_parts.path.rstrip('/').lower():
                continue
            query = dict(parse_qsl(parts.query, keep_blank_values=True))
            try:
                page_number = int(query.get('page'))
            except (TypeError, ValueError):
                continue
            if page_number > current_page:
                candidates.append((page_number, urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))))
        return min(candidates, key=lambda item: item[0])[1] if candidates else False

    def _iter_catalog_entries(self, source, sitemap_error=None):
        if sitemap_error:
            _logger.warning(
                'Fruit of the Loom: el sitemap no se pudo procesar (%s); '
                'se usa el catálogo paginado como respaldo.',
                sitemap_error,
            )
        session = self._get_session(source)
        page_url = self._CATALOG_URL
        visited_pages = set()
        seen_products = set()

        for _page_index in range(20):
            page_key = urlunsplit(urlsplit(page_url)._replace(fragment=''))
            if page_key in visited_pages:
                raise ValueError(
                    'La paginación de Fruit of the Loom ha entrado en un bucle.'
                )
            visited_pages.add(page_key)

            response = self._http_get(session, page_url, source)
            effective_url = response.url or page_url
            product_urls = self._product_urls_from_catalog_html(
                response.content, effective_url
            )
            new_urls = [url for url in product_urls if url not in seen_products]
            if not product_urls and not seen_products:
                raise ValueError(
                    'El catálogo público de Fruit of the Loom no contiene enlaces '
                    'de producto reconocibles.'
                )
            if not new_urls:
                return

            for product_url in new_urls:
                seen_products.add(product_url)
                yield {'url': product_url, 'lastmod': False}, []

            next_page = self._next_catalog_page_url(response.content, effective_url)
            if not next_page:
                return
            page_url = next_page

        raise ValueError(
            'Se alcanzó el límite de 20 páginas del catálogo de Fruit of the Loom.'
        )

    def _collect_product_entries(self, raw_entries, category_filter=None, limit=0):
        entries = []
        seen = set()
        product_count = 0
        filter_text = (category_filter or '').strip().lower()

        for entry, _images in raw_entries:
            product_url = self._canonical_product_url(entry['url'])
            if not self._product_match(product_url):
                continue
            product_count += 1
            if product_url in seen:
                continue

            category_path = '/'.join(self.parse_category_path(product_url)).lower()
            haystack = f'{product_url.lower()} {category_path}'
            if filter_text and filter_text not in haystack:
                continue

            seen.add(product_url)
            entries.append({
                'url': product_url,
                'lastmod': entry.get('lastmod') or False,
            })
            if limit and len(entries) >= limit:
                break
        return entries, product_count

    def get_product_entries(self, source, category_filter=None, limit=0):
        sitemap_error = None
        try:
            entries, product_count = self._collect_product_entries(
                self._read_sitemap(source, source.sitemap_index_url),
                category_filter=category_filter,
                limit=limit,
            )
            if product_count:
                return entries
        except Exception as exc:
            sitemap_error = exc

        entries, _product_count = self._collect_product_entries(
            self._iter_catalog_entries(source, sitemap_error=sitemap_error),
            category_filter=category_filter,
            limit=limit,
        )
        return entries

    def get_image_map(self, source):
        image_map = {}
        try:
            raw_entries = self._read_sitemap(source, source.sitemap_index_url)
            for entry, image_urls in raw_entries:
                product_url = self._canonical_product_url(entry['url'])
                if not self._product_match(product_url) or not image_urls:
                    continue
                target = image_map.setdefault(product_url, [])
                for image_url in image_urls:
                    absolute_url = urljoin(product_url, html.unescape(image_url))
                    if absolute_url not in target:
                        target.append(absolute_url)
        except Exception as exc:
            # La ficha conserva su propia galería, por lo que un fallo del sitemap
            # de imágenes no debe impedir importar un producto ya previsualizado.
            _logger.warning(
                'Fruit of the Loom: no se pudo obtener el mapa de imágenes del '
                'sitemap: %s',
                exc,
            )
        return image_map

    # ------------------------------------------------------------------
    # URL, referencia y clasificación de respaldo
    # ------------------------------------------------------------------
    @classmethod
    def _style_from_url(cls, value):
        match = cls._product_match(value)
        return match.group('style').upper() if match else False

    @classmethod
    def _slug_from_url(cls, value):
        match = cls._product_match(value)
        return match.group('slug') if match else ''

    @staticmethod
    def _humanize_slug(value):
        value = unquote_plus(value or '').replace('_', ' ').replace('-', ' ')
        return re.sub(r'\s+', ' ', value).strip().title()

    @classmethod
    def parse_category_path(cls, url):
        """Clasificación prudente cuando el sitemap no codifica la categoría.

        La ficha puede sustituir esta ruta por sus migas de pan. Para el
        explorador de categorías, que solo consulta el sitemap, se usan reglas
        basadas en nombres públicos estables del catálogo.
        """
        slug = cls._slug_from_url(url).lower()
        if not slug:
            return []

        if re.search(r'(?:^|-)(?:ladies|lady|women|womens)(?:-|$)', slug):
            audience = 'Ladies'
        elif re.search(r'(?:^|-)(?:kids|kid|children|childrens)(?:-|$)', slug):
            audience = 'Kids'
        else:
            audience = 'Men and Unisex'

        if re.search(r'(?:polo)', slug):
            family = 'Polo Shirts'
        elif re.search(r'(?:sweat|hood|hoodie|zip-neck|sweatshirt)', slug):
            family = 'Sweatshirts'
        elif re.search(r'(?:jog|pants|shorts|trousers)', slug):
            family = 'Trousers and Shorts'
        elif re.search(r'(?:shirt)', slug) and not re.search(r'(?:t-shirt|tee)', slug):
            family = 'Shirts'
        elif re.search(r'(?:vest|baseball|ringer|(?:^|-)t(?:-|$)|t-shirt|tee)', slug):
            family = 'T-Shirts'
        else:
            family = 'Other Products'
        return [audience, family]

    # ------------------------------------------------------------------
    # HTML / JSON-LD
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
    def _product_json_ld(cls, tree):
        candidates = []
        for raw_value in tree.xpath('//script[@type="application/ld+json"]/text()'):
            try:
                payload = json.loads(raw_value)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            for node in cls._iter_json_nodes(payload):
                node_type = node.get('@type')
                node_types = node_type if isinstance(node_type, list) else [node_type]
                if any(
                    str(value).lower() == 'product'
                    or str(value).lower().rstrip('/').endswith('/product')
                    for value in node_types if value
                ):
                    candidates.append(node)
        return candidates[0] if candidates else {}

    @staticmethod
    def _first_scalar(value):
        if isinstance(value, list):
            for item in value:
                result = SitemapConnectorFruitOfTheLoomEu._first_scalar(item)
                if result not in (None, False, ''):
                    return result
            return False
        if isinstance(value, dict):
            for key in ('url', 'contentUrl', 'value', 'name'):
                if key in value:
                    result = SitemapConnectorFruitOfTheLoomEu._first_scalar(value[key])
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
            price = cls._parse_price(offer.get('price') or offer.get('lowPrice'))
            if price:
                return price, offer.get('priceCurrency') or 'EUR'

        for meta_name in ('product:price:amount', 'og:price:amount'):
            price = cls._parse_price(cls._meta(tree, meta_name))
            if price:
                currency = (
                    cls._meta(tree, 'product:price:currency')
                    or cls._meta(tree, 'og:price:currency')
                    or 'EUR'
                )
                return price, currency

        # El catálogo normalmente no muestra precio. Este respaldo solo acepta
        # importes con dos decimales y símbolo de moneda para evitar confundir
        # gramajes, tallas o cantidades de caja con precios.
        match = re.search(
            r'(?<![\d.,])([0-9]{1,5}[,.][0-9]{2})\s*(€|EUR)(?=\s|$)',
            main_text,
            flags=re.IGNORECASE,
        )
        if match:
            return cls._parse_price(match.group(1)), 'EUR'
        return 0.0, 'EUR'

    @classmethod
    def _extract_breadcrumb(cls, tree):
        selectors = (
            '//*[contains(translate(@class, "BREADCRUMB", "breadcrumb"), "breadcrumb")]//a//text()',
            '//nav[contains(translate(@aria-label, "BREADCRUMB", "breadcrumb"), "breadcrumb")]//a//text()',
            '//*[@itemtype and contains(@itemtype, "BreadcrumbList")]//*[self::a or @itemprop="name"]//text()',
        )
        values = []
        for selector in selectors:
            values = [cls._normalize_text(value) for value in tree.xpath(selector)]
            values = [value for value in values if value]
            if values:
                break

        ignored = {
            'home', 'inicio', 'products', 'productos', 'fruit europe',
            'fruit of the loom', 'view all', 'ver todo',
        }
        result = []
        for value in values:
            if value.lower() in ignored or value in result:
                continue
            result.append(value)
        return result

    @classmethod
    def _image_identity(cls, value):
        parts = urlsplit(value)
        query = [
            (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in {
                'w', 'h', 'width', 'height', 'quality', 'format', 'rendition',
                'crop', 'fit', 'dpr', 'scale', 'cache', 'cb',
            }
        ]
        return (parts.netloc.lower(), parts.path, tuple(query))

    @classmethod
    def _style_tokens(cls, style_code):
        compact = re.sub(r'[^A-Za-z0-9]', '', style_code or '').upper()
        if not compact:
            return set()
        tokens = {compact}
        if len(compact) == 7:
            tokens.add(f'{compact[:2]}-{compact[2:5]}-{compact[5:]}')
            tokens.add(f'{compact[:3]}-{compact[3:]}')
        return tokens

    @classmethod
    def _extract_images(cls, tree, product_json, page_url, style_code, product_name):
        candidates = []

        json_images = product_json.get('image') if isinstance(product_json, dict) else None
        if json_images:
            json_images = json_images if isinstance(json_images, list) else [json_images]
            for value in json_images:
                image_url = cls._first_scalar(value)
                if image_url:
                    candidates.append((str(image_url), product_name, True))

        for meta_name in ('og:image', 'og:image:secure_url', 'twitter:image'):
            image_url = cls._meta(tree, meta_name)
            if image_url:
                candidates.append((image_url, product_name, True))

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
                    candidates.append((image_url, label, False))
            for attribute in ('srcset', 'data-srcset'):
                for item in (element.get(attribute) or '').split(','):
                    pieces = item.strip().rsplit(None, 1)
                    if pieces and pieces[0]:
                        candidates.append((pieces[0], label, False))

        tokens = cls._style_tokens(style_code)
        normalized_name = re.sub(r'[^a-z0-9]+', ' ', product_name.lower()).strip()
        best_by_identity = {}
        for raw_url, label, trusted in candidates:
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
            if (
                not trusted
                and not cls._IMAGE_EXT_RE.search(lower_url)
                and not any(
                    token in lower_url
                    for token in ('/cms/delivery/media/', '/sfsites/c/')
                )
            ):
                continue

            upper_url = absolute_url.upper()
            normalized_label = re.sub(r'[^a-z0-9]+', ' ', (label or '').lower()).strip()
            matches_style = bool(tokens and any(token in upper_url for token in tokens))
            matches_name = bool(
                normalized_name
                and normalized_label
                and (
                    normalized_name in normalized_label
                    or normalized_label in normalized_name
                )
            )
            if not trusted and not matches_style and not matches_name:
                continue

            identity = cls._image_identity(absolute_url)
            # Prefiere la URL con más información/longitud; suele ser la versión
            # de mayor resolución dentro de un srcset.
            previous = best_by_identity.get(identity)
            score = len(absolute_url)
            if not previous or score > previous[0]:
                best_by_identity[identity] = (score, absolute_url)

        return [value[1] for value in best_by_identity.values()]

    @classmethod
    def _extract_color(cls, product_json, tree, main_text, requested_url):
        query = dict(parse_qsl(urlsplit(requested_url).query, keep_blank_values=True))
        if query.get('color'):
            return cls._normalize_text(unquote_plus(query['color']))
        if isinstance(product_json, dict):
            color = cls._first_scalar(product_json.get('color'))
            if color:
                return cls._normalize_text(str(color))
        match = re.search(
            r'\b(?:Color|Colour)\s*:?\s*([^|\n]{2,80}?)'
            r'(?=\s+(?:Size|Talla|Sizes|Available)\b|$)',
            main_text,
            flags=re.IGNORECASE,
        )
        return cls._normalize_text(match.group(1)) if match else False

    def _parse_product_html(self, content, requested_url):
        tree = self._html_document(content)
        product_json = self._product_json_ld(tree)

        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical_candidate = (
            urljoin(requested_url, canonical_values[0].strip())
            if canonical_values and canonical_values[0].strip()
            else requested_url
        )
        canonical_url = self._canonical_product_url(canonical_candidate)
        if not self._product_match(canonical_url):
            # Algunos despliegues de Experience Cloud omiten o reemplazan la
            # canónica durante la carga inicial. La URL solicitada sigue siendo
            # válida si conserva el patrón de ficha.
            canonical_url = self._canonical_product_url(requested_url)
        if not self._product_match(canonical_url):
            raise ValueError(
                'La URL ya no apunta a una ficha válida de Fruit of the Loom.'
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
                or self._humanize_slug(self._slug_from_url(canonical_url))
            )
        name = re.sub(
            r'\s*[|–-]\s*Fruit\s+of\s+the\s+Loom(?:\s+Europe)?\s*$',
            '',
            name,
            flags=re.IGNORECASE,
        ).strip()

        style_code = self._style_from_url(canonical_url)
        visible_style = re.search(
            r'\b(?:Style|Product|Artículo|Referencia|Ref\.?|Código)\s*#?\s*:?' 
            r'\s*([0-9]{2,3}(?:-?[0-9]{3})-?[0-9])\b',
            main_text,
            flags=re.IGNORECASE,
        )
        if visible_style:
            style_code = re.sub(r'[^0-9A-Za-z]', '', visible_style.group(1)).upper()

        description = self._normalize_text(str(product_json.get('description') or ''))
        if not description:
            description = (
                self._meta(tree, 'og:description')
                or self._meta(tree, 'description')
                or ''
            )

        price, currency = self._extract_offer(product_json, tree, main_text)
        image_urls = self._extract_images(
            tree, product_json, canonical_url, style_code, name
        )
        main_image_url = image_urls[0] if image_urls else False

        fallback_category = self.parse_category_path(canonical_url)
        breadcrumb = self._extract_breadcrumb(tree)
        # Mantiene la misma ruta que ve el explorador de categorías. Solo se
        # recurre a las migas de pan cuando el slug no permite clasificar la
        # familia con seguridad.
        category_path = fallback_category
        if not fallback_category or fallback_category[-1] == 'Other Products':
            category_path = breadcrumb or fallback_category

        return {
            'name': name or canonical_url,
            'description': description,
            'price': price,
            'price_available': bool(price),
            'currency': currency or 'EUR',
            'main_image_url': main_image_url,
            'image_urls': image_urls,
            'canonical_url': canonical_url,
            'style_code': style_code,
            'color_code': self._extract_color(
                product_json, tree, main_text, requested_url
            ),
            'ean_variants': self._ean_variants_from_payload(product_json),
            'category_path': '/'.join(category_path),
        }

    def fetch_preview(self, source, url):
        session = self._get_session(source)
        response = self._http_get(session, url, source)
        return self._parse_product_html(response.content, response.url or url)
