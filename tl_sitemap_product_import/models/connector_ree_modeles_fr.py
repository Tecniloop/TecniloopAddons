import html
import re
from collections import deque
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from lxml import html as lxml_html
from odoo import models


class SitemapConnectorReeModelesFr(models.AbstractModel):
    """Conector del catálogo público de REE Modèles.

    REE no publica un sitemap XML de productos. El catálogo Joomla contiene páginas
    de familia que agrupan varias referencias. El conector recorre únicamente
    /catalogue/, detecta cada referencia y crea una URL virtual por artículo mediante
    el parámetro ``ree_ref``. De este modo cada referencia tiene staging y producto
    Odoo propios sin inventar variantes.
    """

    _name = 'sitemap.connector.ree_modeles_fr'
    _inherit = 'sitemap.import.service'
    _description = 'Conector REE Modèles Francia'

    _HOST = 'ree-modeles.com'
    _CATALOG_PREFIX = '/catalogue/'
    _REF_RE = re.compile(
        r'\b(?:R[ée]f(?:[ée]rence)?\.?|Ref(?:erence)?\.?)\s*[:.]?\s*'
        r'(?P<ref>[A-Z]{1,4}\s*-?\s*\d{2,4}(?:\s*(?:SAC|AC|S|DCC|DC))?)\b',
        re.I,
    )
    _ERA_RE = re.compile(r'\b(?:Ep\.?|Era|Epoque|Époque)\s*\.?\s*(I|II|III|IV|V|VI)\b', re.I)
    _SCALE_RE = re.compile(r'(?<!\w)(H0m|HOm|H0e|HOe|H0|HO|N)(?!\w)', re.I)
    _GTIN_RE = re.compile(r'\b(?:EAN|GTIN)\s*:?\s*(\d{8}|\d{12}|\d{13}|\d{14})\b', re.I)

    @classmethod
    def _clean(cls, value):
        return re.sub(r'\s+', ' ', html.unescape(str(value or '')).replace('\xa0', ' ')).strip()

    @classmethod
    def _normalise_ref(cls, value):
        value = cls._clean(value).upper().replace('–', '-').replace('—', '-')
        value = re.sub(r'\s*-\s*', '-', value)
        value = re.sub(r'\s+', ' ', value)
        # Sufijos comerciales separados: MB-154 S, MB-154 SAC, NW-032.
        match = re.match(r'^([A-Z]{1,4})-?(\d{2,4})(?:\s*(SAC|AC|S|DCC|DC))?$', value)
        if not match:
            return value
        base = f'{match.group(1)}-{match.group(2)}'
        return f'{base} {match.group(3)}' if match.group(3) else base

    @classmethod
    def _canonical_page(cls, value):
        parts = urlsplit(html.unescape(str(value or '')).strip())
        host = parts.netloc.casefold().removeprefix('www.')
        if host != cls._HOST:
            return False
        path = re.sub(r'/+', '/', parts.path or '/')
        if not path.startswith(cls._CATALOG_PREFIX):
            return False
        return urlunsplit(('https', cls._HOST, path.rstrip('/'), '', ''))

    @classmethod
    def _virtual_url(cls, page_url, reference):
        parts = urlsplit(page_url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode({'ree_ref': reference}), ''))

    @classmethod
    def _split_virtual_url(cls, value):
        parts = urlsplit(value)
        page = cls._canonical_page(urlunsplit((parts.scheme, parts.netloc, parts.path, '', '')))
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        reference = cls._normalise_ref(params.get('ree_ref')) if params.get('ree_ref') else False
        return page, reference

    @classmethod
    def _page_references(cls, tree):
        result = []
        # El texto visible es la fuente más estable del Joomla actual.
        for match in cls._REF_RE.finditer(cls._clean(' '.join(tree.xpath('//body//text()')))):
            reference = cls._normalise_ref(match.group('ref'))
            if reference and reference not in result:
                result.append(reference)
        return result

    def get_product_entries(self, source, category_filter=None, limit=0):
        session = self._get_session(source)
        # robots.txt es el punto de entrada solicitado; el catálogo real se descubre
        # desde la portada porque robots no declara Sitemap.
        self._http_get(session, source.sitemap_index_url, source)
        home_url = 'https://ree-modeles.com/'
        home = self._http_get(session, home_url, source)
        home_tree = lxml_html.fromstring(home.content)

        queue = deque()
        queued = set()
        for href in home_tree.xpath('//a/@href'):
            canonical = self._canonical_page(urljoin(home_url, href))
            if canonical and canonical not in queued:
                queue.append(canonical)
                queued.add(canonical)

        products = {}
        visited = set()
        needle = self._clean(category_filter).casefold()
        # Límite de seguridad: suficiente para el catálogo actual sin rastrear noticias,
        # fotos, PDFs, tienda externa o páginas institucionales.
        while queue and len(visited) < 500:
            page_url = queue.popleft()
            if page_url in visited:
                continue
            visited.add(page_url)
            response = self._http_get(session, page_url, source)
            tree = lxml_html.fromstring(response.content)

            for href in tree.xpath('//a/@href'):
                child = self._canonical_page(urljoin(page_url, href))
                if child and child not in queued and child not in visited:
                    queue.append(child)
                    queued.add(child)

            references = self._page_references(tree)
            if not references:
                continue
            page_text = self._clean(' '.join(tree.xpath('//h1//text() | //h2//text() | //title/text()')))
            if needle and needle not in f'{page_url} {page_text}'.casefold():
                continue
            for reference in references:
                virtual = self._virtual_url(page_url, reference)
                products.setdefault(virtual, {'url': virtual, 'lastmod': False})
                if limit and len(products) >= limit:
                    return list(products.values())

        if not products:
            raise ValueError(
                'No se encontraron referencias REE en las páginas públicas de /catalogue/. '
                'La estructura del catálogo puede haber cambiado.'
            )
        return list(products.values())

    def get_image_map(self, source):
        return {}

    @classmethod
    def _breadcrumbs(cls, tree):
        values = []
        for text in tree.xpath(
            '//*[contains(@class,"breadcrumb") or contains(@class,"breadcrumbs")]//a//text() | '
            '//*[contains(@class,"breadcrumb") or contains(@class,"breadcrumbs")]//span//text()'
        ):
            value = cls._clean(text)
            if value and value.casefold() not in {'accueil', 'home', 'catalogue'} and value not in values:
                values.append(value)
        return values

    @classmethod
    def _content_root(cls, tree):
        nodes = tree.xpath(
            '//main | //*[@itemprop="articleBody"] | '
            '//*[contains(@class,"item-page")] | //article'
        )
        return nodes[0] if nodes else tree

    @classmethod
    def _reference_segment(cls, root, reference):
        """Devuelve el texto alrededor de la referencia seleccionada.

        Las fichas no tienen una estructura de variante uniforme. Se linealiza el
        contenido principal y se corta entre la referencia actual y la siguiente.
        """
        text = cls._clean(' '.join(root.xpath('.//text()')))
        matches = list(cls._REF_RE.finditer(text))
        target_index = None
        for index, match in enumerate(matches):
            if cls._normalise_ref(match.group('ref')) == reference:
                target_index = index
                break
        if target_index is None:
            return text
        start = matches[target_index].start()
        end = matches[target_index + 1].start() if target_index + 1 < len(matches) else len(text)
        # Incluye un contexto anterior breve, normalmente nombre/livrea/época.
        previous_end = matches[target_index - 1].end() if target_index else 0
        context_start = max(previous_end, start - 350)
        return cls._clean(text[context_start:end])

    @classmethod
    def _images(cls, tree, page_url, reference):
        base_ref = reference.split()[0]
        candidates = tree.xpath(
            '//meta[@property="og:image"]/@content | '
            '//*[@itemprop="articleBody"]//img/@src | '
            '//*[contains(@class,"item-page")]//img/@src | '
            '//article//img/@src | '
            '//*[@itemprop="articleBody"]//a[contains(@href,"/images/")]/@href'
        )
        absolute = []
        for value in candidates:
            url = urljoin(page_url, str(value))
            folded = url.casefold()
            if not url.startswith('http') or any(token in folded for token in ('logo', 'banner', 'icon', 'header')):
                continue
            if url not in absolute:
                absolute.append(url)
        matching = [url for url in absolute if base_ref.replace('-', '').casefold() in re.sub(r'[^a-z0-9]', '', url.casefold())]
        return matching + [url for url in absolute if url not in matching]

    @classmethod
    def _name_from_segment(cls, segment, reference, page_title):
        cleaned = re.sub(
            r'\b(?:R[ée]f(?:[ée]rence)?\.?|Ref(?:erence)?\.?)\s*[:.]?\s*' + re.escape(reference) + r'\b',
            '', segment, flags=re.I,
        )
        cleaned = re.split(r'\s+(?:Réf\.?|Ref\.?)\s*[:.]?', cleaned, maxsplit=1, flags=re.I)[0]
        cleaned = cls._clean(cleaned).strip(' -–—:')
        # Evita nombres excesivamente largos por contenido trilingüe.
        if len(cleaned) > 220:
            cleaned = cleaned[-220:].lstrip(' -–—:')
        return cleaned or f'{page_title} - {reference}'

    def fetch_preview(self, source, url):
        page_url, reference = self._split_virtual_url(url)
        if not page_url or not reference:
            raise ValueError('La URL virtual de REE no contiene una página de catálogo y una referencia válidas.')

        response = self._http_get(self._get_session(source), page_url, source)
        tree = lxml_html.fromstring(response.content)
        root = self._content_root(tree)
        available_refs = self._page_references(tree)
        if reference not in available_refs:
            raise ValueError(f'La referencia REE {reference} ya no aparece en la ficha de origen.')

        title = self._clean(' '.join(tree.xpath('//h1[1]//text()'))) or self._clean(' '.join(tree.xpath('//title[1]/text()')))
        segment = self._reference_segment(root, reference)
        name = self._name_from_segment(segment, reference, title)
        breadcrumbs = self._breadcrumbs(tree)
        context = self._clean(' '.join([title, segment] + breadcrumbs))
        attrs = {'Marca': ['REE Modèles'], 'Referencia REE': [reference]}

        scale_match = self._SCALE_RE.search(context)
        if scale_match:
            scale = scale_match.group(1).upper().replace('HO', 'H0')
            attrs['Escala ferroviaria'] = [scale]
            numeric = {'H0': '1:87', 'H0M': '1:87', 'H0E': '1:87', 'N': '1:160'}.get(scale)
            if numeric:
                attrs['Escala'] = [numeric]

        era_match = self._ERA_RE.search(segment)
        if era_match:
            attrs['Época'] = [era_match.group(1).upper()]

        folded = segment.casefold()
        for token, label, value in (
            ('analogique', 'Sistema', 'Analógico'),
            ('analog', 'Sistema', 'Analógico'),
            ('dcc', 'Sistema digital', 'DCC'),
            ('sound', 'Sonido', 'Sí'),
            ('sonoris', 'Sonido', 'Sí'),
            ('ac 3 rails', 'Alimentación', 'AC 3 carriles'),
            ('3 rails', 'Alimentación', 'AC 3 carriles'),
            ('fumée', 'Generador de humo', 'Sí'),
            ('smoke', 'Generador de humo', 'Sí'),
            ('esu', 'Decoder', 'ESU'),
        ):
            if token in folded:
                attrs.setdefault(label, [])
                if value not in attrs[label]:
                    attrs[label].append(value)

        images = self._images(tree, page_url, reference)
        eans = []
        for gtin in self._GTIN_RE.findall(segment):
            normal = self._normalise_gtin(gtin)
            if normal:
                eans.append({
                    'ean': normal,
                    'sku': reference,
                    'label': name,
                    'external_variant_id': reference,
                })

        description = segment
        return {
            'name': name,
            'description': description,
            'short_description': description,
            'full_description': description,
            'attributes': attrs,
            'price': 0.0,
            'price_available': False,
            'currency': 'EUR',
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': self._virtual_url(page_url, reference),
            'style_code': reference,
            'color_code': False,
            'category_path': ' / '.join(['REE Modèles'] + breadcrumbs),
            'ean_variants': self._normalise_ean_variants(eans),
            'ean_complete': True,
        }
