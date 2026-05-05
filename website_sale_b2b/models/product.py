# -*- coding: utf-8 -*-
# Part of SoftMuch. See LICENSE file for full copyright and licensing details.

from odoo import models
from odoo.http import request


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def get_qty_order_line(self):
        order = request.website.sale_get_order(force_create=True)
        line = order.order_line.filtered(lambda line: line.product_template_id.id == self.id)

        return int(line.product_uom_qty) if line else 0