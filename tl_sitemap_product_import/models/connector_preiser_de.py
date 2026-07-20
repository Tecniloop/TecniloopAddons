import html
import logging
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorPreiserDe(models.AbstractModel):
    """Conector del catálogo público de Paul M. Preiser.

    ``sitemap.php`` no es un sitemap XML y tampoco enlaza fichas unitarias.
    Es un mapa HTML que conduce a páginas ``showpage.php``; cada una contiene
    múltiples referencias. Para mantener el contrato del importador, el
    conector crea una URL lógica por artículo mediante el parámetro
    ``tl_article``. El servidor de Preiser ignora ese parámetro, pero permite
    identificar de forma estable cada producto dentro de la página compartida.
    """

    _name = 'sitemap.connector.preiser_de'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Preiser Figuren Alemania'

    _HOSTS = {'preiserfiguren.de', 'www.preiserfiguren.de'}
    _ARTICLE_PARAM = 'tl_article'
    # Referencias Preiser habituales: 5 cifras. Merten publica también códigos
    # como "02 40001", que se normalizan como "02 40001" para no perderlos.
    _ARTICLE_RE = re.compile(r'(?<!\d)(?P<code>(?:\d{2}\s+)?\d{5})(?!\d)')
    _SCALE_RE = re.compile(
        r'(?:Ma(?:ß|ss)stab|scale)\s*(?P<scale>1\s*[:/]\s*\d+(?:[,.]\d+)?)',
        re.IGNORECASE,
    )
    _GAUGE_SCALE = {
        'H0': '1:87', 'HO': '1:87', 'G': '1:22,5', 'II': '1:22,5',
        'I': '1:32', '0': '1:43', 'TT': '1:120', 'N': '1:160',
        'Z': '1:220',
    }

    @classmethod
    def _clean(cls, value):
        value = html.unescape(str(value or '')).replace('\xa0', ' ')
        return re.sub(r'\s+', ' ', value).strip(' \t\r\n-|□❐❒')

    @classmethod
    def _base_url(cls, value):
        parts = urlsplit(html.unescape(str(value or '')).strip())
        host = parts.netloc.casefold().removeprefix('www.')
        if host != 'preiserfiguren.de':
            return False
        path = re.sub(r'/+', '/', parts.path or '/')
        if path.endswith('/index.php/showpage.php'):
            path = '/showpage.php'
        query = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
                 if key != cls._ARTICLE_PARAM]
        return urlunsplit(('https', 'www.preiserfiguren.de', path, urlencode(query), ''))

    @classmethod
    def _logical_url(cls, page_url, code):
        base = cls._base_url(page_url)
        if not base:
            return False
        parts = urlsplit(base)
        query = parse_qsl(parts.query, keep_blank_values=True)
        query.append((cls._ARTICLE_PARAM, cls._normalise_code(code)))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))

    @classmethod
    def _normalise_code(cls, code):
        return re.sub(r'\s+', ' ', cls._clean(code))

    @classmethod
    def _article_from_url(cls, value):
        return dict(parse_qsl(urlsplit(value).query, keep_blank_values=True)).get(cls._ARTICLE_PARAM)

    @classmethod
    def _is_catalog_page(cls, value):
        base = cls._base_url(value)
        if not base:
            return False
        path = urlparse(base).path.casefold()
        return path.endswith(('showpage.php', 'index.php'))

    @classmethod
    def _visible_lines(cls, tree):
        for node in tree.xpath('//script|//style|//noscript'):
            node.drop_tree()
        result = []
        for text in tree.xpath('//body//text()'):
            line = cls._clean(text)
            if line:
                result.append(line)
        return result

    @classmethod
    def _page_context(cls, tree):
        title = cls._clean(' '.join(tree.xpath('//h1[1]//text()')))
        if not title:
            title = cls._clean(' '.join(tree.xpath('//title[1]//text()')))
        lines = cls._visible_lines(tree)
        page_text = ' '.join(lines)
        scale_match = cls._SCALE_RE.search(page_text)
        scale = scale_match.group('scale').replace(' ', '').replace('/', ':') if scale_match else False
        gauge = False
        for candidate, default_scale in cls._GAUGE_SCALE.items():
            if re.search(rf'(?<!\w){re.escape(candidate)}(?!\w)', title, re.IGNORECASE):
                gauge = candidate
                scale = scale or default_scale
                break
        return title, lines, gauge, scale

    @classmethod
    def _records_from_tree(cls, tree, page_url):
        title, lines, page_gauge, page_scale = cls._page_context(tree)
        records = {}
        current_heading = title
        current_gauge = page_gauge
        current_scale = page_scale
        for index, line in enumerate(lines):
            if any(token in line.casefold() for token in (
                'miniaturfiguren', 'zubehör', 'automodelle', 'military',
                'elastolin', 'merten', 'maßstab', 'massstab', 'scale',
            )) and len(line) < 220:
                current_heading = line
                heading_scale = cls._SCALE_RE.search(line)
                if heading_scale:
                    current_scale = heading_scale.group('scale').replace(' ', '').replace('/', ':')
                heading_gauge = False
                for candidate, default_scale in cls._GAUGE_SCALE.items():
                    if re.search(rf'(?<!\w){re.escape(candidate)}(?!\w)', line, re.IGNORECASE):
                        heading_gauge = candidate
                        current_scale = current_scale or default_scale
                        break
                if heading_gauge:
                    current_gauge = heading_gauge
            matches = list(cls._ARTICLE_RE.finditer(line))
            for pos, match in enumerate(matches):
                code = cls._normalise_code(match.group('code'))
                tail_end = matches[pos + 1].start() if pos + 1 < len(matches) else len(line)
                name = cls._clean(line[match.end():tail_end])
                if not name and index + 1 < len(lines):
                    candidate = lines[index + 1]
                    if not cls._ARTICLE_RE.fullmatch(candidate) and len(candidate) <= 300:
                        name = cls._clean(candidate)
                # Evita números de teléfono, años, ISBN y precios publicados en
                # textos institucionales. Una referencia de producto necesita
                # una denominación próxima y no debe proceder del pie de página.
                if not name or len(name) < 2:
                    continue
                if any(bad in name.casefold() for bad in (
                    'telefon', 'hypovereinsbank', 'isbn', 'copyright', 'seiten',
                    'catalogue pages', 'katalogseiten', 'eur', 'euro',
                )):
                    continue
                logical = cls._logical_url(page_url, code)
                if not logical:
                    continue
                records[code] = {
                    'code': code,
                    'name': name[:500],
                    'heading': current_heading or title,
                    'page_title': title,
                    'gauge': current_gauge,
                    'scale': current_scale,
                    'url': logical,
                }
        return records

    @classmethod
    def _catalog_links(cls, tree, page_url):
        links = []
        for href in tree.xpath('//a[@href]/@href'):
            absolute = cls._base_url(urljoin(page_url, href))
            if not absolute or not cls._is_catalog_page(absolute):
                continue
            parsed = urlparse(absolute)
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            if parsed.path.endswith('showpage.php') and not query.get('SiteID'):
                continue
            if absolute not in links:
                links.append(absolute)
        return links

    def _discover(self, source, limit=0):
        session = self._get_session(source)
        start = source.sitemap_index_url or 'https://www.preiserfiguren.de/sitemap.php'
        queue = [start]
        visited = set()
        products = {}
        image_map = {}

        while queue and len(visited) < 500:
            page_url = queue.pop(0)
            base = self._base_url(page_url)
            # sitemap.php queda fuera de _is_catalog_page, pero se permite como raíz.
            visit_key = base or page_url
            if visit_key in visited:
                continue
            visited.add(visit_key)
            try:
                response = self._http_get(session, page_url, source)
                tree = lxml_html.fromstring(response.content)
            except Exception as exc:
                _logger.info('Preiser: página no accesible %s: %s', page_url, exc)
                continue

            for link in self._catalog_links(tree, response.url):
                if link not in visited and link not in queue:
                    queue.append(link)

            for code, record in self._records_from_tree(tree, response.url).items():
                if code in products:
                    continue
                products[code] = {'url': record['url'], 'lastmod': False}
                images = self._images_for_article(tree, response.url, code)
                if images:
                    image_map[record['url']] = images
                if limit and len(products) >= limit:
                    return list(products.values()), image_map

        return list(products.values()), image_map

    @classmethod
    def _images_for_article(cls, tree, page_url, code):
        result = []
        compact = code.replace(' ', '')
        nodes = tree.xpath(
            '//*[contains(normalize-space(string(.)), $code) or '
            'contains(normalize-space(string(.)), $compact)]',
            code=code, compact=compact,
        )
        for node in nodes[:20]:
            for img in node.xpath('.//img[@src] | ancestor::*[position() <= 3]//img[@src]'):
                src = urljoin(page_url, img.get('src'))
                if src.startswith(('http://', 'https://')) and src not in result:
                    result.append(src)
        if not result:
            for value in tree.xpath('//meta[@property="og:image"]/@content'):
                src = urljoin(page_url, value)
                if src not in result:
                    result.append(src)
        return result[:8]

    def get_product_entries(self, source, category_filter=None, limit=0):
        entries, image_map = self._discover(source, limit=limit)
        self._preiser_image_map_cache = image_map
        if category_filter:
            needle = str(category_filter).casefold()
            entries = [entry for entry in entries if needle in entry['url'].casefold()]
        if not entries:
            raise ValueError(
                'No se encontraron referencias Preiser desde sitemap.php. '
                'La web publica páginas de catálogo con varios artículos, no fichas unitarias.'
            )
        return entries[:limit] if limit else entries

    def get_image_map(self, source):
        image_map = getattr(self, '_preiser_image_map_cache', None)
        if image_map is None:
            _entries, image_map = self._discover(source)
            self._preiser_image_map_cache = image_map
        return image_map

    @classmethod
    def _category(cls, heading, gauge, scale):
        segments = []
        text = cls._clean(heading)
        if gauge:
            segments.append(f'Escala {gauge}')
        elif scale:
            segments.append(f'Escala {scale}')
        lower = text.casefold()
        if 'merten' in lower:
            segments.append('Merten')
        elif 'elastolin' in lower:
            segments.append('Elastolin')
        elif 'military' in lower:
            segments.append('Military')
        elif 'automodell' in lower or 'vehicle' in lower:
            segments.append('Vehículos')
        elif 'zubehör' in lower or 'accessor' in lower:
            segments.append('Accesorios')
        elif 'miniatur' in lower or 'figur' in lower:
            segments.append('Figuras')
        else:
            segments.append('Catálogo')
        return segments

    def fetch_preview(self, source, url):
        code = self._article_from_url(url)
        page_url = self._base_url(url)
        if not code or not page_url:
            raise ValueError('La URL lógica de Preiser no contiene una referencia válida.')
        session = self._get_session(source)
        response = self._http_get(session, page_url, source)
        tree = lxml_html.fromstring(response.content)
        records = self._records_from_tree(tree, response.url)
        record = records.get(self._normalise_code(code))
        if not record:
            raise ValueError(
                f'La referencia {code} ya no aparece en la página de catálogo de Preiser.'
            )

        images = self._images_for_article(tree, response.url, code)
        heading = self._clean(record.get('heading') or record.get('page_title'))
        scale = record.get('scale')
        gauge = record.get('gauge')
        attributes = {
            'Fabricante': ['Preiser'],
            'Referencia fabricante': [code],
        }
        if gauge:
            attributes['Escala ferroviaria'] = [gauge]
        if scale:
            attributes['Escala'] = [scale]
        lower = heading.casefold()
        if 'unbemalt' in lower or 'unpainted' in lower:
            attributes['Acabado'] = ['Sin pintar']
        elif 'handbemalt' in lower or 'hand painted' in lower:
            attributes['Acabado'] = ['Pintado a mano']
        if 'bausatz' in lower or 'kit' in lower:
            attributes['Presentación'] = ['Kit']
        elif 'fertigmodell' in lower or 'ready-made' in lower:
            attributes['Presentación'] = ['Modelo terminado']

        logical = self._logical_url(response.url, code)
        category = self._category(heading, gauge, scale)
        description = heading if heading and heading != record['name'] else record['name']
        return {
            'name': record['name'],
            'description': description,
            'short_description': record['name'],
            'full_description': description,
            'attributes': attributes,
            # Preiser publica una lista de precios separada. No se toma ningún
            # importe de la página salvo que exista una relación inequívoca por
            # referencia; por seguridad esta primera integración no borra ni
            # sustituye precios manuales.
            'price': 0.0,
            'price_available': False,
            'currency': 'EUR',
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': logical,
            'style_code': code,
            'color_code': False,
            'category_path': ' / '.join(category),
            'ean_variants': [],
            'ean_complete': True,
        }
