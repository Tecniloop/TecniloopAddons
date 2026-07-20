from odoo import fields, models


class SitemapProductEan(models.Model):
    _name = 'sitemap.product.ean'
    _description = 'EAN/GTIN recuperado de una variante externa'
    _order = 'variant_label, sku, ean'

    product_tmpl_id = fields.Many2one(
        'product.template', string='Producto', required=True, ondelete='cascade', index=True)
    source_id = fields.Many2one(
        'sitemap.import.source', string='Fuente', related='product_tmpl_id.sitemap_source_id',
        store=True, readonly=True, index=True)
    ean = fields.Char(string='EAN/GTIN', required=True, index=True)
    gtin_type = fields.Selection([
        ('gtin8', 'GTIN-8'),
        ('gtin12', 'GTIN-12 / UPC-A'),
        ('gtin13', 'GTIN-13 / EAN-13'),
        ('gtin14', 'GTIN-14'),
    ], string='Tipo', readonly=True)
    sku = fields.Char(string='SKU / referencia de variante')
    variant_label = fields.Char(string='Variante externa')
    source_variant_id = fields.Char(string='ID variante externa')
    available = fields.Boolean(string='Disponible', default=True)

    _sql_constraints = [
        ('product_ean_variant_uniq',
         'unique(product_tmpl_id, ean)',
         'Este EAN ya está registrado para el producto.'),
    ]
