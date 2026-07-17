from odoo import fields, models


class ProductImage(models.Model):
    _inherit = "product.image"

    nextmart_url = fields.Char(index=True, copy=False)
    nextmart_kind = fields.Char(copy=False)
