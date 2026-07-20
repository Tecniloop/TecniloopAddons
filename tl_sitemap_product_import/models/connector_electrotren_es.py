import gzip
import html
import json
import logging
import re
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorElectrotrenEs(models.AbstractModel):
    """Conector para el catálogo español de Electrotren.

    Electrotren usa la plataforma de Hornby Hobbies. ``robots.txt`` declara
    ``https://es.electrotren.com/sitemap.xml`` y las fichas usan URLs planas::

        /products/electrotren-h0-187-electric-locomotive-renfe-269604-e2698
        /products/renfe-electric-locomotive-279-...-he2005s

    La página separa la información comercial de las especificaciones. Este
    conector lleva la descripción corta a ``description_sale``, el contenido
    de "Información del producto" a ``description_ecommerce`` y convierte la
    tabla técnica en atributos ``no_variant`` mediante el flujo común.
    """

    _name = 'sitemap.connector.electrotren_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Electrotren España'

    _HOST = 'es.electrotren.com'
    _PRODUCT_RE = re.compile(r'^/products/(?P<slug>[a-z0-9][a-z0-9-]*)/?$', re.IGNORECASE)
    _CODE_SUFFIX_RE = re.compile(
        r'-(?P<code>[a-z]{1,6}\d{2,8}[a-z0-9]{0,4})$', re.IGNORECASE,
    )
    _PRICE_RE = re.compile(
        r'(?:€\s*(?P<prefix>\d[\d.,\s]*\d|\d)|'
        r'(?P<suffix>\d[\d.,\s]*\d|\d)\s*€)',
        re.IGNORECASE,
    )
    _SCALE_RE = re.compile(r'(?<!\d)1\s*[:/]\s*(\d{1,3})(?!\d)', re.IGNORECASE)
    _GAUGE_RE = re.compile(
        r'\b(H0|HO|N|TT|Z|O|OO|G)\s*(?:Scale|Gauge|escala)?\b', re.IGNORECASE,
    )
    _IMAGE_EXT_RE = re.compile(r'\.(?:avif|gif|jpe?g|png|webp)(?:$|\?)', re.IGNORECASE)
    _NON_PRODUCT_IMAGE_RE = re.compile(
        r'(?:logo|favicon|icon|sprite|cookie|newsletter|social|payment|flag|'
        r'placeholder|loader|avatar|footer|header|menu|nav|trustpilot|reward)',
        re.IGNORECASE,
    )

    _SPEC_NAME_MAP = {
        'escala': 'Escala',
        'scale': 'Escala',
        'color': 'Color',
        'colour': 'Color',
        'epoch': 'Época',
        'época': 'Época',
        'dcc': 'DCC',
        'curva mínima (mm)': 'Curva mínima',
        'curva minima (mm)': 'Curva mínima',
        'minimum curve (mm)': 'Curva mínima',
        'motor': 'Motor',
        'con volante de inercia': 'Con volante de inercia',
        'flywheel fitted': 'Con volante de inercia',
        'pantógrafo': 'Pantógrafo',
        'pantografo': 'Pantógrafo',
        'pantograph': 'Pantógrafo',
        'enganche corto': 'Enganche corto',
        'close coupling': 'Enganche corto',
        'carrocería metálica': 'Carrocería metálica',
        'carroceria metalica': 'Carrocería metálica',
        'metal body': 'Carrocería metálica',
        'luz interior': 'Luz interior',
        'interior light': 'Luz interior',
        'topes con resorte': 'Topes con resorte',
        'sprung buffers': 'Topes con resorte',
        'livery (logotipo)': 'Compañía ferroviaria',
        'livery': 'Compañía ferroviaria',
        'bandera de la región': 'País / región',
        'bandera de la region': 'País / región',
        'region flag': 'País / región',
        'longitud': 'Longitud',
        'length': 'Longitud',
        'radio mínimo': 'Radio mínimo',
        'radio minimo': 'Radio mínimo',
        'minimum radius': 'Radio mínimo',
        'conector para decoder': 'Conector de decoder',
        'decoder socket': 'Conector de decoder',
    }
    _SPEC_STOPPERS = {
        'avisos de seguridad', 'safety information', 'comentarios',
        'customer support', 'cantidad', 'recomendado para ti',
    }
    _DESCRIPTION_STOPPERS = {
        'qué contiene', 'que contiene', 'recomendado para ti',
        'especificaciones técnicas', 'especificaciones tecnicas',
        'comentarios', 'cantidad',
    }

    # ------------------------------------------------------------------
    # Red, URL y sitemap
    # ------------------------------------------------------------------
    def _get_session(self, source):
        session = super()._get_session(source)
        session.headers.update({
            'Accept': (
                'text/html,application/xhtml+xml,application/xml;q=0.9,'
                'image/avif,image/webp,*/*;q=0.8'
            ),
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.5',
            'Cache-Control': 'no-cache',
        })
        return session

    @classmethod
    def _canonical_url(cls, value):
        raw = html.unescape(str(value or '')).strip().replace('\\/', '/')
        if not raw:
            return False
        parts = urlsplit(raw)
        host = parts.netloc.casefold()
        if host == 'www.es.electrotren.com':
            host = cls._HOST
        path = re.sub(r'/+', '/', parts.path or '/')
        if path != '/':
            path = path.rstrip('/')
        return urlunsplit((parts.scheme or 'https', host, path, '', ''))

    @classmethod
    def _product_match(cls, value):
        canonical = cls._canonical_url(value)
        if not canonical:
            return False
        parsed = urlparse(canonical)
        if parsed.netloc.casefold() != cls._HOST:
            return False
        return cls._PRODUCT_RE.match(parsed.path)

    @classmethod
    def _product_key(cls, value):
        match = cls._product_match(value)
        if not match:
            return False
        slug = match.group('slug').casefold()
        code_match = cls._CODE_SUFFIX_RE.search(slug)
        return (code_match.group('code') if code_match else slug).upper()

    @classmethod
    def _style_from_url(cls, value):
        return cls._product_key(value)

    @staticmethod
    def _xml_root(content):
        if content[:2] == b'\x1f\x8b':
            content = gzip.decompress(content)
        parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
        return etree.fromstring(content, parser=parser)

    @staticmethod
    def _local_name(element):
        return etree.QName(element).localname.casefold()

    @staticmethod
    def _robots_sitemaps(text, base_url):
        result = []
        # Se usa finditer, no splitlines: algunos proxies compactan robots.txt
        # en una sola línea conservando las directivas Sitemap.
        pattern = re.compile(r'\bSitemap\s*:\s*(https?://[^\s#]+)', re.IGNORECASE)
        for match in pattern.finditer(str(text or '')):
            value = urljoin(base_url, match.group(1).strip())
            if value not in result:
                result.append(value)
        return result

    def _candidate_sitemaps(self, source):
        candidates = []
        session = self._get_session(source)
        for candidate in (
            source.sitemap_index_url,
            'https://es.electrotren.com/robots.txt',
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
                payload = response.content.lstrip()
                if payload.startswith((b'<?xml', b'<urlset', b'<sitemapindex')) or payload[:2] == b'\x1f\x8b':
                    candidates.insert(0, response.url)
            except Exception as exc:
                _logger.info('Electrotren: no se pudo consultar %s: %s', candidate, exc)
        candidates.extend([
            'https://es.electrotren.com/sitemap.xml',
            'https://es.electrotren.com/sitemap_index.xml',
        ])
        return list(dict.fromkeys(candidates))

    def _iter_sitemap_entries(self, source, sitemap_url, depth=0, visited=None):
        if depth > 10:
            raise ValueError('El sitemap de Electrotren supera diez niveles de índices.')
        visited = visited or set()
        clean_url = str(sitemap_url or '').split('#', 1)[0]
        if not clean_url or clean_url in visited:
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
                        source,
                        urljoin(response.url, child.strip()),
                        depth + 1,
                        visited,
                    )
            return
        if root_name != 'urlset':
            raise ValueError('El XML no contiene <urlset> ni <sitemapindex>.')

        for node in root.xpath('./*[local-name()="url"]'):
            locs = node.xpath('./*[local-name()="loc"]/text()')
            if not locs:
                continue
            canonical = self._canonical_url(locs[0])
            if not self._product_match(canonical):
                continue
            lastmods = node.xpath('./*[local-name()="lastmod"]/text()')
            images = node.xpath(
                './*[local-name()="image"]/*[local-name()="loc"]/text()'
            )
            yield {
                'url': canonical,
                'lastmod': self._parse_lastmod(lastmods[0] if lastmods else None),
                'images': [item.strip() for item in images if item and item.strip()],
            }

    @classmethod
    def _clean_image_url(cls, value, page_url=''):
        raw = html.unescape(str(value or '')).strip().replace('\\/', '/')
        if not raw or raw.startswith(('data:', 'blob:')):
            return False
        # En srcset se recibe "url 1200w".
        raw = raw.split()[0]
        absolute = urljoin(page_url, raw)
        parts = urlsplit(absolute)
        if parts.scheme not in ('http', 'https'):
            return False
        if cls._NON_PRODUCT_IMAGE_RE.search(parts.path):
            return False
        if not cls._IMAGE_EXT_RE.search(parts.path):
            return False
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))

    @classmethod
    def _product_links_from_tree(cls, tree, page_url):
        result = []
        for href in tree.xpath('//a[@href]/@href'):
            absolute = cls._canonical_url(urljoin(page_url, href))
            if cls._product_match(absolute) and absolute not in result:
                result.append(absolute)
        return result

    def _fallback_catalog_entries(self, source, limit=0):
        """Recorre el catálogo público si el sitemap no entrega XML utilizable."""
        start_urls = [
            'https://es.electrotren.com/catalogue',
            'https://es.electrotren.com/catalogue/trains-train-sets',
            'https://es.electrotren.com/catalogue/trains-train-sets/locomotoras',
            'https://es.electrotren.com/catalogue/trains-train-sets/coches',
            'https://es.electrotren.com/catalogue/trains-train-sets/wagons-wagon-sets',
            'https://es.electrotren.com/catalogue/track-and-power',
            'https://es.electrotren.com/catalogue/buildings-accessories',
            'https://es.electrotren.com/catalogue/epoch',
        ]
        queue = list(start_urls)
        visited = set()
        products = {}
        session = self._get_session(source)

        while queue and len(visited) < 350:
            page_url = queue.pop(0)
            if page_url in visited:
                continue
            visited.add(page_url)
            try:
                response = self._http_get(session, page_url, source)
                tree = lxml_html.fromstring(response.content)
            except Exception as exc:
                _logger.info('Electrotren: catálogo no accesible %s: %s', page_url, exc)
                continue

            for product_url in self._product_links_from_tree(tree, response.url):
                key = self._product_key(product_url)
                if key and key not in products:
                    products[key] = {'url': product_url, 'lastmod': False}
            if limit and len(products) >= limit:
                break

            for href in tree.xpath('//a[@href]/@href'):
                absolute = urljoin(response.url, href)
                parts = urlsplit(absolute)
                if parts.netloc.casefold() != self._HOST:
                    continue
                if not parts.path.startswith('/catalogue'):
                    continue
                clean = urlunsplit((parts.scheme or 'https', parts.netloc, parts.path, parts.query, ''))
                if clean not in visited and clean not in queue:
                    queue.append(clean)

        return list(products.values())

    def _collect_products(self, source):
        entries = {}
        image_map = {}
        errors = []
        for sitemap_url in self._candidate_sitemaps(source):
            try:
                for item in self._iter_sitemap_entries(source, sitemap_url):
                    key = self._product_key(item['url'])
                    if not key:
                        continue
                    previous = entries.get(key)
                    if not previous or (item.get('lastmod') and not previous.get('lastmod')):
                        entries[key] = {
                            'url': item['url'],
                            'lastmod': item.get('lastmod') or False,
                        }
                    for raw_image in item.get('images') or []:
                        image = self._clean_image_url(raw_image, item['url'])
                        if image and image not in image_map.setdefault(key, []):
                            image_map[key].append(image)
            except Exception as exc:
                errors.append(f'{sitemap_url}: {exc}')
                _logger.info('Electrotren: sitemap no utilizable %s: %s', sitemap_url, exc)
        return entries, image_map, errors

    def get_product_entries(self, source, category_filter=None, limit=0):
        sitemap_entries, _image_map, errors = self._collect_products(source)
        try:
            catalog_entries = self._fallback_catalog_entries(source, limit=0)
        except Exception as exc:
            _logger.warning('Electrotren: no se pudo recorrer el catálogo alternativo: %s', exc)
            catalog_entries = []

        result = self._merge_discovery_entries(
            'Electrotren',
            [('sitemap', list(sitemap_entries.values())),
             ('catalogo_html', catalog_entries)],
            key_getter=self._product_key,
            category_filter=category_filter,
            limit=limit,
        )
        if not result:
            raise ValueError(
                'No se localizaron fichas de Electrotren en el sitemap ni en el catálogo.'
                + (f' Intentos: {" | ".join(errors[:4])}' if errors else '')
            )
        return result

    def get_image_map(self, source):
        entries, image_map, _errors = self._collect_products(source)
        return {
            entry['url']: image_map.get(key, [])
            for key, entry in entries.items()
            if image_map.get(key)
        }

    # ------------------------------------------------------------------
    # Utilidades de ficha
    # ------------------------------------------------------------------
    @staticmethod
    def _normalise_text(value):
        return re.sub(r'\s+', ' ', html.unescape(str(value or ''))).strip()

    @classmethod
    def _visible_lines(cls, tree):
        result = []
        for raw in tree.xpath(
            '//body//*[not(self::script) and not(self::style) and not(self::noscript)]/text()'
        ):
            value = cls._normalise_text(raw)
            if value and value not in result[-2:]:
                result.append(value)
        return result

    @staticmethod
    def _json_payloads(tree):
        result = []
        for raw in tree.xpath(
            '//script[@type="application/ld+json" or @type="application/json"]/text()'
        ):
            if not raw or len(raw) > 10_000_000:
                continue
            try:
                result.append(json.loads(raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return result

    @classmethod
    def _walk_dicts(cls, value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from cls._walk_dicts(child)
        elif isinstance(value, list):
            for child in value:
                yield from cls._walk_dicts(child)

    @classmethod
    def _product_json_node(cls, payloads):
        for payload in payloads:
            for node in cls._walk_dicts(payload):
                raw_type = node.get('@type')
                types = raw_type if isinstance(raw_type, list) else [raw_type]
                if any(str(item or '').casefold() == 'product' for item in types):
                    return node
        return {}

    @classmethod
    def _breadcrumb_json(cls, payloads, product_name):
        for payload in payloads:
            for node in cls._walk_dicts(payload):
                if str(node.get('@type') or '').casefold() != 'breadcrumblist':
                    continue
                values = []
                for item in node.get('itemListElement') or []:
                    if not isinstance(item, dict):
                        continue
                    nested = item.get('item') if isinstance(item.get('item'), dict) else {}
                    name = cls._normalise_text(item.get('name') or nested.get('name'))
                    if name:
                        values.append(name)
                return cls._clean_breadcrumbs(values, product_name)
        return []

    @classmethod
    def _clean_breadcrumbs(cls, values, product_name):
        excluded = {'inicio', 'home', 'electrotren', 'productos', 'products', 'shop', 'tienda'}
        product_fold = cls._normalise_text(product_name).casefold()
        result = []
        for raw in values or []:
            value = cls._normalise_text(raw)
            if not value or value.casefold() in excluded or value.casefold() == product_fold:
                continue
            if value not in result:
                result.append(value)
        return result

    @classmethod
    def _dom_breadcrumbs(cls, tree, product_name):
        values = tree.xpath(
            '//*[contains(@class,"breadcrumb") or @aria-label="breadcrumb" or '
            '@aria-label="Breadcrumb"]//a/text() | '
            '//*[contains(@class,"breadcrumb") or @aria-label="breadcrumb" or '
            '@aria-label="Breadcrumb"]//*[self::span or self::li]/text()'
        )
        return cls._clean_breadcrumbs(values, product_name)

    @staticmethod
    def _offer_nodes(product_node):
        offers = product_node.get('offers') if isinstance(product_node, dict) else None
        if isinstance(offers, dict):
            return [offers]
        if isinstance(offers, list):
            return [item for item in offers if isinstance(item, dict)]
        return []

    @classmethod
    def _parse_amount(cls, value):
        text = cls._normalise_text(value).replace('€', '').replace('\xa0', ' ').strip()
        if not text:
            return 0.0
        text = re.sub(r'[^0-9,.-]', '', text)
        if not text:
            return 0.0
        if ',' in text and '.' in text:
            if text.rfind(',') > text.rfind('.'):
                text = text.replace('.', '').replace(',', '.')
            else:
                text = text.replace(',', '')
        elif ',' in text:
            decimals = len(text.rsplit(',', 1)[1])
            text = text.replace('.', '')
            text = text.replace(',', '.' if decimals in (1, 2) else '')
        elif text.count('.') > 1:
            text = text.replace('.', '')
        try:
            return float(text)
        except ValueError:
            return 0.0

    @classmethod
    def _price_from_page(cls, tree, lines, product_node, product_name):
        prices = []
        currency = 'EUR'
        for offer in cls._offer_nodes(product_node):
            currency = cls._normalise_text(offer.get('priceCurrency')) or currency
            # Hornby puede publicar simultáneamente precio anterior, precio
            # actual y precio rebajado. Se conservan todos y se selecciona el
            # menor importe positivo, que es el precio comercial vigente.
            for field in (
                'salePrice', 'lowPrice', 'price', 'currentPrice',
                'discountedPrice', 'offerPrice',
            ):
                price = cls._parse_amount(offer.get(field))
                if price > 0:
                    prices.append(price)
        if prices:
            return min(prices), currency, True

        def meta(prop):
            values = tree.xpath(
                f'//meta[@property="{prop}" or @name="{prop}"]/@content'
            )
            return values[0] if values else False

        meta_price = meta('product:price:amount') or meta('og:price:amount')
        meta_currency = meta('product:price:currency') or meta('og:price:currency')
        parsed = cls._parse_amount(meta_price)
        if parsed > 0:
            return parsed, cls._normalise_text(meta_currency) or currency, True

        # Limita la búsqueda al bloque de cabecera de la ficha; así no toma
        # precios de "Recomendado para ti".
        start = 0
        name_fold = cls._normalise_text(product_name).casefold()
        for index, line in enumerate(lines):
            if line.casefold() == name_fold:
                start = index
                break
        end = min(len(lines), start + 80)
        for index in range(start, min(len(lines), start + 120)):
            if lines[index].casefold() in {'información del producto', 'informacion del producto'}:
                end = index
                break
        block = ' '.join(lines[start:end])
        header_prices = []
        for match in cls._PRICE_RE.finditer(block):
            price = cls._parse_amount(match.group('prefix') or match.group('suffix'))
            if price > 0:
                header_prices.append(price)
        if header_prices:
            return min(header_prices), currency, True
        return 0.0, currency, False

    @classmethod
    def _item_code(cls, tree, lines, product_node, url):
        candidates = []
        if isinstance(product_node, dict):
            candidates.extend([
                product_node.get('sku'), product_node.get('mpn'),
                product_node.get('productID'), product_node.get('productId'),
            ])
        for value in tree.xpath(
            '//*[@data-product-code]/@data-product-code | '
            '//*[@data-sku]/@data-sku | //*[@itemprop="sku"]/@content | '
            '//*[@itemprop="sku"]/text()'
        ):
            candidates.append(value)
        for index, line in enumerate(lines):
            match = re.search(
                r'(?:Código del artículo|Codigo del articulo|Item code|Product code)\s*:?\s*([A-Z0-9._-]+)?',
                line,
                re.IGNORECASE,
            )
            if not match:
                continue
            candidates.append(match.group(1))
            if index + 1 < len(lines):
                candidates.append(lines[index + 1])
        candidates.append(cls._style_from_url(url))
        for candidate in candidates:
            value = cls._normalise_text(candidate).strip(' .:-').upper()
            if not value or value in {'CÓDIGO DEL ARTÍCULO', 'CODIGO DEL ARTICULO'}:
                continue
            if re.fullmatch(r'[A-Z]{1,8}[A-Z0-9._-]{1,20}', value):
                return value
        return cls._style_from_url(url) or False

    @classmethod
    def _section_lines(cls, lines, heading_names, stoppers):
        headings = {cls._normalise_text(item).casefold() for item in heading_names}
        stopper_set = {cls._normalise_text(item).casefold() for item in stoppers}
        start = False
        # La navegación de pestañas repite estos rótulos antes de los bloques
        # reales. Se usa la última aparición para no empezar en el enlace de
        # navegación y terminar inmediatamente en el siguiente rótulo.
        for index, line in enumerate(lines):
            if line.casefold() in headings:
                start = index + 1
        if start is False:
            return []
        result = []
        for line in lines[start:]:
            folded = line.casefold()
            if folded in stopper_set:
                break
            if line not in result[-2:]:
                result.append(line)
        return result

    @classmethod
    def _section_html(cls, lines, title=False):
        if not lines:
            return ''
        parts = []
        if title:
            parts.append(f'<h3>{html.escape(title)}</h3>')
        bullets = []

        def flush_bullets():
            if bullets:
                parts.append('<ul>' + ''.join(
                    f'<li>{html.escape(item)}</li>' for item in bullets
                ) + '</ul>')
                bullets.clear()

        for raw in lines:
            value = cls._normalise_text(raw)
            if not value:
                continue
            if value.startswith(('•', '·', '- ')):
                bullets.append(value.lstrip('•·- ').strip())
                continue
            flush_bullets()
            if value.endswith(':') or value.casefold().startswith('características de'):
                parts.append(f'<p><strong>{html.escape(value)}</strong></p>')
            else:
                parts.append(f'<p>{html.escape(value)}</p>')
        flush_bullets()
        return ''.join(parts)

    @classmethod
    def _spec_attributes(cls, lines):
        attributes = {}
        spec_lines = cls._section_lines(
            lines,
            ('Especificaciones técnicas', 'Technical specifications'),
            cls._SPEC_STOPPERS,
        )
        if not spec_lines:
            return attributes

        def add(name, value):
            name = cls._normalise_text(name)
            value = cls._normalise_text(value)
            if not name or not value:
                return
            if value.casefold() == 'yes':
                value = 'Sí'
            elif value.casefold() == 'no':
                value = 'No'
            attributes.setdefault(name, [])
            if value not in attributes[name]:
                attributes[name].append(value)

        index = 0
        while index < len(spec_lines):
            raw_label = cls._normalise_text(spec_lines[index]).strip(' :')
            mapped = cls._SPEC_NAME_MAP.get(raw_label.casefold())
            if not mapped or index + 1 >= len(spec_lines):
                index += 1
                continue
            raw_value = cls._normalise_text(spec_lines[index + 1]).strip(' :')
            if raw_value.casefold() in cls._SPEC_NAME_MAP:
                index += 1
                continue
            if mapped == 'Escala':
                scale = cls._SCALE_RE.search(raw_value)
                if scale:
                    add('Escala', f'1:{int(scale.group(1))}')
                gauge = cls._GAUGE_RE.search(raw_value)
                if gauge:
                    gauge_value = gauge.group(1).upper().replace('HO', 'H0')
                    add('Escala ferroviaria', gauge_value)
                if not scale:
                    add(mapped, raw_value)
            else:
                add(mapped, raw_value)
            index += 2
        return attributes

    @classmethod
    def _product_type(cls, lines, name):
        name_fold = cls._normalise_text(name).casefold()
        for index, line in enumerate(lines):
            if line.casefold() != name_fold:
                continue
            for candidate in lines[index + 1:index + 5]:
                folded = candidate.casefold()
                if folded in {
                    'electric', 'diesel', 'steam', 'coach', 'wagon',
                    'train set', 'accessory', 'track', 'decoder',
                }:
                    return candidate
        text = name_fold
        if any(token in text for token in ('eléctrica', 'electrica', 'electric')):
            return 'Electric'
        if any(token in text for token in ('diésel', 'diesel')):
            return 'Diesel'
        if any(token in text for token in ('vapor', 'steam')):
            return 'Steam'
        return False

    @classmethod
    def _inferred_category(cls, name, product_type=False):
        text = f'{name} {product_type or ""}'.casefold()
        if any(token in text for token in ('set de tren', 'train set', 'set base', 'starter set')):
            return ['Trenes y Set', 'Set de trenes']
        if any(token in text for token in ('locomotora', 'locomotive')):
            result = ['Trenes y Set', 'Locomotoras']
            if any(token in text for token in ('eléctrica', 'electrica', 'electric')):
                result.append('Eléctricas')
            elif any(token in text for token in ('diésel', 'diesel')):
                result.append('Diésel')
            elif any(token in text for token in ('vapor', 'steam')):
                result.append('Vapor')
            return result
        if any(token in text for token in ('automotor', 'unidad ', 'electrotrén', 'electrotren basculante', 'railcar', 'emu')):
            return ['Trenes y Set', 'Automotores y unidades']
        if any(token in text for token in ('coche de viajeros', 'coche ', 'coach')):
            return ['Trenes y Set', 'Coches y set']
        if any(token in text for token in ('vagón', 'vagon', 'wagon', 'freight car')):
            return ['Trenes y Set', 'Vagones y set']
        if any(token in text for token in ('vía', 'via ', 'track')):
            return ['Vías y alimentación', 'Vías']
        if any(token in text for token in ('decoder', 'dcc', 'hm7000')):
            return ['Vías y alimentación', 'Control de mando digital DCC']
        if any(token in text for token in ('edificio', 'building', 'puente', 'platform')):
            return ['Edificios y accesorios']
        if any(token in text for token in ('repuesto', 'spare')):
            return ['Trenes y Set', 'Repuestos']
        if any(token in text for token in ('catálogo', 'catalogue', 'publicación', 'publication')):
            return ['Publicaciones y catálogos']
        return ['Trenes y Set']

    @classmethod
    def _images_from_product(cls, tree, product_node, page_url, product_name, style_code):
        result = []

        def add(raw):
            if isinstance(raw, dict):
                raw = raw.get('url') or raw.get('contentUrl')
            image = cls._clean_image_url(raw, page_url)
            if image and image not in result:
                result.append(image)

        raw_images = product_node.get('image') if isinstance(product_node, dict) else None
        if isinstance(raw_images, list):
            for raw in raw_images:
                add(raw)
        else:
            add(raw_images)

        for raw in tree.xpath(
            '//meta[@property="og:image" or @name="og:image"]/@content | '
            '//meta[@property="twitter:image" or @name="twitter:image"]/@content'
        ):
            add(raw)

        name_tokens = [
            token for token in re.findall(r'[a-z0-9]+', product_name.casefold())
            if len(token) >= 4
        ][:6]
        style_fold = str(style_code or '').casefold()
        for node in tree.xpath('//img[@src or @data-src or @data-zoom-image or @srcset]'):
            alt = cls._normalise_text(node.get('alt')).casefold()
            sources = [
                node.get('data-zoom-image'), node.get('data-src'), node.get('src'),
            ]
            if node.get('srcset'):
                sources.extend(
                    part.strip().split()[0]
                    for part in node.get('srcset').split(',') if part.strip()
                )
            for raw in sources:
                raw_fold = str(raw or '').casefold()
                matches_product = (
                    (style_fold and style_fold in raw_fold)
                    or (name_tokens and sum(token in alt for token in name_tokens) >= 2)
                )
                if matches_product:
                    add(raw)
        return result

    # ------------------------------------------------------------------
    # Vista previa
    # ------------------------------------------------------------------
    def fetch_preview(self, source, url):
        canonical_requested = self._canonical_url(url)
        session = self._get_session(source)
        response = self._http_get(session, canonical_requested, source)
        canonical_response = self._canonical_url(response.url)
        if not self._product_match(canonical_response):
            raise ValueError(
                'Electrotren redirigió la ficha a una página que no es un producto: '
                f'{response.url}'
            )

        page_markup = getattr(response, 'text', None) or response.content
        tree = lxml_html.fromstring(page_markup)
        lines = self._visible_lines(tree)
        payloads = self._json_payloads(tree)
        product_node = self._product_json_node(payloads)

        h1_values = tree.xpath('//h1//text()')
        name = self._normalise_text(product_node.get('name')) if product_node else ''
        if not name:
            name = self._normalise_text(' '.join(h1_values))
        if not name:
            name = self._normalise_text(
                (tree.xpath('//meta[@property="og:title"]/@content') or [''])[0]
            )
        if not name:
            raise ValueError('La ficha de Electrotren no contiene un nombre de producto.')

        style_code = self._item_code(tree, lines, product_node, canonical_response)
        # Toda ficha Hornby pasa por el mismo flujo de precio oficial EUR.
        # En Electrotren la propia respuesta española ya es el escaparate EUR,
        # por lo que se reutiliza y no se realiza una segunda petición.
        price, currency, price_available = self._hornby_official_eur_price(
            source=source,
            session=session,
            product_url=canonical_response,
            expected_code=style_code,
            eur_hosts=(self._HOST,),
            existing_response=response,
            code_getter=self._product_key,
            price_parser=lambda eur_tree, eur_lines, eur_node, eur_name: self._price_from_page(
                eur_tree, eur_lines, eur_node, eur_name,
            ),
            brand_name='Electrotren',
        )

        meta_description = self._normalise_text(
            (tree.xpath(
                '//meta[@property="og:description" or @name="description"]/@content'
            ) or [''])[0]
        )
        json_description = self._normalise_text(product_node.get('description')) if product_node else ''
        info_lines = self._section_lines(
            lines,
            ('Información del producto', 'Product information'),
            self._DESCRIPTION_STOPPERS,
        )
        # La primera línea suele repetir el nombre exacto del artículo.
        while info_lines and info_lines[0].casefold() == name.casefold():
            info_lines.pop(0)
        contains_lines = self._section_lines(
            lines,
            ('Qué contiene', 'Que contiene', "What's inside", 'Contents'),
            {'recomendado para ti', 'especificaciones técnicas', 'comentarios', 'cantidad'},
        )
        full_description = self._section_html(info_lines)
        if contains_lines:
            full_description += self._section_html(contains_lines, title='Contenido')
        short_description = json_description or meta_description
        if not short_description and info_lines:
            short_description = info_lines[0]
        description = '\n'.join(info_lines) or short_description or name

        attributes = self._spec_attributes(lines)
        product_type = self._product_type(lines, name)
        if product_type:
            type_map = {
                'electric': 'Eléctrico', 'diesel': 'Diésel', 'steam': 'Vapor',
                'coach': 'Coche de viajeros', 'wagon': 'Vagón',
                'train set': 'Set de trenes', 'track': 'Vía',
                'decoder': 'Decoder', 'accessory': 'Accesorio',
            }
            value = type_map.get(product_type.casefold(), product_type)
            attributes.setdefault('Tipo de producto ferroviario', [])
            if value not in attributes['Tipo de producto ferroviario']:
                attributes['Tipo de producto ferroviario'].append(value)

        breadcrumbs = self._breadcrumb_json(payloads, name) or self._dom_breadcrumbs(tree, name)
        if breadcrumbs:
            category_segments = breadcrumbs
        else:
            category_segments = self._inferred_category(name, product_type)

        images = self._images_from_product(
            tree, product_node, canonical_response, name, style_code,
        )
        ean_variants = self._ean_variants_from_html_content(response.content)

        return {
            'name': name,
            'description': description,
            'short_description': short_description or description,
            'full_description': full_description or html.escape(description),
            'price': price,
            'price_available': price_available,
            'currency': currency or 'EUR',
            'category_path': '/'.join(category_segments),
            'style_code': style_code,
            'color_code': False,
            'attributes': attributes,
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical_response,
            'ean_variants': ean_variants,
            # No se declara completo: la capa común seguirá buscando GTIN en
            # JSON y endpoints públicos que la ficha pueda revelar.
            'ean_complete': False,
        }
