from odoo import api, fields, models

class ProductCategory(models.Model):
    _inherit = 'product.category'

    productos_obligatorios = fields.Many2many('product.template', string="Productos obligatorios")