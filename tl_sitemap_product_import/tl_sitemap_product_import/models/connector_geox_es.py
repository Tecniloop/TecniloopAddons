import gzip
import html
import json
import logging
import re
from urllib.parse import parse_qsl, unquote_plus, urlencode, urljoin, urlparse, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorGeoxEs(models.AbstractModel):
    """Conector del catálogo español de Geox.

    El mercado español publica un índice de sitemaps en::

        https://www.geox.com/es-ES/sitemap_index.xml

    Las fichas de producto terminan en un código alfanumérico de 16
    caracteres::

        /es-ES/<slug>-W6525DT3146F1624.html
        /es-ES/<slug>-J65P7F01454C0496.html

    En los códigos observados, los primeros 11 caracteres identifican el
    artículo/material y los últimos 5 el color. El conector conserva una sola
    ficha por código completo, aunque el sitemap publique alias o URLs con
    parámetros.
    """

    _name = 'sitemap.connector.geox_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Geox España'

    _HOSTS = {'www.geox.com', 'geox.com'}
    _PRODUCT_PATH_RE = re.compile(
        r'^/es-ES/(?P<slug>.+)-(?P<reference>[A-Z0-9]{16})\.html/?$',
        re.IGNORECASE,
    )
    _IMAGE_EXT_RE = re.compile(r'\.(?:avif|gif|jpe?g|png|webp)(?:$|\?)', re.IGNORECASE)
    _NON_PRODUCT_IMAGE_RE = re.compile(
        r'(?:logo|icon|flag|sprite|favicon|payment|social|newsletter|placeholder|spinner|benefeet)',
        re.IGNORECASE,
    )

    # ------------------------------------------------------------------
    # HTTP, sitemap y descubrimiento
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
        return etree.QName(element).localname.lower()

    @staticmethod
    def _without_query_fragment(value):
        parts = urlsplit(value)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))

    @classmethod
    def _canonical_product_url(cls, value):
        parts = urlsplit(cls._without_query_fragment(value))
        host = parts.netloc.lower()
        if host == 'geox.com':
            host = 'www.geox.com'
        path = re.sub(r'/+', '/', parts.path)
        # Se conserva la capitalización oficial del mercado porque Geox usa
        # /es-ES/ en sus canónicas.
        path = re.sub(r'^/es-es/', '/es-ES/', path, flags=re.IGNORECASE)
        return urlunsplit((parts.scheme or 'https', host, path, '', ''))

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

    @classmethod
    def _slug_from_url(cls, value):
        match = cls._product_match(value)
        return match.group('slug') if match else ''

    @classmethod
    def _entry_priority(cls, value):
        parsed = urlparse(value)
        slug = cls._slug_from_url(value)
        return (
            0 if parsed.netloc.lower() == 'www.geox.com' else 1,
            -len(slug),
            len(value),
            value,
        )

    def _iter_sitemap_entries(self, source, sitemap_url, depth=0, visited=None):
        """Recorre sitemapindex/urlset anidados, también si vienen en gzip."""
        if depth > 8:
            raise ValueError('El sitemap de Geox supera ocho niveles de índices.')
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
                'Geox no devolvió XML válido en '
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
            # Si el índice identifica explícitamente mapas de producto, se
            # evitan mapas editoriales, de categorías y tiendas. Si no, se
            # recorren todos porque el filtro estricto de URL se aplica abajo.
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
            raise ValueError('El sitemap de Geox no contiene <urlset> ni <sitemapindex>.')

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
        best_entries = {}
        image_urls_by_key = {}
        for entry, image_urls in self._iter_sitemap_entries(
            source, source.sitemap_index_url
        ):
            product_url = self._canonical_product_url(entry['url'])
            key = self._product_key(product_url)
            if not key:
                continue

            candidate = {
                'url': product_url,
                'lastmod': entry.get('lastmod') or False,
            }
            current = best_entries.get(key)
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
                current['lastmod'] = candidate['lastmod']

            target_images = image_urls_by_key.setdefault(key, [])
            for image_url in image_urls:
                absolute_url = urljoin(product_url, html.unescape(image_url))
                absolute_url = self._high_resolution_image_url(absolute_url)
                if absolute_url not in target_images:
                    target_images.append(absolute_url)

        if not best_entries:
            raise ValueError(
                'El sitemap de Geox no contiene fichas españolas con el patrón '
                'esperado /es-ES/<producto>-<código de 16 caracteres>.html.'
            )
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
            haystack = f"{entry['url']} {category_path} {key}".lower()
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
    # Categoría provisional obtenida de la URL plana
    # ------------------------------------------------------------------
    @staticmethod
    def _humanize_slug(value):
        value = unquote_plus(value or '').replace('_', ' ').replace('-', ' ')
        return re.sub(r'\s+', ' ', value).strip().title()

    @classmethod
    def parse_category_path(cls, url):
        slug = cls._humanize_slug(cls._slug_from_url(url)).lower()
        if not slug:
            return []

        gender = False
        if re.search(r'\b(?:mujer|señora)\b', slug):
            gender = 'Mujer'
        elif re.search(r'\b(?:hombre|caballero)\b', slug):
            gender = 'Hombre'
        elif re.search(r'\b(?:niña|chica)\b', slug):
            gender = 'Niña'
        elif re.search(r'\b(?:niño|chico)\b', slug):
            gender = 'Niño'
        elif re.search(r'\b(?:bebé|bebe|baby)\b', slug):
            gender = 'Bebé'
        elif re.search(r'\bjunior\b', slug):
            gender = 'Junior'

        families = (
            (r'\b(?:sneaker|zapatilla|deportiva)\w*\b', ('Zapatos', 'Sneakers')),
            (r'\b(?:sandalia)\w*\b', ('Zapatos', 'Sandalias')),
            (r'\b(?:mocas[ií]n)\w*\b', ('Zapatos', 'Mocasines')),
            (r'\b(?:bota|bot[ií]n)\w*\b', ('Zapatos', 'Botas y botines')),
            (r'\b(?:bailarina)\w*\b', ('Zapatos', 'Bailarinas')),
            (r'\b(?:tac[oó]n|sal[oó]n|decollet)\w*\b', ('Zapatos', 'Zapatos de tacón')),
            (r'\b(?:slip in|slip on)\b', ('Zapatos', 'Slip on')),
            (r'\b(?:zapato|calzado)\w*\b', ('Zapatos',)),
            (r'\b(?:chaleco)\w*\b', ('Ropa', 'Chalecos')),
            (r'\b(?:plum[ií]fero)\w*\b', ('Ropa', 'Plumíferos')),
            (r'\b(?:chaqueta|cazadora|abrigo|parka|gabardina|chubasquero|cortavientos)\w*\b', ('Ropa', 'Chaquetas y abrigos')),
            (r'\b(?:jersey|c[aá]rdigan|punto)\w*\b', ('Ropa', 'Prendas de punto')),
            (r'\b(?:camiseta|polo)\w*\b', ('Ropa', 'Camisetas y polos')),
            (r'\b(?:sudadera)\w*\b', ('Ropa', 'Sudaderas')),
            (r'\b(?:bolso|mochila)\w*\b', ('Accesorios', 'Bolsos')),
            (r'\b(?:cintur[oó]n)\w*\b', ('Accesorios', 'Cinturones')),
            (r'\b(?:calcet[ií]n)\w*\b', ('Accesorios', 'Calcetines')),
            (r'\b(?:cartera)\w*\b', ('Accesorios', 'Carteras')),
        )
        family = ('Otros productos',)
        for pattern, candidate in families:
            if re.search(pattern, slug, flags=re.IGNORECASE):
                family = candidate
                break
        return ([gender] if gender else []) + list(family)

    # ------------------------------------------------------------------
    # HTML y datos estructurados
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
                result = SitemapConnectorGeoxEs._first_scalar(item)
                if result not in (None, False, ''):
                    return result
            return False
        if isinstance(value, dict):
            for key in ('url', 'contentUrl', 'value', 'name'):
                if key in value:
                    result = SitemapConnectorGeoxEs._first_scalar(value[key])
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
    def _product_text_segment(cls, main_text, reference):
        upper_text = main_text.upper()
        code_index = upper_text.find((reference or '').upper())
        if code_index < 0:
            return main_text[:2500]
        start = max(0, code_index - 900)
        end = min(len(main_text), code_index + 700)
        return main_text[start:end]

    @classmethod
    def _extract_offer(cls, product_json, tree, main_text, reference):
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

        for meta_name in ('product:price:amount', 'og:price:amount', 'twitter:data1'):
            price = cls._parse_price(cls._meta(tree, meta_name))
            if price:
                currency = (
                    cls._meta(tree, 'product:price:currency')
                    or cls._meta(tree, 'og:price:currency')
                    or 'EUR'
                )
                return price, currency

        segment = cls._product_text_segment(main_text, reference)
        before_history = re.split(
            r'cronolog[ií]a\s+de\s+precios', segment, maxsplit=1, flags=re.IGNORECASE
        )[0]
        matches = re.findall(
            r'(?:€\s*([0-9]{1,5}[,.][0-9]{2})|'
            r'([0-9]{1,5}[,.][0-9]{2})\s*(?:€|EUR))',
            before_history,
            flags=re.IGNORECASE,
        )
        prices = [cls._parse_price(left or right) for left, right in matches]
        prices = [value for value in prices if value]
        if prices:
            # En rebajas el bloque presenta precio anterior, precio de lista y
            # finalmente precio vigente. En los rangos de talla se toma el
            # primer valor, que es el mínimo publicado.
            if re.search(r'precio\s+(?:anterior|de\s+lista)', before_history, re.IGNORECASE):
                return prices[-1], 'EUR'
            return prices[0], 'EUR'
        return 0.0, 'EUR'

    @classmethod
    def _extract_breadcrumb(cls, tree, product_name=''):
        values = []
        for node in cls._json_ld_nodes(tree):
            node_type = node.get('@type') if isinstance(node, dict) else None
            if str(node_type).lower() != 'breadcrumblist':
                continue
            items = node.get('itemListElement') or []
            items = items if isinstance(items, list) else [items]
            sorted_items = sorted(
                [item for item in items if isinstance(item, dict)],
                key=lambda item: item.get('position') or 0,
            )
            for item in sorted_items:
                name = item.get('name')
                if not name and isinstance(item.get('item'), dict):
                    name = item['item'].get('name')
                name = cls._normalize_text(str(name or ''))
                if name:
                    values.append(name)
            if values:
                break

        if not values:
            xpath_candidates = (
                '//*[@aria-label and contains(translate(@aria-label, "BREADCRUMB", "breadcrumb"), "breadcrumb")]//a',
                '//*[contains(concat(" ", normalize-space(@class), " "), " breadcrumb ")]//a',
                '//*[contains(translate(@class, "BREADCRUMB", "breadcrumb"), "breadcrumb")]//a',
            )
            for xpath in xpath_candidates:
                nodes = tree.xpath(xpath)
                candidates = [cls._normalize_text(node.text_content()) for node in nodes]
                if candidates:
                    values = candidates
                    break

        ignored = {
            '', 'home', 'inicio', 'geox', 'comprar', 'catálogo', 'catalogo',
            'productos', 'products',
        }
        product_name_lower = product_name.lower()
        result = []
        for value in values:
            normalized = value.lower()
            if normalized in ignored or normalized == product_name_lower:
                continue
            value = value[:1].upper() + value[1:] if value else value
            if value not in result:
                result.append(value)
        return result

    @classmethod
    def _extract_color_name(cls, product_json, tree, main_text, reference):
        if isinstance(product_json, dict):
            for key in ('color', 'colour'):
                value = cls._first_scalar(product_json.get(key))
                value = cls._normalize_text(str(value or ''))
                if value:
                    return value

        candidates = tree.xpath(
            '//*[@itemprop="color"]/@content | //*[@itemprop="color"]//text() | '
            '//*[@data-color-name]/@data-color-name | '
            '//*[@data-selected-color]/@data-selected-color'
        )
        for candidate in candidates:
            value = cls._normalize_text(candidate)
            if value:
                return value

        segment = cls._product_text_segment(main_text, reference)
        matches = re.findall(
            r'Color\s*:\s*(.{1,80}?)(?=\s*/\s*Talla|\s+Seleccionar\s+Talla|$)',
            segment,
            flags=re.IGNORECASE,
        )
        for candidate in matches:
            value = cls._normalize_text(candidate).strip(' ,;|-')
            if value:
                return value

        title = cls._meta(tree, 'og:title') or ''
        title_match = re.search(
            r':\s*[^|]+?\s+-\s+([^|]+?)\s*\|\s*Geox', title, flags=re.IGNORECASE
        )
        return cls._normalize_text(title_match.group(1)) if title_match else ''

    @classmethod
    def _extract_description(cls, product_json, tree, main_text, reference):
        if isinstance(product_json, dict):
            description = cls._normalize_text(str(product_json.get('description') or ''))
            if description:
                return description

        segment = main_text
        match = re.search(
            r'Descripci[oó]n\s+(.*?)\s+C[oó]digo\s+del\s+producto\s*:\s*'
            + re.escape(reference),
            segment,
            flags=re.IGNORECASE,
        )
        if match:
            return cls._normalize_text(match.group(1))

        return cls._meta(tree, 'og:description') or cls._meta(tree, 'description') or ''

    @staticmethod
    def _image_identity(value):
        parts = urlsplit(value)
        path = re.sub(r'/std/\d+x\d+/', '/std/{size}/', parts.path, flags=re.IGNORECASE)
        return parts.netloc.lower(), path

    @staticmethod
    def _image_score(url, descriptor=''):
        score = 0
        descriptor_match = re.search(r'(\d+)(?:w|x)?$', (descriptor or '').strip())
        if descriptor_match:
            score = int(descriptor_match.group(1))
        size_match = re.search(r'/std/(\d+)x(\d+)/', urlsplit(url).path, re.IGNORECASE)
        if size_match:
            score = max(score, int(size_match.group(1)), int(size_match.group(2)))
        query = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
        for key in ('w', 'h', 'width', 'height', 'wid', 'hei', 'sw', 'sh'):
            try:
                score = max(score, int(query.get(key) or 0))
            except (TypeError, ValueError):
                pass
        return score

    @staticmethod
    def _high_resolution_image_url(value):
        parts = urlsplit(value)
        path = parts.path
        if 'geox-cdn.thron.com' in parts.netloc.lower():
            path = re.sub(r'/std/\d+x\d+/', '/std/1600x1600/', path, flags=re.IGNORECASE)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        return urlunsplit((parts.scheme, parts.netloc, path, urlencode(query), ''))

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
        normalized_name = re.sub(r'[^a-z0-9áéíóúñ]+', ' ', product_name.lower()).strip()
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
                if reference_upper not in absolute_url.upper():
                    continue

            upper_haystack = (absolute_url + ' ' + (label or '')).upper()
            matches_reference = bool(reference_upper and reference_upper in upper_haystack)
            normalized_label = re.sub(
                r'[^a-z0-9áéíóúñ]+', ' ', (label or '').lower()
            ).strip()
            matches_name = bool(
                normalized_name and normalized_label
                and (normalized_name in normalized_label or normalized_label in normalized_name)
            )
            is_geox_product_cdn = (
                parsed.netloc.lower() == 'geox-cdn.thron.com'
                and reference_upper in absolute_url.upper()
            )
            if not trusted and not matches_reference and not matches_name and not is_geox_product_cdn:
                continue

            absolute_url = cls._high_resolution_image_url(absolute_url)
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

    @classmethod
    def _extract_product_name(cls, tree, product_json, canonical_url):
        model_values = tree.xpath('//main//h1//text()') or tree.xpath('//h1//text()')
        model_name = cls._normalize_text(' '.join(model_values))

        type_name = ''
        if model_values:
            h1_nodes = tree.xpath('//main//h1') or tree.xpath('//h1')
            if h1_nodes:
                following_h2 = h1_nodes[0].xpath('following::h2[1]//text()')
                type_name = cls._normalize_text(' '.join(following_h2))

        if model_name and type_name and type_name.lower() not in model_name.lower():
            return f'{model_name.upper()} - {type_name}'
        if model_name:
            return model_name.upper()

        json_name = cls._normalize_text(str(product_json.get('name') or ''))
        if json_name:
            return json_name

        title = cls._meta(tree, 'og:title') or cls._meta(tree, 'twitter:title') or ''
        title_match = re.search(
            r'Geox(?:®)?\s+(.+?):\s*(.+?)\s+-\s+[^|]+\|\s*Geox',
            title,
            flags=re.IGNORECASE,
        )
        if title_match:
            return f'{cls._normalize_text(title_match.group(1)).upper()} - {cls._normalize_text(title_match.group(2))}'
        return cls._humanize_slug(cls._slug_from_url(canonical_url))

    # ------------------------------------------------------------------
    # Ficha de producto
    # ------------------------------------------------------------------
    def _parse_product_html(self, content, requested_url):
        requested_url = self._canonical_product_url(requested_url)
        requested_reference = self._product_reference(requested_url)
        if not requested_reference:
            raise ValueError('La URL solicitada no es una ficha válida de Geox España.')

        tree = self._html_document(content)
        product_json = self._product_json_ld(tree)

        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical_candidate = (
            urljoin(requested_url, canonical_values[0].strip())
            if canonical_values and canonical_values[0].strip()
            else requested_url
        )
        canonical_url = self._canonical_product_url(canonical_candidate)
        canonical_reference = self._product_reference(canonical_url)
        if not canonical_reference:
            canonical_url = requested_url
            canonical_reference = requested_reference
        if canonical_reference != requested_reference:
            raise ValueError(
                'La ficha de Geox ha redirigido a otra referencia; el producto '
                'solicitado puede estar descatalogado.'
            )

        main_nodes = tree.xpath('//main')
        main_node = main_nodes[0] if main_nodes else tree
        main_text = self._normalize_text(' '.join(main_node.itertext()))

        name = self._extract_product_name(tree, product_json, canonical_url)
        style_code = canonical_reference[:11]
        technical_color = canonical_reference[11:]
        color_name = self._extract_color_name(
            product_json, tree, main_text, canonical_reference
        )
        color_value = (
            f'{technical_color} - {color_name}'
            if color_name and color_name.lower() != technical_color.lower()
            else technical_color
        )

        price, currency = self._extract_offer(
            product_json, tree, main_text, canonical_reference
        )
        image_urls = self._extract_images(
            tree, product_json, canonical_url, canonical_reference, name
        )

        breadcrumb = self._extract_breadcrumb(tree, product_name=name)
        useful_breadcrumb = [
            value for value in breadcrumb
            if value.lower() not in {'comprar', 'catálogo', 'catalogo'}
        ]
        category_path = useful_breadcrumb or self.parse_category_path(canonical_url)

        return {
            'name': name or canonical_url,
            'description': self._extract_description(
                product_json, tree, main_text, canonical_reference
            ),
            'price': price,
            'price_available': bool(price),
            'currency': currency or 'EUR',
            'main_image_url': image_urls[0] if image_urls else False,
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
