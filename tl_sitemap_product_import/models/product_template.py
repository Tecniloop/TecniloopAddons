from odoo import _, fields, models
from odoo.exceptions import UserError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

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

