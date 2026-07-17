from odoo import fields, models


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
    sitemap_public_categ_id = fields.Many2one(
        'product.public.category', string='Categoría e-commerce (asignada por el importador)',
        copy=False, readonly=True,
        help='Última categoría de comercio electrónico asignada automáticamente por el importador. '
             'Se guarda aparte para poder actualizarla en sincronizaciones posteriores sin tocar '
             'otras categorías de comercio electrónico que hayas añadido manualmente.')

    _sql_constraints = [
        ('sitemap_source_url_uniq', 'unique(sitemap_source_url)',
         'Ya existe un producto importado con esta URL de origen.'),
    ]
