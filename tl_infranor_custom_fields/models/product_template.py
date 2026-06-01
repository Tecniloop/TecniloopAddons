from odoo import fields, models

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    product_responsible_id = fields.Many2one(
        'res.users',
        string='Responsable de producte',
        domain=[('share', '=', False)],  # Solo usuarios internos
        tracking=True,
    )