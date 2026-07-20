import gzip
import html
import json
import logging
import re
from urllib.parse import parse_qs, unquote, urljoin, urlparse, urlsplit, urlunsplit

from lxml import etree
from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorCerveloEs(models.AbstractModel):
    """Conector del catálogo español de Cervélo.

    Cervélo publica una ficha por familia/modelo bajo ``/es-ES/bikes/<slug>``.
    Dentro de cada ficha aparecen varias configuraciones (builds), colores y
    tallas. La web está construida con Next.js y Prismic, por lo que los datos
    pueden estar tanto en el HTML como en JSON-LD o en ``__NEXT_DATA__``.

    Se crea un producto simple por modelo. Los GTIN que la web publique para
    configuraciones o tallas se conservan en ``sitemap.product.ean`` y solo se
    asignan al barcode de Odoo cuando existe un único código inequívoco.
    """

    _name = 'sitemap.connector.cervelo_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Cervélo España'

    _HOSTS = {'cervelo.com', 'www.cervelo.com'}
    _LOCALE_RE = re.compile(r'^/es[-_]es/bikes/', re.IGNORECASE)
    _COLLECTION_SLUGS = {
        '', 'road', 'time-trial-triathlon', 'cx-gravel', 'off-road',
        'electric-bikes', 'e-bikes', 'ltd-edition', 'limited-edition',
    }
    _EDITORIAL_TOKENS = (
        'special-edition', 'grand-tour', 'technology', 'size-guide',
        'bike-finder', 'compare', 'archive', 'manual', 'support',
    )
    _NON_PRODUCT_IMAGE_RE = re.compile(
        r'(?:logo|favicon|icon|sprite|cookie|newsletter|social|payment|flag|'
        r'arrow|loader|placeholder|avatar|team|athlete|footer|header|menu|nav|'
        r'close|play-button|youtube|vimeo|country|language|dealer|retailer)',
        re.IGNORECASE,
    )
    _IMAGE_EXT_RE = re.compile(r'\.(?:avif|gif|jpe?g|png|webp)(?:$|\?)', re.IGNORECASE)
    _PRICE_RE = re.compile(
        r'(?<!\d)(\d{1,3}(?:[.\s]\d{3})+(?:,\d{2})?|\d+(?:[.,]\d{2})?)\s*€'
    )
    _SIZE_RE = re.compile(r'^(?:4[68]|5[01468]|61|XS|S|M|L|XL|XXL)$', re.IGNORECASE)

    _CATEGORY_BY_SLUG = {
        's5': ['Bicicletas', 'Carretera', 'Aero'],
        'r5': ['Bicicletas', 'Carretera', 'Escalada'],
        'soloist': ['Bicicletas', 'Carretera', 'Competición'],
        'caledonia-5': ['Bicicletas', 'Carretera', 'Gran fondo'],
        'caledonia': ['Bicicletas', 'Carretera', 'Gran fondo'],
        'p5': ['Bicicletas', 'Triatlón y contrarreloj'],
        'p-series': ['Bicicletas', 'Triatlón y contrarreloj'],
        'r5-cx': ['Bicicletas', 'Ciclocross'],
        'aspero-5': ['Bicicletas', 'Gravel'],
        'aspero': ['Bicicletas', 'Gravel'],
        'zht-5': ['Bicicletas', 'Montaña', 'Cross Country'],
        'zfs-5': ['Bicicletas', 'Montaña', 'Cross Country'],
        'rouvida': ['Bicicletas eléctricas'],
    }

    # ------------------------------------------------------------------
    # HTTP, URLs y sitemap
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

    @classmethod
    def _canonical_url(cls, value):
        raw = html.unescape(str(value or '')).strip().replace('\\/', '/')
        if not raw:
            return False
        parts = urlsplit(raw)
        host = parts.netloc.lower()
        if host == 'cervelo.com':
            host = 'www.cervelo.com'
        path = re.sub(r'/+', '/', parts.path or '/')
        path = re.sub(r'^/es[-_]es/', '/es-ES/', path, flags=re.IGNORECASE)
        if path != '/':
            path = path.rstrip('/')
        return urlunsplit((parts.scheme or 'https', host, path, '', ''))

    @classmethod
    def _product_slug(cls, value):
        canonical = cls._canonical_url(value)
        if not canonical:
            return False
        parsed = urlparse(canonical)
        if parsed.netloc.lower() not in cls._HOSTS:
            return False
        path = parsed.path
        if not cls._LOCALE_RE.match(path):
            return False
        slug = path.split('/bikes/', 1)[-1].strip('/')
        if not slug or '/' in slug:
            return False
        lowered = slug.casefold()
        if lowered in cls._COLLECTION_SLUGS:
            return False
        if any(token in lowered for token in cls._EDITORIAL_TOKENS):
            return False
        if lowered.endswith(('.xml', '.pdf', '.jpg', '.jpeg', '.png', '.webp')):
            return False
        if not re.search(r'[a-z]', lowered):
            return False
        return slug

    @classmethod
    def _product_key(cls, value):
        slug = cls._product_slug(value)
        return slug.casefold() if slug else False

    def _iter_sitemap_entries(self, source, sitemap_url, depth=0, visited=None):
        if depth > 10:
            raise ValueError('El sitemap de Cervélo supera diez niveles de índices.')
        visited = visited or set()
        parts = urlsplit(sitemap_url)
        clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))
        if clean_url in visited:
            return
        visited.add(clean_url)

        session = self._get_session(source)
        response = self._http_get(session, clean_url, source)
        try:
            root = self._xml_root(response.content)
        except (OSError, ValueError, etree.XMLSyntaxError) as exc:
            raise ValueError(f'Cervélo no devolvió XML válido en {clean_url}.') from exc

        root_name = self._local_name(root)
        if root_name == 'sitemapindex':
            for child_url in root.xpath(
                './*[local-name()="sitemap"]/*[local-name()="loc"]/text()'
            ):
                if child_url and child_url.strip():
                    yield from self._iter_sitemap_entries(
                        source,
                        urljoin(clean_url, child_url.strip()),
                        depth=depth + 1,
                        visited=visited,
                    )
            return

        if root_name != 'urlset':
            raise ValueError('El sitemap de Cervélo no contiene <urlset> ni <sitemapindex>.')

        for url_element in root.xpath('./*[local-name()="url"]'):
            loc_values = url_element.xpath('./*[local-name()="loc"]/text()')
            alternate_values = url_element.xpath(
                './*[local-name()="link" and '
                'translate(@hreflang,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")='
                '"es-es"]/@href'
            )
            loc = False
            for candidate in alternate_values + loc_values:
                canonical = self._canonical_url(candidate)
                if self._product_slug(canonical):
                    loc = canonical
                    break
            if not loc:
                continue

            lastmod_values = url_element.xpath('./*[local-name()="lastmod"]/text()')
            image_values = url_element.xpath(
                './/*[local-name()="image"]/*[local-name()="loc"]/text()'
            )
            yield (
                {
                    'url': loc,
                    'lastmod': self._parse_lastmod(
                        lastmod_values[0].strip() if lastmod_values else False
                    ),
                },
                [item.strip() for item in image_values if item and item.strip()],
            )

    @classmethod
    def _clean_image_url(cls, value, page_url=''):
        raw = html.unescape(str(value or '')).strip().replace('\\/', '/')
        if not raw or raw.startswith(('data:', 'blob:')):
            return False
        absolute = urljoin(page_url, raw.split()[0])
        parts = urlsplit(absolute)
        if parts.scheme not in ('http', 'https'):
            return False

        # Next.js redimensiona imágenes de Prismic mediante /_next/image.
        # Se conserva la URL original para descargar el recurso sin depender
        # del ancho fijo del optimizador.
        if parts.netloc.lower() in cls._HOSTS and parts.path == '/_next/image':
            original = (parse_qs(parts.query).get('url') or [False])[0]
            if original:
                return cls._clean_image_url(unquote(original), page_url)

        if cls._NON_PRODUCT_IMAGE_RE.search(parts.path):
            return False
        if not cls._IMAGE_EXT_RE.search(parts.path):
            return False
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))

    def _collect_sitemap_products(self, source):
        entries_by_key = {}
        images_by_key = {}
        for entry, image_urls in self._iter_sitemap_entries(source, source.sitemap_index_url):
            canonical = self._canonical_url(entry['url'])
            key = self._product_key(canonical)
            if not key:
                continue
            candidate = {'url': canonical, 'lastmod': entry.get('lastmod') or False}
            current = entries_by_key.get(key)
            if not current:
                entries_by_key[key] = candidate
            elif candidate['lastmod'] and (
                not current['lastmod'] or candidate['lastmod'] > current['lastmod']
            ):
                current['lastmod'] = candidate['lastmod']

            target = images_by_key.setdefault(key, [])
            for image_url in image_urls:
                cleaned = self._clean_image_url(image_url, canonical)
                if cleaned and cleaned not in target:
                    target.append(cleaned)
        return entries_by_key, images_by_key

    def _fallback_product_entries(self, source):
        session = self._get_session(source)
        entries = {}
        for page_url in (
            'https://www.cervelo.com/es-ES/bikes/road',
            'https://www.cervelo.com/es-ES/bikes/time-trial-triathlon',
            'https://www.cervelo.com/es-ES/bikes/cx-gravel',
            'https://www.cervelo.com/es-ES/bikes/electric-bikes',
        ):
            try:
                response = self._http_get(session, page_url, source)
                tree = lxml_html.fromstring(response.content)
            except Exception as exc:
                _logger.debug('Cervélo: no se pudo recorrer %s: %s', page_url, exc)
                continue
            for href in tree.xpath('//a[@href]/@href'):
                canonical = self._canonical_url(urljoin(page_url, href))
                key = self._product_key(canonical)
                if key:
                    entries.setdefault(key, {'url': canonical, 'lastmod': False})
        return entries

    def get_product_entries(self, source, category_filter=None, limit=0):
        try:
            entries_by_key, _images = self._collect_sitemap_products(source)
        except Exception as exc:
            _logger.warning(
                'Cervélo: el sitemap no pudo procesarse; se usa el catálogo como respaldo: %s',
                exc,
            )
            entries_by_key = self._fallback_product_entries(source)

        if not entries_by_key:
            raise ValueError('No se localizaron fichas españolas de Cervélo.')

        filter_text = (category_filter or '').strip().casefold()
        result = []
        for key, entry in sorted(entries_by_key.items(), key=lambda item: item[0]):
            category = '/'.join(self.parse_category_path(entry['url']))
            haystack = f'{key} {entry["url"]} {category}'.casefold()
            if filter_text and filter_text not in haystack:
                continue
            result.append(entry)
            if limit and len(result) >= limit:
                break
        return result

    def get_image_map(self, source):
        try:
            entries_by_key, images_by_key = self._collect_sitemap_products(source)
        except Exception:
            return {}
        return {
            entry['url']: images_by_key.get(key, [])
            for key, entry in entries_by_key.items()
            if images_by_key.get(key)
        }

    # ------------------------------------------------------------------
    # Ficha de producto
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_text(value):
        return re.sub(r'\s+', ' ', html.unescape(str(value or ''))).strip()

    @classmethod
    def _meta(cls, tree, name):
        values = tree.xpath(
            f'//meta[@property="{name}" or @name="{name}" or @itemprop="{name}"]/@content'
        )
        return cls._normalize_text(values[0]) if values else False

    @classmethod
    def _json_payloads(cls, tree):
        payloads = []
        for raw in tree.xpath(
            '//script[@type="application/ld+json" or @type="application/json" '
            'or @id="__NEXT_DATA__"]/text()'
        ):
            if not raw or len(raw) > 12_000_000:
                continue
            try:
                payloads.append(json.loads(raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return payloads

    @classmethod
    def _find_product_json_ld(cls, tree):
        found = []

        def walk(value):
            if isinstance(value, list):
                for item in value:
                    walk(item)
                return
            if not isinstance(value, dict):
                return
            item_type = value.get('@type')
            types = item_type if isinstance(item_type, list) else [item_type]
            if any(str(item).casefold() == 'product' for item in types if item):
                found.append(value)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    walk(child)

        for payload in cls._json_payloads(tree):
            walk(payload)
        return found[0] if found else {}

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
    def _extract_product_name(cls, tree, product_json, canonical):
        values = tree.xpath('//main//h1[1]//text()') or tree.xpath('//h1[1]//text()')
        name = cls._normalize_text(' '.join(values)) if values else False
        name = name or cls._normalize_text(product_json.get('name'))
        name = name or cls._meta(tree, 'og:title') or cls._meta(tree, 'twitter:title')
        if name:
            name = re.sub(r'\s*[-|]\s*Cerv[eé]lo.*$', '', name, flags=re.IGNORECASE).strip()
        if not name:
            slug = cls._product_slug(canonical) or ''
            name = slug.replace('-', ' ').title()
        return name

    @staticmethod
    def _parse_price(value):
        text = re.sub(r'[^0-9.,]', '', str(value or ''))
        if not text:
            return False
        if re.fullmatch(r'\d{1,3}(?:[.\s]\d{3})+', text):
            text = text.replace('.', '').replace(' ', '')
        elif ',' in text and '.' in text:
            if text.rfind(',') > text.rfind('.'):
                text = text.replace('.', '').replace(',', '.')
            else:
                text = text.replace(',', '')
        elif ',' in text:
            text = text.replace('.', '').replace(',', '.')
        try:
            return float(text)
        except ValueError:
            return False

    @classmethod
    def _price(cls, tree, product_json, lines):
        prices = []
        currency = False
        offers = product_json.get('offers') if isinstance(product_json, dict) else None
        offers = offers if isinstance(offers, list) else [offers]
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            currency = currency or offer.get('priceCurrency')
            for field in ('salePrice', 'price', 'lowPrice'):
                parsed = cls._parse_price(offer.get(field))
                if parsed is not False and parsed > 0:
                    prices.append(parsed)
                    break

        for field in ('product:price:amount', 'og:price:amount'):
            parsed = cls._parse_price(cls._meta(tree, field))
            if parsed is not False and parsed > 0:
                prices.append(parsed)
        currency = (
            currency or cls._meta(tree, 'product:price:currency')
            or cls._meta(tree, 'og:price:currency') or 'EUR'
        )

        # Las configuraciones pueden publicar precios distintos. Se usa el
        # mínimo vigente como precio informativo del modelo simple.
        for line in lines:
            for match in cls._PRICE_RE.finditer(line):
                parsed = cls._parse_price(match.group(1))
                if parsed is not False and parsed >= 100:
                    prices.append(parsed)
        return (min(prices), currency) if prices else (0.0, currency)

    @classmethod
    def _extract_description(cls, tree, product_json):
        for value in (
            product_json.get('description') if isinstance(product_json, dict) else False,
            cls._meta(tree, 'og:description'),
            cls._meta(tree, 'description'),
        ):
            text = cls._normalize_text(value)
            if text:
                return text
        h1_nodes = tree.xpath('//main//h1[1]') or tree.xpath('//h1[1]')
        if h1_nodes:
            for paragraph in h1_nodes[0].xpath('following::p[normalize-space()][position() <= 5]'):
                text = cls._normalize_text(' '.join(paragraph.xpath('.//text()')))
                if len(text) >= 80:
                    return text
        return ''

    @classmethod
    def _builds(cls, tree, lines):
        builds = []
        seen = set()
        forbidden = {
            'geometry', 'bikes', 'about cervélo', 'support', 'retailers',
            'sign up to be in the know', 'make friends with the wind',
        }
        for node in tree.xpath('//main//h2 | //main//h3'):
            name = cls._normalize_text(' '.join(node.xpath('.//text()')))
            if not name or name.casefold() in forbidden or len(name) > 80:
                continue
            ancestor_text = cls._normalize_text(' '.join(node.xpath('ancestor::*[position() <= 3]//@class'))).casefold()
            sibling_text = cls._normalize_text(' '.join(node.xpath(
                'following-sibling::*[position() <= 5]//text()'
            )))
            context = f'{ancestor_text} {sibling_text}'.casefold()
            is_build = any(token in context for token in (
                'build', 'spec', 'frameset', 'axs', 'di2', 'ultegra', 'dura', 'force', 'rival', 'grx'
            )) or any(token in name.casefold() for token in (
                'frameset', 'axs', 'di2', 'ultegra', 'dura', 'force', 'rival', 'grx', 'apex', '105'
            ))
            if not is_build:
                continue
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            color = False
            for candidate in node.xpath(
                'following-sibling::*[position() <= 4]//text()[normalize-space()]'
            ):
                text = cls._normalize_text(candidate)
                if not text or text == name or text.startswith(('•', '|')):
                    continue
                if cls._PRICE_RE.search(text) or len(text) > 60:
                    continue
                if any(token in text.casefold() for token in (
                    'open build', 'spec', 'carbon', 'wheel', 'speed', 'meter', 'tire', 'storage'
                )):
                    continue
                color = text
                break
            price = False
            price_match = cls._PRICE_RE.search(sibling_text)
            if price_match:
                price = cls._parse_price(price_match.group(1))
            builds.append({'name': name, 'color': color, 'price': price})

        # Respaldo cuando el HTML no conserva la estructura de tarjetas.
        if not builds:
            for index, line in enumerate(lines):
                if not any(token in line.casefold() for token in (
                    'frameset', 'axs', 'di2', 'ultegra', 'dura ace', 'force', 'rival', 'grx', 'apex', '105'
                )):
                    continue
                if len(line) > 80 or line.casefold() in seen:
                    continue
                seen.add(line.casefold())
                color = False
                if index + 1 < len(lines):
                    candidate = lines[index + 1]
                    if len(candidate) <= 60 and not cls._PRICE_RE.search(candidate):
                        color = candidate
                builds.append({'name': line, 'color': color, 'price': False})
                if len(builds) >= 30:
                    break
        return builds

    @classmethod
    def _sizes(cls, lines):
        result = []
        for index, line in enumerate(lines):
            if line.casefold() != 'geometry':
                continue
            for candidate in lines[index + 1:index + 8]:
                values = [item for item in re.split(r'[\s/|,]+', candidate) if item]
                matched = [item.upper() for item in values if cls._SIZE_RE.fullmatch(item)]
                if len(matched) >= 2:
                    for item in matched:
                        if item not in result:
                            result.append(item)
                    return result
        text = ' '.join(lines)
        match = re.search(
            r'(?:sizes?|tallas?)\s*[:：]\s*((?:4[68]|5[01468]|61|XS|S|M|L|XL|XXL)(?:\s*[/,| ]\s*(?:4[68]|5[01468]|61|XS|S|M|L|XL|XXL))*)',
            text,
            flags=re.IGNORECASE,
        )
        if match:
            for item in re.split(r'[\s/|,]+', match.group(1)):
                item = item.upper()
                if cls._SIZE_RE.fullmatch(item) and item not in result:
                    result.append(item)
        return result

    @classmethod
    def _style_code(cls, canonical, product_json):
        if isinstance(product_json, dict):
            for field in ('sku', 'mpn', 'productID', 'productId'):
                value = cls._normalize_text(product_json.get(field))
                if value and re.fullmatch(r'[A-Z0-9._/-]{2,60}', value, re.I):
                    return value.upper()
        slug = cls._product_slug(canonical)
        return slug.upper() if slug else False

    @classmethod
    def _category_path(cls, canonical):
        slug = (cls._product_slug(canonical) or '').casefold()
        base_slug = re.sub(r'-(?:20\d{2}|\d{2}-\d{2})$', '', slug)
        category = cls._CATEGORY_BY_SLUG.get(base_slug)
        if category:
            result = list(category)
        elif any(token in slug for token in ('rouvida', 'electric', 'e-bike')):
            result = ['Bicicletas eléctricas']
        else:
            result = ['Bicicletas']
        if re.search(r'-(?:20\d{2}|\d{2}-\d{2})$', slug):
            result.append('Archivo')
        return result

    @classmethod
    def parse_category_path(cls, product_url):
        return cls._category_path(product_url) if cls._product_slug(product_url) else []

    @classmethod
    def _images_from_payloads(cls, payloads, page_url):
        result = []

        def walk(value, key=''):
            if isinstance(value, list):
                for item in value:
                    walk(item, key)
                return
            if isinstance(value, dict):
                for child_key, child in value.items():
                    walk(child, str(child_key))
                return
            if not isinstance(value, str):
                return
            if key.casefold() not in {
                'image', 'images', 'url', 'src', 'imageurl', 'image_url',
                'contenturl', 'thumbnailurl', 'mobile', 'desktop',
            } and not cls._IMAGE_EXT_RE.search(value):
                return
            cleaned = cls._clean_image_url(value, page_url)
            if cleaned and cleaned not in result:
                result.append(cleaned)

        for payload in payloads:
            walk(payload)
        return result

    @classmethod
    def _html_images(cls, tree, page_url):
        result = []
        scopes = tree.xpath(
            '//main//*[contains(translate(@class,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"gallery") '
            'or contains(translate(@class,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"product") '
            'or contains(translate(@class,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"bike") '
            'or contains(translate(@class,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"carousel") '
            'or contains(translate(@class,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"slider")]'
        )
        nodes = []
        for scope in scopes[:120]:
            nodes.extend(scope.xpath('.//img | .//source | .//a[@href]'))
        if not nodes:
            main = (tree.xpath('//main') or [tree])[0]
            nodes = main.xpath('.//img | .//source')
        for node in nodes:
            candidates = []
            for attr in ('href', 'src', 'data-src', 'data-original', 'data-lazy-src'):
                if node.get(attr):
                    candidates.append(node.get(attr))
            for attr in ('srcset', 'data-srcset'):
                if node.get(attr):
                    candidates.extend(
                        item.strip().split(' ')[0]
                        for item in node.get(attr).split(',') if item.strip()
                    )
            for raw in reversed(candidates):
                cleaned = cls._clean_image_url(raw, page_url)
                if cleaned and cleaned not in result:
                    result.append(cleaned)
        return result

    @classmethod
    def _is_product_page(cls, tree, lines, canonical):
        if not cls._product_slug(canonical):
            return False
        h1 = tree.xpath('//main//h1 | //h1')
        text = ' '.join(lines[:500]).casefold()
        markers = (
            'card view', 'spec view', 'open build specs', 'geometry',
            'please note: price and parts spec', 'frame size',
        )
        return bool(h1 and sum(1 for marker in markers if marker in text) >= 1)

    def fetch_preview(self, source, url):
        session = self._get_session(source)
        response = self._http_get(session, url, source)
        tree = lxml_html.fromstring(response.content)
        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical = self._canonical_url(
            canonical_values[0] if canonical_values else response.url or url
        )
        lines = self._page_lines(tree)
        if not self._is_product_page(tree, lines, canonical):
            fallback = self._canonical_url(url)
            if fallback != canonical and self._is_product_page(tree, lines, fallback):
                canonical = fallback
            else:
                raise ValueError(
                    'La URL no parece una ficha de modelo Cervélo; puede ser una '
                    'colección, página editorial o modelo retirado.'
                )

        payloads = self._json_payloads(tree)
        product_json = self._find_product_json_ld(tree)
        name = self._extract_product_name(tree, product_json, canonical)
        description = self._extract_description(tree, product_json)
        builds = self._builds(tree, lines)
        sizes = self._sizes(lines)
        price, currency = self._price(tree, product_json, lines)
        category = self._category_path(canonical)

        description_html = f'<p>{html.escape(description)}</p>' if description else ''
        details = []
        if sizes:
            details.append(
                '<li><strong>Tallas de cuadro:</strong> %s</li>'
                % html.escape(' / '.join(sizes))
            )
        colors = []
        for build in builds:
            color = build.get('color')
            if color and color not in colors:
                colors.append(color)
        if colors:
            details.append(
                '<li><strong>Colores:</strong> %s</li>'
                % html.escape(' / '.join(colors))
            )
        if details:
            description_html += '<p><strong>Opciones publicadas:</strong></p><ul>%s</ul>' % ''.join(details)
        if builds:
            rows = []
            for build in builds:
                text = html.escape(build['name'])
                if build.get('color'):
                    text += ' — ' + html.escape(build['color'])
                if build.get('price'):
                    text += ' — %.2f €' % build['price']
                rows.append(f'<li>{text}</li>')
            description_html += '<p><strong>Configuraciones:</strong></p><ul>%s</ul>' % ''.join(rows)

        images = self._images_from_payloads(payloads, canonical)
        og_image = self._clean_image_url(self._meta(tree, 'og:image'), canonical)
        if og_image and og_image not in images:
            images.insert(0, og_image)
        for image_url in self._html_images(tree, canonical):
            if image_url not in images:
                images.append(image_url)

        ean_variants = []
        for payload in payloads:
            ean_variants.extend(self._ean_variants_from_payload(payload))
        ean_variants.extend(self._ean_variants_from_html_content(response.content))

        return {
            'name': name,
            'description': description_html,
            'price': price,
            'price_available': bool(price),
            'currency': currency or 'EUR',
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical,
            'style_code': self._style_code(canonical, product_json),
            'color_code': ' / '.join(colors) if colors else False,
            'category_path': ' / '.join(category),
            'ean_variants': self._normalise_ean_variants(ean_variants),
            # Next.js puede contener las variantes completas en __NEXT_DATA__,
            # pero se mantiene False para permitir que el enriquecedor común
            # pruebe también endpoints de variante publicados en la ficha.
            'ean_complete': False,
        }
