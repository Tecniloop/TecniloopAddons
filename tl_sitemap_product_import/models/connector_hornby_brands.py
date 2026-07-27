import html
import logging
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

from lxml import html as lxml_html

from odoo import models

from .connector_jouef_uk import SitemapConnectorJouefUk

_logger = logging.getLogger(__name__)


class SitemapConnectorHornbyPlatformBase(models.AbstractModel):
    """Base reutilizable para las tiendas de la plataforma Hornby Hobbies.

    Las marcas comparten ``/products/<slug>-<referencia>``, bloques Product Info,
    What's Inside y Tech Specs, sitemaps, galería y estructura de precios. Las
    subclases solo declaran dominio, mercado EUR, categorías y atributos propios.
    """

    _name = 'sitemap.connector.hornby_platform_base'
    _inherit = 'sitemap.connector.jouef_uk'
    _description = 'Base común para marcas Hornby Hobbies'

    _BRAND_NAME = 'Hornby Hobbies'
    _HOST = False
    _EUR_HOSTS = ()
    _ROBOTS_URL = False
    _CATALOG_PATHS = ('/catalogue',)
    _DEFAULT_CATEGORY = ('Productos',)
    _USE_EUR_CURRENCY_SELECTOR = False
    _CURRENCY_QUERY_KEYS = ('currency', 'currency_code', 'cur')
    _PRODUCT_RE = re.compile(r'^/products/(?P<slug>[a-z0-9][a-z0-9-]*)/?$', re.IGNORECASE)
    _CODE_SUFFIX_RE = re.compile(
        r'-(?P<code>(?:bundle)?[a-z]{1,10}[a-z0-9]{1,24})$', re.IGNORECASE,
    )
    _INFO_HEADINGS = (
        'Información del producto', 'Product information', 'Product Info',
        'Produktinformationen', 'Produktinfo', 'Informazioni sul prodotto',
        'Informazioni prodotto', 'Descrizione del prodotto',
    )
    _CONTENTS_HEADINGS = (
        'Qué contiene', 'Que contiene', "What's inside", 'Contents',
        'Packungsinhalt', 'Was ist drin?', 'Contenuto della confezione',
        'Cosa contiene',
    )
    _TECH_HEADINGS = (
        'Especificaciones técnicas', 'Especificaciones tecnicas',
        'Technical specifications', 'Tech Specs', 'Technische Daten',
        'Technische Spezifikationen', 'Specifiche tecniche', 'Dati tecnici',
    )
    _CATEGORY_MAP = {}
    _DESCRIPTION_STOPPERS = set(SitemapConnectorJouefUk._DESCRIPTION_STOPPERS) | {
        'technische daten', 'technische spezifikationen', 'was ist drin?',
        'empfohlen für sie', 'rezensionen', 'menge',
        'specifiche tecniche', 'dati tecnici', 'cosa contiene',
        'consigliati per te', 'recensioni', 'quantità',
    }
    _SPEC_STOPPERS = set(SitemapConnectorJouefUk._SPEC_STOPPERS) | {
        'sicherheitshinweise', 'rezensionen', 'kundenservice', 'menge',
        'avvertenze di sicurezza', 'recensioni', 'assistenza clienti', 'quantità',
    }
    _SPEC_NAME_MAP = dict(SitemapConnectorJouefUk._SPEC_NAME_MAP)
    _SPEC_NAME_MAP.update({
        'item length - without packaging (cm)': 'Longitud sin embalaje (cm)',
        'item height - without packaging (cm)': 'Altura sin embalaje (cm)',
        'item width - without packaging (cm)': 'Anchura sin embalaje (cm)',
        'item weight - without packaging (kg)': 'Peso sin embalaje',
        'package length': 'Longitud del embalaje',
        'package height': 'Altura del embalaje',
        'package width': 'Anchura del embalaje',
        'package weight': 'Peso del embalaje',
        'number of parts': 'Número de piezas',
        'how many pieces will be found in the box opened by the customer?': 'Número de piezas',
        'skill level': 'Nivel de dificultad',
        'finish': 'Acabado',
        'colour': 'Color',
        'color': 'Color',
        'license': 'Licencia',
        'license line': 'Licencia',
        'contents (what\'s in the box) sets': 'Contenido',
        'age suitability': 'Edad recomendada',
        'product status': 'Estado del producto',
    })

    def _get_session(self, source):
        session = super()._get_session(source)
        session.headers.update({
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.7,de;q=0.5,it;q=0.5',
        })
        return session

    @classmethod
    def _canonical_url(cls, value):
        raw = html.unescape(str(value or '')).strip().replace('\\/', '/')
        if not raw:
            return False
        parts = urlsplit(raw)
        host = parts.netloc.casefold()
        if host.startswith('www.'):
            host = host[4:]
        path = re.sub(r'/+', '/', parts.path or '/')
        if path != '/':
            path = path.rstrip('/')
        return urlunsplit((parts.scheme or 'https', host, path, '', ''))

    def _candidate_sitemaps(self, source):
        candidates = []
        session = self._get_session(source)
        for candidate in (
            source.sitemap_index_url,
            self._ROBOTS_URL or (f'https://{self._HOST}/robots.txt' if self._HOST else False),
        ):
            if not candidate or candidate in candidates:
                continue
            try:
                response = session.get(
                    candidate,
                    timeout=source.request_timeout or 20,
                    allow_redirects=True,
                )
                if response.status_code >= 400:
                    continue
                candidates.extend(self._robots_sitemaps(response.text, response.url))
                payload = response.content.lstrip()
                if payload.startswith((b'<?xml', b'<urlset', b'<sitemapindex')) or payload[:2] == b'\x1f\x8b':
                    candidates.insert(0, response.url)
            except Exception as exc:
                _logger.info('%s: no se pudo consultar %s: %s', self._BRAND_NAME, candidate, exc)
        if self._HOST:
            candidates.extend([
                f'https://{self._HOST}/sitemap.xml',
                f'https://{self._HOST}/sitemap_index.xml',
                f'https://{self._HOST}/sitemapindex.xml',
            ])
        return list(dict.fromkeys(candidates))

    def _fallback_catalog_entries(self, source, limit=0):
        start_urls = [urljoin(f'https://{self._HOST}', path) for path in self._CATALOG_PATHS]
        queue = list(start_urls)
        visited = set()
        products = {}
        session = self._get_session(source)

        while queue and len(visited) < 450:
            page_url = queue.pop(0)
            if page_url in visited:
                continue
            visited.add(page_url)
            try:
                response = self._http_get(session, page_url, source)
                tree = lxml_html.fromstring(response.content)
            except Exception as exc:
                _logger.info('%s: catálogo no accesible %s: %s', self._BRAND_NAME, page_url, exc)
                continue

            for product_url in self._product_links_from_tree(tree, response.url):
                key = self._product_key(product_url)
                if key and key not in products:
                    products[key] = {'url': product_url, 'lastmod': False}
            if limit and len(products) >= limit:
                break

            for href in tree.xpath('//a[@href]/@href'):
                absolute = urljoin(response.url, href)
                parts = urlsplit(absolute)
                host = parts.netloc.casefold().removeprefix('www.')
                if host != self._HOST:
                    continue
                if not any(parts.path.startswith(path.rstrip('/')) for path in self._CATALOG_PATHS):
                    continue
                clean = urlunsplit((parts.scheme or 'https', host, parts.path, parts.query, ''))
                if clean not in visited and clean not in queue:
                    queue.append(clean)

        return list(products.values())

    @classmethod
    def _clean_breadcrumbs(cls, values, product_name):
        cleaned = super()._clean_breadcrumbs(values, product_name)
        brand_fold = cls._normalise_text(cls._BRAND_NAME).casefold()
        host_brand = cls._normalise_text((cls._HOST or '').split('.', 1)[0]).casefold()
        return [
            value for value in cleaned
            if cls._normalise_text(value).casefold() not in {brand_fold, host_brand}
        ]

    @classmethod
    def _translate_categories(cls, values):
        result = []
        for value in values or []:
            cleaned = cls._normalise_text(value)
            if not cleaned:
                continue
            mapped = cls._CATEGORY_MAP.get(cleaned.casefold(), cleaned)
            if mapped and mapped not in result:
                result.append(mapped)
        return result

    @classmethod
    def _spec_attributes(cls, lines):
        attributes = {}
        spec_lines = cls._section_lines(lines, cls._TECH_HEADINGS, cls._SPEC_STOPPERS)
        if not spec_lines:
            return attributes

        def add(name, value):
            name = cls._normalise_text(name)
            value = cls._normalise_text(value)
            if not name or not value:
                return
            yes_no = {
                'yes': 'Sí', 'ja': 'Sí', 'sì': 'Sí', 'si': 'Sí',
                'no': 'No', 'nein': 'No',
            }
            value = yes_no.get(value.casefold(), value)
            attributes.setdefault(name, [])
            if value not in attributes[name]:
                attributes[name].append(value)

        index = 0
        while index < len(spec_lines):
            raw_label = cls._normalise_text(spec_lines[index]).strip(' :')
            mapped = cls._SPEC_NAME_MAP.get(raw_label.casefold())
            if not mapped or index + 1 >= len(spec_lines):
                index += 1
                continue
            raw_value = cls._normalise_text(spec_lines[index + 1]).strip(' :')
            if raw_value.casefold() in cls._SPEC_NAME_MAP:
                index += 1
                continue
            if mapped == 'Escala':
                scale = cls._SCALE_RE.search(raw_value)
                if scale:
                    add('Escala', f'1:{int(scale.group(1))}')
                gauge = cls._GAUGE_RE.search(raw_value)
                if gauge:
                    add('Escala ferroviaria', gauge.group(1).upper().replace('HO', 'H0'))
                if not scale:
                    add(mapped, raw_value)
            else:
                add(mapped, raw_value)
            index += 2
        return attributes

    @classmethod
    def _inferred_category(cls, name, product_type=False):
        return list(cls._DEFAULT_CATEGORY)

    def _eur_selector_responses(self, source, session, product_url):
        """Prueba los mecanismos públicos habituales del selector de moneda Hornby.

        No hay conversión. Solo se acepta una respuesta que publique un precio en EUR.
        Las variantes se mantienen porque la implementación del selector puede cambiar
        entre marcas o versiones de la plataforma.
        """
        raw = self._canonical_url(product_url)
        if not raw:
            return []
        candidates = [raw]
        parts = urlsplit(raw)
        for key in self._CURRENCY_QUERY_KEYS:
            query = dict(parse_qsl(parts.query, keep_blank_values=True))
            query[key] = 'EUR'
            candidates.append(urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), '')))

        responses = []
        original_cookies = session.cookies.copy()
        for cookie_name in ('currency', 'Currency', 'selected_currency', 'selectedCurrency', 'store_currency'):
            session.cookies.set(cookie_name, 'EUR', domain=self._HOST)
        headers = {'X-Currency': 'EUR', 'X-Requested-Currency': 'EUR'}
        try:
            for candidate in dict.fromkeys(candidates):
                try:
                    response = session.get(
                        candidate,
                        timeout=source.request_timeout or 20,
                        allow_redirects=True,
                        headers=headers,
                    )
                    response.raise_for_status()
                    if source.request_delay:
                        import time
                        time.sleep(source.request_delay)
                    responses.append(response)
                except Exception as exc:
                    _logger.info('%s: selector EUR no disponible en %s: %s', self._BRAND_NAME, candidate, exc)
        finally:
            session.cookies.clear()
            session.cookies.update(original_cookies)
        return responses

    def _official_eur_price(self, source, session, product_url, expected_code, existing_response=None):
        if self._EUR_HOSTS:
            return self._hornby_official_eur_price(
                source=source,
                session=session,
                product_url=product_url,
                expected_code=expected_code,
                eur_hosts=self._EUR_HOSTS,
                existing_response=existing_response,
                code_getter=self._code_from_product_url,
                price_parser=lambda tree, lines, product_node, name: self._price_from_page(
                    tree, lines, product_node, name,
                    default_currency='EUR',
                    price_pattern=self._EUR_PRICE_RE,
                ),
                brand_name=self._BRAND_NAME,
            )

        if not self._USE_EUR_CURRENCY_SELECTOR:
            return 0.0, 'EUR', False

        for response in self._eur_selector_responses(source, session, product_url):
            canonical = self._canonical_url(response.url)
            if not self._product_match(canonical):
                continue
            response_code = self._code_from_product_url(canonical)
            if expected_code and response_code and response_code.upper() != str(expected_code).upper():
                continue
            try:
                tree = lxml_html.fromstring(getattr(response, 'text', None) or response.content)
                lines = self._visible_lines(tree)
                payloads = self._json_payloads(tree)
                product_node = self._product_json_node(payloads)
                name = self._normalise_text(product_node.get('name')) if isinstance(product_node, dict) else ''
                if not name:
                    name = self._normalise_text(' '.join(tree.xpath('//h1//text()')))
                price, currency, available = self._price_from_page(
                    tree, lines, product_node, name,
                    default_currency='EUR', price_pattern=self._EUR_PRICE_RE,
                )
                if available and price > 0 and str(currency).upper() in {'EUR', '€'}:
                    return price, 'EUR', True
            except Exception as exc:
                _logger.info('%s: no se pudo interpretar el precio EUR de %s: %s', self._BRAND_NAME, response.url, exc)
        return 0.0, 'EUR', False

    def fetch_preview(self, source, url):
        canonical_requested = self._canonical_url(url)
        session = self._get_session(source)
        response = self._http_get(session, canonical_requested, source)
        canonical_response = self._canonical_url(response.url)
        if not self._product_match(canonical_response):
            raise ValueError(
                f'{self._BRAND_NAME} redirigió la ficha a una página que no es un producto: '
                f'{response.url}'
            )

        tree = lxml_html.fromstring(getattr(response, 'text', None) or response.content)
        lines = self._visible_lines(tree)
        payloads = self._json_payloads(tree)
        product_node = self._product_json_node(payloads)

        name = self._normalise_text(product_node.get('name')) if isinstance(product_node, dict) else ''
        if not name:
            name = self._normalise_text(' '.join(tree.xpath('//h1//text()')))
        if not name:
            name = self._normalise_text(
                (tree.xpath('//meta[@property="og:title" or @name="og:title"]/@content') or [''])[0]
            )
        if not name:
            raise ValueError(f'La ficha de {self._BRAND_NAME} no contiene un nombre de producto.')

        style_code = self._item_code(tree, lines, product_node, canonical_response)
        # En la plataforma Hornby el H1/JSON-LD puede omitir la referencia.
        # El nombre comercial en Odoo debe conservarla para identificar bien
        # productos y recambios: "HK105-U-01 Huracan Dashboard extension".
        if style_code:
            code_fold = self._normalise_text(style_code).casefold()
            name_fold = self._normalise_text(name).casefold()
            if not name_fold.startswith(code_fold):
                name = self._normalise_text(f'{style_code} {name}')

        price, currency, price_available = self._official_eur_price(
            source, session, canonical_response, style_code, existing_response=response,
        )

        meta_description = self._normalise_text(
            (tree.xpath('//meta[@property="og:description" or @name="description"]/@content') or [''])[0]
        )
        json_description = self._normalise_text(product_node.get('description')) if isinstance(product_node, dict) else ''
        info_lines = self._section_lines(lines, self._INFO_HEADINGS, self._DESCRIPTION_STOPPERS)
        while info_lines and info_lines[0].casefold() == name.casefold():
            info_lines.pop(0)
        contains_lines = self._section_lines(
            lines, self._CONTENTS_HEADINGS,
            set(self._TECH_HEADINGS) | {'recommended for you', 'recomendado para ti', 'reviews', 'comentarios', 'quantity', 'cantidad'},
        )
        full_description = self._section_html(info_lines)
        if contains_lines:
            full_description += self._section_html(contains_lines, title='Contenido')
        short_description = json_description or meta_description
        if not short_description and info_lines:
            short_description = info_lines[0]
        description = '\n'.join(info_lines) or short_description or name

        attributes = self._spec_attributes(lines)
        product_type = self._product_type(lines, name)
        if product_type:
            attributes.setdefault('Tipo de producto', [])
            if product_type not in attributes['Tipo de producto']:
                attributes['Tipo de producto'].append(product_type)

        breadcrumbs = self._breadcrumb_json(payloads, name) or self._dom_breadcrumbs(tree, name)
        category_segments = self._translate_categories(breadcrumbs) if breadcrumbs else self._inferred_category(name, product_type)
        category_segments = self._sanitize_product_category_segments(
            category_segments, product_name=name, style_code=style_code, url=canonical_response,
        )
        if not category_segments:
            category_segments = list(self._DEFAULT_CATEGORY)

        images = self._images_from_product(tree, product_node, canonical_response, name, style_code)
        ean_variants = self._ean_variants_from_html_content(response.content)

        return {
            'name': name,
            'description': description,
            'short_description': short_description or description,
            'full_description': full_description or html.escape(description),
            'price': price,
            'price_available': price_available,
            'currency': currency or 'EUR',
            'category_path': '/'.join(category_segments),
            'style_code': style_code,
            'color_code': False,
            'attributes': attributes,
            'main_image_url': images[0] if images else False,
            'image_urls': images,
            'canonical_url': canonical_response,
            'ean_variants': ean_variants,
        }


class SitemapConnectorArnoldDe(models.AbstractModel):
    _name = 'sitemap.connector.arnold_de'
    _inherit = 'sitemap.connector.hornby_platform_base'
    _description = 'Conector Arnold Europa'
    _BRAND_NAME = 'Arnold'
    _HOST = 'de.arnoldmodel.com'
    _EUR_HOSTS = ('de.arnoldmodel.com',)
    _ROBOTS_URL = 'https://de.arnoldmodel.com/robots.txt'
    _CATALOG_PATHS = ('/catalogue', '/catalogue/trains-train-sets', '/catalogue/n-scale', '/catalogue/tt-scale')
    _DEFAULT_CATEGORY = ('Modelismo ferroviario', 'Arnold')
    _CATEGORY_MAP = {
        'züge und zugsets': 'Trenes y sets', 'lokomotiven': 'Locomotoras',
        'wagen und wagenpakete': 'Vagones y coches', 'ersatzteile': 'Repuestos',
        'gleis und leistung': 'Vías y alimentación', 'gebäude und zubehör': 'Edificios y accesorios',
        'epoche': 'Época', 'n scale': 'Escala N', 'tt scale': 'Escala TT',
    }
    _SPEC_NAME_MAP = dict(SitemapConnectorHornbyPlatformBase._SPEC_NAME_MAP)
    _SPEC_NAME_MAP.update({
        'spur': 'Escala ferroviaria', 'farbe': 'Color', 'epoche': 'Época',
        'dcc-status': 'DCC', 'minimale kurve (mm)': 'Curva mínima',
        'mit schwungmasse ausgerüstet': 'Con volante de inercia',
        'stromabnehmer': 'Pantógrafo', 'kurzkupplungskinematik': 'Enganche corto',
        'gehäuse aus metall': 'Carrocería metálica', 'innenbeleuchtung': 'Luz interior',
        'federpuffer': 'Topes con resorte', 'lackierung (logo)': 'Compañía ferroviaria',
    })


class SitemapConnectorRivarossiIt(models.AbstractModel):
    _name = 'sitemap.connector.rivarossi_it'
    _inherit = 'sitemap.connector.hornby_platform_base'
    _description = 'Conector Rivarossi Europa'
    _BRAND_NAME = 'Rivarossi'
    _HOST = 'it.rivarossi.com'
    _EUR_HOSTS = ('it.rivarossi.com',)
    _ROBOTS_URL = 'https://it.rivarossi.com/robots.txt'
    _CATALOG_PATHS = ('/catalogo', '/catalogo/treni-sets', '/catalogo/accessori-alimentazione', '/catalogo/fabbricati-materiale-per-plastici')
    _DEFAULT_CATEGORY = ('Modelismo ferroviario', 'Rivarossi')
    _CATEGORY_MAP = {
        'treni e set di treni': 'Trenes y sets', 'locomotive': 'Locomotoras',
        'carrozze': 'Coches de viajeros', 'carri': 'Vagones', 'set': 'Sets',
        'accessori e alimentazione': 'Vías y alimentación',
        'fabbricati e materiale per plastici': 'Edificios y accesorios',
        'ricambi': 'Repuestos', 'pubblicazioni e cataloghi': 'Publicaciones y catálogos',
    }
    _SPEC_NAME_MAP = dict(SitemapConnectorHornbyPlatformBase._SPEC_NAME_MAP)
    _SPEC_NAME_MAP.update({
        'scala': 'Escala', 'scartamento': 'Escala ferroviaria', 'colore': 'Color',
        'epoca': 'Época', 'stato dcc': 'DCC', 'curva minima (mm)': 'Curva mínima',
        'motore': 'Motor', 'volano': 'Con volante de inercia', 'pantografo': 'Pantógrafo',
        'aggancio corto': 'Enganche corto', 'carrozzeria in metallo': 'Carrocería metálica',
        'illuminazione interna': 'Luz interior', 'luci': 'Luces',
        'respingenti molleggiati': 'Topes con resorte', 'livrea': 'Compañía ferroviaria',
    })


class SitemapConnectorLimaIt(models.AbstractModel):
    _name = 'sitemap.connector.lima_it'
    _inherit = 'sitemap.connector.rivarossi_it'
    _description = 'Conector Lima Europa'
    _BRAND_NAME = 'Lima'
    _HOST = 'it.limamodel.it'
    _EUR_HOSTS = ('it.limamodel.it',)
    _ROBOTS_URL = 'https://it.limamodel.it/robots.txt'
    _CATALOG_PATHS = ('/catalogo', '/catalogo/treni-sets', '/catalogo/accessori-alimentazione')
    _DEFAULT_CATEGORY = ('Modelismo ferroviario', 'Lima')


class SitemapConnectorPocherUk(models.AbstractModel):
    _name = 'sitemap.connector.pocher_uk'
    _inherit = 'sitemap.connector.hornby_platform_base'
    _description = 'Conector Pocher Europa'
    _BRAND_NAME = 'Pocher'
    _HOST = 'uk.pocher.com'
    _ROBOTS_URL = 'https://uk.pocher.com/robots.txt'
    _CATALOG_PATHS = ('/catalogue', '/catalogue/large-scale-model-kits', '/catalogue/accessories')
    _DEFAULT_CATEGORY = ('Modelismo', 'Pocher')
    _USE_EUR_CURRENCY_SELECTOR = True
    _CATEGORY_MAP = {
        'large model scale kits': 'Kits de gran escala', 'cars': 'Automóviles',
        'motorcycles': 'Motocicletas', 'engines': 'Motores', 'accessories': 'Accesorios',
        'display cases': 'Vitrinas', 'merchandise': 'Merchandising', 'exclusives': 'Exclusivos',
    }

    @classmethod
    def _inferred_category(cls, name, product_type=False):
        text = f'{name} {product_type or ""}'.casefold()
        if 'display case' in text or 'vitrina' in text:
            return ['Modelismo', 'Pocher', 'Accesorios', 'Vitrinas']
        if any(token in text for token in ('motorcycle', 'ducati', 'moto')):
            return ['Modelismo', 'Pocher', 'Kits de gran escala', 'Motocicletas']
        if 'engine' in text or 'motor ' in text:
            return ['Modelismo', 'Pocher', 'Kits de gran escala', 'Motores']
        if any(token in text for token in ('porsche', 'pagani', 'ferrari', 'car ', 'coche')):
            return ['Modelismo', 'Pocher', 'Kits de gran escala', 'Automóviles']
        return list(cls._DEFAULT_CATEGORY)


class SitemapConnectorHornbyUk(models.AbstractModel):
    _name = 'sitemap.connector.hornby_uk'
    _inherit = 'sitemap.connector.hornby_platform_base'
    _description = 'Conector Hornby Europa'
    _BRAND_NAME = 'Hornby'
    _HOST = 'uk.hornby.com'
    _ROBOTS_URL = 'https://uk.hornby.com/robots.txt'
    _CATALOG_PATHS = ('/catalogue', '/catalogue/trains-sets', '/catalogue/track-power', '/catalogue/buildings-accessories')
    _DEFAULT_CATEGORY = ('Modelismo ferroviario', 'Hornby')
    _USE_EUR_CURRENCY_SELECTOR = True


class SitemapConnectorAirfixUk(models.AbstractModel):
    _name = 'sitemap.connector.airfix_uk'
    _inherit = 'sitemap.connector.hornby_platform_base'
    _description = 'Conector Airfix Europa'
    _BRAND_NAME = 'Airfix'
    _HOST = 'uk.airfix.com'
    _ROBOTS_URL = 'https://uk.airfix.com/robots.txt'
    _CATALOG_PATHS = ('/catalogue', '/catalogue/aircraft', '/catalogue/military-vehicles', '/catalogue/cars', '/catalogue/ships', '/catalogue/space', '/catalogue/figures', '/catalogue/gift-sets')
    _DEFAULT_CATEGORY = ('Modelismo', 'Airfix')
    _USE_EUR_CURRENCY_SELECTOR = True
    _CATEGORY_MAP = {
        'aircraft': 'Aeronaves', 'military vehicles': 'Vehículos militares',
        'cars': 'Automóviles', 'ships': 'Barcos', 'space': 'Espacio',
        'figures': 'Figuras', 'gift sets': 'Sets de regalo', 'starter sets': 'Sets de iniciación',
        'vintage classics': 'Vintage Classics', 'accessories': 'Accesorios',
    }
    _SPEC_NAME_MAP = dict(SitemapConnectorHornbyPlatformBase._SPEC_NAME_MAP)
    _SPEC_NAME_MAP.update({
        'parts included': 'Número de piezas', 'scheme options': 'Opciones de decoración',
        'wingspan (mm)': 'Envergadura', 'flying hours': 'Flying Hours',
    })

    @classmethod
    def _inferred_category(cls, name, product_type=False):
        text = f'{name} {product_type or ""}'.casefold()
        groups = (
            (('aircraft', 'spitfire', 'messerschmitt', 'helicopter', 'avión', 'aeroplane'), 'Aeronaves'),
            (('tank', 'military vehicle', 'armoured', 'tanque'), 'Vehículos militares'),
            (('ship', 'boat', 'submarine', 'barco', 'hovercraft'), 'Barcos'),
            (('car ', 'automobile', 'ford ', 'jaguar ', 'aston martin'), 'Automóviles'),
            (('space', 'rocket', 'apollo', 'satellite'), 'Espacio'),
            (('figure', 'soldier'), 'Figuras'),
            (('starter set', 'gift set', 'bundle'), 'Sets'),
        )
        for tokens, label in groups:
            if any(token in text for token in tokens):
                return ['Modelismo', 'Airfix', label]
        return list(cls._DEFAULT_CATEGORY)


class SitemapConnectorCorgiUk(models.AbstractModel):
    _name = 'sitemap.connector.corgi_uk'
    _inherit = 'sitemap.connector.hornby_platform_base'
    _description = 'Conector Corgi y Corgi Premiums Europa'
    _BRAND_NAME = 'Corgi'
    _HOST = 'uk.corgi.co.uk'
    _ROBOTS_URL = 'https://uk.corgi.co.uk/robots.txt'
    _CATALOG_PATHS = ('/catalogue', '/catalogue/die-cast-models', '/catalogue/aviation', '/catalogue/pop-culture')
    _DEFAULT_CATEGORY = ('Coleccionismo', 'Corgi')
    _USE_EUR_CURRENCY_SELECTOR = True
    _CATEGORY_MAP = {
        'aviation': 'Aviación', 'cars': 'Automóviles', 'vehicles': 'Vehículos',
        'pop culture': 'Cultura popular', 'tv and film': 'Televisión y cine',
        'military': 'Militar', 'buses': 'Autobuses', 'corgi toys': 'Corgi Toys',
        'corgi premiums': 'Corgi Premiums', 'accessories': 'Accesorios',
    }

    @classmethod
    def _inferred_category(cls, name, product_type=False):
        text = f'{name} {product_type or ""}'.casefold()
        if any(token in text for token in ('aircraft', 'spitfire', 'eurofighter', 'aviation', 'helicopter')):
            return ['Coleccionismo', 'Corgi', 'Aviación']
        if any(token in text for token in ('thunderbirds', 'batman', 'batmobile', 'star trek', 'tv ', 'film')):
            return ['Coleccionismo', 'Corgi', 'Televisión y cine']
        if any(token in text for token in ('bus', 'coach')):
            return ['Coleccionismo', 'Corgi', 'Autobuses']
        if any(token in text for token in ('tank', 'military')):
            return ['Coleccionismo', 'Corgi', 'Militar']
        return ['Coleccionismo', 'Corgi', 'Vehículos']


class SitemapConnectorHumbrolUk(models.AbstractModel):
    _name = 'sitemap.connector.humbrol_uk'
    _inherit = 'sitemap.connector.hornby_platform_base'
    _description = 'Conector Humbrol Europa'
    _BRAND_NAME = 'Humbrol'
    _HOST = 'uk.humbrol.com'
    _ROBOTS_URL = 'https://uk.humbrol.com/robots.txt'
    _CATALOG_PATHS = ('/catalogue', '/catalogue/paints', '/catalogue/tools', '/catalogue/adhesives', '/catalogue/accessories')
    _DEFAULT_CATEGORY = ('Modelismo', 'Humbrol')
    _USE_EUR_CURRENCY_SELECTOR = True
    _SPEC_NAME_MAP = dict(SitemapConnectorHornbyPlatformBase._SPEC_NAME_MAP)
    _SPEC_NAME_MAP.update({
        'product volume in millilitres (if applicable)': 'Volumen',
        'finish': 'Acabado', 'application': 'Aplicación', 'drying time': 'Tiempo de secado',
        'how to clean': 'Limpieza', 'substrate': 'Superficies compatibles',
    })

    @classmethod
    def _inferred_category(cls, name, product_type=False):
        text = f'{name} {product_type or ""}'.casefold()
        if any(token in text for token in ('enamel', 'acrylic', 'paint', 'tinlet', 'dropper', 'pintura')):
            return ['Modelismo', 'Humbrol', 'Pinturas']
        if any(token in text for token in ('thinner', 'diluyente')):
            return ['Modelismo', 'Humbrol', 'Diluyentes']
        if any(token in text for token in ('adhesive', 'glue', 'cement', 'pegamento')):
            return ['Modelismo', 'Humbrol', 'Adhesivos']
        if any(token in text for token in ('brush', 'tool', 'cutter', 'palette', 'airbrush')):
            return ['Modelismo', 'Humbrol', 'Herramientas']
        if any(token in text for token in ('weathering', 'pigment')):
            return ['Modelismo', 'Humbrol', 'Envejecido y efectos']
        if any(token in text for token in ('3d', 'filament', 'printer')):
            return ['Modelismo', 'Humbrol', 'Impresión 3D']
        return list(cls._DEFAULT_CATEGORY)


class SitemapConnectorBassettLowkeUk(models.AbstractModel):
    _name = 'sitemap.connector.bassett_lowke_uk'
    _inherit = 'sitemap.connector.hornby_platform_base'
    _description = 'Conector Bassett-Lowke Europa'
    _BRAND_NAME = 'Bassett-Lowke'
    _HOST = 'uk.bassettlowke.co.uk'
    _ROBOTS_URL = 'https://uk.bassettlowke.co.uk/robots.txt'
    _CATALOG_PATHS = ('/catalogue',)
    _DEFAULT_CATEGORY = ('Modelismo ferroviario', 'Bassett-Lowke')
    _USE_EUR_CURRENCY_SELECTOR = True
