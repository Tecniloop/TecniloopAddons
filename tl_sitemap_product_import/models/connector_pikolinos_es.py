import gzip
import html
import json
import logging
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorPikolinosEs(models.AbstractModel):
    """Conector del catálogo español de Pikolinos.

    El índice público es ``https://www.pikolinos.com/sitemap_index.xml``.
    Pikolinos usa Salesforce Commerce Cloud y publica fichas españolas como::

        /es-es/palma-w4n-0650c2.html
        /es-es/formentera-pkw8q-0894c1.html

    La referencia final (``W4N-0650C2`` o ``PKW8Q-0894C1``) identifica el
    artículo. El color seleccionado se transmite normalmente mediante un
    parámetro ``dwvar_<pid>_color``. Si el sitemap no enumera los colores, se
    importa el color predeterminado de la ficha como producto simple.

    Para evitar interpretar importes del pie de página, el conector consulta
    primero el endpoint JSON público de vista rápida::

        /es-es/product/quickview?pid=<pid>

    El HTML y JSON-LD quedan como respaldo por si cambia ese endpoint.
    """

    _name = 'sitemap.connector.pikolinos_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Pikolinos España'

    _HOSTS = {'www.pikolinos.com', 'pikolinos.com'}
    _LOCALE = 'es-es'
    _PRODUCT_PATH_RE = re.compile(
        r'^/es-es/(?P<pid>(?P<slug>.+)-(?P<reference>[a-z0-9]{2,8}-[a-z0-9]{3,12}))\.html/?$',
        re.IGNORECASE,
    )
    _IMAGE_EXT_RE = re.compile(r'\.(?:avif|gif|jpe?g|png|webp)(?:$|\?)', re.IGNORECASE)
    _NON_PRODUCT_IMAGE_RE = re.compile(
        r'(?:logo|icon|flag|sprite|favicon|payment|social|newsletter|placeholder|spinner|ribbon)',
        re.IGNORECASE,
    )

    # ------------------------------------------------------------------
    # HTTP y normalización
    # ------------------------------------------------------------------
    def _get_session(self, source):
        session = super()._get_session(source)
        session.headers.update({
            'Accept': (
                'text/html,application/xhtml+xml,application/xml,application/json;q=0.9,'
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

    @staticmethod
    def _without_fragment(value):
        parts = urlsplit(value)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))

    @classmethod
    def _canonical_product_url(cls, value):
        parts = urlsplit(html.unescape(value))
        host = parts.netloc.lower()
        if host == 'pikolinos.com':
            host = 'www.pikolinos.com'
        path = re.sub(r'/+', '/', parts.path)
        path = re.sub(r'^/es-es/', '/es-es/', path, flags=re.IGNORECASE)

        # Se conservan únicamente los parámetros de color; campañas y tracking
        # no deben crear filas distintas en staging.
        color_params = [
            (key, val)
            for key, val in parse_qsl(parts.query, keep_blank_values=False)
            if key.lower().endswith('_color') and val
        ]
        query = urlencode(color_params)
        return urlunsplit((parts.scheme or 'https', host, path, query, ''))

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
    def _product_pid(cls, value):
        match = cls._product_match(value)
        return match.group('pid').lower() if match else False

    @classmethod
    def _query_color(cls, value):
        for key, val in parse_qsl(urlsplit(value).query, keep_blank_values=False):
            if key.lower().endswith('_color') and val:
                return val.strip()
        return False

    @classmethod
    def _product_key(cls, value):
        reference = cls._product_reference(value)
        if not reference:
            return False
        color = cls._query_color(value)
        return f'{reference}|{color.upper()}' if color else reference

    @classmethod
    def _entry_priority(cls, value):
        parsed = urlparse(value)
        return (
            0 if parsed.netloc.lower() == 'www.pikolinos.com' else 1,
            0 if cls._query_color(value) else 1,
            len(value),
            value,
        )

    # ------------------------------------------------------------------
    # Sitemap
    # ------------------------------------------------------------------
    def _iter_sitemap_entries(self, source, sitemap_url, depth=0, visited=None):
        if depth > 8:
            raise ValueError('El sitemap de Pikolinos supera ocho niveles de índices.')
        visited = visited or set()
        sitemap_url = self._without_fragment(sitemap_url)
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
                'Pikolinos no devolvió XML válido en '
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
            # Los índices actuales distinguen mapas "product" e "image". Se
            # recorren ambos porque los segundos completan la galería.
            useful = [
                value for value in child_urls
                if any(token in value.lower() for token in ('product', 'image'))
            ]
            if useful:
                child_urls = useful
            for child_url in child_urls:
                yield from self._iter_sitemap_entries(
                    source,
                    urljoin(sitemap_url, child_url),
                    depth=depth + 1,
                    visited=visited,
                )
            return

        if root_name != 'urlset':
            raise ValueError('El sitemap de Pikolinos no contiene <urlset> ni <sitemapindex>.')

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
        for entry, raw_images in self._iter_sitemap_entries(
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
                if current['lastmod'] and (
                    not candidate['lastmod'] or current['lastmod'] > candidate['lastmod']
                ):
                    candidate['lastmod'] = current['lastmod']
                best_entries[key] = candidate
            elif (
                candidate['lastmod']
                and (not current['lastmod'] or candidate['lastmod'] > current['lastmod'])
            ):
                current['lastmod'] = candidate['lastmod']

            target_images = image_urls_by_key.setdefault(key, [])
            for image_url in raw_images:
                absolute_url = urljoin(product_url, html.unescape(image_url))
                if self._is_product_image(absolute_url, self._product_reference(product_url)):
                    if absolute_url not in target_images:
                        target_images.append(absolute_url)

        if not best_entries:
            raise ValueError(
                'El sitemap de Pikolinos no contiene fichas españolas con el patrón '
                'esperado /es-es/<modelo>-<referencia>.html.'
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
            haystack = f"{entry['url']} {key}".lower()
            if filter_text and filter_text not in haystack:
                continue
            result.append(entry)
            if limit and len(result) >= limit:
                break
        return result

    def get_image_map(self, source):
        best_entries, images_by_key = self._collect_sitemap_products(source)
        result = {}
        for key, entry in best_entries.items():
            images = images_by_key.get(key) or []
            if images:
                result[entry['url']] = images
        return result

    def parse_category_path(self, url):
        # La URL de Pikolinos es plana. La categoría real se obtiene de las
        # migas de pan de la ficha durante fetch_preview.
        return []

    # ------------------------------------------------------------------
    # JSON/HTML de ficha
    # ------------------------------------------------------------------
    @staticmethod
    def _meta(tree, name):
        values = tree.xpath(
            f'//meta[@property={json.dumps(name)} or @name={json.dumps(name)}]/@content'
        )
        return values[0].strip() if values and values[0].strip() else False

    @staticmethod
    def _iter_json_nodes(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from SitemapConnectorPikolinosEs._iter_json_nodes(child)
        elif isinstance(value, list):
            for child in value:
                yield from SitemapConnectorPikolinosEs._iter_json_nodes(child)

    def _json_ld_product(self, tree):
        for raw_value in tree.xpath('//script[@type="application/ld+json"]/text()'):
            try:
                payload = json.loads(raw_value)
            except (TypeError, ValueError):
                continue
            for node in self._iter_json_nodes(payload):
                node_type = node.get('@type')
                types = node_type if isinstance(node_type, list) else [node_type]
                if any(str(value).lower() == 'product' for value in types if value):
                    return node
        return {}

    @staticmethod
    def _number(value):
        if isinstance(value, (int, float)):
            return float(value)
        if not value:
            return None
        text = str(value).strip().replace('\xa0', '').replace('€', '')
        text = re.sub(r'[^0-9,.-]', '', text)
        if not text:
            return None
        if ',' in text and '.' in text:
            if text.rfind(',') > text.rfind('.'):
                text = text.replace('.', '').replace(',', '.')
            else:
                text = text.replace(',', '')
        elif ',' in text:
            text = text.replace('.', '').replace(',', '.')
        try:
            return float(text)
        except ValueError:
            return None

    @classmethod
    def _extract_price_from_quickview(cls, product):
        price = product.get('price') if isinstance(product, dict) else {}
        if not isinstance(price, dict):
            return None, None
        sales = price.get('sales') or {}
        if not isinstance(sales, dict):
            sales = {}
        value = cls._number(sales.get('value') or sales.get('decimalPrice') or sales.get('formatted'))
        currency = sales.get('currency') or price.get('currency') or 'EUR'
        return value, currency

    @classmethod
    def _extract_price_from_page(cls, tree, product_node):
        offers = product_node.get('offers') if isinstance(product_node, dict) else {}
        if isinstance(offers, list):
            offers = next((item for item in offers if isinstance(item, dict)), {})
        if isinstance(offers, dict):
            value = cls._number(offers.get('price') or offers.get('lowPrice'))
            if value is not None:
                return value, offers.get('priceCurrency') or 'EUR'

        selectors = (
            '//div[contains(concat(" ", normalize-space(@class), " "), " price ")]'
            '//*[contains(concat(" ", normalize-space(@class), " "), " sales ")]'
            '//*[contains(concat(" ", normalize-space(@class), " "), " value ")]/@content',
            '//*[@itemprop="price"]/@content',
            '//meta[@property="product:price:amount" or @property="og:price:amount"]/@content',
        )
        for selector in selectors:
            for raw_value in tree.xpath(selector):
                value = cls._number(raw_value)
                if value is not None:
                    return value, 'EUR'

        # Último respaldo, pero limitado al bloque de precio para no confundir
        # los 50 € del envío gratuito ni promociones del pie de página.
        price_blocks = tree.xpath(
            '//div[contains(concat(" ", normalize-space(@class), " "), " price ")]'
        )
        for block in price_blocks:
            values = re.findall(r'(\d{1,4}(?:[.,]\d{2})?)\s*€', block.text_content())
            if values:
                value = cls._number(values[-1])
                if value is not None:
                    return value, 'EUR'
        return None, 'EUR'

    @staticmethod
    def _extract_color_from_quickview(product):
        if not isinstance(product, dict):
            return False

        direct = product.get('selectedColor') or product.get('color') or product.get('colorName')
        if isinstance(direct, dict):
            direct = direct.get('displayValue') or direct.get('name') or direct.get('value')
        if direct:
            return str(direct).strip()

        attributes = product.get('variationAttributes') or product.get('variationAttrs') or []
        if isinstance(attributes, dict):
            attributes = list(attributes.values())
        for attribute in attributes if isinstance(attributes, list) else []:
            if not isinstance(attribute, dict):
                continue
            attr_id = str(attribute.get('id') or attribute.get('attributeId') or '').lower()
            if 'color' not in attr_id and 'colour' not in attr_id:
                continue
            selected = attribute.get('selectedValue') or attribute.get('selected')
            if isinstance(selected, dict):
                value = selected.get('displayValue') or selected.get('name') or selected.get('value')
                if value:
                    return str(value).strip()
            values = attribute.get('values') or []
            for option in values if isinstance(values, list) else []:
                if isinstance(option, dict) and option.get('selected'):
                    value = option.get('displayValue') or option.get('name') or option.get('value')
                    if value:
                        return str(value).strip()
        return False

    @staticmethod
    def _extract_page_color(tree):
        text = ' '.join(tree.text_content().split())
        match = re.search(r'\bColor:\s*(.+?)\s+Ref:\s*[A-Z0-9-]+', text, re.IGNORECASE)
        return match.group(1).strip() if match else False

    @classmethod
    def _image_identity(cls, value):
        path = urlsplit(value).path
        filename = path.rsplit('/', 1)[-1].lower()
        filename = re.sub(r'_(?:full|small|mini)(?=\.[a-z0-9]+$)', '', filename)
        return filename

    @classmethod
    def _is_product_image(cls, value, reference):
        if not value or not cls._IMAGE_EXT_RE.search(value):
            return False
        if cls._NON_PRODUCT_IMAGE_RE.search(value):
            return False
        if not reference:
            return True
        normalized_url = re.sub(r'[^a-z0-9]', '', value.lower())
        normalized_ref = re.sub(r'[^a-z0-9]', '', reference.lower())
        return normalized_ref in normalized_url

    @classmethod
    def _extract_quickview_images(cls, product, reference):
        images = product.get('images') if isinstance(product, dict) else {}
        if not isinstance(images, dict):
            return []
        result = []
        identities = set()
        for group_name in ('hiRes', 'large', 'medium', 'small'):
            group = images.get(group_name) or []
            if isinstance(group, dict):
                group = list(group.values())
            for item in group if isinstance(group, list) else []:
                if isinstance(item, dict):
                    value = item.get('absURL') or item.get('url') or item.get('src')
                else:
                    value = item
                if value and value.startswith('/'):
                    value = urljoin('https://www.pikolinos.com', value)
                if not cls._is_product_image(value, reference):
                    continue
                identity = cls._image_identity(value)
                if identity in identities:
                    continue
                identities.add(identity)
                result.append(value)
        return result

    @classmethod
    def _extract_page_images(cls, tree, base_url, reference):
        raw_values = []
        raw_values.extend(tree.xpath('//meta[@property="og:image"]/@content'))
        raw_values.extend(tree.xpath('//img/@src | //img/@data-src | //img/@data-lazy'))
        for srcset in tree.xpath('//img/@srcset | //source/@srcset'):
            raw_values.extend(
                part.strip().split()[0]
                for part in srcset.split(',')
                if part.strip()
            )

        result = []
        identities = set()
        for raw_value in raw_values:
            value = urljoin(base_url, html.unescape(raw_value.strip()))
            if not cls._is_product_image(value, reference):
                continue
            identity = cls._image_identity(value)
            if identity in identities:
                continue
            identities.add(identity)
            result.append(value)
        return result

    @staticmethod
    def _extract_breadcrumb(tree):
        candidates = (
            tree.xpath(
                '//*[@itemtype and contains(@itemtype, "BreadcrumbList")]'
                '//*[@itemprop="name"]/text()'
            )
            or tree.xpath(
                '//nav[contains(translate(@aria-label, "BREADCRUMB", "breadcrumb"), "breadcrumb")]'
                '//a//text()'
            )
            or tree.xpath(
                '//*[contains(concat(" ", normalize-space(@class), " "), " breadcrumb ")]'
                '//a//text()'
            )
        )
        ignored = {
            'inicio', 'home', 'tipo de calzado', 'ver todo', 'rebajas',
        }
        result = []
        for candidate in candidates:
            value = ' '.join(str(candidate).split()).strip()
            if not value or value.lower() in ignored:
                continue
            title = value.title()
            if title not in result:
                result.append(title)
        return result

    @staticmethod
    def _category_fallback(product, subtitle):
        gender = str(product.get('gender') or '').upper() if isinstance(product, dict) else ''
        root = {
            'WOM': 'Mujer',
            'WOMEN': 'Mujer',
            'MEN': 'Hombre',
            'MAN': 'Hombre',
            'KID': 'Niños',
            'KIDS': 'Niños',
        }.get(gender)

        text = (subtitle or '').lower()
        families = (
            ('sandalia', 'Sandalias'),
            ('deportivo', 'Deportivos'),
            ('mocas', 'Mocasines'),
            ('botín', 'Botines'),
            ('botin', 'Botines'),
            ('bota', 'Botas'),
            ('bailarina', 'Bailarinas'),
            ('zapato', 'Zapatos'),
            ('bolso', 'Bolsos'),
            ('mochila', 'Mochilas'),
            ('cintur', 'Cinturones'),
            ('cartera', 'Carteras'),
        )
        family = next((name for token, name in families if token in text), False)
        return [value for value in (root, family) if value]

    def _fetch_quickview(self, source, product_url, pid):
        parsed = urlparse(product_url)
        params = [('pid', pid)]
        selected_color = self._query_color(product_url)
        if selected_color:
            params.insert(0, (f'dwvar_{pid}_color', selected_color))
        quickview_url = urlunsplit((
            parsed.scheme or 'https',
            parsed.netloc or 'www.pikolinos.com',
            f'/{self._LOCALE}/product/quickview',
            urlencode(params),
            '',
        ))
        session = self._get_session(source)
        response = self._http_get(session, quickview_url, source)
        try:
            payload = response.json()
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError('La vista rápida de Pikolinos no devolvió JSON válido.') from exc
        product = payload.get('product') if isinstance(payload, dict) else False
        if not isinstance(product, dict):
            raise ValueError('La vista rápida de Pikolinos no contiene el objeto product.')
        return product


    @classmethod
    def _variation_endpoint_urls(cls, payload, base_url):
        urls = []

        def walk(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if isinstance(child, str):
                        lowered_key = str(key).casefold()
                        lowered_value = child.casefold()
                        if (
                            'url' in lowered_key
                            and ('variation' in lowered_value or 'dwvar_' in lowered_value)
                        ):
                            absolute = urljoin(base_url, html.unescape(child))
                            if absolute not in urls:
                                urls.append(absolute)
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(payload)
        return urls

    def _fetch_site_ean_variants(self, source, product_url, preview_data):
        """Recupera los EAN de talla desde los endpoints de variación de Pikolinos."""
        product_url = self._canonical_product_url(product_url)
        match = self._product_match(product_url)
        if not match:
            return super()._fetch_site_ean_variants(source, product_url, preview_data)

        pid = match.group('pid').lower()
        variants = []
        quickview = {}
        try:
            quickview = self._fetch_quickview(source, product_url, pid)
            variants.extend(self._ean_variants_from_payload(quickview))
        except Exception as exc:
            _logger.info('Pikolinos: no se pudo leer quickview para EAN: %s', exc)

        limit = max(int(source.max_ean_requests_per_product or 0), 0)
        urls = self._variation_endpoint_urls(quickview, product_url)[:limit]
        session = self._get_session(source)
        for endpoint in urls:
            try:
                response = self._http_get(session, endpoint, source)
                try:
                    payload = response.json()
                except (TypeError, ValueError, json.JSONDecodeError):
                    payload = None
                if payload is not None:
                    variants.extend(self._ean_variants_from_payload(payload))
                else:
                    variants.extend(self._ean_variants_from_html_content(response.content))
            except Exception as exc:
                _logger.debug('Pikolinos: endpoint de variante sin EAN %s: %s', endpoint, exc)

        if not variants:
            variants.extend(super()._fetch_site_ean_variants(source, product_url, preview_data))
        return self._normalise_ean_variants(variants)

    def fetch_preview(self, source, url):
        product_url = self._canonical_product_url(url)
        match = self._product_match(product_url)
        if not match:
            raise ValueError(f'La URL no es una ficha española válida de Pikolinos: {url}')

        reference = match.group('reference').upper()
        pid = match.group('pid').lower()
        session = self._get_session(source)
        response = self._http_get(session, product_url, source)
        tree = lxml_html.fromstring(response.content)

        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical_url = self._canonical_product_url(
            urljoin(product_url, canonical_values[0].strip())
            if canonical_values else product_url
        )
        canonical_reference = self._product_reference(canonical_url)
        if canonical_reference and canonical_reference != reference:
            raise ValueError(
                'La ficha redirige a otra referencia: '
                f'se pidió {reference} y la canónica contiene {canonical_reference}.'
            )

        product_node = self._json_ld_product(tree)
        quickview_product = {}
        try:
            quickview_product = self._fetch_quickview(source, product_url, pid)
        except Exception as exc:
            _logger.warning(
                'Pikolinos: no se pudo usar quickview para %s; se usa HTML/JSON-LD: %s',
                product_url,
                exc,
            )

        model_name = str(
            quickview_product.get('tituloCommerce')
            or product_node.get('model')
            or ''
        ).strip()
        subtitle = str(
            quickview_product.get('subtituloCommerce')
            or product_node.get('description')
            or ''
        ).strip()

        page_h1 = [
            ' '.join(value.split()).strip()
            for value in tree.xpath('//h1//text()')
            if value and value.strip()
        ]
        og_title = self._meta(tree, 'og:title')
        if model_name and subtitle:
            name = f'{model_name} - {subtitle}'
        elif model_name:
            name = model_name
        elif page_h1:
            name = ' - '.join(dict.fromkeys(page_h1))
        elif og_title:
            name = og_title.split('|')[0].strip()
        else:
            name = reference

        description = str(
            quickview_product.get('longDescription')
            or quickview_product.get('shortDescription')
            or quickview_product.get('description')
            or product_node.get('description')
            or self._meta(tree, 'og:description')
            or self._meta(tree, 'description')
            or ''
        ).strip()

        price, currency = self._extract_price_from_quickview(quickview_product)
        if price is None:
            price, currency = self._extract_price_from_page(tree, product_node)
        price_available = price is not None
        price = price if price is not None else 0.0

        color = (
            self._extract_color_from_quickview(quickview_product)
            or self._extract_page_color(tree)
            or self._query_color(product_url)
            or False
        )

        category_path = self._extract_breadcrumb(tree)
        if not category_path:
            category_path = self._category_fallback(quickview_product, subtitle or name)

        image_urls = self._extract_quickview_images(quickview_product, reference)
        for image_url in self._extract_page_images(tree, product_url, reference):
            if image_url not in image_urls:
                image_urls.append(image_url)

        return {
            'name': name or reference,
            'description': description,
            'price': price,
            'price_available': price_available,
            'currency': currency or 'EUR',
            'main_image_url': image_urls[0] if image_urls else False,
            'image_urls': image_urls,
            'canonical_url': canonical_url,
            'style_code': reference,
            'color_code': color,
            'ean_variants': self._ean_variants_from_payload(quickview_product),
            'category_path': '/'.join(category_path),
        }
