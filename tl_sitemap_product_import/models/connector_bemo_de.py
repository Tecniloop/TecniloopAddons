import html
import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html
from odoo import models


class SitemapConnectorBemoDe(models.AbstractModel):
    """Conector del catálogo público de BEMO Modelleisenbahnen.

    El sitemap es el índice WordPress estándar. Solo se conservan las fichas
    individuales bajo ``/produkt/``; páginas de categorías, noticias, medios y
    archivos quedan fuera del descubrimiento.
    """

    _name = 'sitemap.connector.bemo_de'
    _inherit = 'sitemap.import.service'
    _description = 'Conector BEMO Modelleisenbahnen Alemania'

    _HOST = 'bemo-modellbahn.de'
    _PRODUCT_PREFIX = '/produkt/'
    _SKU_RE = re.compile(r'(?<!\d)(?P<a>\d{4})\s+(?P<b>\d{3})(?!\d)')
    _PRICE_RE = re.compile(r'\bUVP\s*:\s*(?P<price>\d{1,5}(?:[.\s]\d{3})*,\d{2})\s*Euro\b', re.I)
    _GTIN_RE = re.compile(r'\b(?:EAN|GTIN)\s*:?\s*(\d{8}|\d{12}|\d{13}|\d{14})\b', re.I)
    _SCALE_RE = re.compile(r'(?<!\w)(0m|H0m|H0e|H0|HOm|HOe|HO)(?!\w)', re.I)
    _ERA_RE = re.compile(r'(?<![A-Z0-9])(I(?:-I|I|II|V|VI)?|II(?:-III|I|V)?|III(?:-IV|I|V)?|IV(?:-V|I)?|V(?:-VI|I)?|VI)(?![A-Z0-9])', re.I)
    _RADIUS_RE = re.compile(r'R\s*>?\s*(\d{2,4})', re.I)

    @classmethod
    def _clean(cls, value):
        return re.sub(r'\s+', ' ', html.unescape(str(value or '')).replace('\xa0', ' ')).strip()

    @classmethod
    def _canonical_url(cls, value):
        parts = urlsplit(html.unescape(str(value or '')).strip())
        host = parts.netloc.casefold().removeprefix('www.')
        if host != cls._HOST:
            return False
        path = re.sub(r'/+', '/', parts.path or '/')
        return urlunsplit(('https', 'www.bemo-modellbahn.de', path.rstrip('/') or '/', '', ''))

    @classmethod
    def _is_product_url(cls, value):
        canonical = cls._canonical_url(value)
        return bool(canonical and urlsplit(canonical).path.startswith(cls._PRODUCT_PREFIX))

    def _read_wordpress_sitemap(self, source, url, visited=None):
        """Lee un sitemap WordPress, tanto índice como urlset.

        WordPress puede dividir cada tipo de contenido en varios ficheros. Se
        limita la recursión al mismo dominio y se deduplican todos los nodos.
        """
        visited = visited or set()
        canonical = self._canonical_url(url)
        if not canonical or canonical in visited:
            return []
        visited.add(canonical)
        response = self._http_get(self._get_session(source), canonical, source)
        root = etree.fromstring(response.content)
        tag = etree.QName(root.tag).localname
        namespace = {'sm': root.nsmap.get(None) or 'http://www.sitemaps.org/schemas/sitemap/0.9'}

        if tag == 'sitemapindex':
            entries = []
            for loc in root.xpath('//sm:sitemap/sm:loc/text()', namespaces=namespace):
                child = self._canonical_url(loc)
                if child:
                    entries.extend(self._read_wordpress_sitemap(source, child, visited))
            return entries

        entries = []
        for node in root.xpath('//sm:url', namespaces=namespace):
            loc = node.xpath('./sm:loc/text()', namespaces=namespace)
            if not loc:
                continue
            lastmod = node.xpath('./sm:lastmod/text()', namespaces=namespace)
            entries.append({
                'url': self._canonical_url(loc[0]) or loc[0].strip(),
                'lastmod': self._parse_lastmod(lastmod[0]) if lastmod else False,
            })
        return entries

    def get_product_entries(self, source, category_filter=None, limit=0):
        entries = self._read_wordpress_sitemap(source, source.sitemap_index_url)
        needle = self._clean(category_filter).casefold()
        products = {}
        for item in entries:
            url = self._canonical_url(item.get('url'))
            if not self._is_product_url(url):
                continue
            if needle and needle not in url.casefold():
                continue
            products.setdefault(url, {'url': url, 'lastmod': item.get('lastmod') or False})
            if limit and len(products) >= limit:
                break
        if not products:
            raise ValueError(
                'El sitemap WordPress de BEMO no contiene fichas bajo /produkt/ '
                'o la estructura pública del sitio ha cambiado.'
            )
        return list(products.values())

    def get_image_map(self, source):
        return {}

    @staticmethod
    def _meta(tree, name):
        values = tree.xpath(
            f'//meta[@property={json.dumps(name)} or @name={json.dumps(name)}]/@content'
        )
        return values[0].strip() if values else False

    @classmethod
    def _json_ld_products(cls, tree):
        result = []
        for raw in tree.xpath('//script[@type="application/ld+json"]/text()'):
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            stack = payload if isinstance(payload, list) else [payload]
            while stack:
                item = stack.pop()
                if isinstance(item, list):
                    stack.extend(item)
                elif isinstance(item, dict):
                    item_type = item.get('@type')
                    if item_type == 'Product' or (isinstance(item_type, list) and 'Product' in item_type):
                        result.append(item)
                    stack.extend(value for value in item.values() if isinstance(value, (dict, list)))
        return result

    @classmethod
    def _main_root(cls, tree):
        nodes = tree.xpath(
            '//main//*[contains(@class,"single-product")] | '
            '//main//article | //*[@itemtype="https://schema.org/Product"] | '
            '//*[@itemtype="http://schema.org/Product"] | //main'
        )
        return nodes[0] if nodes else tree

    @classmethod
    def _sku(cls, root, product):
        candidates = []
        if product:
            candidates.extend([product.get('sku'), product.get('mpn')])
        candidates.extend(root.xpath(
            './/*[@itemprop="sku"]/@content | .//*[@itemprop="sku"]//text() | '
            './/*[contains(@class,"sku")]//text()'
        ))
        candidates.append(cls._clean(' '.join(root.xpath('.//text()'))))
        for candidate in candidates:
            match = cls._SKU_RE.search(cls._clean(candidate))
            if match:
                return f'{match.group("a")} {match.group("b")}'
        return False

    @classmethod
    def _price(cls, root, product):
        offers = product.get('offers') if product else None
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if isinstance(offers, dict):
            raw = offers.get('price') or offers.get('lowPrice')
            currency = str(offers.get('priceCurrency') or '').upper()
            try:
                price = float(str(raw).replace(',', '.'))
                if price > 0 and currency in {'EUR', '€'}:
                    return price, 'EUR'
            except Exception:
                pass
        focused = cls._clean(' '.join(root.xpath(
            './/*[contains(@class,"price") or @itemprop="offers" or @itemprop="price"]//text() | '
            './/*[@itemprop="price"]/@content'
        )))
        match = cls._PRICE_RE.search(focused)
        if not match:
            match = cls._PRICE_RE.search(cls._clean(' '.join(root.xpath('.//text()'))))
        if match:
            value = match.group('price').replace('.', '').replace(' ', '').replace(',', '.')
            return float(value), 'EUR'
        return 0.0, 'EUR'

    @classmethod
    def _breadcrumbs(cls, tree):
        values = []
        for text in tree.xpath(
            '//*[contains(@class,"breadcrumb") or contains(@class,"breadcrumbs")]//a//text() | '
            '//*[contains(@class,"breadcrumb") or contains(@class,"breadcrumbs")]//*[self::span or self::li]//text()'
        ):
            value = cls._clean(text)
            if value and value.casefold() not in {'home', 'startseite', 'produkte', 'produkt'} and value not in values:
                values.append(value)
        return values

    @classmethod
    def _section_text(cls, root, headings):
        folded_headings = tuple(value.casefold() for value in headings)
        blocks = []
        for heading in root.xpath('.//*[self::h2 or self::h3 or self::h4]'):
            title = cls._clean(' '.join(heading.xpath('.//text()')))
            if not any(token in title.casefold() for token in folded_headings):
                continue
            texts = []
            for sibling in heading.itersiblings():
                if sibling.tag in {'h2', 'h3', 'h4'}:
                    break
                text = cls._clean(' '.join(sibling.xpath('.//text()')) if hasattr(sibling, 'xpath') else sibling.text)
                if text:
                    texts.append(text)
            value = cls._clean(' '.join(texts))
            if value and value not in blocks:
                blocks.append(value)
        return '\n\n'.join(blocks)

    @classmethod
    def _images(cls, tree, product, page_url, sku):
        """Extract product images, including Elementor lazy-loaded thumbnails.

        BEMO uses Elementor-generated URLs under ``wp-content/uploads/elementor/thumbs``
        and may publish them through ``srcset``, lazy-load attributes, links or inline
        background styles instead of a plain ``img[src]``.
        """
        candidates = []
        image = product.get('image') if product else None
        if isinstance(image, list):
            candidates.extend(image)
        elif isinstance(image, dict):
            candidates.append(image.get('url') or image.get('contentUrl'))
        elif image:
            candidates.append(image)

        candidates.extend(tree.xpath(
            '//meta[@property="og:image"]/@content | '
            '//meta[@name="twitter:image"]/@content | '
            '//main//a[contains(@href,"wp-content/uploads")]/@href | '
            '//main//img/@data-large-file | //main//img/@data-large_image | '
            '//main//img/@data-full | //main//img/@data-original | '
            '//main//img/@data-lazy-src | //main//img/@data-src | '
            '//main//img/@src'
        ))

        # Elementor/WordPress commonly places the useful URL in srcset.
        srcsets = tree.xpath(
            '//main//img/@srcset | //main//img/@data-srcset | '
            '//main//source/@srcset | //main//source/@data-srcset'
        )
        for srcset in srcsets:
            for item in str(srcset or '').split(','):
                url = item.strip().split()[0] if item.strip() else ''
                if url:
                    candidates.append(url)

        # Elementor may render gallery images as CSS background-image URLs.
        styles = tree.xpath('//main//*[@style]/@style')
        for style in styles:
            candidates.extend(re.findall(
                r'url\(\s*["\']?(.*?\.(?:jpe?g|png|webp|gif))(?:\?[^"\')\s]*)?["\']?\s*\)',
                str(style or ''),
                flags=re.I,
            ))

        result = []
        compact_sku = re.sub(r'\D', '', sku or '')
        for value in candidates:
            if not value:
                continue
            absolute = urljoin(page_url, html.unescape(str(value)).strip())
            folded = absolute.casefold()
            path = urlsplit(absolute).path.casefold()
            if not absolute.startswith(('http://', 'https://')):
                continue
            if not re.search(r'\.(?:jpe?g|png|webp|gif)$', path, re.I):
                continue
            if any(token in folded for token in ('logo', 'icon', 'avatar', 'header', 'lieferbar')):
                continue
            if absolute not in result:
                result.append(absolute)

        # Product-reference images first. For SKU ``1001 802``, BEMO uses
        # ``1001802-<elementor hash>.jpg``.
        matching = [
            url for url in result
            if compact_sku and compact_sku in re.sub(r'\D', '', urlsplit(url).path)
        ]
        return matching + [url for url in result if url not in matching]

    @classmethod
    def _attributes(cls, root, name, breadcrumbs, sku):
        text = cls._clean(' '.join(root.xpath('.//text()')))
        # El bloque inicial contiene los datos de la ficha; se corta antes de los
        # productos relacionados para no heredar escalas, referencias o precios.
        text = re.split(r'\bModelle für die Zugbildung\b|\bÄhnliche Produkte\b', text, maxsplit=1, flags=re.I)[0]
        context = cls._clean(' '.join(breadcrumbs + [name, text]))
        attrs = {'Marca': ['BEMO'], 'Referencia BEMO': [sku]}

        scale_match = cls._SCALE_RE.search(context)
        if scale_match:
            scale = scale_match.group(1).upper().replace('HO', 'H0')
            attrs['Escala ferroviaria'] = [scale]
            numeric = {'0M': '1:45', 'H0M': '1:87', 'H0E': '1:87', 'H0': '1:87'}.get(scale)
            if numeric:
                attrs['Escala'] = [numeric]

        # La época suele aparecer inmediatamente después de la escala.
        # Busca la combinación escala + época en el bloque de datos, no en el
        # nombre del vehículo (p. ej. Ge 4/4 II), para evitar falsos positivos.
        era_match = re.search(
            r'(?<!\w)(?:0m|H0m|H0e|H0|HOm|HOe|HO)\s+'
            r'(I(?:-I|I|II|V|VI)?|II(?:-III|I|V)?|III(?:-IV|I|V)?|IV(?:-V|I)?|V(?:-VI|I)?|VI)(?![A-Z0-9])',
            text, re.I,
        )
        if era_match:
            attrs['Época'] = [era_match.group(1).upper()]

        radius = cls._RADIUS_RE.search(context)
        if radius:
            attrs['Radio mínimo'] = [f'{radius.group(1)} mm']

        availability = re.search(r'Lieferstatus\s*:\s*([^:]{2,100}?)(?=Liefertermin|UVP|Produktbeschreibung|$)', context, re.I)
        if availability:
            attrs['Disponibilidad'] = [cls._clean(availability.group(1))]
        delivery = re.search(r'Liefertermin\s*:\s*([^:]{2,80}?)(?=UVP|Produktbeschreibung|$)', context, re.I)
        if delivery:
            attrs['Entrega prevista'] = [cls._clean(delivery.group(1))]

        token_map = (
            ('DCC', 'Sistema digital', 'DCC'), ('digital', 'Sistema', 'Digital'),
            ('analog', 'Sistema', 'Analógico'), ('Sounddecoder', 'Sonido', 'Sí'),
            ('Loksound', 'Sonido', 'Sí'), ('Kurvensound', 'Sonido', 'Sí'),
            ('Soundvorbereitung', 'Sonido', 'Preparado'), ('Next18', 'Interfaz digital', 'Next18'),
            ('ESU', 'Decoder', 'ESU'), ('LED', 'Iluminación', 'LED'),
            ('Wechselstrom', 'Alimentación', 'AC'), ('3L', 'Alimentación', 'AC 3 carriles'),
            ('Gleichstrom', 'Alimentación', 'DC'), ('2L', 'Alimentación', 'DC 2 carriles'),
            ('Metal Collection', 'Línea de producto', 'Metal Collection'),
            ('Bausatz', 'Presentación', 'Kit'), ('Fertigmodell', 'Presentación', 'Modelo terminado'),
            ('Zahnradantrieb', 'Tracción', 'Cremallera'),
        )
        folded = context.casefold()
        for token, label, value in token_map:
            if token.casefold() in folded:
                attrs.setdefault(label, [])
                if value not in attrs[label]:
                    attrs[label].append(value)
        return attrs

    def fetch_preview(self, source, url):
        response = self._http_get(self._get_session(source), url, source)
        tree = lxml_html.fromstring(response.content)
        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical = self._canonical_url(canonical_values[0] if canonical_values else response.url)
        if not self._is_product_url(canonical):
            canonical = self._canonical_url(url)
        if not self._is_product_url(canonical):
            raise ValueError('La URL de BEMO ya no corresponde a una ficha bajo /produkt/.')

        products = self._json_ld_products(tree)
        product = products[0] if products else {}
        root = self._main_root(tree)
        name = self._clean(product.get('name')) or self._clean(' '.join(tree.xpath('//h1[1]//text()')))
        if not name:
            name = self._clean(self._meta(tree, 'og:title'))
        if not name:
            raise ValueError('La ficha BEMO no publica un nombre reconocible.')

        sku = self._sku(root, product)
        if not sku:
            raise ValueError('La ficha BEMO no publica una referencia con formato 0000 000.')

        price, currency = self._price(root, product)
        breadcrumbs = self._breadcrumbs(tree)
        description = self._section_text(root, ('Produktbeschreibung',))
        details = self._section_text(root, ('Modelldetails', 'Produktdetails'))
        if not description:
            description = self._clean(product.get('description')) if product else ''
        if not description:
            description = self._clean(self._meta(tree, 'description'))
        full_description = '\n\n'.join(value for value in (description, details) if value)
        attrs = self._attributes(root, name, breadcrumbs, sku)
        images = self._images(tree, product, canonical, sku)

        eans = []
        focused = self._clean(' '.join(root.xpath('.//text()')))
        for raw in self._GTIN_RE.findall(focused):
            gtin = self._normalise_gtin(raw)
            if gtin:
                eans.append({
                    'ean': gtin,
                    'sku': sku,
                    'label': name,
                    'external_variant_id': sku,
                })

        return {
            'name': name,
            'description': description or full_description,
            'short_description': description or full_description,
            'full_description': full_description or description,
            'attributes': attrs,
            'price': price,
            'price_available': bool(price),
            'currency': currency,
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical,
            'style_code': sku,
            'color_code': False,
            'category_path': ' / '.join(['BEMO'] + breadcrumbs),
            'ean_variants': self._normalise_ean_variants(eans),
            'ean_complete': True,
        }
