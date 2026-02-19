from odoo import models, fields, api, _
from datetime import date

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'
    
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
         
    @api.depends('product_id', 'move_id.ref', 'move_id.payment_reference')
    def _compute_name(self):
        def get_name(line):
            """Devuelve el nombre del producto con descripción personalizada."""
            values = []
            if not line.product_id:
                return False

            if line.partner_id.lang:
                product = line.product_id.with_context(lang=line.partner_id.lang)
            else:
                product = line.product_id

            
            name = product.display_name or ''
            if line.journal_id.type == 'sale':
                if product.description_sale and not product.default_code:
                    name += '\n' + product.name + '\n' + product.description_sale
                elif product.description_sale:
                    name += '\n' + product.description_sale
                elif product and not product.default_code:
                    name += '\n' + product.name
                else:
                    name += '\n' + product.name
                    
            elif line.journal_id.type == 'purchase':
                if product.description_purchase and not product.default_code:
                    name += '\n' + product.name + '\n' + product.description_purchase            
                elif product.description_purchase:
                    name += '\n' + product.description_purchase
                elif product and not product.default_code:
                    name += '\n' + product.name
                else:
                    name += '\n' + product.name

            return name.strip() if name else False

        term_by_move = (self.move_id.line_ids | self).filtered(lambda l: l.display_type == 'payment_term').sorted(lambda l: l.date_maturity or date.max).grouped('move_id')
        for line in self.filtered(lambda l: l.move_id.inalterable_hash is False):
            if line.display_type == 'payment_term':
                term_lines = term_by_move.get(line.move_id, self.env['account.move.line'])
                n_terms = len(line.move_id.invoice_payment_term_id.line_ids)
                if line.move_id.payment_reference and line.move_id.ref and line.move_id.payment_reference != line.move_id.ref:
                    name = f'{line.move_id.ref} - {line.move_id.payment_reference}'
                else:
                    name = line.move_id.payment_reference or False

                if n_terms > 1:
                    index = term_lines._ids.index(line.id) if line in term_lines else len(term_lines)

                    name = _('%(name)s installment #%(number)s', name=name if name else '', number=index + 1).lstrip()
                if name:
                    line.name = name
            if not line.product_id or line.display_type in ('line_section', 'line_note'):
                continue

            if not line.name or line._origin.name == get_name(line._origin):
                line.name = get_name(line)