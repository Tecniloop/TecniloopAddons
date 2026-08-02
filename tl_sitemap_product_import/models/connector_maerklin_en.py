import gzip
import html
import logging
import re
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorMaerklinEn(models.AbstractModel):
    """Conector para la base de productos internacional de Märklin.

    El sitemap inglés expone páginas de artículo con esta forma::

        /en/products/details/article/36506
        /en/products/details/article/36506/21
        /en/products/details/article/55388/9%2C51%2C75

    El último segmento es navegación/contexto de la web y no identifica una
    variante. Todas esas URLs se deduplican por ``Article No.``.

    Las fichas publican precio recomendado en EUR, escala, época, tipo de
    artículo, prototipo, descripción del modelo, funciones digitales, imágenes
    y estado del producto. La web también conserva artículos históricos; si ya
    no publica precio se marca ``price_available=False`` para no borrar precios
    introducidos manualmente en Odoo.
    """

    _name = 'sitemap.connector.maerklin_en'
    _inherit = 'sitemap.connector.electrotren_es'
    _description = 'Conector Märklin Europa'

    _HOST = 'www.maerklin.de'
    _PRODUCT_RE = re.compile(
        r'^/en/products/details/article/(?P<code>\d+)(?:/[^/?#]+)?/?$',
        re.IGNORECASE,
    )
    _PRICE_RE = re.compile(
        r'(?:€\s*(?P<prefix>\d[\d.,\s]*\d|\d)|'
        r'(?P<suffix>\d[\d.,\s]*\d|\d)\s*€)',
        re.IGNORECASE,
    )
    _DETAIL_LABELS = {
        'article no.': 'Número de artículo',
        'article no': 'Número de artículo',
        'gauge / design type': 'Escala / tipo de diseño',
        'gauge/design type': 'Escala / tipo de diseño',
        'gauge': 'Escala ferroviaria',
        'design type': 'Escala',
        'era': 'Época',
        'kind': 'Tipo de producto ferroviario',
        'product line': 'Línea de producto',
        'manufacturer': 'Fabricante',
    }
    _SECTION_HEADINGS = {
        'highlights', 'product description', 'prototype', 'model',
        'digital functions', 'most important facts', 'downloads',
        'spare parts', 'buy online', 'dealer search', 'warning',
    }
    _SECTION_STOPPERS = {
        'downloads', 'spare parts', 'buy online', 'dealer search',
        'tax details', 'warning', 'usa', 'back to list', 'quantity',
        'recommended for you', 'these services process personal information',
    }
    _NON_PRODUCT_PATHS = (
        '/en/products/products', '/en/products/gauge-h0', '/en/products/gauge-1',
        '/en/products/z-scale', '/en/products/my-world', '/en/products/start-up',
    )

    # ------------------------------------------------------------------
    # URL, sitemap y descubrimiento
    # ------------------------------------------------------------------
    def _get_session(self, source):
        session = super()._get_session(source)
        session.headers.update({
            'Accept': (
                'text/html,application/xhtml+xml,application/xml;q=0.9,'
                'image/avif,image/webp,*/*;q=0.8'
            ),
            'Accept-Language': 'en-GB,en;q=0.9,de;q=0.6',
            'Cache-Control': 'no-cache',
        })
        return session

    @classmethod
    def _canonical_url(cls, value):
        raw = html.unescape(str(value or '')).strip().replace('\\/', '/')
        if not raw:
            return False
        parts = urlsplit(raw)
        host = parts.netloc.casefold().removeprefix('www.')
        if host not in {'maerklin.de', 'marklin.de'}:
            return False
        path = re.sub(r'/+', '/', parts.path or '/')
        if path != '/':
            path = path.rstrip('/')
        return urlunsplit((parts.scheme or 'https', cls._HOST, path, '', ''))

    @classmethod
    def _product_match(cls, value):
        canonical = cls._canonical_url(value)
        if not canonical:
            return False
        return cls._PRODUCT_RE.match(urlparse(canonical).path)

    @classmethod
    def _product_key(cls, value):
        match = cls._product_match(value)
        return match.group('code') if match else False

    @classmethod
    def _style_from_url(cls, value):
        return cls._product_key(value)

    @staticmethod
    def _xml_root(content):
        if content[:2] == b'\x1f\x8b':
            content = gzip.decompress(content)
        parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
        return etree.fromstring(content, parser=parser)

    # ------------------------------------------------------------------
    # Descubrimiento numérico del catálogo del grupo Märklin
    # ------------------------------------------------------------------
    def _uses_numeric_scanner(self, source):
        """Estas fuentes no dependen del sitemap para descubrir artículos."""
        return True

    def _numeric_scan_bounds(self, source):
        start = int(source.numeric_scan_start or 0)
        end = int(source.numeric_scan_end or 0)
        if source.numeric_scan_resume and source.numeric_scan_last_article:
            start = max(start, int(source.numeric_scan_last_article) + 1)
        return start, end

    def _numeric_scan_block_size(self, source):
        return max(int(source.numeric_scan_block_size or 250), 1)

    def _numeric_scan_url(self, source, article_number):
        return f"https://{self._HOST}/en/products/details/article/{article_number}"

    @staticmethod
    def _numeric_page_missing(content):
        """Descarta la página antes de construir lxml o analizar metadatos."""
        payload = bytes(content or b'').lower()
        return any(message in payload for message in (
            b'unfortunately, no product could be found for your search inquiry',
            b'leider konnte kein produkt zu ihrer suchanfrage gefunden werden',
        ))

    def _numeric_page_matches_source(self, content):
        # Märklin usa un dominio independiente, por lo que una ficha válida
        # pertenece a esta fuente. Trix/Minitrix especializan este método.
        return True

    def _candidate_sitemaps(self, source):
        candidates = []
        session = self._get_session(source)
        for candidate in (
            source.sitemap_index_url,
            'https://www.maerklin.de/robots.txt',
            'https://www.maerklin.de/en/robots.txt',
        ):
            if not candidate or candidate in candidates:
                continue
            try:
                response = session.get(
                    candidate,
                    timeout=source.request_timeout or 30,
                    allow_redirects=True,
                )
                if response.status_code >= 400:
                    continue
                candidates.extend(self._robots_sitemaps(response.text, response.url))
                payload = response.content.lstrip()
                if payload.startswith((b'<?xml', b'<urlset', b'<sitemapindex')) \
                        or payload[:2] == b'\x1f\x8b':
                    candidates.insert(0, response.url)
            except Exception as exc:
                _logger.info('Märklin: no se pudo consultar %s: %s', candidate, exc)
        candidates.extend([
            'https://www.maerklin.de/en/sitemap.xml',
            'https://www.maerklin.de/sitemap.xml',
            'https://www.maerklin.de/sitemap_index.xml',
            'https://www.maerklin.de/sitemapindex.xml',
        ])
        return list(dict.fromkeys(candidates))

    def _iter_sitemap_entries(self, source, sitemap_url, depth=0, visited=None):
        if depth > 12:
            raise ValueError('El sitemap de Märklin supera doce niveles de índices.')
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
                        source, urljoin(response.url, child.strip()), depth + 1, visited,
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
    def _product_links_from_tree(cls, tree, page_url):
        result = []
        for href in tree.xpath('//a[@href]/@href'):
            absolute = cls._canonical_url(urljoin(page_url, href))
            if cls._product_match(absolute) and absolute not in result:
                result.append(absolute)
        return result

    def _fallback_catalog_entries(self, source, limit=0):
        """Recorre las áreas públicas cuando el sitemap no puede leerse.

        Se incluyen los tres anchos de vía y las líneas infantiles. Las páginas
        de resultados paginadas se siguen únicamente dentro de ``/en/products``.
        """
        start_urls = [
            'https://www.maerklin.de/en/products/gauge-h0/all-items',
            'https://www.maerklin.de/en/products/gauge-h0/locomotives',
            'https://www.maerklin.de/en/products/gauge-h0/sets',
            'https://www.maerklin.de/en/products/gauge-1/all-items',
            'https://www.maerklin.de/en/products/z-scale/all-items',
            'https://www.maerklin.de/en/products/my-world/product-search',
            'https://www.maerklin.de/en/products/start-up/product-search',
            'https://www.maerklin.de/en/products/products',
        ]
        queue = list(start_urls)
        visited = set()
        products = {}
        session = self._get_session(source)

        while queue and len(visited) < 650:
            page_url = queue.pop(0)
            if page_url in visited:
                continue
            visited.add(page_url)
            try:
                response = self._http_get(session, page_url, source)
                tree = lxml_html.fromstring(response.content)
            except Exception as exc:
                _logger.info('Märklin: catálogo no accesible %s: %s', page_url, exc)
                continue

            for product_url in self._product_links_from_tree(tree, response.url):
                key = self._product_key(product_url)
                if key and key not in products:
                    products[key] = {'url': product_url, 'lastmod': False}
            if limit and len(products) >= limit:
                break

            for href in tree.xpath('//a[@href]/@href'):
                absolute = self._canonical_url(urljoin(response.url, href))
                if not absolute:
                    continue
                parts = urlsplit(absolute)
                if not parts.path.startswith('/en/products/'):
                    continue
                if self._product_match(absolute):
                    continue
                # Solo resultados/listados/paginación; se evitan noticias y servicios.
                if not any(token in parts.path for token in (
                    '/gauge-h0/', '/gauge-1/', '/z-scale/', '/my-world/',
                    '/start-up/', '/products', '/product-search',
                )):
                    continue
                if absolute not in visited and absolute not in queue:
                    queue.append(absolute)
        return list(products.values())

    def _collect_products(self, source, limit=0):
        products = {}
        image_map = {}
        errors = []
        for sitemap_url in self._candidate_sitemaps(source):
            try:
                for item in self._iter_sitemap_entries(source, sitemap_url):
                    key = self._product_key(item['url'])
                    if not key:
                        continue
                    existing = products.get(key)
                    if not existing or (item.get('lastmod') and not existing.get('lastmod')):
                        products[key] = {
                            'url': item['url'], 'lastmod': item.get('lastmod'),
                        }
                    if item.get('images'):
                        image_map.setdefault(key, [])
                        for image in item['images']:
                            cleaned = self._clean_image_url(image, item['url'])
                            if cleaned and cleaned not in image_map[key]:
                                image_map[key].append(cleaned)
                if products:
                    break
            except Exception as exc:
                errors.append(f'{sitemap_url}: {exc}')
                _logger.info('Märklin: sitemap no utilizable %s: %s', sitemap_url, exc)

        if not products:
            for item in self._fallback_catalog_entries(source, limit=limit):
                key = self._product_key(item['url'])
                if key and key not in products:
                    products[key] = item
        if not products and errors:
            raise ValueError(
                'No se pudieron descubrir productos de Märklin. ' + ' | '.join(errors[-3:])
            )
        return list(products.values()), image_map

    def get_product_entries(self, source, category_filter=None, limit=0):
        entries, _image_map = self._collect_products(source, limit=limit)
        # Las categorías no están codificadas en la URL de detalle. Se aplican
        # tras leer la ficha y no se finge un filtro previo poco fiable.
        return entries[:limit] if limit else entries

    def get_image_map(self, source):
        entries, image_map = self._collect_products(source)
        url_by_key = {self._product_key(item['url']): item['url'] for item in entries}
        return {
            url_by_key[key]: values
            for key, values in image_map.items()
            if key in url_by_key and values
        }

    def parse_category_path(self, product_url):
        return []

    # ------------------------------------------------------------------
    # Ficha de producto
    # ------------------------------------------------------------------
    @classmethod
    def _line_value(cls, lines, labels):
        labels_fold = {cls._normalise_text(label).casefold() for label in labels}
        for index, line in enumerate(lines):
            clean = cls._normalise_text(line)
            folded = clean.casefold().strip(' :')
            for label in labels_fold:
                if folded == label:
                    for candidate in lines[index + 1:index + 4]:
                        value = cls._normalise_text(candidate).strip(' :')
                        if value and value.casefold().strip(' :') not in labels_fold:
                            return value
                if folded.startswith(label + ':'):
                    value = clean.split(':', 1)[1].strip()
                    if value:
                        return value
                if folded.startswith(label + ' '):
                    value = clean[len(label):].strip(' :')
                    if value:
                        return value
        return False

    @classmethod
    def _maerklin_price(cls, tree, lines, product_node, product_name):
        # Primero ofertas estructuradas y metadatos del producto principal.
        prices = []
        currency = 'EUR'
        for offer in cls._offer_nodes(product_node):
            currency = cls._normalise_text(offer.get('priceCurrency')) or currency
            for field in (
                'salePrice', 'lowPrice', 'price', 'currentPrice',
                'discountedPrice', 'offerPrice',
            ):
                amount = cls._parse_amount(offer.get(field))
                if amount > 0:
                    prices.append(amount)
        if prices and str(currency).upper() in {'EUR', '€'}:
            return min(prices), 'EUR', True

        def meta(prop):
            values = tree.xpath(
                f'//meta[@property="{prop}" or @name="{prop}"]/@content'
            )
            return values[0] if values else False

        meta_price = meta('product:price:amount') or meta('og:price:amount')
        meta_currency = cls._normalise_text(
            meta('product:price:currency') or meta('og:price:currency') or 'EUR'
        ).upper()
        parsed_meta = cls._parse_amount(meta_price)
        if parsed_meta > 0 and meta_currency in {'EUR', '€'}:
            return parsed_meta, 'EUR', True

        # En la ficha visible el PVP aparece en "Most Important Facts" y/o
        # junto a "RRP, incl.". Se limita la ventana para no leer artículos
        # recomendados situados al final de la página.
        windows = []
        for index, line in enumerate(lines):
            folded = line.casefold().strip(' :')
            if folded == 'most important facts':
                windows.append(' '.join(lines[index:index + 50]))
            if 'rrp' in folded or 'recommended retail price' in folded:
                windows.append(' '.join(lines[max(0, index - 4):index + 5]))
        if not windows:
            name_fold = cls._normalise_text(product_name).casefold()
            for index, line in enumerate(lines):
                if line.casefold() == name_fold:
                    windows.append(' '.join(lines[index:index + 45]))
                    break

        for block in windows:
            block_prices = []
            for match in cls._PRICE_RE.finditer(block):
                value = cls._parse_amount(match.group('prefix') or match.group('suffix'))
                if value > 0:
                    block_prices.append(value)
            if block_prices:
                return min(block_prices), 'EUR', True
        return 0.0, 'EUR', False

    @classmethod
    def _status(cls, lines):
        joined = ' '.join(lines).casefold()
        checks = (
            ('article not produced anymore', 'Ya no se fabrica'),
            ('production sold out', 'Producción agotada'),
            ('article not yet in stock', 'Todavía no disponible'),
            ('article in stock', 'En stock'),
            ('available ex works', 'Disponible de fábrica'),
            ('new item', 'Novedad'),
        )
        return [label for needle, label in checks if needle in joined]

    @classmethod
    def _gauge_attributes(cls, raw_value):
        value = cls._normalise_text(raw_value)
        attributes = {}
        if not value:
            return attributes
        gauge_match = re.search(r'\b(H0|HO|Z|N|TT|G|Gauge\s*1|1)\b', value, re.IGNORECASE)
        if gauge_match:
            gauge = gauge_match.group(1).upper().replace('HO', 'H0')
            if gauge.startswith('GAUGE') or gauge == '1':
                gauge = '1'
            attributes['Escala ferroviaria'] = [gauge]
        scale_match = re.search(r'(?<!\d)1\s*[:/]\s*(\d{1,3})(?!\d)', value)
        if scale_match:
            attributes['Escala'] = [f'1:{int(scale_match.group(1))}']
        elif gauge_match:
            default_scales = {'H0': '1:87', 'Z': '1:220', '1': '1:32'}
            gauge = attributes['Escala ferroviaria'][0]
            if gauge in default_scales:
                attributes['Escala'] = [default_scales[gauge]]
        return attributes

    @classmethod
    def _detail_attributes(cls, tree, lines, name):
        attributes = {}

        def add(key, value):
            key = cls._normalise_text(key)
            value = cls._normalise_text(value)
            if not key or not value:
                return
            attributes.setdefault(key, [])
            if value not in attributes[key]:
                attributes[key].append(value)

        gauge_value = cls._line_value(lines, ('Gauge / Design type', 'Gauge/Design type'))
        if gauge_value:
            for key, values in cls._gauge_attributes(gauge_value).items():
                for value in values:
                    add(key, value)

        era = cls._line_value(lines, ('Era',))
        if era:
            add('Época', era)
        kind = cls._line_value(lines, ('Kind', 'Type'))
        if kind:
            add('Tipo de producto ferroviario', kind)

        page_text = ' '.join(lines)
        title_text = f'{name} {page_text[:12000]}'
        if re.search(r'\bMärklin\s+my\s+world\b', title_text, re.IGNORECASE):
            add('Línea de producto', 'Märklin my world')
        if re.search(r'\bMärklin\s+Start\s*up\b', title_text, re.IGNORECASE):
            add('Línea de producto', 'Märklin Start up')

        status_values = cls._status(lines)
        for value in status_values:
            add('Estado del producto', value)

        if re.search(r'\bmfx\+\b', page_text, re.IGNORECASE):
            add('Decoder digital', 'mfx+')
        elif re.search(r'\bmfx\b', page_text, re.IGNORECASE):
            add('Decoder digital', 'mfx')
        if re.search(r'\bDCC\b', page_text):
            add('Sistema digital', 'DCC')
        if re.search(r'\b(sound functions?|sound generator|operating sounds?)\b', page_text, re.IGNORECASE):
            add('Sonido', 'Sí')

        age_patterns = (
            r'(?:children|ages?)\s+(?:ages?\s+)?(\d{1,2})\s+(?:and above|years? and above)',
            r'not for children under\s+(\d{1,2})\s+years?',
        )
        for pattern in age_patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                if pattern.startswith('not'):
                    add('Edad recomendada', f'A partir de {match.group(1)} años')
                else:
                    add('Edad recomendada', f'A partir de {match.group(1)} años')
                break

        # Datos estructurados adicionales que Märklin pueda publicar.
        for value in tree.xpath(
            '//*[@itemprop="brand"]/@content | //*[@itemprop="brand"]/text()'
        ):
            if cls._normalise_text(value):
                add('Marca', cls._normalise_text(value))
                break
        return attributes

    @classmethod
    def _section_after_heading(cls, lines, heading, stop_headings=None):
        heading_fold = cls._normalise_text(heading).casefold().strip(' :')
        stop_set = {
            cls._normalise_text(value).casefold().strip(' :')
            for value in (stop_headings or cls._SECTION_HEADINGS | cls._SECTION_STOPPERS)
        }
        starts = []
        inline_value = False
        for index, value in enumerate(lines):
            clean = cls._normalise_text(value)
            folded = clean.casefold().strip(' :')
            if folded == heading_fold:
                starts.append(index + 1)
                inline_value = False
            elif clean.casefold().startswith(heading_fold + ':'):
                starts.append(index + 1)
                inline_value = clean.split(':', 1)[1].strip()
        if not starts:
            return []
        start = starts[-1]
        result = [inline_value] if inline_value else []
        for value in lines[start:]:
            folded = value.casefold().strip(' :')
            if folded in stop_set and folded != heading_fold:
                break
            if value not in result[-2:]:
                result.append(value)
        return result

    @classmethod
    def _descriptions(cls, tree, lines, product_node, name):
        meta_description = cls._normalise_text(
            (tree.xpath('//meta[@property="og:description" or @name="description"]/@content') or [''])[0]
        )
        json_description = cls._normalise_text(product_node.get('description')) \
            if isinstance(product_node, dict) else ''

        prototype = cls._section_after_heading(lines, 'Prototype')
        model = cls._section_after_heading(lines, 'Model')
        highlights = cls._section_after_heading(lines, 'Highlights')
        product_description = cls._section_after_heading(lines, 'Product description')
        digital = cls._section_after_heading(lines, 'Digital Functions')

        def trim(values):
            cleaned = []
            for value in values:
                text = cls._normalise_text(value)
                if not text or text.casefold() == name.casefold():
                    continue
                if text.casefold() in cls._SECTION_STOPPERS:
                    break
                if text not in cleaned:
                    cleaned.append(text)
            return cleaned

        prototype = trim(prototype)
        model = trim(model)
        highlights = trim(highlights)
        product_description = trim(product_description)
        digital = trim(digital)

        short_description = json_description or meta_description
        if not short_description:
            short_description = (prototype or product_description or model or [name])[0]

        parts = []
        for title, values in (
            ('Prototipo', prototype),
            ('Descripción del modelo', model or product_description),
            ('Aspectos destacados', highlights),
            ('Funciones digitales', digital),
        ):
            if values:
                parts.append(cls._section_html(values, title=title))
        full_description = ''.join(parts) or html.escape(short_description or name)
        plain_description = '\n'.join(prototype + model + product_description) or short_description or name
        return short_description, full_description, plain_description, digital

    @classmethod
    def _download_attachments(cls, tree, canonical):
        documents = []
        seen = set()
        anchors = tree.xpath('//a[@href]')
        for anchor in anchors:
            href = cls._normalise_text(anchor.get('href'))
            if not href:
                continue
            absolute = urljoin(canonical, href)
            path = urlparse(absolute).path.casefold()
            text = cls._normalise_text(' '.join(anchor.itertext()))
            context = cls._normalise_text(' '.join(anchor.xpath(
                'ancestor::*[self::li or self::div or self::section][1]//text()'
            )))
            combined = f'{text} {context} {path}'.casefold()
            extension = path.rsplit('.', 1)[-1] if '.' in path.rsplit('/', 1)[-1] else ''
            is_file = extension in {'pdf', 'zip', 'doc', 'docx', 'xls', 'xlsx'}
            is_download = any(token in combined for token in (
                'download', 'manual', 'instruction', 'anleitung', 'spare part',
                'ersatzteil', 'exploded', 'brochure', 'catalog', 'certificate',
            ))
            if not (is_file and is_download) or absolute in seen:
                continue
            seen.add(absolute)
            documents.append({
                'url': absolute,
                'name': text or unquote(path.rsplit('/', 1)[-1]) or 'Documento',
                'document_type': cls._guess_document_type(text, absolute),
            })
        return documents

    @classmethod
    def _translated_kind(cls, value):
        text = cls._normalise_text(value)
        folded = text.casefold()
        mapping = {
            'diesel locomotives': ('Locomotoras', 'Diésel'),
            'electric locomotives': ('Locomotoras', 'Eléctricas'),
            'steam locomotives': ('Locomotoras', 'Vapor'),
            'locomotives': ('Locomotoras',),
            'passenger cars': ('Coches de viajeros',),
            'freight cars': ('Vagones de mercancías',),
            'train sets': ('Sets de trenes',),
            'starter sets': ('Sets de iniciación',),
            'track': ('Vías',),
            'tracks': ('Vías',),
            'digital control': ('Control digital',),
            'accessories': ('Accesorios',),
            'buildings': ('Edificios',),
        }
        for key, result in mapping.items():
            if key in folded:
                return list(result)
        return [text] if text else []

    @classmethod
    def _category_path(cls, attributes, name):
        segments = []
        gauge = (attributes.get('Escala ferroviaria') or [False])[0]
        if gauge:
            segments.append(f'Escala {gauge}')
        kind = (attributes.get('Tipo de producto ferroviario') or [False])[0]
        segments.extend(cls._translated_kind(kind))
        if len(segments) <= 1:
            inferred = cls._inferred_category(name, kind)
            for item in inferred:
                translated = {
                    'Trenes y Set': 'Trenes y sets',
                    'Vías y alimentación': 'Vías y alimentación',
                }.get(item, item)
                if translated not in segments:
                    segments.append(translated)
        return segments or ['Productos Märklin']

    @staticmethod
    def _article_number_from_value(value):
        """Devuelve un número de artículo inequívoco desde un valor estructurado."""
        text = str(value or '').strip()
        if not text:
            return False
        match = re.search(r'(?<!\d)(\d{3,8})(?!\d)', text)
        return match.group(1) if match else False

    @classmethod
    def _product_node_article_numbers(cls, node):
        """Identificadores publicados por un nodo JSON-LD de tipo Product."""
        if not isinstance(node, dict):
            return set()
        values = []
        for field in (
            'sku', 'mpn', 'productID', 'productId', 'url', '@id',
        ):
            value = node.get(field)
            if isinstance(value, dict):
                values.extend(value.values())
            elif isinstance(value, (list, tuple, set)):
                values.extend(value)
            else:
                values.append(value)
        for prop in node.get('additionalProperty') or []:
            if not isinstance(prop, dict):
                continue
            name = cls._normalise_text(prop.get('name')).casefold()
            if any(token in name for token in ('article', 'artikel', 'sku', 'item')):
                values.append(prop.get('value'))
        return {
            article
            for article in (cls._article_number_from_value(value) for value in values)
            if article
        }

    @classmethod
    def _product_json_node_for_article(cls, payloads, article_no):
        """Selecciona el Product JSON-LD de la ficha, no uno recomendado.

        Märklin puede publicar varios nodos ``Product`` en la misma respuesta.
        El primero no tiene por qué ser el artículo principal, por lo que se
        prioriza el nodo cuyo SKU/MPN/URL coincide con la referencia solicitada.
        Si hay varios nodos y ninguno identifica el artículo, se evita elegir
        uno arbitrariamente y se continúa con el H1/metadatos de la ficha.
        """
        product_nodes = []
        for payload in payloads:
            for node in cls._walk_dicts(payload):
                raw_type = node.get('@type') if isinstance(node, dict) else False
                types = raw_type if isinstance(raw_type, list) else [raw_type]
                if any(str(item or '').casefold() == 'product' for item in types):
                    product_nodes.append(node)
                    if article_no in cls._product_node_article_numbers(node):
                        return node
        return product_nodes[0] if len(product_nodes) == 1 else {}

    @classmethod
    def _page_article_number(cls, tree, lines, product_node, requested_article):
        """Obtiene la referencia principal sin leer productos relacionados."""
        structured = cls._product_node_article_numbers(product_node)
        if requested_article in structured:
            return requested_article
        if len(structured) == 1:
            return next(iter(structured))

        candidates = tree.xpath(
            '//main//*[@itemprop="sku"]/@content | '
            '//main//*[@itemprop="sku"]/text() | '
            '//main//*[@data-article-number]/@data-article-number | '
            '//main//*[@data-product-number]/@data-product-number | '
            '//main//*[@data-product-code]/@data-product-code | '
            '//meta[@property="product:retailer_item_id" or '
            '@name="product:retailer_item_id"]/@content'
        )
        parsed = [cls._article_number_from_value(value) for value in candidates]
        if requested_article in parsed:
            return requested_article
        parsed = [value for value in parsed if value]
        if len(set(parsed)) == 1:
            return parsed[0]

        # Último respaldo: solo se acepta la referencia solicitada cuando está
        # inmediatamente junto al rótulo principal. No se devuelve una referencia
        # distinta, porque podría proceder de "Recommended for you".
        labels = {'article no.', 'article no', 'artikel-nr.', 'artikel-nr'}
        for index, line in enumerate(lines):
            folded = cls._normalise_text(line).casefold().strip(' :')
            if folded not in labels and not any(folded.startswith(label + ':') for label in labels):
                continue
            window = ' '.join(lines[index:index + 4])
            if re.search(rf'(?<!\d){re.escape(requested_article)}(?!\d)', window):
                return requested_article
        return False

    @staticmethod
    def _article_from_response_url(value):
        """Extrae la referencia de una URL final, incluso desde marklin.com."""
        path = urlsplit(str(value or '')).path
        match = re.search(
            r'/(?:en/)?products/details/article/(?P<code>\d+)(?:/|$)',
            path,
            re.IGNORECASE,
        )
        return match.group('code') if match else False

    def _identity_fallback_urls(self, requested_article):
        """Alternativas oficiales usadas solo si la respuesta no es del artículo."""
        if self._HOST == 'www.maerklin.de':
            return [
                f'https://www.marklin.com/products/details/article/{requested_article}',
            ]
        return []

    def _response_product_context(self, response, requested_article):
        tree = lxml_html.fromstring(getattr(response, 'text', None) or response.content)
        lines = self._visible_lines(tree)
        payloads = self._json_payloads(tree)
        product_node = self._product_json_node_for_article(payloads, requested_article)
        page_article = self._page_article_number(
            tree, lines, product_node, requested_article,
        )
        return {
            'response': response,
            'tree': tree,
            'lines': lines,
            'product_node': product_node,
            'page_article': page_article,
            'response_article': self._article_from_response_url(response.url),
        }

    @staticmethod
    def _context_matches_article(context, requested_article):
        page_article = context.get('page_article')
        response_article = context.get('response_article')
        if page_article and page_article != requested_article:
            return False
        if response_article and response_article != requested_article:
            return page_article == requested_article
        return True

    def fetch_preview(self, source, url):
        requested = self._canonical_url(url)
        if not self._product_match(requested):
            raise ValueError('La URL no corresponde a una ficha de producto Märklin.')

        requested_article = self._product_key(requested)
        session = self._get_session(source)
        candidate_urls = [requested] + self._identity_fallback_urls(requested_article)
        errors = []
        context = False

        for candidate_url in candidate_urls:
            try:
                candidate_response = self._http_get(session, candidate_url, source)
                candidate_context = self._response_product_context(
                    candidate_response, requested_article,
                )
            except Exception as exc:
                errors.append(
                    f'{candidate_url} -> {type(exc).__name__}: {exc}'
                )
                continue

            if self._context_matches_article(candidate_context, requested_article):
                context = candidate_context
                if candidate_url != requested:
                    _logger.warning(
                        'Märklin: la ficha %s se ha recuperado desde la alternativa '
                        'oficial %s.', requested_article, candidate_url,
                    )
                break

            response_article = candidate_context.get('response_article') or '?'
            page_article = candidate_context.get('page_article') or '?'
            errors.append(
                f'{candidate_url} -> URL final artículo {response_article}; '
                f'contenido artículo {page_article}'
            )

        if not context:
            raise ValueError(
                f'Märklin no devolvió la ficha correcta para el artículo '
                f'{requested_article}. Intentos: {" | ".join(errors)}'
            )

        response = context['response']
        tree = context['tree']
        lines = context['lines']
        product_node = context['product_node']
        page_article = context['page_article']
        response_article = context['response_article']

        if response_article and response_article != requested_article:
            _logger.warning(
                'Märklin: response.url apunta a %s, pero el contenido identifica '
                'correctamente el artículo solicitado %s; se conserva la URL original.',
                response_article, requested_article,
            )

        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        for canonical_value in canonical_values:
            canonical_candidate = self._canonical_url(canonical_value)
            canonical_article = self._product_key(canonical_candidate)
            if canonical_article and canonical_article != requested_article:
                _logger.warning(
                    'Märklin: se ignora canonical del artículo %s al procesar %s.',
                    canonical_article, requested_article,
                )
                break

        # La URL canónica funcional del importador es la solicitada y validada.
        canonical = requested
        page_base_url = response.url or requested

        name = self._normalise_text(product_node.get('name')) if isinstance(product_node, dict) else ''
        if not name:
            name = self._normalise_text(' '.join(tree.xpath('//h1[1]//text()')))
        if not name:
            name = self._normalise_text(
                (tree.xpath('//meta[@property="og:title"]/@content') or [''])[0]
            )
        if not name:
            raise ValueError('La ficha de Märklin no publica un nombre reconocible.')

        article_no = requested_article

        price, currency, price_available = self._maerklin_price(
            tree, lines, product_node, name,
        )
        short_description, full_description, description, digital_lines = self._descriptions(
            tree, lines, product_node, name,
        )
        attributes = self._detail_attributes(tree, lines, name)
        if digital_lines:
            clean_functions = []
            for value in digital_lines:
                candidate = self._normalise_text(value)
                if candidate and len(candidate) <= 120 and candidate not in clean_functions:
                    clean_functions.append(candidate)
            if clean_functions:
                attributes['Funciones digitales'] = clean_functions[:40]

        category_segments = self._category_path(attributes, name)
        images = self._images_from_product(tree, product_node, page_base_url, name, article_no)
        ean_variants = self._ean_variants_from_html_content(response.content)

        return {
            'name': name,
            'description': description,
            'short_description': short_description or description,
            'full_description': full_description,
            'price': price,
            'price_available': price_available,
            'currency': currency or 'EUR',
            'category_path': '/'.join(category_segments),
            'style_code': article_no,
            'color_code': False,
            'attributes': attributes,
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'attachments': self._download_attachments(tree, page_base_url),
            'canonical_url': canonical,
            'ean_variants': ean_variants,
            # La capa común seguirá inspeccionando JSON y atributos HTML para
            # GTIN que Märklin pueda publicar en determinadas referencias.
            'ean_complete': False,
        }
