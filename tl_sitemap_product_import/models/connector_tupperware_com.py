import re
import time
from urllib.parse import urljoin, urlparse, urlunparse

from odoo import models


class SitemapConnectorTupperwareCom(models.AbstractModel):
    """Conector para el catálogo de Tupperware en español.

    Tupperware usa Shopify. La fuente puede configurarse con ``robots.txt``;
    el conector obtiene de él el sitemap declarado, selecciona los urlsets de
    productos y los completa con el catálogo público ``/products.json``.

    Aunque el sitemap principal publique fichas sin prefijo de idioma, las URL
    descubiertas se convierten a ``/es/products/<handle>`` para que el nombre,
    la descripción, las categorías y los metadatos se recuperen en español.
    La URL original se conserva como respaldo si la versión localizada no está
    disponible para un producto concreto.
    """

    _name = 'sitemap.connector.tupperware_com'
    _inherit = 'sitemap.connector.panamajack_es'
    _description = 'Conector Tupperware en español'

    _SPANISH_PREFIX = '/es'
    _COLLECTION_CACHE = {}
    _COLLECTION_CACHE_TTL = 3600

    @classmethod
    def _spanish_product_url(cls, url):
        """Return the Spanish storefront URL for a Tupperware product."""
        if not url:
            return url
        parsed = urlparse(str(url).strip())
        path = re.sub(r'/+', '/', parsed.path or '/')
        match = re.search(
            r'/(?:[a-z]{2}(?:-[a-z]{2})?/)?products/([^/?#]+)',
            path,
            flags=re.IGNORECASE,
        )
        if not match:
            return url
        handle = match.group(1).strip('/')
        localized_path = f'{cls._SPANISH_PREFIX}/products/{handle}'
        return urlunparse(parsed._replace(path=localized_path))

    @classmethod
    def _default_product_url(cls, url):
        """Remove a locale prefix, preserving query string and fragment."""
        if not url:
            return url
        parsed = urlparse(str(url).strip())
        path = re.sub(
            r'^/[a-z]{2}(?:-[a-z]{2})?(?=/products/)',
            '',
            parsed.path or '',
            flags=re.IGNORECASE,
        )
        return urlunparse(parsed._replace(path=path or '/'))

    def _is_default_locale(self, url):
        """Accept both raw and localized product URLs during discovery."""
        return bool(self._product_handle(url))

    @staticmethod
    def _robots_sitemaps(text, base_url):
        result = []
        # Shopify puede devolver robots.txt prácticamente en una sola línea.
        patterns = (
            r'(?im)^\s*Sitemap\s*:\s*(\S+)',
            r'(?i)\bSitemap\s*:\s*(https?://[^\s#]+)',
        )
        for pattern in patterns:
            for match in re.finditer(pattern, text or ''):
                value = match.group(1).strip().rstrip(';,')
                absolute = urljoin(base_url, value)
                if absolute not in result:
                    result.append(absolute)
            if result:
                break
        return result

    def _configured_sitemap_urls(self, source):
        configured = str(source.sitemap_index_url or '').strip()
        if not configured:
            return []
        if not configured.casefold().endswith('/robots.txt'):
            return [configured]

        session = self._get_session(source)
        response = self._http_get(session, configured, source)
        result = self._robots_sitemaps(response.text, response.url)
        if not result:
            parsed = urlparse(configured)
            result = [f'{parsed.scheme}://{parsed.netloc}/sitemap.xml']
        return result

    @classmethod
    def _localize_entries(cls, entries):
        """Convert every product discovery entry to the Spanish storefront."""
        localized = []
        for raw_entry in entries or []:
            if not isinstance(raw_entry, dict):
                continue
            entry = dict(raw_entry)
            localized_url = cls._spanish_product_url(entry.get('url'))
            if localized_url:
                entry['url'] = localized_url
                localized.append(entry)
        return localized


    def _shopify_collection_map(self, source, force=False):
        """Return ``product_handle -> collections`` for the Spanish storefront.

        Shopify does not include collection memberships in ``products.json``.
        The public collection catalogue and each collection's ``products.json``
        endpoint are therefore read once and cached per worker for one hour.
        """
        cache_key = (self.env.cr.dbname, source.id)
        cached = self._COLLECTION_CACHE.get(cache_key)
        now = time.monotonic()
        if cached and not force and now - cached['time'] < self._COLLECTION_CACHE_TTL:
            return cached['map']

        session = self._get_session(source)
        parsed = urlparse(source.sitemap_index_url)
        base_url = f'{parsed.scheme}://{parsed.netloc}'
        locale_root = f'{base_url}{self._SPANISH_PREFIX}'
        collections = []
        page = 1
        while page <= 100:
            endpoint = f'{locale_root}/collections.json?limit=250&page={page}'
            try:
                response = self._http_get(session, endpoint, source)
                payload = response.json()
            except Exception:  # noqa: BLE001 - collections are supplementary
                break
            page_items = payload.get('collections') if isinstance(payload, dict) else []
            if not isinstance(page_items, list) or not page_items:
                break
            collections.extend(item for item in page_items if isinstance(item, dict))
            if len(page_items) < 250:
                break
            page += 1

        membership = {}
        for collection in collections:
            handle = self._clean_text(collection.get('handle'))
            title = self._clean_text(collection.get('title'))
            if not handle or not title or handle.casefold() == 'all':
                continue
            collection_info = {
                'handle': handle,
                'name': title,
                'url': f'{locale_root}/collections/{handle}',
                'description_html': collection.get('body_html') or '',
            }
            product_page = 1
            while product_page <= 100:
                endpoint = (
                    f'{locale_root}/collections/{handle}/products.json'
                    f'?limit=250&page={product_page}'
                )
                try:
                    response = self._http_get(session, endpoint, source)
                    payload = response.json()
                except Exception:  # noqa: BLE001 - skip inaccessible collection
                    break
                products = payload.get('products') if isinstance(payload, dict) else []
                if not isinstance(products, list) or not products:
                    break
                for product in products:
                    if not isinstance(product, dict):
                        continue
                    product_handle = self._clean_text(product.get('handle'))
                    if not product_handle:
                        continue
                    rows = membership.setdefault(product_handle.casefold(), [])
                    if not any(row.get('handle') == handle for row in rows):
                        rows.append(dict(collection_info))
                if len(products) < 250:
                    break
                product_page += 1

        self._COLLECTION_CACHE[cache_key] = {'time': now, 'map': membership}
        return membership

    def get_product_collections(self, source, url, force=False):
        handle = self._product_handle(url)
        if not handle:
            return []
        return list(self._shopify_collection_map(source, force=force).get(handle.casefold(), []))

    def resolve_product_collection_categories(self, source, collections):
        """Create/find Odoo public categories matching Shopify Collections."""
        categories = self.env['product.public.category']
        seen = set()
        for collection in collections or []:
            if not isinstance(collection, dict):
                continue
            name = self._clean_text(collection.get('name') or collection.get('title'))
            handle = self._clean_text(collection.get('handle'))
            token = (handle or name).casefold()
            if not name or not token or token in seen or handle.casefold() == 'all':
                continue
            seen.add(token)
            category = self._resolve_category_chain([name], source, 'public')
            categories |= category
        return categories

    def get_product_entries(self, source, category_filter=None, limit=0):
        sitemap_entries = []
        sitemap_roots = self._configured_sitemap_urls(source)

        for sitemap_root in sitemap_roots:
            try:
                sub_sitemaps = self._fetch_sitemap_index_locs(source, sitemap_root)
            except Exception:  # noqa: BLE001 - puede ser un urlset directo
                sub_sitemaps = []

            product_sitemaps = [
                sitemap_url
                for sitemap_url in sub_sitemaps
                if 'product' in sitemap_url.casefold()
            ]
            if not product_sitemaps:
                product_sitemaps = [sitemap_root]

            for sitemap_url in product_sitemaps:
                try:
                    sitemap_entries.extend(self._fetch_urlset(source, sitemap_url))
                except Exception:  # noqa: BLE001 - products.json sigue disponible
                    continue

        # Se obtiene completo antes de aplicar el límite para deduplicar bien.
        catalog_entries = self._shopify_catalog_entries(source, limit=0)

        # El sitemap y products.json suelen devolver /products/<handle>. Se
        # localizan antes de guardar staging para que toda sincronización y
        # reparación posterior trabaje directamente con la ficha española.
        sitemap_entries = self._localize_entries(sitemap_entries)
        catalog_entries = self._localize_entries(catalog_entries)

        def valid_handle(url):
            return self._product_handle(url)

        filtered_groups = []
        for group_name, raw_entries in (
            ('sitemap_es', sitemap_entries),
            ('shopify_catalog_es', catalog_entries),
        ):
            filtered_groups.append((
                group_name,
                [
                    entry for entry in raw_entries
                    if valid_handle((entry or {}).get('url'))
                ],
            ))

        merged = self._merge_discovery_entries(
            'Tupperware',
            filtered_groups,
            key_getter=self._product_handle,
            category_filter=category_filter,
            limit=limit,
        )
        collection_map = self._shopify_collection_map(source)
        for entry in merged:
            handle = self._product_handle(entry.get('url'))
            entry['shopify_collections'] = list(
                collection_map.get((handle or '').casefold(), [])
            )
        return merged

    def fetch_preview(self, source, url):
        """Fetch Spanish content, with the unlocalized page as fallback."""
        localized_url = self._spanish_product_url(url)
        fallback_url = self._default_product_url(localized_url)

        try:
            values = super().fetch_preview(source, localized_url)
            effective_url = localized_url
        except Exception:  # noqa: BLE001 - localized storefront may miss a handle
            if fallback_url == localized_url:
                raise
            values = super().fetch_preview(source, fallback_url)
            effective_url = fallback_url

        values['brand_name'] = values.get('brand_name') or 'Tupperware'
        if str(values.get('brand_name') or '').casefold() == 'panama jack':
            values['brand_name'] = 'Tupperware'

        # El parser Shopify genérico convierte ``body_html`` a texto plano para
        # obtener una descripción breve. Tupperware publica, sin embargo, un
        # fragmento HTML completo y localizado con encabezados, listas, negritas
        # y enlaces. Se vuelve a leer el payload de la ficha efectiva y se
        # conserva ese fragmento sin aplanarlo para ``public_description``.
        product_payload = self._fetch_shopify_product(source, effective_url)
        raw_html = (
            product_payload.get('body_html')
            or product_payload.get('description')
            or product_payload.get('content')
            or ''
        ) if isinstance(product_payload, dict) else ''
        if raw_html:
            values['full_description'] = raw_html
            values['description_html'] = raw_html
            values['description'] = self._strip_html(raw_html)
            values['short_description'] = self._strip_html(raw_html)

        # El detector de color heredado busca texto visible de calzado y puede
        # capturar variables CSS del tema Shopify. Tupperware no publica aquí un
        # código de color fiable, por lo que se descarta.
        values['color_code'] = False

        # Mantener la URL española como canónica del importador cuando fue la
        # ficha que proporcionó el contenido. Shopify puede anunciar en el HTML
        # una canonical sin idioma, pero no debe hacer que Odoo vuelva a inglés.
        if effective_url == localized_url:
            values['canonical_url'] = localized_url

        # En Shopify el slug no debe usarse como referencia si existe SKU.
        default_code = self._clean_text(values.get('default_code'))
        if default_code:
            values['style_code'] = default_code
        return values
