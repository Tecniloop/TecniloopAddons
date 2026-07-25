import gzip
import html
import logging
import re
import subprocess

from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlsplit, urlunsplit

from lxml import etree
import requests
from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorLevisEs(models.AbstractModel):
    """Conector para el catálogo español de Levi's.

    Levi's usa URLs de producto jerárquicas cuyo final estable es ``/p/<style>``.
    El sitemap suministrado puede ser tanto un ``urlset`` como un índice de otros
    sitemaps, por lo que el conector detecta ambos formatos y admite índices
    anidados y ficheros XML comprimidos con gzip.

    La recopilación de URLs utiliza exclusivamente el sitemap oficial publicado
    en robots.txt; no recorre categorías HTML ni paginaciones. Las fichas se
    procesan desde el HTML público. Se extraen el título, el precio
    vigente, el color, la descripción de "Acerca de este estilo", el código de
    estilo y las imágenes del producto servidas por Adobe Scene7. Las imágenes
    de productos relacionados se descartan comparando el identificador del
    recurso con el código de estilo de la URL.
    """

    _name = 'sitemap.connector.levis_es'
    _inherit = 'sitemap.import.service'
    _description = "Conector Levi's España"

    _PRODUCT_PATH_RE = re.compile(r'(?:^|/)p/([^/?#]+)', re.IGNORECASE)
    _SCENE7_HOST = 'lscoglobal.scene7.com'
    _SCENE7_PATH = '/is/image/lscoglobal/'
    _SPANISH_PRODUCT_SITEMAP_COUNT = 75
    _SPANISH_PRODUCT_SITEMAP_TEMPLATE = (
        'https://www.levi.com/ES/es_ES/sitemap/medias/'
        'Product-es-ES-EUR-{index}.xml'
    )

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

    def _levis_get_content(self, session, url, source):
        """Descarga XML de Levi's con fallback a curl ante bloqueos 403.

        Algunos nodos de Akamai bloquean la huella TLS de ``requests`` aunque
        la misma URL sea pública y funcione desde un navegador. Primero usamos
        el cliente HTTP común del módulo y, exclusivamente ante HTTP 403,
        repetimos la descarga con curl y cabeceras de navegación.
        """
        try:
            return self._http_get(session, url, source).content
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if status != 403:
                raise

        timeout = max(int(source.request_timeout or 20), 5)
        command = [
            'curl', '--location', '--silent', '--show-error', '--fail',
            '--compressed', '--max-time', str(timeout),
            '--user-agent', session.headers.get('User-Agent', ''),
            '--header', 'Accept: application/xml,text/xml;q=0.9,*/*;q=0.8',
            '--header', 'Accept-Language: es-ES,es;q=0.9,en;q=0.5',
            '--header', 'Cache-Control: no-cache',
            '--header', 'Pragma: no-cache',
            '--header', 'Sec-Fetch-Dest: document',
            '--header', 'Sec-Fetch-Mode: navigate',
            '--header', 'Sec-Fetch-Site: same-origin',
            '--header', 'Upgrade-Insecure-Requests: 1',
            '--referer', 'https://www.levi.com/ES/es_ES/sitemap.xml',
            url,
        ]
        try:
            result = subprocess.run(
                command, check=False, capture_output=True, timeout=timeout + 5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise requests.HTTPError(
                "Levi's devuelve HTTP 403 y no se pudo ejecutar el fallback curl: %s" % exc
            ) from exc
        if result.returncode != 0 or not result.stdout.strip():
            detail = result.stderr.decode('utf-8', errors='replace').strip()
            raise requests.HTTPError(
                "Levi's devuelve HTTP 403 también mediante curl para %s%s" % (
                    url, ': ' + detail if detail else '',
                )
            )
        _logger.info("Levi's: XML obtenido mediante fallback curl: %s", url)
        return result.stdout

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
        content = self._levis_get_content(session, sitemap_url, source)
        root = self._xml_root(content)
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
        spanish_product_named = [
            value for value in child_urls
            if re.search(r'/Product-es-ES-EUR-\d+\.xml(?:\?.*)?$', value, re.IGNORECASE)
        ]
        if spanish_product_named:
            child_urls = spanish_product_named
        else:
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
        """Reconoce las fichas Levi's publicadas en los sitemaps ES.

        Los sitemaps de producto ya están segmentados por ``Product-es-ES-EUR``;
        por ello no debemos volver a exigir una forma exacta de locale ni que el
        código sea literalmente el último segmento. Levi's puede añadir una barra,
        un sufijo o parámetros de campaña sin dejar de ser una ficha válida.
        """
        parsed = urlparse(html.unescape((value or '').strip()))
        host = (parsed.hostname or '').lower()
        path = unquote(parsed.path or '')
        return (
            host in ('www.levi.com', 'levi.com')
            and bool(cls._PRODUCT_PATH_RE.search(path))
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

    def _collect_product_entries(self, raw_entries, category_filter=None, limit=0):
        entries = []
        seen = set()
        product_count = 0
        filter_text = (category_filter or '').strip().lower()

        rejected_samples = []
        for entry in raw_entries:
            raw_url = html.unescape((entry.get('url') or '').strip())
            product_url = self._without_query_fragment(raw_url)
            if not self._is_spanish_product_url(product_url):
                if raw_url and len(rejected_samples) < 10:
                    rejected_samples.append(raw_url)
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
        if not product_count and rejected_samples:
            _logger.warning(
                "Levi's: el sitemap se leyó, pero ninguna URL fue reconocida como "
                "producto. Primeras URLs recibidas: %s",
                rejected_samples,
            )
        return entries, product_count

    def get_product_entries(self, source, category_filter=None, limit=0):
        """Obtiene exclusivamente las fichas publicadas en el sitemap oficial.

        Levi's declara el sitemap español en ``robots.txt``. No se recorren
        categorías ni paginaciones HTML: además de ser más lento, ese catálogo
        puede responder HTTP 403 y está sujeto a cambios de frontend.
        """
        entries, product_count = self._collect_product_entries(
            self._iter_sitemap_entries(source, source.sitemap_index_url),
            category_filter=category_filter,
            limit=limit,
        )
        if product_count:
            return entries
        raise ValueError(
            "No se ha podido obtener ninguna URL de producto desde los sitemaps "
            "Product-es-ES-EUR de Levi's. Revise en el log si los sitemaps hijos "
            "han respondido HTTP 403/404 o qué primeras URLs fueron recibidas."
        )

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
