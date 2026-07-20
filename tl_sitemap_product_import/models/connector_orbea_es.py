import gzip
import html as html_lib
import json
import logging
import re
from collections import deque
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorOrbeaEs(models.AbstractModel):
    """Conector del catálogo público español de Orbea.

    Orbea no declara actualmente un sitemap en ``robots.txt``. El conector
    intenta primero los endpoints XML habituales y, si no obtiene un mapa
    útil, descubre las fichas desde las páginas públicas de familias y los
    catálogos de equipamiento. Las fichas actuales pueden ser planas::

        /es-es/onna-50
        /es-es/orca-m30
        /es-es/ra80ltd-cs-shimano-hg-set

    o utilizar rutas históricas/anidadas de equipamiento::

        /es-es/equipamiento/cycle-clothing/cat/<slug>
        /es-es/oprema/oquowheels/cat/<slug>

    La lista obtenida mediante navegación se considera potencialmente parcial,
    por lo que la fuente se instala con el archivado automático desactivado.
    """

    _name = 'sitemap.connector.orbea_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Orbea España'

    _HOSTS = {'www.orbea.com', 'orbea.com', 'cms.orbea.com'}
    _MARKET_PREFIX_RE = re.compile(r'^/es[-_]es(?:/|$)', re.IGNORECASE)
    _IMAGE_EXT_RE = re.compile(r'\.(?:avif|gif|jpe?g|png|webp)(?:$|\?)', re.IGNORECASE)
    _PRICE_RE = re.compile(
        r'(?<!\d)(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2})?)\s*€'
    )
    _REFERENCE_RE = re.compile(
        r'(?:ref(?:erencia)?|sku|mpn|c[oó]digo(?:\s+de\s+producto)?|'
        r'n[uú]mero\s+de\s+art[ií]culo|article\s*(?:number|no\.?))\s*[:#-]?\s*'
        r'([A-Z0-9][A-Z0-9._/\-]{2,50})',
        re.IGNORECASE,
    )
    _NON_PRODUCT_IMAGE_RE = re.compile(
        r'(?:logo|favicon|icon|sprite|cookie|newsletter|social|payment|flag|'
        r'loader|placeholder|avatar|footer|header|menu|nav|country|language|'
        r'dealer|storefinder|store-finder|youtube|vimeo|award|badge|spinner)',
        re.IGNORECASE,
    )
    _EXCLUDED_PATH_RE = re.compile(
        r'^/es-es/(?:$|m(?:/|$)|catalogo(?:/|$)|soporte(?:/|$)|contacto(?:/|$)|'
        r'cuenta(?:/|$)|account(?:/|$)|checkout(?:/|$)|cart(?:/|$)|cesta(?:/|$)|'
        r'buscar(?:/|$)|search(?:/|$)|tiendas?(?:/|$)|distribuidores?(?:/|$)|'
        r'legal(?:/|$)|politica(?:/|$)|pol[ií]tica(?:/|$)|terminos(?:/|$)|'
        r't[eé]rminos(?:/|$)|cookies?(?:/|$)|privacidad(?:/|$)|garantia(?:/|$)|'
        r'garant[ií]a(?:/|$)|eventos?(?:/|$)|historias?(?:/|$)|stories(?:/|$)|'
        r'compromiso(?:/|$)|personalizacion(?:/|$)|personalizaci[oó]n(?:/|$)|'
        r'unete(?:/|$)|[uú]nete(?:/|$)|registro(?:/|$)|login(?:/|$)|'
        r'condiciones(?:/|$)|manuales?(?:/|$)|recambios(?:/|$))',
        re.IGNORECASE,
    )
    _GENERIC_TITLES = {
        'orbea', 'bicicletas de montaña', 'bicicletas de carretera',
        'bicicletas urban & active', 'ruedas', 'accesorios', 'ropa ciclista',
        'cascos', 'equipamiento', 'recambios',
    }

    _DISCOVERY_PAGES = (
        'https://www.orbea.com/es-es/',
        'https://www.orbea.com/es-es/m/bicicletas-montana',
        'https://www.orbea.com/es-es/m/bicicletas-carretera',
        'https://www.orbea.com/es-es/m/bicicletas-urban-active',
        'https://www.orbea.com/es-es/catalogo/equipamiento-ruedas',
        'https://www.orbea.com/es-es/catalogo/equipamiento-accesorios',
        'https://www.orbea.com/es-es/catalogo/equipamiento-ropa_ciclista',
        'https://www.orbea.com/es-es/catalogo/equipamiento-cascos',
        'https://www.orbea.com/es-es/catalogo/equipamiento-componentes',
    )

    _SPEC_LABELS = (
        'Cuadro', 'Horquilla', 'Direccion', 'Dirección', 'Amortiguador',
        'Plato/Biela', 'Manetas', 'Piñon', 'Piñón', 'Cambio', 'Desviador',
        'Cadena', 'Manillar', 'Potencia', 'Freno', 'Frenos', 'Rueda',
        'Ruedas', 'Cubierta', 'Neumático', 'Neumáticos', 'Sillin', 'Sillín',
        'Tija sillin', 'Tija sillín', 'Pedales', 'Motor', 'Batería', 'Peso',
        'Material', 'Talla', 'Tallas', 'Color', 'Colores', 'Capacidad',
        'Longitud de cable', 'Contenido de la caja', 'Compatibilidad',
        'Límite de peso del sistema', 'Llanta', 'Buje', 'Núcleo', 'Radios',
    )

    # ------------------------------------------------------------------
    # HTTP, URLs y XML
    # ------------------------------------------------------------------
    def _get_session(self, source):
        session = super()._get_session(source)
        session.headers.update({
            'Accept': (
                'text/html,application/xhtml+xml,application/xml;q=0.9,'
                'image/avif,image/webp,*/*;q=0.8'
            ),
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.4',
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
        return etree.QName(element).localname.casefold()

    @classmethod
    def _canonical_url(cls, value):
        raw = html_lib.unescape(str(value or '')).strip().replace('\\/', '/')
        raw = raw.replace('\\u002F', '/').replace('\\u002f', '/')
        if not raw:
            return False
        if raw.startswith('//'):
            raw = 'https:' + raw
        parts = urlsplit(raw)
        host = parts.netloc.casefold()
        if host in {'orbea.com', 'cms.orbea.com'}:
            host = 'www.orbea.com'
        path = re.sub(r'/+', '/', parts.path or '/')
        path = re.sub(r'^/es[-_]es(?:/|$)', '/es-es/', path, flags=re.IGNORECASE)
        if path != '/':
            path = path.rstrip('/')
        return urlunsplit((parts.scheme or 'https', host, path, '', ''))

    @classmethod
    def _is_market_url(cls, value):
        canonical = cls._canonical_url(value)
        if not canonical:
            return False
        parsed = urlparse(canonical)
        return (
            parsed.netloc.casefold() in {'www.orbea.com'}
            and bool(cls._MARKET_PREFIX_RE.match(parsed.path))
        )

    @classmethod
    def _is_product_candidate(cls, value):
        canonical = cls._canonical_url(value)
        if not canonical or not cls._is_market_url(canonical):
            return False
        path = urlparse(canonical).path
        if cls._EXCLUDED_PATH_RE.match(path):
            return False
        if path.endswith(('.xml', '.xml.gz', '.txt', '.pdf', '.jpg', '.jpeg', '.png', '.webp')):
            return False
        # Evita aceptar la raíz de secciones genéricas de equipamiento.
        if path.casefold() in {
            '/es-es/equipamiento', '/es-es/oprema', '/es-es/bicicletas',
            '/es-es/products', '/es-es/productos',
        }:
            return False
        return len([part for part in path.split('/') if part]) >= 2

    @classmethod
    def _product_key(cls, value):
        canonical = cls._canonical_url(value)
        if not canonical:
            return False
        path = urlparse(canonical).path.casefold()
        return path.rstrip('/')

    @classmethod
    def _is_discovery_url(cls, value):
        canonical = cls._canonical_url(value)
        if not canonical or not cls._is_market_url(canonical):
            return False
        path = urlparse(canonical).path.casefold()
        return (
            path in {'/es-es', '/es-es/'}
            or path.startswith('/es-es/m/')
            or path.startswith('/es-es/catalogo/')
        )

    @classmethod
    def _clean_image_url(cls, value, page_url=''):
        raw = html_lib.unescape(str(value or '')).strip().replace('\\/', '/')
        if not raw or raw.startswith(('data:', 'blob:')):
            return False
        # srcset: conserva la primera URL; las de mayor resolución se añaden
        # también de forma independiente desde _html_images.
        raw = raw.split()[0]
        absolute = urljoin(page_url, raw)
        parts = urlsplit(absolute)
        if parts.scheme not in ('http', 'https'):
            return False
        if cls._NON_PRODUCT_IMAGE_RE.search(absolute):
            return False
        if not cls._IMAGE_EXT_RE.search(parts.path):
            return False
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))

    @staticmethod
    def _robots_sitemaps(text, base_url):
        result = []
        for line in str(text or '').splitlines():
            match = re.match(r'^\s*Sitemap\s*:\s*(\S+)\s*$', line, re.IGNORECASE)
            if match:
                value = urljoin(base_url, match.group(1).strip())
                if value not in result:
                    result.append(value)
        return result

    def _candidate_sitemaps(self, source):
        root = 'https://www.orbea.com/'
        result = []
        session = self._get_session(source)
        for url in ('https://www.orbea.com/robots.txt', source.sitemap_index_url):
            if not url:
                continue
            try:
                response = session.get(
                    url,
                    timeout=source.request_timeout or 20,
                    allow_redirects=True,
                )
                if response.status_code >= 400:
                    continue
                result.extend(self._robots_sitemaps(response.text, response.url))
                payload = response.content.lstrip()
                if payload.startswith((b'<?xml', b'<urlset', b'<sitemapindex')) or payload[:2] == b'\x1f\x8b':
                    result.insert(0, response.url)
            except Exception as exc:
                _logger.info('Orbea: no se pudo consultar %s: %s', url, exc)
        result.extend([
            urljoin(root, 'sitemap.xml'),
            urljoin(root, 'sitemap_index.xml'),
            urljoin(root, 'sitemapindex.xml'),
            urljoin(root, 'sitemap-index.xml'),
            urljoin(root, 'sitemap/sitemap.xml'),
            urljoin(root, 'sitemap/index.xml'),
        ])
        return list(dict.fromkeys(result))

    def _iter_sitemap_entries(self, source, sitemap_url, depth=0, visited=None):
        if depth > 10:
            raise ValueError('El sitemap de Orbea supera diez niveles de índices.')
        visited = visited or set()
        clean_url = self._canonical_url(sitemap_url) or sitemap_url
        if clean_url in visited:
            return
        visited.add(clean_url)
        session = self._get_session(source)
        response = self._http_get(session, clean_url, source)
        root = self._xml_root(response.content)
        root_name = self._local_name(root)
        if root_name == 'sitemapindex':
            for child in root.xpath(
                './*[local-name()="sitemap"]/*[local-name()="loc"]/text()'
            ):
                if child and child.strip():
                    yield from self._iter_sitemap_entries(
                        source, urljoin(response.url, child.strip()), depth + 1, visited
                    )
            return
        if root_name != 'urlset':
            raise ValueError('El XML no contiene <urlset> ni <sitemapindex>.')
        for node in root.xpath('./*[local-name()="url"]'):
            locs = node.xpath('./*[local-name()="loc"]/text()')
            alternates = node.xpath(
                './*[local-name()="link" and '
                'translate(@hreflang,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")='
                '"es-es"]/@href'
            )
            selected = False
            for candidate in alternates + locs:
                canonical = self._canonical_url(candidate)
                if self._is_product_candidate(canonical):
                    selected = canonical
                    break
            if not selected:
                continue
            lastmods = node.xpath('./*[local-name()="lastmod"]/text()')
            images = node.xpath(
                './*[local-name()="image"]/*[local-name()="loc"]/text()'
            )
            yield {
                'url': selected,
                'lastmod': self._parse_lastmod(lastmods[0] if lastmods else None),
                'images': [item.strip() for item in images if item and item.strip()],
            }

    @classmethod
    def _urls_from_html(cls, content, base_url):
        text = content.decode('utf-8', errors='ignore') if isinstance(content, bytes) else str(content or '')
        text = html_lib.unescape(text).replace('\\/', '/').replace('\\u002F', '/').replace('\\u002f', '/')
        urls = []

        try:
            tree = lxml_html.fromstring(content)
            attrs = tree.xpath(
                '//@href | //@data-href | //@data-url | //@data-product-url | '
                '//@data-product-href | //@content'
            )
            attrs.extend(tree.xpath('//link[@hreflang="es-ES" or @hreflang="es-es"]/@href'))
            for value in attrs:
                absolute = cls._canonical_url(urljoin(base_url, value))
                if absolute and absolute not in urls:
                    urls.append(absolute)
        except (ValueError, etree.ParserError):
            pass

        patterns = (
            r'https?://(?:www\.)?orbea\.com/es[-_]es/[A-Za-z0-9_./%\-]+',
            r'(?P<path>/es[-_]es/[A-Za-z0-9_./%\-]+)',
        )
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                value = match.groupdict().get('path') or match.group(0)
                absolute = cls._canonical_url(urljoin(base_url, value.rstrip('"\'<>),;')))
                if absolute and absolute not in urls:
                    urls.append(absolute)
        return urls

    @staticmethod
    def _merge_entry(entries, image_map, entry):
        key = SitemapConnectorOrbeaEs._product_key(entry.get('url'))
        if not key:
            return
        previous = entries.get(key)
        if not previous or (entry.get('lastmod') and not previous.get('lastmod')):
            entries[key] = {
                'url': SitemapConnectorOrbeaEs._canonical_url(entry['url']),
                'lastmod': entry.get('lastmod') or False,
            }
        for image in entry.get('images') or []:
            clean = SitemapConnectorOrbeaEs._clean_image_url(image, entry['url'])
            if clean and clean not in image_map.setdefault(key, []):
                image_map[key].append(clean)

    def _collect_xml_products(self, source):
        entries, image_map, errors = {}, {}, []
        for sitemap_url in self._candidate_sitemaps(source):
            try:
                for entry in self._iter_sitemap_entries(source, sitemap_url):
                    self._merge_entry(entries, image_map, entry)
            except Exception as exc:
                errors.append(f'{sitemap_url}: {exc}')
                _logger.info('Orbea: sitemap no utilizable %s: %s', sitemap_url, exc)
        return entries, image_map, errors

    def _fallback_catalog_entries(self, source, max_pages=180):
        entries, image_map = {}, {}
        session = self._get_session(source)
        queue = deque(self._DISCOVERY_PAGES)
        visited = set()
        while queue and len(visited) < max_pages:
            page_url = self._canonical_url(queue.popleft())
            if not page_url or page_url in visited:
                continue
            visited.add(page_url)
            try:
                response = self._http_get(session, page_url, source)
            except Exception as exc:
                _logger.info('Orbea: página de descubrimiento no accesible %s: %s', page_url, exc)
                continue
            for found in self._urls_from_html(response.content, response.url):
                if self._is_discovery_url(found) and found not in visited:
                    queue.append(found)
                elif self._is_product_candidate(found):
                    self._merge_entry(entries, image_map, {
                        'url': found,
                        'lastmod': False,
                        'images': [],
                    })
        return entries, image_map

    def _collect_products(self, source):
        entries, image_map, errors = self._collect_xml_products(source)
        # Aunque exista un sitemap, se completa con el catálogo: Orbea puede
        # omitir URLs de configuradores o equipamiento del mapa principal.
        fallback_entries, fallback_images = self._fallback_catalog_entries(source)
        for entry in fallback_entries.values():
            self._merge_entry(entries, image_map, entry)
        for key, images in fallback_images.items():
            for image in images:
                if image not in image_map.setdefault(key, []):
                    image_map[key].append(image)
        return entries, image_map, errors

    def get_product_entries(self, source, category_filter=None, limit=0):
        entries, image_map, errors = self._collect_products(source)
        self._orbea_entries_cache = entries
        self._orbea_images_cache = image_map
        if not entries:
            detail = ' | '.join(errors[:4])
            raise ValueError(
                'No se localizaron fichas españolas de Orbea. No fue posible '
                'procesar un sitemap ni descubrir URLs desde los catálogos públicos.'
                + (f' Intentos: {detail}' if detail else '')
            )
        needle = (category_filter or '').strip().casefold()
        result = []
        for key, entry in sorted(entries.items()):
            category = '/'.join(self.parse_category_path(entry['url']))
            haystack = f'{entry["url"]} {key} {category}'.casefold()
            if needle and needle not in haystack:
                continue
            result.append(entry)
            if limit and len(result) >= limit:
                break
        return result

    def get_image_map(self, source):
        entries = getattr(self, '_orbea_entries_cache', None)
        images = getattr(self, '_orbea_images_cache', None)
        if entries is None or images is None:
            entries, images, _errors = self._collect_products(source)
        return {
            entry['url']: images.get(key, [])
            for key, entry in entries.items()
            if images.get(key)
        }

    # ------------------------------------------------------------------
    # Extracción de ficha
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_text(value):
        return re.sub(r'\s+', ' ', html_lib.unescape(str(value or ''))).strip()

    @classmethod
    def _meta(cls, tree, name):
        values = tree.xpath(
            f'//meta[@property="{name}" or @name="{name}" or @itemprop="{name}"]/@content'
        )
        return cls._normalize_text(values[0]) if values else False

    @classmethod
    def _json_payloads(cls, tree):
        result = []
        for raw in tree.xpath(
            '//script[@type="application/ld+json" or @type="application/json"]/text()'
        ):
            if not raw or len(raw) > 12_000_000:
                continue
            try:
                result.append(json.loads(raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return result

    @classmethod
    def _product_json(cls, tree):
        products = []

        def walk(value):
            if isinstance(value, list):
                for item in value:
                    walk(item)
                return
            if not isinstance(value, dict):
                return
            types = value.get('@type')
            types = types if isinstance(types, list) else [types]
            if any(str(item).casefold() == 'product' for item in types if item):
                products.append(value)
            for key in ('@graph', 'mainEntity', 'itemListElement', 'hasVariant', 'variants', 'product'):
                if key in value:
                    walk(value[key])

        for payload in cls._json_payloads(tree):
            walk(payload)
        return products[0] if products else {}

    @classmethod
    def _page_lines(cls, tree):
        scopes = tree.xpath('//main')
        scope = scopes[0] if scopes else tree
        result = []
        for raw in scope.xpath('.//text()[normalize-space()]'):
            value = cls._normalize_text(raw)
            if value and (not result or result[-1] != value):
                result.append(value)
        return result

    @classmethod
    def _name(cls, tree, product_json, canonical):
        values = tree.xpath('//main//h1[1]//text()') or tree.xpath('//h1[1]//text()')
        name = cls._normalize_text(' '.join(values)) if values else False
        name = name or cls._normalize_text(product_json.get('name'))
        name = name or cls._meta(tree, 'og:title') or cls._meta(tree, 'twitter:title')
        if name:
            name = re.sub(r'\s*[|\-]\s*Orbea.*$', '', name, flags=re.IGNORECASE).strip()
        if not name:
            slug = urlparse(canonical).path.rsplit('/', 1)[-1]
            name = re.sub(r'[-_]+', ' ', slug).title()
        return name

    @classmethod
    def _description(cls, tree, product_json):
        candidates = []
        for value in (
            product_json.get('description'),
            cls._meta(tree, 'og:description'),
            cls._meta(tree, 'description'),
        ):
            text = cls._normalize_text(value)
            if text and len(text) > 35:
                candidates.append(text)
        for node in tree.xpath('//main//p | //article//p')[:80]:
            text = cls._normalize_text(' '.join(node.itertext()))
            if len(text) > 70 and not any(token in text.casefold() for token in (
                'cookie', 'newsletter', 'política de privacidad', 'suscríbete',
                'al completar el formulario', 'todos los derechos',
            )):
                candidates.append(text)
        return max(candidates, key=len) if candidates else ''

    @classmethod
    def _extract_sizes_colors(cls, lines):
        sizes, colors = [], []
        ignored = {
            'ver geometrías', 'ver guía de tallas', 'ver color', 'color', 'talla',
            'tallas', 'componentes', 'cuadro', 'resumen', 'cerrar', 'editar',
            'configuración estándar', 'elige talla', 'elige color',
        }
        size_re = re.compile(
            r'^(?:XXXS|XXS|XS|S|M|L|XL|XXL|XXXL|UNIQUE|UNICO|ÚNICO|'
            r'\d{2}(?:[.,]\d)?(?:/\d{2}(?:[.,]\d)?)?|'
            r'\d{2,3}\s*(?:mm|cm)|\d{2,3}C|'
            r'[A-Z]{1,3}-\d{2}(?:\.\d)?")$',
            re.IGNORECASE,
        )
        for index, line in enumerate(lines):
            low = line.rstrip(':').casefold()
            if low in {'talla', 'tallas', 'tamaño de rueda', 'elige talla'}:
                for candidate in lines[index + 1:index + 35]:
                    candidate_low = candidate.rstrip(':').casefold()
                    if candidate_low in {'color', 'colores', 'componentes', 'resumen'}:
                        break
                    if candidate_low in ignored or len(candidate) > 35:
                        continue
                    if size_re.fullmatch(candidate) and candidate not in sizes:
                        sizes.append(candidate)
            if low in {'color', 'colores', 'elige color'}:
                for candidate in lines[index + 1:index + 25]:
                    candidate_low = candidate.rstrip(':').casefold()
                    if candidate_low in {'componentes', 'resumen', 'talla', 'tallas'}:
                        break
                    if candidate_low in ignored or len(candidate) > 100:
                        continue
                    if any(phrase in candidate_low for phrase in (
                        'diseñados para', 'selecciona', 'mostrar selector', 'inspiraciones',
                        'nuestras propuestas', 'left color', 'right color',
                    )):
                        continue
                    if re.search(r'[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]', candidate) and candidate not in colors:
                        colors.append(candidate)
        return sizes[:40], colors[:30]

    @classmethod
    def _label_values(cls, lines):
        labels = {item.casefold(): item for item in cls._SPEC_LABELS}
        result = {}
        for index, line in enumerate(lines):
            normalized = line.rstrip(':').strip().casefold()
            label = labels.get(normalized)
            values = []
            if label:
                for candidate in lines[index + 1:index + 5]:
                    if candidate.rstrip(':').strip().casefold() in labels:
                        break
                    if len(candidate) > 260 or candidate.casefold() in {'cerrar', 'editar', 'más información'}:
                        break
                    if candidate not in values:
                        values.append(candidate)
                    if len(values) >= 2:
                        break
            if label and values:
                current = result.get(label, [])
                if sum(map(len, values)) > sum(map(len, current)):
                    result[label] = values
        return result

    @classmethod
    def _description_with_details(cls, description, sizes, colors, specs):
        parts = []
        if description:
            parts.append(f'<p>{html_lib.escape(description)}</p>')
        if sizes:
            parts.append(
                '<p><strong>Tallas:</strong> '
                + html_lib.escape(' / '.join(sizes)) + '</p>'
            )
        if colors:
            parts.append(
                '<p><strong>Colores:</strong> '
                + html_lib.escape(' / '.join(colors)) + '</p>'
            )
        rows = []
        for label, values in specs.items():
            if label.casefold() in {'talla', 'tallas', 'color', 'colores'}:
                continue
            value = ' / '.join(values)
            rows.append(
                f'<p><strong>{html_lib.escape(label)}:</strong> '
                f'{html_lib.escape(value)}</p>'
            )
        if rows:
            parts.append(''.join(rows))
        return ''.join(parts) or description or ''

    @classmethod
    def _parse_price_number(cls, value):
        text = re.sub(r'[^0-9.,]', '', str(value or ''))
        if not text:
            return False
        if ',' in text and '.' in text:
            if text.rfind(',') > text.rfind('.'):
                text = text.replace('.', '').replace(',', '.')
            else:
                text = text.replace(',', '')
        elif ',' in text:
            tail = text.rsplit(',', 1)[-1]
            text = text.replace('.', '')
            text = text.replace(',', '.' if len(tail) <= 2 else '')
        elif text.count('.') > 1:
            text = text.replace('.', '')
        elif '.' in text and len(text.rsplit('.', 1)[-1]) == 3:
            text = text.replace('.', '')
        try:
            return float(text)
        except ValueError:
            return False

    @classmethod
    def _structured_price(cls, tree, product_json, lines):
        offers = product_json.get('offers') or {}
        offers = offers if isinstance(offers, list) else [offers]
        values, currency = [], False
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            currency = currency or offer.get('priceCurrency')
            for key in ('price', 'lowPrice', 'salePrice', 'highPrice'):
                parsed = cls._parse_price_number(offer.get(key))
                if parsed and parsed > 0:
                    values.append(parsed)
        for meta_name in ('product:price:amount', 'og:price:amount', 'price'):
            parsed = cls._parse_price_number(cls._meta(tree, meta_name))
            if parsed and parsed > 0:
                values.append(parsed)
        currency = (
            currency or cls._meta(tree, 'product:price:currency')
            or cls._meta(tree, 'og:price:currency') or 'EUR'
        )
        selectors = (
            '//*[contains(translate(@class,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"product-price")]//text()',
            '//*[contains(translate(@class,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"current-price")]//text()',
            '//*[contains(translate(@class,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"final-price")]//text()',
            '//*[contains(translate(@id,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"product-price")]//text()',
        )
        for selector in selectors:
            for value in tree.xpath(selector):
                for match in cls._PRICE_RE.finditer(cls._normalize_text(value)):
                    parsed = cls._parse_price_number(match.group(1))
                    if parsed and parsed > 0:
                        values.append(parsed)
        # Respaldo: el precio base es normalmente el mayor importe visible.
        # Los importes menores corresponden a suplementos configurables (0 €, 85 €, 249 €).
        if not values:
            main_text = ' '.join(lines[:1000])
            for match in cls._PRICE_RE.finditer(main_text):
                parsed = cls._parse_price_number(match.group(1))
                if parsed and 1 <= parsed <= 100000:
                    values.append(parsed)
        return (max(values) if values else 0.0), currency

    @classmethod
    def _valid_reference(cls, value):
        candidate = cls._normalize_text(value).strip(' .,:;#-').upper()
        if not re.fullmatch(r'[A-Z0-9._/\-]{3,60}', candidate, re.IGNORECASE):
            return False
        # En algunas fichas el pie contiene etiquetas vacías consecutivas:
        # "Ref.: Color: Talla:". Nunca deben convertirse en referencias.
        if candidate in {
            'COLOR', 'COLORES', 'TALLA', 'TALLAS', 'SIZE', 'SIZES',
            'CONFIGURACION', 'CONFIGURACIÓN', 'COMPONENTES', 'RESUMEN',
            'CARGANDO', 'EDITAR', 'CERRAR', 'PRODUCTO', 'PRODUCT',
        }:
            return False
        return candidate

    @classmethod
    def _style_code(cls, tree, product_json, lines, canonical):
        for key in ('sku', 'mpn', 'productID', 'productId', 'model'):
            candidate = cls._valid_reference(product_json.get(key))
            if candidate:
                return candidate
        body = cls._normalize_text(' '.join(lines))
        for match in cls._REFERENCE_RE.finditer(body):
            candidate = cls._valid_reference(match.group(1))
            if candidate:
                return candidate
        for attr in (
            'data-sku', 'data-reference', 'data-product-reference',
            'data-product-code', 'data-product-id', 'data-article-number',
        ):
            for value in tree.xpath(f'//*[@{attr}]/@{attr}'):
                candidate = cls._valid_reference(value)
                if candidate:
                    return candidate
        content = etree.tostring(tree, encoding='unicode', method='html')
        for key in ('sku', 'mpn', 'reference', 'productCode', 'articleNumber'):
            regex = re.compile(
                rf'["\']{re.escape(key)}["\']\s*:\s*["\']([^"\']{{3,60}})["\']',
                re.IGNORECASE,
            )
            for found in regex.findall(content):
                candidate = cls._valid_reference(found)
                if candidate:
                    return candidate
        slug = urlparse(canonical).path.rsplit('/', 1)[-1]
        return re.sub(r'[^A-Z0-9]+', '-', slug.upper()).strip('-') or False

    @classmethod
    def _json_images(cls, product_json, page_url):
        values = product_json.get('image') or []
        values = values if isinstance(values, list) else [values]
        result = []
        for item in values:
            if isinstance(item, dict):
                item = item.get('url') or item.get('contentUrl')
            clean = cls._clean_image_url(item, page_url)
            if clean and clean not in result:
                result.append(clean)
        return result

    @classmethod
    def _html_images(cls, tree, page_url):
        result = []
        attrs = tree.xpath(
            '//main//img/@src | //main//img/@data-src | //main//img/@data-lazy-src | '
            '//main//source/@srcset | //main//img/@srcset | '
            '//img[contains(@class,"product")]/@src | //img[contains(@class,"gallery")]/@src'
        )
        for raw in attrs:
            candidates = [part.strip().split()[0] for part in str(raw).split(',') if part.strip()]
            for candidate in reversed(candidates):
                clean = cls._clean_image_url(candidate, page_url)
                if clean and clean not in result:
                    result.append(clean)
        return result

    @classmethod
    def _catalog_category(cls, tree):
        hrefs = tree.xpath('//a[contains(@href,"/es-es/catalogo/")]/@href')
        for href in hrefs:
            path = urlparse(cls._canonical_url(href)).path.casefold()
            slug = path.split('/catalogo/', 1)[-1]
            if slug.startswith('bicicletas-montana-'):
                family = slug.split('bicicletas-montana-', 1)[-1]
                return ['Bicicletas', 'Montaña', family.replace('-', ' ').title()]
            if slug.startswith('bicicletas-carretera-'):
                family = slug.split('bicicletas-carretera-', 1)[-1]
                return ['Bicicletas', 'Carretera', family.replace('-', ' ').title()]
            if slug.startswith(('bicicletas-urban_active-', 'bicicletas-urban-active-')):
                family = re.split(r'bicicletas-urban[_-]active-', slug, maxsplit=1)[-1]
                return ['Bicicletas', 'Urban & Active', family.replace('-', ' ').title()]
        return []

    @classmethod
    def _category_from_content(cls, canonical, name, lines, tree):
        path = urlparse(canonical).path.casefold()
        text = f'{name} {" ".join(lines[:400])}'.casefold()
        if '/equipamiento/' in path or '/oprema/' in path:
            if any(token in path or token in text for token in ('cycle-clothing', 'jersey', 'culote', 'maillot', 'ropa')):
                return ['Equipamiento', 'Ropa ciclista']
            if any(token in path or token in text for token in ('oquowheels', 'wheel', 'rueda', 'llanta')):
                return ['Equipamiento', 'Ruedas']
            if any(token in path or token in text for token in ('helmet', 'casco')):
                return ['Equipamiento', 'Cascos']
            return ['Equipamiento', 'Accesorios']
        if any(token in text for token in ('ra80', 'ra57', 'rp50', 'rp45', 'rp35', 'rc25', 'oquo', 'juego de ruedas')):
            return ['Equipamiento', 'Ruedas']
        if any(token in text for token in ('range extender', 'carrier', 'rack', 'basket', 'bag ', 'dongle', 'adaptador')):
            return ['Equipamiento', 'Accesorios']
        catalog = cls._catalog_category(tree)
        electric = any(token in text for token in (
            'motor bosch', 'motor shimano', 'batería', 'battery', 'ebike', 'e-bike',
            'asistencia eléctrica', 'avinci', 'aviri', 'mahle', 'ep801',
        ))
        if catalog:
            if electric:
                catalog[0] = 'Bicicletas eléctricas'
            return catalog
        patterns = (
            (('rallon dh',), ['Bicicletas', 'Montaña', 'Downhill']),
            (('rallon', 'wild lt'), ['Bicicletas', 'Montaña', 'Enduro']),
            (('oiz', 'alma', 'onna'), ['Bicicletas', 'Montaña', 'Cross Country']),
            (('occam', 'laufey', 'rise', 'wild tr', 'urrun'), ['Bicicletas', 'Montaña', 'Trail']),
            (('orca aero',), ['Bicicletas', 'Carretera', 'Aero']),
            (('orca',), ['Bicicletas', 'Carretera', 'Competición']),
            (('terra', 'denna'), ['Bicicletas', 'Gravel']),
            (('ordu',), ['Bicicletas', 'Triatlón y contrarreloj']),
            (('avant', 'gain'), ['Bicicletas', 'Carretera', 'Gran fondo']),
            (('diem', 'carpe', 'vector', 'kemen', 'muga'), ['Bicicletas', 'Urban & Active']),
        )
        for needles, category in patterns:
            if any(token in text for token in needles):
                result = list(category)
                if electric:
                    result[0] = 'Bicicletas eléctricas'
                return result
        return ['Bicicletas eléctricas' if electric else 'Bicicletas']

    @classmethod
    def parse_category_path(cls, product_url):
        path = urlparse(cls._canonical_url(product_url) or '').path.casefold()
        if '/equipamiento/' in path or '/oprema/' in path:
            return ['Equipamiento']
        return ['Bicicletas'] if cls._is_product_candidate(product_url) else []

    @classmethod
    def _is_product_page(cls, tree, product_json, lines, canonical):
        if not cls._is_product_candidate(canonical):
            return False
        name = cls._name(tree, product_json, canonical)
        if not name or name.casefold() in cls._GENERIC_TITLES:
            return False
        text = ' '.join(lines[:1000]).casefold()
        markers = sum(token in text for token in (
            'añadir a la cesta', 'configuración estándar', 'encuentra tu distribuidor',
            'elige talla', 'elige color', 'tamaño de rueda', 'envío estimado',
            'características principales', 'conjunto cuadro', 'ref.:',
        ))
        return bool(product_json) or markers >= 2 or (
            markers >= 1 and bool(cls._PRICE_RE.search(text))
        )

    def fetch_preview(self, source, url):
        session = self._get_session(source)
        response = self._http_get(session, url, source)
        tree = lxml_html.fromstring(response.content)
        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical = self._canonical_url(
            canonical_values[0] if canonical_values else response.url or url
        )
        product_json = self._product_json(tree)
        lines = self._page_lines(tree)
        if not self._is_product_page(tree, product_json, lines, canonical):
            fallback = self._canonical_url(url)
            if fallback != canonical and self._is_product_page(tree, product_json, lines, fallback):
                canonical = fallback
            else:
                raise ValueError(
                    'La URL no contiene una ficha española de producto Orbea; '
                    'puede ser una familia, una categoría o una redirección.'
                )

        name = self._name(tree, product_json, canonical)
        sizes, colors = self._extract_sizes_colors(lines)
        specs = self._label_values(lines)
        description = self._description_with_details(
            self._description(tree, product_json), sizes, colors, specs
        )
        price, currency = self._structured_price(tree, product_json, lines)

        images = self._json_images(product_json, canonical)
        for meta_name in ('og:image', 'twitter:image'):
            image = self._clean_image_url(self._meta(tree, meta_name), canonical)
            if image and image not in images:
                images.insert(0, image)
        for image in self._html_images(tree, canonical):
            if image not in images:
                images.append(image)

        ean_variants = self._ean_variants_from_html_content(response.content)
        category = self._category_from_content(canonical, name, lines, tree)
        return {
            'name': name,
            'description': description,
            'price': price,
            'price_available': bool(price),
            'currency': currency or 'EUR',
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical,
            'style_code': self._style_code(tree, product_json, lines, canonical),
            'color_code': ' / '.join(colors) if colors else False,
            'category_path': ' / '.join(category),
            'ean_variants': self._normalise_ean_variants(ean_variants),
            # Las combinaciones finales dependen de talla/color/configuración.
            # El extractor genérico puede enriquecerlas con endpoints descubiertos.
            'ean_complete': False,
        }
