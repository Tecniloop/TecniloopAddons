import re
from urllib.parse import urlparse

from lxml import html as lxml_html

from odoo import models


class SitemapConnectorPikolinosEs(models.AbstractModel):
    """Conector para pikolinos.com (Salesforce Commerce Cloud), locale es-es.

    Particularidades comprobadas con datos reales:
    - El sitemap índice tiene DOS sitemaps de productos (sitemap_0/1-product.xml) y OCHO
      de imágenes (sitemap_2..9-image.xml) que hay que fusionar -como Mustang, pero con
      otros números-.
    - CADA producto aparece unas 28-30 veces en el sitemap, una por cada combinación de
      idioma/país que vende Pikolinos (be-nl, bg-en, es-en, es-es...). Solo interesa el
      primer segmento de ruta EXACTAMENTE "es-es" (no basta con empezar por "es-", eso
      colaría "es-en", que es España en inglés).
    - Las fichas de producto NO tienen metaetiqueta de precio (a diferencia de Skechers/
      Mustang); el precio solo aparece como texto visible en la página, así que aquí no
      se reutiliza _fetch_og_meta del servicio base -no da lo que hace falta- y este
      conector hace su propio parseo completo. Tampoco hay categoría en la URL (es plana:
      /es-es/modelo-referencia.html); la categoría se lee de las migas de pan de la página.
    - El color no va en la URL del sitemap sino por parámetro de query
      (?dwvar_..._color=X), que el sitemap no enumera; se usa el color por defecto que
      indica la propia ficha como texto ("Color: NEGRO"), si se detecta.
    - Algunas URLs del sitemap redirigen a una página de categoría en vez de mostrar un
      producto (visto con datos reales: probablemente artículos descatalogados tras un
      cambio de catálogo). Se detecta comparando el último segmento de la URL solicitada
      con el de la URL canónica devuelta; si no coinciden, se lanza un error en vez de
      importar una ficha vacía -así queda visible como error en la cola, no como un
      producto fantasma sin precio ni imagen.
    """
    _name = 'sitemap.connector.pikolinos_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Pikolinos España (es-es)'

    LOCALE = 'es-es'

    def _is_target_locale(self, url):
        segments = [s for s in urlparse(url).path.split('/') if s]
        return bool(segments) and segments[0].lower() == self.LOCALE

    def get_product_entries(self, source, category_filter=None, limit=0):
        sub_sitemaps = self._fetch_sitemap_index_locs(source, source.sitemap_index_url)
        product_sitemaps = [s for s in sub_sitemaps if 'product' in s.lower()]
        entries, seen = [], set()
        for sitemap_url in product_sitemaps:
            for entry in self._fetch_urlset(source, sitemap_url):
                if not self._is_target_locale(entry['url']):
                    continue
                if entry['url'] in seen:
                    continue
                if category_filter and category_filter.lower() not in entry['url'].lower():
                    continue
                seen.add(entry['url'])
                entries.append(entry)
                if limit and len(entries) >= limit:
                    return entries
        return entries

    def get_image_map(self, source):
        sub_sitemaps = self._fetch_sitemap_index_locs(source, source.sitemap_index_url)
        image_sitemaps = [s for s in sub_sitemaps if 'image' in s.lower()]
        image_map = {}
        for sitemap_url in image_sitemaps:
            for url, images in self._fetch_image_urlset(source, sitemap_url).items():
                if not self._is_target_locale(url):
                    continue
                image_map.setdefault(url, []).extend(images)
        return image_map

    def fetch_preview(self, source, url):
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

        requested_slug = urlparse(url).path.rstrip('/').split('/')[-1]
        canonical_slug = urlparse(canonical_url).path.rstrip('/').split('/')[-1]
        if requested_slug != canonical_slug:
            # La ficha ha redirigido a otra página (normalmente una categoría de un
            # producto descatalogado). Se trata como error: mejor visible en la cola
            # de errores que importado con precio 0€ y sin imagen.
            raise ValueError(
                f'La URL redirige a otra página (posible producto descatalogado): '
                f'se pidió "{requested_slug}" y la canónica es "{canonical_slug}"')

        title_els = tree.xpath('//title/text()')
        title = meta('og:title') or (title_els[0].split('|')[0].strip() if title_els else url)
        description = meta('og:description') or meta('description') or ''
        image_url = meta('og:image')

        text_content = tree.text_content()

        # Precio: no hay metaetiqueta; se coge el último importe con "€" del texto visible
        # (el reducido, si hay rebaja -aparece en segundo lugar-; el único, si no la hay).
        price_matches = re.findall(r'(\d{1,4}(?:[.,]\d{2})?)\s*€', text_content)
        price = 0.0
        if price_matches:
            try:
                price = float(price_matches[-1].replace('.', '').replace(',', '.'))
            except ValueError:
                price = 0.0

        category_path = self._extract_breadcrumb(tree)

        # Estilo: el segmento final de la URL es "modelo-REFERENCIA.html"; la referencia
        # (todo lo que va después del primer guion) es lo que la propia ficha muestra
        # como "Ref: XXX" -comprobado con varios ejemplos reales-.
        style_code = False
        slug_match = re.match(r'^[^-]+-(.+)$', requested_slug)
        if slug_match:
            style_code = slug_match.group(1).upper()

        # Color: se lee del texto "Color: NOMBRE ... Ref:" si la ficha lo muestra así.
        # No viene de la URL del sitemap (el color va por parámetro dwvar_..._color=,
        # que el sitemap no enumera), así que esto es el color POR DEFECTO de la ficha.
        color_match = re.search(r'Color:\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ0-9 ]*?)\s+Ref:', text_content)
        color_code = color_match.group(1).strip() if color_match else False

        return {
            'name': title or url,
            'description': description,
            'price': price,
            'currency': 'EUR',
            'main_image_url': image_url or False,
            'canonical_url': canonical_url,
            'style_code': style_code,
            'color_code': color_code,
            'category_path': '/'.join(category_path),
        }

    @staticmethod
    def _extract_breadcrumb(tree):
        """Best-effort: probado que el texto de las migas de pan aparece en la página
        (Inicio > Mujer > Tipo de Calzado > Sandalias > Sandalias Planas), pero no se ha
        podido confirmar el selector CSS/HTML exacto contra el HTML en bruto -solo se vio
        en la versión convertida a texto-. Si ninguno de estos selectores habituales
        encuentra nada, se deja sin categoría (se anida bajo la raíz de la fuente) en
        lugar de fallar. Revisar y ajustar el selector si no funciona en la práctica.
        """
        candidates = (
            tree.xpath('//*[contains(@class, "breadcrumb")]//a/text()')
            or tree.xpath('//nav[@aria-label="breadcrumb" or @aria-label="Breadcrumb"]//a/text()')
            or tree.xpath('//*[@itemtype and contains(@itemtype, "BreadcrumbList")]//a/text()')
        )
        names = [c.strip() for c in candidates if c and c.strip()]
        names = [n for n in names if n.lower() not in ('inicio', 'home')]
        return [n.title() for n in names]
