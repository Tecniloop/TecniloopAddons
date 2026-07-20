import logging
from urllib.parse import urlparse

from lxml import html as lxml_html

from odoo import models

_logger = logging.getLogger(__name__)


class SitemapConnectorPrestashopBase(models.AbstractModel):
    """Base comun para conectores PrestaShop.

    Centraliza la fusion multifuente, la deduplicacion por id de producto,
    la extraccion escalonada y la validacion minima de las vistas previas.
    Los conectores concretos conservan sus patrones de URL, categorias,
    atributos y enriquecimientos de variantes.
    """

    _name = 'sitemap.connector.prestashop_base'
    _inherit = 'sitemap.import.service'
    _description = 'Parser comun PrestaShop'

    def _prestashop_merge_discovery(self, source_name, sitemap_entries=None, category_entries=None, related_entries=None, category_filter=None, limit=0):
        groups = [
            ('sitemap', sitemap_entries or []),
            ('categorias', category_entries or []),
            ('relacionados', related_entries or []),
        ]
        return self._merge_discovery_entries(
            source_name, groups, key_getter=self._product_key,
            category_filter=category_filter, limit=limit,
        )

    def _prestashop_extract_common(self, source, url, product_page_validator=None):
        session = self._get_session(source)
        response = self._http_get(session, url, source)
        tree = lxml_html.fromstring(response.content)

        canonical_values = tree.xpath('//link[@rel="canonical"]/@href')
        canonical = self._canonical_url(canonical_values[0] if canonical_values else response.url or url)
        if not self._product_match(canonical):
            fallback = self._canonical_url(url)
            if self._product_match(fallback):
                canonical = fallback
            else:
                raise ValueError('La URL ya no apunta a una ficha PrestaShop valida.')

        payloads = self._json_ld_payloads(tree)
        product_json = False
        for payload in payloads:
            product_json = self._find_product_json(payload)
            if product_json:
                break
        if product_page_validator and not product_page_validator(tree, product_json):
            raise ValueError('La pagina no contiene marcadores suficientes de una ficha de producto PrestaShop.')

        sources = {}
        name = self._normalize_text((product_json or {}).get('name'))
        if name:
            sources['name'] = 'json_ld'
        if not name:
            name = self._meta(tree, 'og:title')
            if name:
                sources['name'] = 'opengraph'
        if not name:
            values = tree.xpath('//*[@itemprop="name"][1]/@content | //*[@itemprop="name"][1]//text()')
            name = self._normalize_text(' '.join(values)) if values else ''
            if name:
                sources['name'] = 'microdata'
        if not name:
            values = tree.xpath('//h1[1]//text()')
            name = self._normalize_text(' '.join(values)) if values else ''
            if name:
                sources['name'] = 'html'

        lines = self._page_lines(tree)
        price, currency = self._extract_price(tree, product_json, lines)
        if price:
            if self._offer_price(product_json or {})[0]:
                sources['price'] = 'json_ld'
            elif self._meta(tree, 'product:price:amount') or self._meta(tree, 'og:price:amount'):
                sources['price'] = 'opengraph'
            elif tree.xpath('//*[@itemprop="price"]'):
                sources['price'] = 'microdata'
            else:
                sources['price'] = 'html'

        images = self._images(tree, product_json, canonical)
        if images:
            json_images = (product_json or {}).get('image') if isinstance(product_json, dict) else False
            if json_images:
                sources['images'] = 'json_ld'
            elif self._meta(tree, 'og:image'):
                sources['images'] = 'opengraph'
            elif tree.xpath('//*[@itemprop="image"]'):
                sources['images'] = 'microdata'
            else:
                sources['images'] = 'html'

        description = self._extract_description(tree, product_json)
        if (product_json or {}).get('description'):
            sources['description'] = 'json_ld'
        elif self._meta(tree, 'description'):
            sources['description'] = 'metadata'
        elif description:
            sources['description'] = 'html'

        if not name:
            raise ValueError('La ficha PrestaShop no publica un nombre reconocible.')
        if not price or price <= 0:
            raise ValueError('La ficha PrestaShop no publica un precio valido.')
        if not images:
            raise ValueError('La ficha PrestaShop no publica ninguna imagen de producto valida.')

        reference = self._reference(tree, product_json, lines, canonical)
        breadcrumbs = self._breadcrumbs(tree, canonical, name)
        _logger.info(
            'PrestaShop %s: name=%s price=%s images=%s description=%s canonical=%s',
            self._name, sources.get('name', 'none'), sources.get('price', 'none'),
            sources.get('images', 'none'), sources.get('description', 'none'), canonical,
        )
        return {
            'response': response, 'tree': tree, 'canonical': canonical,
            'product_json': product_json, 'name': name, 'lines': lines,
            'price': price, 'currency': currency or 'EUR', 'images': images,
            'description': description, 'reference': reference,
            'breadcrumbs': breadcrumbs, 'extraction_sources': sources,
        }
