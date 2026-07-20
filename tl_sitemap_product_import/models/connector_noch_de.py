import html
import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html
from odoo import models


class SitemapConnectorNochDeBase(models.AbstractModel):
    """Conector del catálogo público de NOCH y sus marcas distribuidas."""

    _name = 'sitemap.connector.noch_de_base'
    _inherit = 'sitemap.import.service'
    _description = 'Base común de conectores NOCH Alemania'

    _BRAND_FILTER = False
    _HOST = 'noch.de'
    _PRODUCT_RE = re.compile(r'^/[^/]+/(\d{5,8})/?$', re.I)
    _SKU_RE = re.compile(r'(?<!\d)(\d{5,8})(?!\d)')
    _GTIN_RE = re.compile(r'\b(?:GTIN(?:/EAN)?|EAN|Barcode)\s*:?\s*(\d{8}|\d{12}|\d{13}|\d{14})\b', re.I)
    _PRICE_RE = re.compile(r'(?:(\d{1,5}(?:[.,]\d{2}))\s*(?:€|EUR)|(?:€|EUR)\s*(\d{1,5}(?:[.,]\d{2})))', re.I)
    _EXCLUDED = (
        '/produkte/', '/service/', '/downloads/', '/blog/', '/sale/', '/neuheiten/',
        '/das-ist-noch/', '/unternehmen/', '/kontakt/', '/search/', '/media/',
    )

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
        return urlunsplit(('https', 'www.noch.de', path.rstrip('/') or '/', '', ''))

    @classmethod
    def _is_product_url(cls, value):
        canonical = cls._canonical_url(value)
        if not canonical:
            return False
        path = urlsplit(canonical).path
        return bool(cls._PRODUCT_RE.match(path) and not path.casefold().startswith(cls._EXCLUDED))

    def _read_sitemap(self, source, url, visited=None):
        visited = visited or set()
        canonical = self._canonical_url(url)
        if not canonical or canonical in visited:
            return []
        visited.add(canonical)
        response = self._http_get(self._get_session(source), canonical, source)
        root = etree.fromstring(response.content)
        local = etree.QName(root.tag).localname
        ns = {'sm': root.nsmap.get(None) or 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        if local == 'sitemapindex':
            result = []
            for child in root.xpath('//sm:sitemap/sm:loc/text()', namespaces=ns):
                child_url = self._canonical_url(child)
                if child_url:
                    result.extend(self._read_sitemap(source, child_url, visited))
            return result
        result = []
        for node in root.xpath('//sm:url', namespaces=ns):
            loc = node.xpath('./sm:loc/text()', namespaces=ns)
            if not loc:
                continue
            lastmod = node.xpath('./sm:lastmod/text()', namespaces=ns)
            result.append({
                'url': self._canonical_url(loc[0]) or self._clean(loc[0]),
                'lastmod': self._parse_lastmod(lastmod[0]) if lastmod else False,
            })
        return result

    def get_product_entries(self, source, category_filter=None, limit=0):
        entries = self._read_sitemap(source, source.sitemap_index_url)
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
        entries = list(products.values())
        if self._BRAND_FILTER:
            filtered = []
            session = self._get_session(source)
            for item in entries:
                try:
                    response = self._http_get(session, item['url'], source)
                    tree = lxml_html.fromstring(response.content)
                    products_ld = self._json_ld_products(tree)
                    product_ld = products_ld[0] if products_ld else {}
                    if self._normalise_brand(self._brand(product_ld, tree)) == self._BRAND_FILTER:
                        filtered.append(item)
                        if limit and len(filtered) >= limit:
                            break
                except Exception:
                    continue
            entries = filtered
        elif limit:
            entries = entries[:limit]
        if not entries:
            raise ValueError('El sitemap de NOCH no contiene fichas para la marca configurada.')
        return entries

    def get_image_map(self, source):
        return {}

    @staticmethod
    def _meta(tree, name):
        values = tree.xpath(f'//meta[@property={json.dumps(name)} or @name={json.dumps(name)}]/@content')
        return values[0].strip() if values else False

    @classmethod
    def _json_ld_products(cls, tree):
        products = []
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
                    typ = item.get('@type')
                    if typ == 'Product' or (isinstance(typ, list) and 'Product' in typ):
                        products.append(item)
                    stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
        return products

    @classmethod
    def _breadcrumbs(cls, tree):
        values = []
        for raw in tree.xpath('//*[contains(@class,"breadcrumb")]//a//text() | //nav[contains(@aria-label,"readcrumb")]//a//text()'):
            value = cls._clean(raw)
            if value and value.casefold() not in {'home', 'startseite', 'produkte'} and value not in values:
                values.append(value)
        return values

    @classmethod
    def _label_values(cls, tree):
        labels = {}
        for row in tree.xpath('//table//tr | //dl/*[self::dt or self::dd] | //*[contains(@class,"product-detail") or contains(@class,"product--properties")]//*[self::li or self::div]'):
            text = cls._clean(' '.join(row.xpath('.//text()')))
            if not text:
                continue
            if row.tag == 'tr':
                cells = [cls._clean(' '.join(cell.xpath('.//text()'))) for cell in row.xpath('./th|./td')]
                if len(cells) >= 2 and cells[0] and cells[1]:
                    labels.setdefault(cells[0].rstrip(':'), cells[1])
            elif row.tag == 'dt':
                nxt = row.getnext()
                if nxt is not None and nxt.tag == 'dd':
                    labels.setdefault(text.rstrip(':'), cls._clean(' '.join(nxt.xpath('.//text()'))))
            else:
                match = re.match(r'^([^:]{2,50}):\s*(.+)$', text)
                if match:
                    labels.setdefault(match.group(1).strip(), match.group(2).strip())
        return labels

    @classmethod
    def _value(cls, labels, *names):
        folded = {cls._clean(k).casefold(): v for k, v in labels.items()}
        for name in names:
            if name.casefold() in folded:
                return cls._clean(folded[name.casefold()])
        return False

    @classmethod
    def _price(cls, tree, product, text):
        offers = product.get('offers') if product else None
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if isinstance(offers, dict):
            currency = str(offers.get('priceCurrency') or '').upper()
            raw = offers.get('price') or offers.get('lowPrice')
            try:
                price = float(str(raw).replace(',', '.'))
                if currency == 'EUR' and price >= 0:
                    return price, True
            except Exception:
                pass
        focused = cls._clean(' '.join(tree.xpath('//*[@itemprop="price"]/@content | //*[contains(@class,"price")]//text()')))
        match = cls._PRICE_RE.search(focused) or cls._PRICE_RE.search(text)
        if match:
            raw = match.group(1) or match.group(2)
            return float(raw.replace('.', '').replace(',', '.') if ',' in raw else raw), True
        return 0.0, False

    @classmethod
    def _images(cls, tree, product, page_url):
        candidates = []
        image = product.get('image') if product else None
        if isinstance(image, list):
            candidates.extend(image)
        elif isinstance(image, dict):
            candidates.append(image.get('url') or image.get('contentUrl'))
        elif image:
            candidates.append(image)
        candidates.extend(tree.xpath('//meta[@property="og:image"]/@content | //main//img/@data-src | //main//img/@data-zoom-image | //main//img/@src | //main//a[contains(@href,"media")]/@href'))
        result = []
        for raw in candidates:
            if not raw:
                continue
            url = urljoin(page_url, str(raw))
            folded = url.casefold()
            if not url.startswith('http') or any(token in folded for token in ('logo', 'icon', 'sprite', 'payment', 'avatar')):
                continue
            if url not in result:
                result.append(url)
        return result

    @classmethod
    def _brand(cls, product, tree):
        raw = product.get('brand') if product else None
        if isinstance(raw, dict):
            raw = raw.get('name')
        brand = cls._clean(raw)
        if brand:
            return brand
        manufacturer = cls._clean(' '.join(tree.xpath('//*[contains(@class,"manufacturer")]//text()')))
        return manufacturer or 'NOCH'


    @classmethod
    def _normalise_brand(cls, value):
        folded = cls._clean(value).casefold()
        aliases = (
            ('rokuhan', 'Rokuhan'), ('athearn', 'Athearn'), ('ammo', 'AMMO'),
            ('proxxon', 'PROXXON'), ('noch', 'NOCH'),
        )
        for token, brand in aliases:
            if token in folded:
                return brand
        return cls._clean(value) or 'NOCH'

    def fetch_preview(self, source, url):
        response = self._http_get(self._get_session(source), url, source)
        tree = lxml_html.fromstring(response.content)
        canonicals = tree.xpath('//link[@rel="canonical"]/@href')
        canonical = self._canonical_url(canonicals[0] if canonicals else response.url) or self._canonical_url(url)
        if not self._is_product_url(canonical):
            raise ValueError('La URL no corresponde a una ficha individual de NOCH.')

        products = self._json_ld_products(tree)
        product = products[0] if products else {}
        name = self._clean(product.get('name')) or self._clean(' '.join(tree.xpath('//h1[1]//text()'))) or self._clean(self._meta(tree, 'og:title'))
        page_text = self._clean(' '.join(tree.xpath('//main//text()')))
        labels = self._label_values(tree)

        sku = False
        for candidate in (product.get('sku'), product.get('mpn'), self._value(labels, 'Art.-Nr.', 'Artikelnummer', 'Article number'), urlsplit(canonical).path):
            match = self._SKU_RE.search(self._clean(candidate))
            if match:
                sku = match.group(1)
                break
        if not sku:
            raise ValueError('La ficha de NOCH no publica una referencia reconocible.')

        description = self._clean(product.get('description')) or self._clean(self._meta(tree, 'description'))
        detail_blocks = []
        for node in tree.xpath('//*[contains(@class,"product-detail-description") or contains(@class,"product--description") or @itemprop="description"]'):
            value = self._clean(' '.join(node.xpath('.//text()')))
            if value and value not in detail_blocks:
                detail_blocks.append(value)
        if detail_blocks:
            description = '\n\n'.join(detail_blocks[:4])

        brand = self._normalise_brand(self._brand(product, tree))
        if self._BRAND_FILTER and brand != self._BRAND_FILTER:
            raise ValueError('La ficha pertenece a %s y no a %s.' % (brand, self._BRAND_FILTER))
        attrs = {'Marca': [brand], 'Referencia fabricante': [sku]}
        gauge = self._value(labels, 'Spurweite', 'Gauge')
        if not gauge:
            match = re.search(r'\b(?:Spurweite|Gauge)\s*:\s*([^\n]{1,80})', page_text, re.I)
            gauge = self._clean(match.group(1)) if match else False
        if gauge:
            values = re.findall(r'(?<![A-Z0-9])(H0m|H0e|H0|HO|TT|N|Z|G|0|1)(?![A-Z0-9])', gauge, re.I)
            values = list(dict.fromkeys(v.upper().replace('HO', 'H0') for v in values))
            if values:
                attrs['Escala ferroviaria'] = values

        scale = self._value(labels, 'Maßstab', 'Scale')
        if not scale:
            match = re.search(r'\b(?:Maßstab|Scale)\s*:\s*([^\n]{1,160})', page_text, re.I)
            scale = self._clean(match.group(1)) if match else False
        if scale:
            scales = re.findall(r'1\s*:\s*\d+(?:[.,]\d+)?|\b(?:15|28-32)\s*mm\b', scale, re.I)
            if scales:
                attrs['Escala'] = list(dict.fromkeys(v.replace(' ', '') for v in scales))

        mapping = {
            'Breite': ('Breite', 'Width'), 'Höhe': ('Höhe', 'Height'),
            'Länge': ('Länge', 'Length'), 'Gewicht': ('Gewicht', 'Weight'),
            'Produkthinweise': ('Produkthinweise', 'Product notes'),
        }
        for target, names in mapping.items():
            value = self._value(labels, *names)
            if value:
                attrs[target] = [value]

        availability = self._clean(' '.join(tree.xpath('//*[contains(@class,"delivery") or contains(@class,"availability")]//text()')))
        if availability:
            attrs['Disponibilidad'] = [availability]
        release = re.search(r'(?:erscheint|lieferbar|Liefertermin)[^\d]*(\d{1,2}\.\s*[A-Za-zäöüÄÖÜ]+\s*\d{4}|[A-Za-zäöüÄÖÜ]+\s*\d{4})', page_text, re.I)
        if release:
            attrs['Fecha prevista'] = [self._clean(release.group(1))]

        images = self._images(tree, product, canonical)
        eans = []
        candidates = [product.get(k) for k in ('gtin8', 'gtin12', 'gtin13', 'gtin14')] if product else []
        candidates += self._GTIN_RE.findall(page_text)
        for raw in candidates:
            gtin = self._normalise_gtin(raw)
            if gtin:
                eans.append({'ean': gtin, 'sku': sku, 'label': name, 'external_variant_id': sku})

        price, price_available = self._price(tree, product, page_text)
        breadcrumbs = self._breadcrumbs(tree)
        return {
            'name': name,
            'description': description,
            'short_description': description,
            'full_description': description,
            'attributes': attrs,
            'price': price,
            'price_available': price_available,
            'currency': 'EUR',
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical,
            'style_code': sku,
            'color_code': False,
            'category_path': ' / '.join([brand] + breadcrumbs),
            'ean_variants': self._normalise_ean_variants(eans),
            'ean_complete': True,
        }


class SitemapConnectorNochNoch(models.AbstractModel):
    _name = 'sitemap.connector.noch_noch'
    _inherit = 'sitemap.connector.noch_de_base'
    _description = 'Conector NOCH desde NOCH Alemania'
    _BRAND_FILTER = 'NOCH'


class SitemapConnectorNochRokuhan(models.AbstractModel):
    _name = 'sitemap.connector.noch_rokuhan'
    _inherit = 'sitemap.connector.noch_de_base'
    _description = 'Conector Rokuhan desde NOCH Alemania'
    _BRAND_FILTER = 'Rokuhan'


class SitemapConnectorNochAthearn(models.AbstractModel):
    _name = 'sitemap.connector.noch_athearn'
    _inherit = 'sitemap.connector.noch_de_base'
    _description = 'Conector Athearn desde NOCH Alemania'
    _BRAND_FILTER = 'Athearn'


class SitemapConnectorNochAmmo(models.AbstractModel):
    _name = 'sitemap.connector.noch_ammo'
    _inherit = 'sitemap.connector.noch_de_base'
    _description = 'Conector AMMO desde NOCH Alemania'
    _BRAND_FILTER = 'AMMO'


class SitemapConnectorNochProxxon(models.AbstractModel):
    _name = 'sitemap.connector.noch_proxxon'
    _inherit = 'sitemap.connector.noch_de_base'
    _description = 'Conector PROXXON desde NOCH Alemania'
    _BRAND_FILTER = 'PROXXON'
