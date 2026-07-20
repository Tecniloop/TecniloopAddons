import html
import re
from collections import deque
from urllib.parse import urljoin, urlsplit, urlunsplit

from lxml import html as lxml_html
from odoo import models


class SitemapConnectorBachmannUkBase(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_uk_base'
    _inherit = 'sitemap.import.service'
    _description = 'Base común de conectores Bachmann Europe UK'

    _HOST = 'bachmann.co.uk'
    _PRODUCT_PREFIX = '/product/category/'
    _CATEGORY_PREFIX = '/category/'
    _SKU_RE = re.compile(r'(?<![A-Z0-9])([A-Z0-9]{1,5}(?:-[A-Z0-9]{2,8}){1,3})(?![A-Z0-9])', re.I)
    _BRAND_FILTER = False
    _GTIN_RE = re.compile(r'\b(?:EAN|GTIN|Barcode)\s*:?\s*(\d{8}|\d{12}|\d{13}|\d{14})\b', re.I)

    _BRAND_ALIASES = {
        'branchline': 'Bachmann Branchline', 'branch': 'Bachmann Branchline',
        'graham farish': 'Graham Farish', 'grafar': 'Graham Farish',
        'liliput': 'Liliput', 'efe rail': 'EFE Rail', 'eferail': 'EFE Rail',
        'scenecraft': 'Scenecraft', 'narrow gauge': 'Bachmann Narrow Gauge',
        'thomas': 'Thomas & Friends', 'woodland scenics': 'Woodland Scenics',
        'proses': 'Proses', 'bachmann trains': 'Bachmann Trains USA',
        'bachmann china': 'Bachmann China', 'efe road': 'EFE Road',
        'exclusive first editions': 'Exclusive First Editions',
        'greenlight': 'GreenLight', 'mini gt': 'Mini GT',
        'academy': 'Academy', 'trumpeter': 'Trumpeter', 'airfix': 'Airfix',
        'accurate figures': 'Accurate Figures', 'afv club': 'AFV Club',
        'amt': 'AMT', 'emhar': 'Emhar', 'hk models': 'HK Models',
        'i love kit': 'I Love Kit', 'mpc': 'MPC', 'polar lights': 'Polar Lights',
        'roden': 'Roden', 'takom': 'Takom', 'toyway': 'Toyway',
    }

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
        return urlunsplit(('https', 'www.bachmann.co.uk', path.rstrip('/') or '/', '', ''))

    @classmethod
    def _is_product_url(cls, value):
        canonical = cls._canonical_url(value)
        return bool(canonical and urlsplit(canonical).path.startswith(cls._PRODUCT_PREFIX))

    def get_product_entries(self, source, category_filter=None, limit=0):
        session = self._get_session(source)
        queue = deque(['https://www.bachmann.co.uk/category/model-railway'])
        visited = set()
        products = {}
        needle = self._clean(category_filter).casefold()
        max_pages = max(250, (limit or 0) * 3)
        while queue and len(visited) < max_pages:
            page = self._canonical_url(queue.popleft())
            if not page or page in visited:
                continue
            visited.add(page)
            response = self._http_get(session, page, source)
            tree = lxml_html.fromstring(response.content)
            for href in tree.xpath('//a[@href]/@href'):
                absolute = self._canonical_url(urljoin(response.url, href))
                if not absolute:
                    continue
                if self._is_product_url(absolute):
                    if not needle or needle in absolute.casefold():
                        products.setdefault(absolute, {'url': absolute, 'lastmod': False})
                        # El límite se aplica después del filtro de marca.
                elif urlsplit(absolute).path.startswith(self._CATEGORY_PREFIX) and absolute not in visited:
                    queue.append(absolute)
        entries = list(products.values())
        if self._BRAND_FILTER:
            filtered = []
            for item in entries:
                try:
                    response = self._http_get(session, item['url'], source)
                    tree = lxml_html.fromstring(response.content)
                    text = self._clean(' '.join(tree.xpath('//main//text() | //body//text()')))
                    if self._brand(tree, text) == self._BRAND_FILTER:
                        filtered.append(item)
                        if limit and len(filtered) >= limit:
                            break
                except Exception:
                    continue
            entries = filtered
        elif limit:
            entries = entries[:limit]
        if not entries:
            raise ValueError('No se han encontrado fichas Bachmann para la marca configurada.')
        return entries

    def get_image_map(self, source):
        return {}

    @classmethod
    def _brand(cls, tree, text):
        candidates = tree.xpath('//*[contains(@class,"breadcrumb") or contains(@class,"breadcrumbs")]//text()')
        candidates += tree.xpath('//*[normalize-space(text())="By"]/following-sibling::*[1]//text()')
        candidates += re.findall(r'\bBy\s+([A-Za-z][A-Za-z &-]{2,40})', text)
        folded = ' | '.join(cls._clean(v).casefold() for v in candidates if cls._clean(v))
        for token, brand in cls._BRAND_ALIASES.items():
            if token in folded:
                return brand
        for token, brand in cls._BRAND_ALIASES.items():
            if token in text.casefold():
                return brand
        return 'Bachmann Europe'

    @classmethod
    def _label_value(cls, tree, label):
        wanted = label.casefold().rstrip(':')
        for node in tree.xpath('//*[self::div or self::span or self::p or self::dt or self::th or self::strong]'):
            value = cls._clean(' '.join(node.xpath('.//text()')))
            if value.casefold().rstrip(':') != wanted:
                continue
            for sibling in node.itersiblings():
                result = cls._clean(' '.join(sibling.xpath('.//text()')) if hasattr(sibling, 'xpath') else sibling.text)
                if result:
                    return result
            parent = node.getparent()
            if parent is not None:
                texts = [cls._clean(v) for v in parent.xpath('./*/text() | ./text()') if cls._clean(v)]
                for result in texts:
                    if result.casefold().rstrip(':') != wanted:
                        return result
        return False

    @classmethod
    def _breadcrumbs(cls, tree):
        values = []
        for raw in tree.xpath('//*[contains(@class,"breadcrumb") or contains(@class,"breadcrumbs")]//a//text()'):
            value = cls._clean(raw)
            if value and value.casefold() not in {'home'} and value not in values:
                values.append(value)
        return values

    def fetch_preview(self, source, url):
        response = self._http_get(self._get_session(source), url, source)
        tree = lxml_html.fromstring(response.content)
        canonical = self._canonical_url(response.url) or self._canonical_url(url)
        if not self._is_product_url(canonical):
            raise ValueError('La URL de Bachmann no corresponde a una ficha de producto.')
        name = self._clean(' '.join(tree.xpath('//h1[1]//text()')))
        text = self._clean(' '.join(tree.xpath('//main//text() | //body//text()')))
        sku = self._label_value(tree, 'SKU')
        if sku:
            match = self._SKU_RE.search(sku)
            sku = match.group(1).upper() if match else sku.strip().upper()
        if not sku:
            match = self._SKU_RE.search(urlsplit(canonical).path.rsplit('/', 1)[-1])
            sku = match.group(1).upper() if match else False
        if not name or not sku:
            raise ValueError('La ficha Bachmann no publica nombre o SKU reconocible.')

        brand = self._brand(tree, text)
        if self._BRAND_FILTER and brand != self._BRAND_FILTER:
            raise ValueError('La ficha pertenece a %s y no a %s.' % (brand, self._BRAND_FILTER))
        scale = self._label_value(tree, 'Scale')
        era = self._label_value(tree, 'Era')
        availability = self._label_value(tree, 'Availability')
        attrs = {'Marca': brand}
        if scale:
            attrs['Escala ferroviaria'] = scale
            scale_map = {'OO': '1:76', 'N': '1:148', 'HO': '1:87', 'H0': '1:87', 'HOE': '1:87', 'H0E': '1:87', 'O': '1:43.5', 'G': '1:22.5'}
            if scale.upper() in scale_map:
                attrs['Escala'] = scale_map[scale.upper()]
        if era:
            attrs['Época'] = era
        if availability:
            attrs['Disponibilidad'] = availability
        folded = text.casefold()
        if 'dcc' in folded:
            attrs['DCC'] = 'Sí'
        if 'sound fitted' in folded or sku.endswith(('SF', 'DS')):
            attrs['Sonido'] = 'Sí'
        if 'decoder fitted' in folded or sku.endswith('DC'):
            attrs['Decoder instalado'] = 'Sí'
        if 'weathered' in folded or '[w]' in folded:
            attrs['Acabado envejecido'] = 'Sí'
        if 'passenger figures fitted' in folded or '[pf]' in folded:
            attrs['Figuras de pasajeros'] = 'Incluidas'

        desc_nodes = tree.xpath('//*[self::h2 or self::h3][contains(translate(normalize-space(.),"DESCRIPTION","description"),"description")]/following-sibling::*')
        description_parts = []
        for node in desc_nodes:
            if node.tag in {'h2', 'h3'}:
                break
            val = self._clean(' '.join(node.xpath('.//text()')))
            if val and 'you might be also interested' not in val.casefold():
                description_parts.append(val)
        description = '\n\n'.join(description_parts[:8]) or self._clean(tree.xpath('string(//meta[@name="description"]/@content)'))

        images = []
        for raw in tree.xpath('//meta[@property="og:image"]/@content | //main//img/@data-src | //main//img/@src'):
            absolute = urljoin(canonical, raw)
            if absolute not in images and not any(x in absolute.casefold() for x in ('logo', 'icon', 'spinner')):
                images.append(absolute)

        eans = []
        for raw in self._GTIN_RE.findall(text):
            gtin = self._normalise_gtin(raw)
            if gtin:
                eans.append({'ean': gtin, 'sku': sku, 'label': name, 'external_variant_id': sku})

        breadcrumbs = self._breadcrumbs(tree)
        return {
            'name': name,
            'description': description,
            'short_description': description,
            'full_description': description,
            'attributes': attrs,
            'price': 0.0,
            'price_available': False,
            'currency': 'GBP',
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical,
            'style_code': sku,
            'color_code': False,
            'category_path': ' / '.join(['Bachmann Europe', brand] + breadcrumbs),
            'ean_variants': self._normalise_ean_variants(eans),
            'ean_complete': True,
        }


class SitemapConnectorBachmannBachmannBranchline(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_bachmann_branchline'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector Bachmann Branchline desde Bachmann UK'
    _BRAND_FILTER = 'Bachmann Branchline'


class SitemapConnectorBachmannGrahamFarish(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_graham_farish'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector Graham Farish desde Bachmann UK'
    _BRAND_FILTER = 'Graham Farish'


class SitemapConnectorBachmannLiliput(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_liliput'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector Liliput desde Bachmann UK'
    _BRAND_FILTER = 'Liliput'


class SitemapConnectorBachmannEfeRail(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_efe_rail'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector EFE Rail desde Bachmann UK'
    _BRAND_FILTER = 'EFE Rail'


class SitemapConnectorBachmannScenecraft(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_scenecraft'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector Scenecraft desde Bachmann UK'
    _BRAND_FILTER = 'Scenecraft'


class SitemapConnectorBachmannBachmannNarrowGauge(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_bachmann_narrow_gauge'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector Bachmann Narrow Gauge desde Bachmann UK'
    _BRAND_FILTER = 'Bachmann Narrow Gauge'


class SitemapConnectorBachmannThomasFriends(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_thomas_friends'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector Thomas & Friends desde Bachmann UK'
    _BRAND_FILTER = 'Thomas & Friends'


class SitemapConnectorBachmannWoodlandScenics(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_woodland_scenics'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector Woodland Scenics desde Bachmann UK'
    _BRAND_FILTER = 'Woodland Scenics'


class SitemapConnectorBachmannProses(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_proses'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector Proses desde Bachmann UK'
    _BRAND_FILTER = 'Proses'


class SitemapConnectorBachmannBachmannTrainsUsa(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_bachmann_trains_usa'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector Bachmann Trains USA desde Bachmann UK'
    _BRAND_FILTER = 'Bachmann Trains USA'


class SitemapConnectorBachmannBachmannChina(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_bachmann_china'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector Bachmann China desde Bachmann UK'
    _BRAND_FILTER = 'Bachmann China'


class SitemapConnectorBachmannEfeRoad(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_efe_road'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector EFE Road desde Bachmann UK'
    _BRAND_FILTER = 'EFE Road'


class SitemapConnectorBachmannExclusiveFirstEditions(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_exclusive_first_editions'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector Exclusive First Editions desde Bachmann UK'
    _BRAND_FILTER = 'Exclusive First Editions'


class SitemapConnectorBachmannGreenlight(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_greenlight'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector GreenLight desde Bachmann UK'
    _BRAND_FILTER = 'GreenLight'


class SitemapConnectorBachmannMiniGt(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_mini_gt'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector Mini GT desde Bachmann UK'
    _BRAND_FILTER = 'Mini GT'


class SitemapConnectorBachmannAcademy(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_academy'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector Academy desde Bachmann UK'
    _BRAND_FILTER = 'Academy'


class SitemapConnectorBachmannTrumpeter(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_trumpeter'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector Trumpeter desde Bachmann UK'
    _BRAND_FILTER = 'Trumpeter'


class SitemapConnectorBachmannAirfixBachmann(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_airfix_bachmann'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector Airfix desde Bachmann UK'
    _BRAND_FILTER = 'Airfix'


class SitemapConnectorBachmannAccurateFigures(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_accurate_figures'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector Accurate Figures desde Bachmann UK'
    _BRAND_FILTER = 'Accurate Figures'


class SitemapConnectorBachmannAfvClub(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_afv_club'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector AFV Club desde Bachmann UK'
    _BRAND_FILTER = 'AFV Club'


class SitemapConnectorBachmannAmt(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_amt'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector AMT desde Bachmann UK'
    _BRAND_FILTER = 'AMT'


class SitemapConnectorBachmannEmhar(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_emhar'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector Emhar desde Bachmann UK'
    _BRAND_FILTER = 'Emhar'


class SitemapConnectorBachmannHkModels(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_hk_models'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector HK Models desde Bachmann UK'
    _BRAND_FILTER = 'HK Models'


class SitemapConnectorBachmannILoveKit(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_i_love_kit'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector I Love Kit desde Bachmann UK'
    _BRAND_FILTER = 'I Love Kit'


class SitemapConnectorBachmannMpc(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_mpc'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector MPC desde Bachmann UK'
    _BRAND_FILTER = 'MPC'


class SitemapConnectorBachmannPolarLights(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_polar_lights'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector Polar Lights desde Bachmann UK'
    _BRAND_FILTER = 'Polar Lights'


class SitemapConnectorBachmannRoden(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_roden'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector Roden desde Bachmann UK'
    _BRAND_FILTER = 'Roden'


class SitemapConnectorBachmannTakom(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_takom'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector Takom desde Bachmann UK'
    _BRAND_FILTER = 'Takom'


class SitemapConnectorBachmannToyway(models.AbstractModel):
    _name = 'sitemap.connector.bachmann_toyway'
    _inherit = 'sitemap.connector.bachmann_uk_base'
    _description = 'Conector Toyway desde Bachmann UK'
    _BRAND_FILTER = 'Toyway'
