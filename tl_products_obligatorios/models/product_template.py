from odoo import api, fields, models
from odoo.exceptions import MissingError, UserError, AccessError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    productos_obligatorios = fields.Many2many(
        comodel_name='product.template',
        relation="product_template_rel",
        column1="src_id",
        column2="dest_id",
        string="Productos obligatorios")