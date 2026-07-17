from odoo import models


class ProductProduct(models.Model):
    _inherit = "product.product"

    def action_nextmart_enrich(self):
        self.ensure_one()
        return self.product_tmpl_id._nextmart_enrich(variant=self)
