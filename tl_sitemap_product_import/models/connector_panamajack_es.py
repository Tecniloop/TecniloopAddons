import re
from urllib.parse import urlparse

from lxml import html as lxml_html

from odoo import models


class SitemapConnectorPanamajackEs(models.AbstractModel):
    """Conector para panamajack.es -Shopify, no Salesforce Commerce Cloud como los
    cuatro anteriores-, locale español (por defecto, sin prefijo de idioma).

    Particularidades comprobadas con datos reales:
    - El sitemap índice es de Shopify: sitemap_products_1.xml / sitemap_pages_1.xml /
      sitemap_collections_1.xml / sitemap_blogs_1.xml, con variantes /en/... para el
      idioma inglés. A diferencia de Pikolinos (todos los idiomas mezclados en un mismo
      fichero), aquí cada idioma tiene sus propios ficheros separados, así que basta con
      excluir los que llevan "/en/" en la ruta para quedarse solo con el español.
    - No hay sitemap de imágenes separado (a diferencia de los conectores SFCC); se
      importa solo la imagen principal (metaetiqueta og:image), sin galería adicional.
    - SÍ hay metaetiqueta de precio (`og:price:amount`), a diferencia de Joma y
      Pikolinos, pero en formato europeo con coma decimal ("179,00"), no con punto como
      en Skechers/Mustang -si se le pasara directo a float() fallaría o daría un valor
      erróneo-, así que este conector no reutiliza _fetch_og_meta del servicio base
      (que asume formato con punto) y hace su propio parseo de precio.
    - `og:type` vale "product" en fichas reales (a diferencia de Joma/Pikolinos, donde
      valía "website" incluso en la ficha correcta); se usa como comprobación extra.
    - El color no va como parámetro de query ni es descomponible de la URL: cada color
      es un producto/URL distinto (mismo patrón que Skechers/Mustang), así que no se
      intenta separar estilo/color de la URL; el color se lee del texto "Color: X" de
      la propia ficha, si está.
    - Categoría: no se ha encontrado ni en la URL (plana: /products/handle) ni una miga
      de pan fiable en la ficha probada; se deja sin categoría (los productos quedan
      bajo la raíz de la fuente) en lugar de arriesgar un selector no verificado.

    Posible mejora futura, NO implementada por falta de verificación directa: Shopify
    expone opcionalmente cada producto como JSON estructurado en
    "<url-del-producto>.json" (con precio, variantes e imágenes ya parseados, sin
    depender de metaetiquetas ni regex sobre texto). No se ha podido comprobar contra
    panamajack.es en este desarrollo -las restricciones de la herramienta de descarga
    usada para investigar no permitieron probar esa URL concreta-, así que antes de
    darlo por bueno conviene abrir manualmente algo como
    https://www.panamajack.es/products/bota-panama-b1.json en el navegador: si devuelve
    JSON válido, sería una fuente de datos bastante más robusta que el HTML actual.
    """
    _name = 'sitemap.connector.panamajack_es'
    _inherit = 'sitemap.import.service'
    _description = 'Conector Panama Jack España'

    def _is_default_locale(self, url):
        # El español es el idioma por defecto (sin prefijo); se descartan los "/en/...".
        path = urlparse(url).path
        return not path.startswith('/en/')

    def get_product_entries(self, source, category_filter=None, limit=0):
        sub_sitemaps = self._fetch_sitemap_index_locs(source, source.sitemap_index_url)
        product_sitemaps = [
            s for s in sub_sitemaps if 'product' in s.lower() and self._is_default_locale(s)
        ]
        entries, seen = [], set()
        for sitemap_url in product_sitemaps:
            for entry in self._fetch_urlset(source, sitemap_url):
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
        # No se ha encontrado un sitemap de imágenes independiente para este sitio
        # (a diferencia de los conectores basados en Salesforce Commerce Cloud); se
        # importa solo la imagen principal (og:image) de cada ficha, sin galería extra.
        return {}

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

        og_type = meta('og:type')
        if og_type and og_type != 'product':
            # Comprobado con datos reales: en una ficha válida og:type vale "product"
            # -a diferencia de Joma/Pikolinos, donde ni siquiera las fichas correctas
            # lo usaban-, así que aquí sí sirve como aviso barato de que la página ha
            # redirigido a otra cosa (colección, inicio...).
            raise ValueError(
                f'La página no parece una ficha de producto (og:type={og_type!r}); '
                'posible redirección o URL descatalogada.')

        title_els = tree.xpath('//title/text()')
        title = meta('og:title') or (title_els[0].split('|')[0].strip() if title_els else url)
        description = meta('og:description') or meta('description') or ''
        image_url = meta('og:image')
        price = self._parse_price(meta('og:price:amount') or '0')
        currency = meta('og:price:currency') or 'EUR'

        text_content = tree.text_content()
        color_match = re.search(
            r'Color:\s*([A-ZÁÉÍÓÚÑa-záéíóúñ][A-Za-zÁÉÍÓÚÑáéíóúñ ]*?)(?:\s+Forro:|\s+Ref:|\n|$)',
            text_content)
        color_code = color_match.group(1).strip() if color_match else False

        # El "handle" final de la URL (p. ej. "bota-panama-b1") identifica de forma
        # única esta combinación de modelo/color -en este sitio cada color es un
        # producto/URL distinto, no una variante dentro de la misma URL-, así que se usa
        # tal cual como código de estilo en vez de intentar descomponerlo.
        style_code = urlparse(canonical_url).path.rstrip('/').split('/')[-1].upper() or False

        return {
            'name': title or url,
            'description': description,
            'price': price,
            'currency': currency,
            'main_image_url': image_url or False,
            'canonical_url': canonical_url,
            'style_code': style_code,
            'color_code': color_code,
            'category_path': '',
        }

    @staticmethod
    def _parse_price(price_str):
        if not price_str:
            return 0.0
        price_str = str(price_str).strip()
        if ',' in price_str:
            # Formato europeo: punto de miles opcional, coma decimal (comprobado con
            # datos reales: "179,00").
            price_str = price_str.replace('.', '').replace(',', '.')
        try:
            return float(price_str)
        except ValueError:
            return 0.0
