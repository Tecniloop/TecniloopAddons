import base64
import logging
import time
from datetime import datetime
from urllib.parse import urlparse

import requests
from lxml import etree
from lxml import html as lxml_html

from odoo import fields, models

_logger = logging.getLogger(__name__)

SITEMAP_NS = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
IMAGE_NS = {'image': 'http://www.google.com/schemas/sitemap-image/1.1'}

IMAGE_MARKER = '[Sitemap Import]'


class SitemapImportService(models.AbstractModel):
    """Modelo base con la mecánica GENÉRICA compartida por todos los conectores: HTTP,
    robots.txt, parseo de XML de sitemaps, extracción de metaetiquetas de una página,
    resolución de categorías de Odoo y creación/actualización de productos.

    A propósito, este modelo NO decide qué sub-sitemaps son "de productos", ni con qué
    expresión regular se extrae el estilo/color, ni qué segmentos de la URL forman la
    categoría: cada sitio tiene su propia estructura y esas decisiones viven en su propio
    conector (sitemap.connector.*, ver models/connector_*.py), no aquí. Así, la estructura
    de un sitio nuevo -por muy distinta que sea- no obliga a retocar un sistema genérico de
    configuración, solo a escribir un conector pequeño y explícito.

    Un conector se registra como un modelo nuevo que hereda de este
    (_name = 'sitemap.connector.xxx', _inherit = 'sitemap.import.service') e implementa:
    - get_product_entries(source, category_filter=None, limit=0) -> [{'url','lastmod'}, ...]
    - get_image_map(source) -> {url_producto: [url_imagen, ...]}
    - fetch_preview(source, url) -> dict con name/description/price/currency/category_path/
      style_code/color_code/main_image_url/canonical_url
    """
    _name = 'sitemap.import.service'
    _description = 'Mecánica compartida de importación por sitemap (base para los conectores)'

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    def _get_session(self, source):
        session = requests.Session()
        session.headers.update({
            'User-Agent': source.user_agent or 'Mozilla/5.0 (compatible; OdooSitemapImporter/1.0)',
            'Accept-Language': 'es-ES,es;q=0.9',
        })
        return session

    def _http_get(self, session, url, source):
        _logger.debug('Sitemap import: GET %s', url)
        response = session.get(url, timeout=source.request_timeout or 20)
        response.raise_for_status()
        if source.request_delay:
            time.sleep(source.request_delay)
        return response

    # ------------------------------------------------------------------
    # robots.txt (parser propio: la librería estándar de Python no
    # interpreta correctamente los comodines "*" habituales en robots.txt,
    # p. ej. "Disallow: /carrito*" -> comprobado contra robots.txt reales)
    # ------------------------------------------------------------------
    def check_robots(self, source, sample_url):
        if not source.respect_robots_txt:
            return True
        parsed = urlparse(sample_url)
        robots_url = f'{parsed.scheme}://{parsed.netloc}/robots.txt'
        try:
            session = self._get_session(source)
            response = session.get(robots_url, timeout=source.request_timeout or 20)
            if response.status_code >= 400:
                return True  # sin robots.txt publicado -> se asume permitido
            allowed = self._robots_allowed(response.text, source.user_agent, sample_url)
            if not allowed:
                _logger.warning('Sitemap import: robots.txt no permite el acceso a %s', sample_url)
            return allowed
        except Exception as exc:
            _logger.warning('Sitemap import: no se pudo leer robots.txt (%s); se continúa por defecto', exc)
            return True

    @staticmethod
    def _robots_pattern_to_regex(pattern):
        import re
        end_anchor = pattern.endswith('$')
        if end_anchor:
            pattern = pattern[:-1]
        parts = []
        for token in re.split(r'(\*)', pattern):
            if token == '*':
                parts.append('.*')
            elif token:
                parts.append(re.escape(token))
        regex = '^' + ''.join(parts) + ('$' if end_anchor else '')
        return re.compile(regex)

    @staticmethod
    def _parse_robots(text):
        groups = []
        current_agents, current_rules = [], []
        seen_rule_in_group = False
        for raw_line in text.splitlines():
            line = raw_line.split('#', 1)[0].strip()
            if not line or ':' not in line:
                continue
            field, _, value = line.partition(':')
            field, value = field.strip().lower(), value.strip()
            if field == 'user-agent':
                if seen_rule_in_group:
                    groups.append((current_agents, current_rules))
                    current_agents, current_rules = [], []
                    seen_rule_in_group = False
                current_agents.append(value.lower())
            elif field in ('allow', 'disallow'):
                current_rules.append((field, value or None))
                seen_rule_in_group = True
        if current_agents:
            groups.append((current_agents, current_rules))
        return groups

    def _robots_allowed(self, robots_text, user_agent, url):
        groups = self._parse_robots(robots_text)
        ua = (user_agent or '*').lower()
        rules = None
        for agents, group_rules in groups:
            if any(a != '*' and a in ua for a in agents):
                rules = group_rules
                break
        if rules is None:
            for agents, group_rules in groups:
                if '*' in agents:
                    rules = group_rules
                    break
        if not rules:
            return True
        parsed = urlparse(url)
        path = parsed.path or '/'
        if parsed.query:
            path = f'{path}?{parsed.query}'
        best_len, best_allow = -1, True
        for rule_type, pattern in rules:
            if pattern is None:
                if rule_type == 'disallow' and 0 > best_len:
                    best_len, best_allow = 0, True
                continue
            if self._robots_pattern_to_regex(pattern).match(path):
                if len(pattern) > best_len:
                    best_len, best_allow = len(pattern), (rule_type == 'allow')
        return best_allow

    # ------------------------------------------------------------------
    # Mecánica XML genérica de sitemaps (sin decisiones específicas de sitio:
    # qué ficheros combinar lo decide cada conector, esto solo sabe leer UN
    # fichero de índice o UN urlset dado su URL)
    # ------------------------------------------------------------------
    def _fetch_sitemap_index_locs(self, source, index_url):
        """Dado un sitemap_index.xml, devuelve la lista de <loc> de sus sub-sitemaps."""
        session = self._get_session(source)
        response = self._http_get(session, index_url, source)
        root = etree.fromstring(response.content)
        return [el.text.strip() for el in root.findall('.//sm:sitemap/sm:loc', SITEMAP_NS) if el.text]

    def _fetch_urlset(self, source, sitemap_url):
        """Dado UN sitemap de URLs (urlset), devuelve sus entradas {'url','lastmod'}."""
        session = self._get_session(source)
        response = self._http_get(session, sitemap_url, source)
        root = etree.fromstring(response.content)
        entries = []
        for url_el in root.findall('.//sm:url', SITEMAP_NS):
            loc_el = url_el.find('sm:loc', SITEMAP_NS)
            if loc_el is None or not loc_el.text:
                continue
            lastmod_el = url_el.find('sm:lastmod', SITEMAP_NS)
            entries.append({
                'url': loc_el.text.strip(),
                'lastmod': self._parse_lastmod(lastmod_el.text if lastmod_el is not None else None),
            })
        return entries

    def _fetch_image_urlset(self, source, sitemap_url):
        """Dado UN sitemap de imágenes, devuelve {url_producto: [url_imagen, ...]}."""
        session = self._get_session(source)
        response = self._http_get(session, sitemap_url, source)
        root = etree.fromstring(response.content)
        image_map = {}
        for url_el in root.findall('.//sm:url', SITEMAP_NS):
            loc_el = url_el.find('sm:loc', SITEMAP_NS)
            if loc_el is None or not loc_el.text:
                continue
            loc = loc_el.text.strip()
            images = []
            for img_el in url_el.findall('image:image', IMAGE_NS):
                loc_img = img_el.find('image:loc', IMAGE_NS)
                if loc_img is not None and loc_img.text:
                    images.append(loc_img.text.strip())
            if images:
                image_map[loc] = images
        return image_map

    @staticmethod
    def _parse_lastmod(value):
        if not value:
            return False
        try:
            return datetime.strptime(value[:19], '%Y-%m-%dT%H:%M:%S')
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # Mecánica genérica de ficha de producto: SOLO extrae metaetiquetas
    # (Open Graph / Twitter Card), sin interpretar estilo/color/categoría
    # -eso es cada conector quien lo decide en su propio fetch_preview-.
    # ------------------------------------------------------------------
    def _fetch_og_meta(self, source, url):
        session = self._get_session(source)
        response = self._http_get(session, url, source)
        tree = lxml_html.fromstring(response.content)

        def meta(prop):
            values = tree.xpath(f'//meta[@property="{prop}"]/@content')
            if not values:
                values = tree.xpath(f'//meta[@name="{prop}"]/@content')
            return values[0].strip() if values else False

        canonical_els = tree.xpath('//link[@rel="canonical"]/@href')
        canonical_url = canonical_els[0].strip() if canonical_els else url

        title = meta('og:title')
        if not title:
            title_els = tree.xpath('//title/text()')
            title = title_els[0].split('|')[0].strip() if title_els else url

        description = meta('og:description') or meta('description') or ''
        price_str = meta('product:price:amount') or meta('og:price:amount') or '0'
        currency = meta('product:price:currency') or meta('og:price:currency') or 'EUR'
        image_url = meta('og:image')

        try:
            price = float(price_str)
        except (TypeError, ValueError):
            price = 0.0

        return {
            'name': title or url,
            'description': description,
            'price': price,
            'currency': currency,
            'main_image_url': image_url or False,
            'canonical_url': canonical_url,
        }

    # ------------------------------------------------------------------
    # Ganchos que CADA CONECTOR debe implementar (aquí solo hay una
    # implementación de respaldo que no rompe la importación, pero deja
    # estilo/color/categoría vacíos y avisa en el log).
    # ------------------------------------------------------------------
    def get_product_entries(self, source, category_filter=None, limit=0):
        _logger.warning(
            'Sitemap import: get_product_entries no implementado por el conector de "%s"', source.name)
        return []

    def get_image_map(self, source):
        _logger.warning('Sitemap import: get_image_map no implementado por el conector de "%s"', source.name)
        return {}

    def fetch_preview(self, source, url):
        _logger.warning('Sitemap import: fetch_preview no implementado por el conector de "%s"', source.name)
        data = self._fetch_og_meta(source, url)
        data.update({'category_path': '', 'style_code': False, 'color_code': False})
        return data

    # ------------------------------------------------------------------
    # Categorías (genérico: resuelve contra los modelos de Odoo y los
    # mapeos manuales de la fuente; no depende de la estructura del sitio)
    # ------------------------------------------------------------------
    def _get_root_category(self, source, category_field='internal'):
        if category_field == 'internal':
            Model = self.env['product.category']
            configured_root = source.root_category_id
        else:
            Model = self.env['product.public.category']
            configured_root = source.public_root_category_id
        if configured_root:
            return configured_root
        root = Model.search([('name', '=', source.name), ('parent_id', '=', False)], limit=1)
        return root or Model.create({'name': source.name})

    def _find_category_mapping(self, category_segments, category_field, source):
        target_field = 'product_category_id' if category_field == 'internal' else 'public_category_id'
        mappings = self.env['sitemap.category.mapping'].search([
            (target_field, '!=', False),
            ('source_id', '=', source.id),
        ])
        lower_segments = [s.lower() for s in category_segments]
        best_len, best_target = 0, None
        for mapping in mappings:
            mapping_segments = [s.strip() for s in (mapping.category_path or '').split('/') if s.strip()]
            n = len(mapping_segments)
            if not n or n > len(lower_segments):
                continue
            if [s.lower() for s in mapping_segments] == lower_segments[:n] and n > best_len:
                best_len, best_target = n, mapping[target_field]
        return best_target, best_len

    def _resolve_category_chain(self, category_segments, source, category_field='internal'):
        Model = self.env['product.category'] if category_field == 'internal' else self.env['product.public.category']
        mapped_target, consumed = self._find_category_mapping(category_segments, category_field, source)
        if mapped_target:
            parent, remaining = mapped_target, category_segments[consumed:]
        else:
            parent, remaining = self._get_root_category(source, category_field), category_segments
        for segment in remaining:
            existing = Model.search([('name', '=', segment), ('parent_id', '=', parent.id)], limit=1)
            parent = existing or Model.create({'name': segment, 'parent_id': parent.id})
        return parent

    # ------------------------------------------------------------------
    # Imágenes (genérico)
    # ------------------------------------------------------------------
    def _download_image(self, source, image_url):
        session = self._get_session(source)
        response = self._http_get(session, image_url, source)
        return response.content

    def _import_images(self, product_tmpl, data, image_urls, source):
        urls = list(image_urls) if image_urls else []
        main_url = data.get('main_image_url')
        if main_url and main_url not in urls:
            urls.insert(0, main_url)
        if not urls:
            return
        urls = urls[:max(source.max_images_per_product, 1)]

        try:
            main_bytes = self._download_image(source, urls[0])
            product_tmpl.image_1920 = base64.b64encode(main_bytes)
        except Exception as exc:
            _logger.warning('Sitemap import: no se pudo descargar la imagen principal %s: %s', urls[0], exc)

        old_images = self.env['product.image'].search([
            ('product_tmpl_id', '=', product_tmpl.id),
            ('name', 'like', IMAGE_MARKER),
        ])
        old_images.unlink()

        for index, extra_url in enumerate(urls[1:], start=1):
            try:
                img_bytes = self._download_image(source, extra_url)
                self.env['product.image'].create({
                    'product_tmpl_id': product_tmpl.id,
                    'name': f'{IMAGE_MARKER} {product_tmpl.name} ({index})',
                    'image_1920': base64.b64encode(img_bytes),
                })
            except Exception as exc:
                _logger.warning('Sitemap import: no se pudo descargar la imagen %s: %s', extra_url, exc)

    # ------------------------------------------------------------------
    # Orquestación (genérica: solo llama a los ganchos de arriba, así que
    # sirve igual para cualquier conector sin cambios)
    # ------------------------------------------------------------------
    def refresh_staging_row(self, staging_row, source, image_map=None, force=False):
        """Obtiene los datos LIGEROS de vista previa (nunca imágenes) para una fila de
        staging, usando el conector de 'source'.
        - Si la URL ya corresponde a un producto de Odoo (aprobada e importada antes -en OTRO
          lote, o en este mismo-), se aplica la actualización completa de inmediato -incluidas
          imágenes, vía import_staging_row- porque esa decisión ya se tomó.
        - Si no, se guardan solo los datos de vista previa (estado 'preview_ready') a la espera
          de selección manual."""
        if not staging_row.product_tmpl_id:
            linked = self.env['product.template'].search([('sitemap_source_url', '=', staging_row.url)], limit=1)
            if linked:
                staging_row.product_tmpl_id = linked.id

        if not force and staging_row.product_tmpl_id and staging_row.product_tmpl_id.sitemap_lastmod \
                and staging_row.sitemap_lastmod \
                and staging_row.product_tmpl_id.sitemap_lastmod >= staging_row.sitemap_lastmod:
            staging_row.write({'state': 'skipped', 'preview_date': fields.Datetime.now()})
            return

        try:
            data = self.fetch_preview(source, staging_row.url)
        except Exception as exc:
            _logger.exception('Sitemap import: error obteniendo vista previa de %s', staging_row.url)
            staging_row.write({
                'state': 'error', 'error_message': str(exc), 'preview_date': fields.Datetime.now(),
            })
            return

        staging_row.write({
            'name': data['name'],
            'list_price': data['price'],
            'currency_name': data['currency'],
            'category_path': data.get('category_path') or '',
            'style_code': data.get('style_code') or False,
            'color_code': data.get('color_code') or False,
            'description_preview': data['description'],
            'main_image_url': data['main_image_url'] or False,
            'preview_date': fields.Datetime.now(),
            'error_message': False,
        })

        if staging_row.product_tmpl_id:
            self.import_staging_row(staging_row, source, (image_map or {}).get(staging_row.url, []))
        else:
            staging_row.write({'state': 'preview_ready'})

    def import_staging_row(self, staging_row, source, image_urls):
        """Crea o actualiza el product.template a partir de los datos YA guardados en la fila
        de staging -no vuelve a descargar la ficha-. Es genérico: por este punto, todo lo que
        necesita ya es un simple diccionario de datos, sin decisiones específicas del sitio.
        Devuelve 'created', 'updated' o 'error'."""
        Product = self.env['product.template']
        existing = staging_row.product_tmpl_id or Product.search(
            [('sitemap_source_url', '=', staging_row.url)], limit=1)

        try:
            segments = staging_row.category_path.split('/') if staging_row.category_path else []
            category = self._resolve_category_chain(segments, source, 'internal')

            vals = {
                'name': staging_row.name or staging_row.url,
                'description_sale': staging_row.description_preview or '',
                'list_price': staging_row.list_price,
                'categ_id': category.id,
                'sitemap_source_id': source.id,
                'sitemap_source_url': staging_row.url,
                'sitemap_style_code': staging_row.style_code,
                'sitemap_color_code': staging_row.color_code,
                'sitemap_lastmod': staging_row.sitemap_lastmod,
                'sitemap_last_sync': fields.Datetime.now(),
                'is_sitemap_import_product': True,
                'sale_ok': source.sale_ok,
                'purchase_ok': source.purchase_ok,
                'active': True,
            }
            if source.product_tag_ids:
                vals['product_tag_ids'] = [(6, 0, source.product_tag_ids.ids)]

            if source.import_public_categories:
                public_category = self._resolve_category_chain(segments, source, 'public')
                previous_public = existing.sitemap_public_categ_id if existing else False
                commands = [(4, public_category.id, 0)]
                if previous_public and previous_public.id != public_category.id:
                    commands.insert(0, (3, previous_public.id, 0))
                vals['public_categ_ids'] = commands
                vals['sitemap_public_categ_id'] = public_category.id

            if existing:
                existing.write(vals)
                product_tmpl = existing
                result = 'updated'
            else:
                product_tmpl = Product.create(vals)
                result = 'created'

            if source.import_images:
                image_data = {'main_image_url': staging_row.main_image_url}
                self._import_images(product_tmpl, image_data, image_urls, source)

            staging_row.write({
                'state': 'imported',
                'result': result,
                'product_tmpl_id': product_tmpl.id,
                'imported_date': fields.Datetime.now(),
                'error_message': False,
            })
            return result
        except Exception as exc:
            _logger.exception('Sitemap import: error importando %s', staging_row.url)
            staging_row.write({'state': 'error', 'error_message': str(exc)})
            return 'error'
