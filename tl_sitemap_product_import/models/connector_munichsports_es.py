import html
import json
import logging
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html
from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorMunichSportsEs(models.AbstractModel):
    """Conector de la tienda oficial MUNICH Sports.

    El sitemap mezcla páginas corporativas, categorías y las traducciones
    ``-ca``, ``-it`` y ``-en`` de cada ficha. Solo se conserva la URL española
    canónica cuyo último segmento termina en la referencia numérica del artículo.
    Las tallas se importan como variantes incluso cuando la web no publica GTIN.
    """

    _name = 'sitemap.connector.munichsports_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector MUNICH Sports España'

    _HOSTS = {'munichsports.com', 'www.munichsports.com'}
    _PRODUCT_RE = re.compile(r'^/(?P<slug>[^/]+)-(?P<reference>\d{5,12})/?$', re.I)
    _LANG_SUFFIX_RE = re.compile(r'-(?:ca|it|en)$', re.I)
    _PRICE_RE = re.compile(r'(?<!\d)(\d{1,5}(?:[.]\d{3})*(?:,\d{2})|\d+(?:[.]\d{2}))\s*€')
    _IMAGE_RE = re.compile(r'\.(?:avif|gif|jpe?g|png|webp)(?:$|[?#])', re.I)
    _NON_PRODUCT_IMAGE_RE = re.compile(
        r'(?:logo|icon|sprite|favicon|payment|social|newsletter|placeholder|loader|spinner|flag|cookie|clickcease)',
        re.I,
    )

    @staticmethod
    def _clean(value):
        return re.sub(r'\s+', ' ', html.unescape(str(value or '')).replace('\xa0', ' ')).strip()

    @classmethod
    def _canonical_url(cls, value):
        parts = urlsplit(html.unescape(str(value or '')).strip())
        if parts.netloc.casefold() not in cls._HOSTS:
            return False
        path = re.sub(r'/+', '/', parts.path or '/')
        # El sitemap puede publicar /es/<slug>; la ficha española canónica no lo necesita.
        path = re.sub(r'^/es/', '/', path, flags=re.I)
        return urlunsplit(('https', 'www.munichsports.com', path.rstrip('/') or '/', '', ''))

    @classmethod
    def _product_match(cls, value):
        canonical = cls._canonical_url(value)
        if not canonical:
            return False
        path = urlsplit(canonical).path
        if cls._LANG_SUFFIX_RE.search(path):
            return False
        return cls._PRODUCT_RE.match(path)

    @classmethod
    def _is_product_url(cls, value):
        return bool(cls._product_match(value))

    @classmethod
    def _reference(cls, value):
        match = cls._product_match(value)
        return match.group('reference') if match else False

    def _walk_sitemap(self, source, url, visited=None, depth=0):
        if depth > 8:
            raise ValueError('El sitemap de MUNICH Sports supera ocho niveles.')
        visited = visited or set()
        clean_url = self._canonical_url(url)
        if not clean_url or clean_url in visited:
            return []
        visited.add(clean_url)
        response = self._http_get(self._get_session(source), clean_url, source)
        content = response.content or b''
        stripped = content.lstrip()
        if not stripped.startswith(b'<'):
            preview = stripped[:160].decode('utf-8', errors='replace').replace('\n', ' ')
            message = (
                'MUNICH Sports devolvió contenido no XML para %s '
                '(HTTP %s, Content-Type %s, inicio: %r)'
                % (
                    clean_url,
                    response.status_code,
                    response.headers.get('Content-Type', ''),
                    preview,
                )
            )
            if depth:
                _logger.warning('%s. Se omite este sitemap hijo.', message)
                return []
            raise ValueError(message)
        try:
            parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
            root = etree.fromstring(content, parser=parser)
        except (etree.ParserError, etree.XMLSyntaxError) as exc:
            message = 'MUNICH Sports devolvió XML inválido para %s: %s' % (clean_url, exc)
            if depth:
                _logger.warning('%s. Se omite este sitemap hijo.', message)
                return []
            raise ValueError(message) from exc
        tag = etree.QName(root.tag).localname.casefold()
        if tag == 'sitemapindex':
            result = []
            for loc in root.xpath('./*[local-name()="sitemap"]/*[local-name()="loc"]/text()'):
                child = self._canonical_url(loc)
                if child:
                    try:
                        result.extend(self._walk_sitemap(source, child, visited, depth + 1))
                    except Exception as exc:
                        _logger.warning(
                            'MUNICH Sports: se omite el sitemap hijo %s por error: %s',
                            child,
                            exc,
                        )
            return result
        if tag != 'urlset':
            raise ValueError('MUNICH Sports no devolvió un sitemap XML válido.')
        result = []
        for node in root.xpath('./*[local-name()="url"]'):
            loc = node.xpath('./*[local-name()="loc"]/text()')
            if not loc:
                continue
            lastmod = node.xpath('./*[local-name()="lastmod"]/text()')
            result.append({
                'url': self._canonical_url(loc[0]) or loc[0].strip(),
                'lastmod': self._parse_lastmod(lastmod[0]) if lastmod else False,
            })
        return result

    def get_product_entries(self, source, category_filter=None, limit=0):
        needle = self._clean(category_filter).casefold()
        products = {}
        for entry in self._walk_sitemap(source, source.sitemap_index_url):
            url = self._canonical_url(entry.get('url'))
            reference = self._reference(url)
            if not reference:
                continue
            if needle and needle not in url.casefold() and needle not in reference.casefold():
                continue
            current = products.get(reference)
            candidate = {'url': url, 'lastmod': entry.get('lastmod') or False}
            if not current or (candidate['lastmod'] and not current['lastmod']):
                products[reference] = candidate
            if limit and len(products) >= limit:
                break
        if not products:
            raise ValueError(
                'El sitemap de MUNICH Sports no contiene fichas españolas cuyo URL termine en una referencia numérica.'
            )
        return list(products.values())

    def get_image_map(self, source):
        return {}

    @staticmethod
    def _meta(tree, key):
        values = tree.xpath(
            f'//meta[@property={json.dumps(key)} or @name={json.dumps(key)}]/@content'
        )
        return values[0].strip() if values else False

    @classmethod
    def _json_products(cls, tree):
        found = []
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
                    kind = item.get('@type')
                    if kind == 'Product' or (isinstance(kind, list) and 'Product' in kind):
                        found.append(item)
                    stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
        return found

    @classmethod
    def _breadcrumbs(cls, tree, name):
        values = []
        for text in tree.xpath(
            '//*[contains(@class,"breadcrumb") or contains(@class,"migas")]//a//text() | '
            '//*[@itemtype="https://schema.org/BreadcrumbList"]//*[@itemprop="name"]//text()'
        ):
            value = cls._clean(text)
            if not value or value.casefold() in {'inicio', 'home', name.casefold()}:
                continue
            if value not in values:
                values.append(value)
        return values

    @classmethod
    def _prices(cls, tree, product):
        offers = product.get('offers') if product else None
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        candidates = []
        if isinstance(offers, dict):
            candidates.extend([offers.get('price'), offers.get('lowPrice')])
        candidates.extend(tree.xpath(
            '//*[@itemprop="price"]/@content | '
            '//*[contains(@class,"price") or contains(@class,"precio")]//text()'
        ))
        numbers = []
        for raw in candidates:
            text = cls._clean(raw)
            for match in cls._PRICE_RE.findall(text):
                try:
                    value = float(match.replace('.', '').replace(',', '.'))
                except ValueError:
                    continue
                if value > 0 and value not in numbers:
                    numbers.append(value)
            if re.fullmatch(r'\d+(?:[.,]\d+)?', text):
                try:
                    value = float(text.replace(',', '.'))
                except ValueError:
                    value = 0
                if value > 0 and value not in numbers:
                    numbers.append(value)
        # En rebajas la web muestra primero el precio vigente y después el PVP anterior.
        return numbers[0] if numbers else 0.0

    @classmethod
    def _images(cls, tree, product, page_url):
        raw = []
        if product:
            images = product.get('image')
            raw.extend(images if isinstance(images, list) else [images] if images else [])
        for key in ('og:image', 'twitter:image'):
            value = cls._meta(tree, key)
            if value:
                raw.append(value)
        raw.extend(tree.xpath(
            '//main//img/@src | //main//img/@data-src | //main//img/@data-lazy-src | '
            '//main//img/@data-original | //main//source/@srcset | //main//img/@srcset | '
            '//*[@itemprop="image"]/@content | //*[@itemprop="image"]/@href'
        ))
        result = []
        for value in raw:
            if isinstance(value, dict):
                value = value.get('url') or value.get('contentUrl')
            for candidate in str(value or '').split(','):
                candidate = candidate.strip().split(' ')[0]
                if not candidate:
                    continue
                absolute = urljoin(page_url, html.unescape(candidate).replace('\\/', '/'))
                if not cls._IMAGE_RE.search(absolute) or cls._NON_PRODUCT_IMAGE_RE.search(absolute):
                    continue
                parts = urlsplit(absolute)
                clean = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))
                if clean not in result:
                    result.append(clean)
        return result

    @classmethod
    def _extract_description(cls, tree, product):
        blocks = []
        if product and product.get('description'):
            blocks.append(cls._clean(product.get('description')))
        for heading in tree.xpath('//h2|//h3|//button|//*[@role="tab"]'):
            title = cls._clean(' '.join(heading.xpath('.//text()'))).casefold()
            if 'descripción del producto' not in title and 'descripcion del producto' not in title:
                continue
            texts = []
            for sibling in heading.itersiblings():
                if sibling.tag in {'h2', 'h3'}:
                    break
                text = cls._clean(' '.join(sibling.xpath('.//text()')))
                if text:
                    texts.append(text)
            if texts:
                blocks.append(cls._clean(' '.join(texts)))
        if not blocks:
            meta = cls._meta(tree, 'description') or cls._meta(tree, 'og:description')
            if meta:
                blocks.append(cls._clean(meta))
        unique = []
        for value in blocks:
            if value and value not in unique:
                unique.append(value)
        return '\n\n'.join(unique)

    @classmethod
    def _sizes(cls, tree):
        values = []
        # Selectores explícitos y opciones accesibles.
        selectors = tree.xpath(
            '//select[contains(translate(@name,"TALLA","talla"),"talla") or '
            'contains(translate(@id,"TALLA","talla"),"talla")]/option | '
            '//*[@data-size or @data-talla or @data-value][ancestor::*['
            'contains(translate(@class,"TALLA","talla"),"talla") or '
            'contains(translate(@class,"SIZE","size"),"size")]]'
        )
        for node in selectors:
            raw = node.get('data-size') or node.get('data-talla') or node.get('data-value') or node.get('value')
            text = cls._clean(' '.join(node.xpath('.//text()')))
            value = cls._clean(raw or text)
            if not value or value.casefold() in {'0', 'talla', 'seleccione talla', 'select size', 'size'}:
                continue
            match = re.match(r'^(\d{1,3}(?:[.,]\d)?)\b', value)
            value = match.group(1).replace(',', '.') if match else value
            if value not in values:
                values.append(value)
        # Respaldo para botones/listas cuyo texto contiene la equivalencia EU/UK/US.
        for text in tree.xpath('//*[contains(text(),"EU ") and (contains(text(),"UK ") or contains(text(),"US "))]/text()'):
            match = re.search(r'\bEU\s*(\d{1,3}(?:[.,]\d)?)', cls._clean(text), re.I)
            if match:
                value = match.group(1).replace(',', '.')
                if value not in values:
                    values.append(value)
        return values

    def fetch_preview(self, source, url):
        response = self._http_get(self._get_session(source), url, source)
        tree = lxml_html.fromstring(response.content)
        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical = self._canonical_url(canonical_values[0] if canonical_values else response.url)
        if not self._is_product_url(canonical):
            canonical = self._canonical_url(url)
        reference = self._reference(canonical)
        if not reference:
            raise ValueError('La URL de MUNICH Sports no corresponde a una ficha española de producto.')

        products = self._json_products(tree)
        product = products[0] if products else {}
        name = self._clean(product.get('name')) or self._clean(' '.join(tree.xpath('//h1[1]//text()')))
        if not name:
            name = self._clean(self._meta(tree, 'og:title'))
        if not name:
            raise ValueError('La ficha de MUNICH Sports no publica un nombre reconocible.')

        description = self._extract_description(tree, product)
        price = self._prices(tree, product)
        images = self._images(tree, product, canonical)
        breadcrumbs = self._breadcrumbs(tree, name)
        sizes = self._sizes(tree)
        variants = [
            {
                'ean': False,
                'sku': f'{reference}-{size}',
                'label': name,
                'variant_label': f'Talla: {size}',
                'external_variant_id': f'{reference}-{size}',
            }
            for size in sizes
        ]
        attributes = {'Marca': ['MUNICH']}
        if sizes:
            attributes['Talla'] = sizes

        return {
            'name': name,
            'description': description,
            'short_description': description,
            'full_description': description,
            'attributes': attributes,
            'price': price,
            'price_available': bool(price),
            'currency': 'EUR',
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical,
            'style_code': reference,
            'color_code': False,
            'category_path': ' / '.join(['MUNICH Sports'] + breadcrumbs),
            'ean_variants': self._normalise_ean_variants(variants),
            'ean_complete': True,
        }
