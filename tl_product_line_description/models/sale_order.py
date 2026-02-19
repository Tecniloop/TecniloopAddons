from odoo import models, fields, api, _
from datetime import datetime, date
from odoo.exceptions import MissingError, UserError, ValidationError
from dateutil.relativedelta import relativedelta

class SaleOrderLine(models.Model):
    _inherit = ['sale.order.line']    
    
    product_display = fields.Char(string='Producto', compute='_compute_name_display')
    description_display = fields.Char(string='Descripción', compute='_compute_name_display')
    
    @api.depends('product_id','name')
    def _compute_name_display(self):
        for record in self:
            record.product_display = False
            record.description_display = False

            if not record.name:
                continue

            lang = record.order_id.partner_id.lang or self.env.user.lang or 'es_ES'
            product_name = record.with_context(lang=lang).product_id.display_name

            lines = record.name.split("\n")

            first = lines[0] if len(lines) > 0 else ''
            second = lines[1] if len(lines) > 1 else False
            third = "\n".join(lines[2:]) if len(lines) > 2 else False

            if first != product_name:
                second = "\n".join(lines[1:]) if len(lines) > 1 else False
                record.product_display = first
                record.description_display = second
            else:
                record.product_display = second
                if not second:
                    record.product_display = first                    
                record.description_display = third            
         