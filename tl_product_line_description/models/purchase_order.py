from odoo import models, fields, api, _

class PurchaseOrderLine(models.Model):
    _inherit = ['purchase.order.line']    
    
    product_display = fields.Char(string='Producto', compute='_compute_name_display')
    description_display = fields.Char(string='Descripción', compute='_compute_name_display')
    
    @api.depends('product_id','name')
    def _compute_name_display(self):
        for record in self:
            record.product_display = False
            record.description_display = False

            if not record.name:
                continue

            lang = record.partner_id.lang or self.env.user.lang or 'es_ES'
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
         
    def _get_product_purchase_description(self, product_lang):
        self.ensure_one()
        name = product_lang.display_name
        if product_lang.description_purchase and not product_lang.default_code:
            name += '\n' + product_lang.name + '\n' + product_lang.description_purchase            
        elif product_lang.description_purchase:
            name += '\n' + product_lang.description_purchase
        elif product_lang and not product_lang.default_code:
            name += '\n' + product_lang.name
        else:
            name += '\n' + product_lang.name
            
        return name