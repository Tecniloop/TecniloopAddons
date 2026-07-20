import gzip
import html
import logging
import re
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorLevisEs(models.AbstractModel):
    """Conector para el catálogo español de Levi's.

    Levi's usa URLs de producto jerárquicas cuyo final estable es ``/p/<style>``.
    El sitemap suministrado puede ser tanto un ``urlset`` como un índice de otros
    sitemaps, por lo que el conector detecta ambos formatos y admite índices
    anidados y ficheros XML comprimidos con gzip.

    Las fichas se procesan desde el HTML público. Se extraen el título, el precio
    vigente, el color, la descripción de "Acerca de este estilo", el código de
    estilo y las imágenes del producto servidas por Adobe Scene7. Las imágenes
    de productos relacionados se descartan comparando el identificador del
    recurso con el código de estilo de la URL.
    """

    _name = 'sitemap.connector.levis_es'
    _inherit = 'sitemap.import.service'
    _description = "Conector Levi's España"

    _PRODUCT_PATH_RE = re.compile(r'/p/([^/?#]+)/?$', re.IGNORECASE)
    _SCENE7_HOST = 'lscoglobal.scene7.com'
    _SCENE7_PATH = '/is/image/lscoglobal/'

    # ------------------------------------------------------------------
    # HTTP y sitemap
    # ------------------------------------------------------------------
    def _get_session(self, source):
        """Usa cabeceras de navegador para evitar respuestas HTML de protección.

        No se falsea ninguna sesión ni se eluden controles de acceso: simplemente
        se solicita el recurso público con cabeceras que el frontal de Levi's
        espera habitualmente de un navegador normal.
        """
        session = super()._get_session(source)
        session.headers.update({
            'Accept': (
                'text/html,application/xhtml+xml,application/xml;q=0.9,'
                'image/avif,image/webp,*/*;q=0.8'
            ),
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.5',
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

    def _iter_sitemap_entries(self, source, sitemap_url, depth=0, visited=None):
        """Generador recursivo que acepta urlset, sitemapindex y XML .gz."""
        if depth > 3:
            _logger.warning("Levi's: se ignora un índice de sitemap con profundidad > 3: %s", sitemap_url)
            return
        visited = visited or set()
        if sitemap_url in visited:
            return
        visited.add(sitemap_url)

        session = self._get_session(source)
        response = self._http_get(session, sitemap_url, source)
        root = self._xml_root(response.content)
        root_name = self._local_name(root)

        if root_name == 'urlset':
            for url_el in root.xpath('./*[local-name()="url"]'):
                loc_values = url_el.xpath('./*[local-name()="loc"]/text()')
                if not loc_values:
                    continue
                lastmod_values = url_el.xpath('./*[local-name()="lastmod"]/text()')
                yield {
                    'url': loc_values[0].strip(),
                    'lastmod': self._parse_lastmod(lastmod_values[0] if lastmod_values else None),
                }
            return

        if root_name != 'sitemapindex':
            raise ValueError(
                "El sitemap de Levi's no es un <urlset> ni un <sitemapindex> válido."
            )

        child_urls = [
            value.strip()
            for value in root.xpath('./*[local-name()="sitemap"]/*[local-name()="loc"]/text()')
            if value and value.strip()
        ]
        # Si los nombres permiten identificar sitemaps de producto, evitamos leer
        # páginas editoriales/categorías. Si no, se recorren todos y se filtran las
        # URLs finales por el patrón inequívoco /p/<código>.
        product_named = [
            value for value in child_urls
            if any(token in value.lower() for token in ('product', 'products', 'pdp'))
        ]
        if product_named:
            child_urls = product_named

        for child_url in child_urls:
            yield from self._iter_sitemap_entries(
                source, child_url, depth=depth + 1, visited=visited
            )

    @classmethod
    def _is_spanish_product_url(cls, value):
        parsed = urlparse(value)
        return (
            parsed.netloc.lower() in ('www.levi.com', 'levi.com')
            and parsed.path.lower().startswith('/es/es_es/')
            and bool(cls._PRODUCT_PATH_RE.search(parsed.path))
        )

    @staticmethod
    def _without_query_fragment(value):
        parts = urlsplit(value)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))

    @staticmethod
    def _html_document(content):
        # El frontal europeo de Levi's publica UTF-8. Forzar la decodificación
        # evita que un HTML sin cabecera/meta charset convierta ``€`` en mojibake
        # y haga fallar la detección de precio o textos acentuados.
        if isinstance(content, (bytes, bytearray)):
            content = bytes(content).decode('utf-8', errors='replace')
        return lxml_html.fromstring(content)

    @classmethod
    def _catalog_url_from_html(cls, content, base_url):
        """Localiza el catálogo general cuando ``sitemap.xml`` devuelve HTML.

        Levi's puede redirigir la URL facilitada a su mapa del sitio visible en
        navegador. Ese documento no contiene todas las fichas, pero sí enlaza el
        catálogo ``ropa/c/levi_clothing``. Se usa únicamente como respaldo del
        sitemap XML, nunca como primera opción.
        """
        try:
            tree = cls._html_document(content)
        except (TypeError, ValueError, etree.ParserError):
            tree = None

        if tree is not None:
            for href in tree.xpath('//a[@href]/@href'):
                absolute_url = cls._without_query_fragment(urljoin(base_url, href))
                parsed = urlparse(absolute_url)
                if (
                    parsed.netloc.lower() in ('www.levi.com', 'levi.com')
                    and parsed.path.lower().startswith('/es/es_es/')
                    and parsed.path.lower().rstrip('/').endswith('/ropa/c/levi_clothing')
                ):
                    return absolute_url

        parsed = urlparse(base_url)
        locale_match = re.match(r'^/(ES/es_ES)(?:/|$)', parsed.path, flags=re.IGNORECASE)
        if locale_match and parsed.scheme and parsed.netloc:
            locale = locale_match.group(1)
            return f'{parsed.scheme}://{parsed.netloc}/{locale}/ropa/c/levi_clothing'
        return 'https://www.levi.com/ES/es_ES/ropa/c/levi_clothing'

    @classmethod
    def _product_urls_from_catalog_html(cls, content, page_url):
        """Extrae solo enlaces PDP españoles de una página de categoría."""
        tree = cls._html_document(content)
        urls = []
        seen = set()
        for href in tree.xpath('//a[@href]/@href'):
            product_url = cls._without_query_fragment(urljoin(page_url, href))
            if not cls._is_spanish_product_url(product_url) or product_url in seen:
                continue
            seen.add(product_url)
            urls.append(product_url)
        return urls

    @staticmethod
    def _catalog_page_url(catalog_url, page_number):
        if not page_number:
            return catalog_url
        parts = urlsplit(catalog_url)
        query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != 'page']
        query.append(('page', str(page_number)))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))

    @classmethod
    def _next_catalog_page_url(cls, content, current_url):
        """Devuelve la siguiente página enlazada por la paginación pública."""
        tree = cls._html_document(content)
        current_parts = urlsplit(current_url)
        current_query = dict(parse_qsl(current_parts.query, keep_blank_values=True))
        try:
            current_page = int(current_query.get('page') or 0)
        except (TypeError, ValueError):
            current_page = 0

        candidates = []
        for href in tree.xpath('//a[@href]/@href'):
            absolute = urljoin(current_url, href)
            parts = urlsplit(absolute)
            if parts.netloc.lower() not in ('www.levi.com', 'levi.com'):
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
        """Respaldo para el mapa HTML: recorre la paginación del catálogo.

        La paginación pública de Levi's usa ``?page=1`` para la segunda página.
        Se detiene cuando una página no contiene fichas nuevas. El límite de 100
        páginas evita bucles si el frontal cambia o redirige páginas inexistentes.
        """
        session = self._get_session(source)
        fallback_reason = sitemap_error or 'sin URLs de producto'
        try:
            sitemap_response = self._http_get(session, source.sitemap_index_url, source)
            catalog_url = self._catalog_url_from_html(
                sitemap_response.content,
                sitemap_response.url or source.sitemap_index_url,
            )
        except Exception as exc:
            # También puede ocurrir que el endpoint ``sitemap.xml`` sea bloqueado
            # mientras las categorías y fichas públicas siguen accesibles.
            fallback_reason = f'{fallback_reason}; segundo acceso al sitemap: {exc}'
            catalog_url = self._catalog_url_from_html(b'', source.sitemap_index_url)

        _logger.warning(
            "Levi's: el recurso %s no se pudo usar como sitemap XML (%s). "
            'Se recurre al catálogo paginado %s; las entradas no tendrán lastmod.',
            source.sitemap_index_url,
            fallback_reason,
            catalog_url,
        )

        seen = set()
        visited_pages = set()
        page_url = catalog_url
        for _page_index in range(100):
            normalized_page_url = self._without_query_fragment(page_url)
            page_key = (normalized_page_url, urlsplit(page_url).query)
            if page_key in visited_pages:
                raise ValueError("La paginación del catálogo de Levi's ha entrado en un bucle.")
            visited_pages.add(page_key)

            response = self._http_get(session, page_url, source)
            effective_url = response.url or page_url
            product_urls = self._product_urls_from_catalog_html(response.content, effective_url)
            new_urls = [url for url in product_urls if url not in seen]
            if not product_urls:
                raise ValueError(
                    "Una página enlazada del catálogo de Levi's no contiene fichas de producto: "
                    f'{effective_url}'
                )
            if not new_urls:
                raise ValueError(
                    "Una página enlazada del catálogo de Levi's solo repite productos ya leídos: "
                    f'{effective_url}'
                )

            for product_url in new_urls:
                seen.add(product_url)
                yield {'url': product_url, 'lastmod': False}

            next_page_url = self._next_catalog_page_url(response.content, effective_url)
            if not next_page_url:
                return
            page_url = next_page_url

        raise ValueError(
            "Se alcanzó el límite de 100 páginas del catálogo de Levi's; "
            'revise la paginación antes de archivar productos.'
        )

    def _collect_product_entries(self, raw_entries, category_filter=None, limit=0):
        entries = []
        seen = set()
        product_count = 0
        filter_text = (category_filter or '').strip().lower()

        for entry in raw_entries:
            product_url = self._without_query_fragment(entry['url'])
            if not self._is_spanish_product_url(product_url):
                continue
            product_count += 1

            category_path = '/'.join(self.parse_category_path(product_url)).lower()
            if filter_text and filter_text not in category_path and filter_text not in product_url.lower():
                continue
            if product_url in seen:
                continue

            seen.add(product_url)
            entries.append({'url': product_url, 'lastmod': entry.get('lastmod') or False})
            if limit and len(entries) >= limit:
                break
        return entries, product_count

    def get_product_entries(self, source, category_filter=None, limit=0):
        sitemap_error = None
        try:
            entries, product_count = self._collect_product_entries(
                self._iter_sitemap_entries(source, source.sitemap_index_url),
                category_filter=category_filter,
                limit=limit,
            )
            # Si el sitemap era válido y sí contenía productos, una lista vacía
            # puede ser simplemente el resultado normal del filtro solicitado.
            if product_count:
                return entries
        except Exception as exc:  # el respaldo informa del motivo exacto en log
            sitemap_error = exc

        fallback_entries, _product_count = self._collect_product_entries(
            self._iter_catalog_entries(source, sitemap_error=sitemap_error),
            category_filter=category_filter,
            limit=limit,
        )
        return fallback_entries

    def get_image_map(self, source):
        # La propia ficha ofrece la galería completa y permite descartar imágenes
        # de productos relacionados. Releer el sitemap entero aquí duplicaría una
        # operación costosa sin aportar imágenes adicionales fiables.
        return {}

    # ------------------------------------------------------------------
    # URL, categoría y datos básicos
    # ------------------------------------------------------------------
    @classmethod
    def _style_from_url(cls, value):
        match = cls._PRODUCT_PATH_RE.search(urlparse(value).path)
        return unquote(match.group(1)).upper() if match else False

    @staticmethod
    def _humanize_slug(value):
        value = unquote(value).replace('_', ' ').replace('-', ' ')
        value = re.sub(r'\s+', ' ', value).strip()
        return value.title()

    @classmethod
    def parse_category_path(cls, url):
        parts = [unquote(part) for part in urlparse(url).path.split('/') if part]
        lower_parts = [part.lower() for part in parts]
        try:
            locale_index = lower_parts.index('es_es')
            product_marker_index = lower_parts.index('p', locale_index + 1)
        except ValueError:
            return []

        # El segmento inmediatamente anterior a /p/ es el slug del producto.
        category_slugs = parts[locale_index + 1:max(locale_index + 1, product_marker_index - 1)]
        return [cls._humanize_slug(part) for part in category_slugs if part]

    @staticmethod
    def _normalize_text(value):
        return re.sub(r'\s+', ' ', html.unescape(value or '')).strip()

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

    @staticmethod
    def _meta(tree, name):
        values = tree.xpath(f'//meta[@property="{name}"]/@content')
        if not values:
            values = tree.xpath(f'//meta[@name="{name}"]/@content')
        return values[0].strip() if values else False

    @classmethod
    def _extract_price(cls, tree, main_text):
        for meta_name in (
            'product:price:amount',
            'og:price:amount',
            'twitter:data1',
        ):
            value = cls._meta(tree, meta_name)
            price = cls._parse_price(value)
            if price:
                return price

        patterns = (
            r'(?:Sale\s+price\s+is|Precio\s+(?:de\s+venta\s+)?(?:es\s+)?)\s*([0-9][0-9.,]*)\s*€',
            r'(?:Ahora|Oferta)\s*([0-9][0-9.,]*)\s*€',
        )
        for pattern in patterns:
            match = re.search(pattern, main_text, flags=re.IGNORECASE)
            if match:
                price = cls._parse_price(match.group(1))
                if price:
                    return price

        # Último respaldo: primer precio decimal dentro del contenido principal.
        # Se evita aceptar importes enteros para no confundir tallas o descuentos.
        match = re.search(r'(?<![\d.,])([0-9]{1,4}[,.][0-9]{2})\s*€', main_text)
        return cls._parse_price(match.group(1)) if match else 0.0

    @classmethod
    def _extract_color(cls, tree, main_text):
        candidates = []
        for element in tree.xpath('//*[contains(normalize-space(.), "Color:")]'):
            text = cls._normalize_text(element.text_content())
            if text.lower().startswith('color:') and len(text) <= 180:
                candidates.append(text)
        candidates.sort(key=len)

        for text in candidates + [main_text]:
            match = re.search(
                r'\bColor:\s*(.+?)(?=\s+(?:Elasticidad|Cintura|Longitud|Talla|'
                r'Seleccionar|Guía|Añadir|Acerca de|Style\s*#|Ajuste)\b|$)',
                text,
                flags=re.IGNORECASE,
            )
            if match:
                color = cls._normalize_text(match.group(1)).strip(' ,;|-')
                if color:
                    return color
        return False

    @classmethod
    def _extract_description(cls, tree, main_text):
        match = re.search(
            r'Acerca\s+de\s+este\s+estilo\s+(.+?)(?=\s+(?:Ajuste|Composición\s+y\s+cuidado|Reseñas)\b)',
            main_text,
            flags=re.IGNORECASE,
        )
        if match:
            return cls._normalize_text(match.group(1))
        return cls._meta(tree, 'og:description') or cls._meta(tree, 'description') or ''

    # ------------------------------------------------------------------
    # Imágenes Scene7
    # ------------------------------------------------------------------
    @staticmethod
    def _style_asset_tokens(style_code):
        if not style_code:
            return set()
        compact = re.sub(r'[^A-Za-z0-9]', '', style_code).upper()
        tokens = {compact}
        if len(compact) > 4:
            tokens.add(f'{compact[:5]}-{compact[5:]}')
            tokens.add(f'{compact[:5]}_{compact[5:]}')
        return {token for token in tokens if token}

    @classmethod
    def _image_score(cls, url, descriptor=''):
        score = 0
        descriptor_match = re.search(r'(\d+)(?:w|x)?$', descriptor.strip())
        if descriptor_match:
            score = int(descriptor_match.group(1))
        query = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
        for key in ('wid', 'hei'):
            try:
                score = max(score, int(query.get(key) or 0))
            except (TypeError, ValueError):
                pass
        return score

    @classmethod
    def _scene7_high_resolution_url(cls, value):
        parts = urlsplit(value)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        # Se conserva la nitidez publicada, pero se elimina el recorte de miniatura
        # y se solicita un ancho suficiente para image_1920 de Odoo.
        query.pop('hei', None)
        query.pop('fit', None)
        query['wid'] = '1600'
        query['fmt'] = query.get('fmt') or 'jpeg'
        query['qlt'] = query.get('qlt') or '85'
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))

    @classmethod
    def _extract_images(cls, tree, canonical_url, style_code):
        raw_candidates = []

        for name in ('og:image', 'og:image:secure_url', 'twitter:image'):
            value = cls._meta(tree, name)
            if value:
                raw_candidates.append((value, ''))

        for element in tree.xpath('//img | //source'):
            for attribute in ('src', 'data-src', 'data-original', 'data-lazy-src'):
                value = element.get(attribute)
                if value:
                    raw_candidates.append((value, ''))
            for attribute in ('srcset', 'data-srcset'):
                srcset = element.get(attribute) or ''
                for item in srcset.split(','):
                    item = item.strip()
                    if not item:
                        continue
                    pieces = item.rsplit(None, 1)
                    raw_candidates.append((pieces[0], pieces[1] if len(pieces) == 2 else ''))

        tokens = cls._style_asset_tokens(style_code)
        best_by_asset = {}
        for raw_url, descriptor in raw_candidates:
            raw_url = html.unescape(str(raw_url)).strip()
            if not raw_url or raw_url.startswith('data:'):
                continue
            absolute_url = urljoin(canonical_url, raw_url)
            parsed = urlsplit(absolute_url)
            if parsed.netloc.lower() != cls._SCENE7_HOST:
                continue
            if not parsed.path.lower().startswith(cls._SCENE7_PATH):
                continue
            upper_url = absolute_url.upper()
            if tokens and not any(token in upper_url for token in tokens):
                continue

            asset_key = (parsed.netloc.lower(), parsed.path)
            score = cls._image_score(absolute_url, descriptor)
            previous = best_by_asset.get(asset_key)
            if not previous or score > previous[0]:
                best_by_asset[asset_key] = (score, absolute_url)

        images = []
        for _score, image_url in best_by_asset.values():
            high_resolution = cls._scene7_high_resolution_url(image_url)
            if high_resolution not in images:
                images.append(high_resolution)
        return images

    # ------------------------------------------------------------------
    # Ficha
    # ------------------------------------------------------------------
    def _parse_product_html(self, content, requested_url):
        tree = self._html_document(content)
        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical_url = urljoin(requested_url, canonical_values[0].strip()) if canonical_values else requested_url
        canonical_url = self._without_query_fragment(canonical_url)
        if not self._is_spanish_product_url(canonical_url):
            raise ValueError(
                "La URL de Levi's ya no apunta a una ficha española válida; "
                'puede tratarse de una redirección o de un producto descatalogado.'
            )

        main_nodes = tree.xpath('//main')
        main_node = main_nodes[0] if main_nodes else tree
        main_text = self._normalize_text(main_node.text_content())

        heading_values = tree.xpath('//main//h1//text()') or tree.xpath('//h1//text()')
        name = self._normalize_text(' '.join(heading_values))
        if not name:
            name = self._meta(tree, 'og:title') or self._meta(tree, 'twitter:title') or requested_url
        name = re.sub(r'\s*[|–-]\s*Levi(?:\'s|’s)®?\s*ES\s*$', '', name, flags=re.IGNORECASE).strip()

        style_code = self._style_from_url(canonical_url)
        visible_style = re.search(r'Style\s*#\s*([A-Za-z0-9-]+)', main_text, flags=re.IGNORECASE)
        if visible_style:
            style_code = visible_style.group(1).upper()

        image_urls = self._extract_images(tree, canonical_url, style_code)
        main_image_url = image_urls[0] if image_urls else self._meta(tree, 'og:image') or False

        return {
            'name': name,
            'description': self._extract_description(tree, main_text),
            'price': self._extract_price(tree, main_text),
            'currency': (
                self._meta(tree, 'product:price:currency')
                or self._meta(tree, 'og:price:currency')
                or 'EUR'
            ),
            'main_image_url': main_image_url,
            'image_urls': image_urls,
            'canonical_url': canonical_url,
            'style_code': style_code,
            'color_code': self._extract_color(tree, main_text),
            'category_path': '/'.join(self.parse_category_path(canonical_url)),
        }

    def fetch_preview(self, source, url):
        session = self._get_session(source)
        response = self._http_get(session, url, source)
        return self._parse_product_html(response.content, response.url or url)
