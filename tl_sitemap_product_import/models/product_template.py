import html
import json
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    brand_id = fields.Many2one(
        'res.brand',
        string='Marca',
        index=True,
        ondelete='restrict',
        help='Marca OCA asignada al producto.',
    )
    is_sitemap_import_product = fields.Boolean(
        string='Producto importado por sitemap', default=False, copy=False, index=True, readonly=True)
    sitemap_source_id = fields.Many2one(
        'sitemap.import.source', string='Fuente de importación', copy=False, readonly=True, index=True)
    sitemap_source_url = fields.Char(string='URL de origen', copy=False, index=True, readonly=True)
    sitemap_style_code = fields.Char(string='Código de estilo', copy=False, readonly=True)
    sitemap_color_code = fields.Char(string='Código de color', copy=False, readonly=True)
    sitemap_lastmod = fields.Datetime(string='Última modificación en sitemap', copy=False, readonly=True)
    sitemap_last_sync = fields.Datetime(string='Última sincronización', copy=False, readonly=True)
    sitemap_single_ean = fields.Char(
        string='EAN único recuperado', copy=False, readonly=True, index=True,
        help='Se informa únicamente cuando la fuente publica un solo GTIN válido para la ficha.')
    sitemap_ean_count = fields.Integer(string='Número de EAN recuperados', copy=False, readonly=True)
    sitemap_ean_ids = fields.One2many(
        'sitemap.product.ean', 'product_tmpl_id', string='EAN/GTIN por variante', copy=False, readonly=True)
    sitemap_attributes_json = fields.Text(
        string='Atributos técnicos importados (JSON)', copy=False, readonly=True,
        help='Mapa de atributos informativos gestionados por el importador de sitemap.')
    sitemap_collection_categ_ids = fields.Many2many(
        'product.public.category',
        'product_template_sitemap_collection_rel',
        'product_tmpl_id', 'public_categ_id',
        string='Collections Shopify importadas', copy=False, readonly=True,
        help='Categorías públicas procedentes de Collections Shopify. Se guardan aparte para poder actualizar sus asociaciones sin eliminar categorías añadidas manualmente.')
    sitemap_public_categ_id = fields.Many2one(
        'product.public.category', string='Categoría e-commerce (asignada por el importador)',
        copy=False, readonly=True,
        help='Última categoría de comercio electrónico asignada automáticamente por el importador. '
             'Se guarda aparte para poder actualizarla en sincronizaciones posteriores sin tocar '
             'otras categorías de comercio electrónico que hayas añadido manualmente.')

    _sitemap_source_url_uniq = models.Constraint(
        'unique(sitemap_source_url)',
        message='Ya existe un producto importado con esta URL de origen.',
    )

    @staticmethod
    def _sitemap_fix_mojibake(value):
        """Repara texto UTF-8 interpretado como latin-1/cp1252."""
        if not isinstance(value, str):
            return value
        text = value
        markers = ('Ã', 'Â', 'â€', 'â€™', 'â€œ', 'â€\x9d', 'â€“', 'â€”', 'ðŸ', 'ï»¿', '\ufffd')

        def score(candidate):
            return sum(candidate.count(marker) for marker in markers)

        for _index in range(3):
            before = score(text)
            if not before:
                break
            candidates = []
            for codec in ('latin-1', 'cp1252'):
                try:
                    candidates.append(text.encode(codec).decode('utf-8'))
                except (UnicodeEncodeError, UnicodeDecodeError):
                    continue
            if not candidates:
                break
            best = min(candidates, key=score)
            if score(best) >= before:
                break
            text = best
        return text.lstrip('\ufeff')

    @api.model
    def _sitemap_prepare_public_description(self, value):
        """Normaliza HTML importado y convierte texto plano a HTML de Odoo.

        Algunas fuentes entregan el fragmento HTML escapado una o varias veces,
        por ejemplo ``&lt;p&gt;Texto&lt;/p&gt;`` o
        ``&amp;lt;p&amp;gt;Texto&amp;lt;/p&amp;gt;``. Antes de decidir si el
        contenido es HTML se desescapa de forma limitada e iterativa.
        """
        value = self._sitemap_fix_mojibake(str(value or '')).strip().replace('\\/', '/')
        if not value:
            return False

        # Deshacer hasta tres niveles de entidades HTML. El límite evita ciclos
        # o transformaciones excesivas en textos que contengan entidades válidas.
        for _iteration in range(3):
            decoded = html.unescape(value)
            if decoded == value:
                break
            value = decoded.strip()

        if re.search(r'<\s*[a-zA-Z][^>]*>', value):
            # Conservar el fragmento original, pero envolverlo para que el editor
            # web de Odoo aplique la estructura y márgenes habituales. Si ya es
            # contenido de Odoo no se añade otro contenedor.
            if re.search(r'<\s*div\b[^>]*data-oe-version=', value, flags=re.I):
                return value
            return '<div data-oe-version="2.0">%s</div>' % value

        paragraphs = [
            '<p>%s</p>' % html.escape(block.strip()).replace('\n', '<br/>')
            for block in re.split(r'\n\s*\n', value)
            if block.strip()
        ]
        return '<div data-oe-version="2.0">%s</div>' % ''.join(paragraphs)

    @api.model
    def _sitemap_description_cleanup_vals(self, public_html):
        """Guarda el HTML original de la ficha en ``public_description``.

        ``public_description`` es el campo HTML editable utilizado por la ficha
        pública del producto en esta instalación. El contenido se conserva como
        HTML estructurado; no se convierte a texto plano ni se envuelve dentro de
        un único párrafo.
        """
        vals = {}
        prepared_html = self._sitemap_prepare_public_description(public_html)

        if 'public_description' in self._fields:
            vals['public_description'] = prepared_html

        # Limpiar el campo usado por la versión 19.0.1.113.0 para evitar que
        # queden dos descripciones web distintas en productos reparados.
        if 'website_description' in self._fields:
            vals['website_description'] = False

        # Las descripciones de venta no deben contaminar presupuestos ni crear
        # bloques e-commerce alternativos.
        for field_name in (
            'description_sale',
            'description_sale_short',
            'description_sale_long',
            'description_ecommerce',
        ):
            if field_name in self._fields:
                vals[field_name] = False
        return vals

    def _is_munich_sitemap_product(self):
        self.ensure_one()
        return bool(
            self.is_sitemap_import_product
            and self.sitemap_source_id
            and self.sitemap_source_id.connector_model == 'sitemap.connector.munichsports_es'
            and self.sitemap_source_url
        )

    def action_queue_repair_imported_products(self):
        products = self.filtered(
            lambda product: product.is_sitemap_import_product
            and product.sitemap_source_id
            and product.sitemap_source_url
        )
        if not products:
            raise UserError(_('Seleccione productos importados por sitemap.'))
        for product in products:
            product.with_delay(
                channel='root.sitemap.import',
                description=_('Corregir producto importado: %s') % product.display_name,
                identity_key=f'sitemap_repair_imported_{product.id}',
            )._job_repair_imported_product()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Corrección de productos en cola'),
                'message': _('%s productos enviados a queue_job.') % len(products),
                'type': 'success',
                'sticky': False,
            },
        }

    def _job_repair_imported_product(self):
        self.ensure_one()
        source = self.sitemap_source_id
        if not self.is_sitemap_import_product or not source or not self.sitemap_source_url:
            return False

        connector = self.env[source.connector_model]
        data = connector.fetch_preview(source, self.sitemap_source_url)
        data = connector._normalise_extracted_charset(data)

        # Se prioriza siempre el HTML ampliado recuperado de la fuente. Solo si
        # no existe se usa la descripción genérica/breve como respaldo.
        source_description = (
            data.get('full_description')
            or data.get('description_html')
            or data.get('description')
            or data.get('short_description')
            or ''
        )
        vals = self._sitemap_description_cleanup_vals(source_description)

        extracted_name = str(data.get('name') or '').strip()
        style_code = str(data.get('style_code') or self.sitemap_style_code or '').strip()
        if extracted_name and style_code:
            if not extracted_name.casefold().startswith(style_code.casefold()):
                extracted_name = f'{style_code} {extracted_name}'.strip()
        if extracted_name:
            vals['name'] = extracted_name
        if style_code:
            vals['sitemap_style_code'] = style_code

        raw_segments = [
            segment.strip() for segment in str(data.get('category_path') or '').split('/')
            if segment.strip()
        ]
        segments = connector._sanitize_product_category_segments(
            raw_segments,
            product_name=extracted_name or self.name,
            style_code=style_code,
            url=self.sitemap_source_url,
        )
        internal_category = connector._resolve_category_chain(segments, source, 'internal')
        vals['categ_id'] = internal_category.id

        if source.import_public_categories:
            public_category = connector._resolve_category_chain(segments, source, 'public')
            commands = []
            if self.sitemap_public_categ_id and self.sitemap_public_categ_id != public_category:
                commands.append((3, self.sitemap_public_categ_id.id, 0))
            commands.append((4, public_category.id, 0))
            vals.update({
                'public_categ_ids': commands,
                'sitemap_public_categ_id': public_category.id,
            })

            resolver = getattr(connector, 'resolve_product_collection_categories', None)
            collection_fetcher = getattr(connector, 'get_product_collections', None)
            if resolver and collection_fetcher and 'sitemap_collection_categ_ids' in self._fields:
                raw_collections = collection_fetcher(
                    source, self.sitemap_source_url
                )
                collection_categories = resolver(source, raw_collections)
                previous_collections = self.sitemap_collection_categ_ids
                vals['public_categ_ids'] += [
                    (3, category.id, 0)
                    for category in previous_collections - collection_categories
                ] + [
                    (4, category.id, 0)
                    for category in collection_categories - previous_collections
                ]
                vals['sitemap_collection_categ_ids'] = [
                    (6, 0, collection_categories.ids)
                ]

        self.write(vals)

        if self._is_munich_sitemap_product():
            variants = connector._normalise_ean_variants(data.get('ean_variants') or [])
            labelled = [
                item for item in variants
                if connector._variant_label_parts(item.get('variant_label'))
            ]
            if labelled:
                connector._sync_product_variants(self, labelled)
            connector._remove_duplicate_variant_informational_attributes(self, labelled)

            # Limpia además líneas históricas Talla (informativo/informativa).
            suffix_re = re.compile(r'^talla\s*\((?:informativo|informativa)\)\s*$', re.I)
            duplicate_lines = self.attribute_line_ids.filtered(
                lambda line: bool(suffix_re.match(line.attribute_id.name or ''))
            )
            if duplicate_lines:
                duplicate_lines.unlink()

            try:
                stored = json.loads(self.sitemap_attributes_json or '{}')
            except (TypeError, ValueError, json.JSONDecodeError):
                stored = {}
            if isinstance(stored, dict):
                stored = {
                    name: values for name, values in stored.items()
                    if re.sub(
                        r'\s*\((?:informativo|informativa)\)\s*$', '', name, flags=re.I
                    ).strip().casefold() != 'talla'
                }
                self.sitemap_attributes_json = json.dumps(
                    stored, ensure_ascii=False, sort_keys=True
                )
        return True

    def action_refresh_sitemap_eans(self):
        """Vuelve a consultar los EAN sin modificar precio, descripción o imágenes."""
        refreshed = without_ean = failed = 0
        errors = []
        for product in self:
            source = product.sitemap_source_id
            if not product.is_sitemap_import_product or not source or not product.sitemap_source_url:
                failed += 1
                continue
            if not source.import_eans:
                failed += 1
                errors.append(_('%s: la recuperación de EAN está desactivada en la fuente.') % product.display_name)
                continue
            connector = self.env[source.connector_model]
            try:
                data = connector.fetch_preview(source, product.sitemap_source_url)
                data = connector.enrich_preview_eans(source, product.sitemap_source_url, data)
                if not data.get('ean_checked'):
                    raise UserError(_('La fuente no pudo confirmar la consulta de EAN.'))
                connector._sync_product_eans(product, source, data.get('ean_variants') or [])
                if data.get('ean_count'):
                    refreshed += 1
                else:
                    without_ean += 1
            except Exception as exc:
                failed += 1
                errors.append(f'{product.display_name}: {exc}')

        message = _('%(refreshed)s productos con EAN actualizados; %(without)s sin EAN publicado') % {
            'refreshed': refreshed,
            'without': without_ean,
        }
        if failed:
            message += _('; %s con error') % failed
        if errors:
            message += '\n' + '\n'.join(errors[:5])
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Actualización de EAN/GTIN'),
                'message': message,
                'type': 'warning' if failed else 'success',
                'sticky': bool(failed),
            },
        }



class ProductProduct(models.Model):
    _inherit = 'product.product'

    sitemap_source_variant_id = fields.Char(
        string='ID de variante de origen', copy=False, index=True, readonly=True)
    sitemap_variant_available = fields.Boolean(
        string='Disponible en origen', copy=False, default=True, readonly=True)


class ProductImage(models.Model):
    _inherit = 'product.image'

    is_sitemap_import_image = fields.Boolean(
        string='Imagen importada por sitemap', default=False, copy=False, index=True)
    sitemap_source_url = fields.Char(
        string='URL de imagen de origen', copy=False, index=True)
