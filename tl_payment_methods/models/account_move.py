from odoo import models, api

class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.depends('move_type', 'payment_state', 'invoice_payment_term_id')
    def _compute_show_payment_term_details(self):
        # Mantener la lógica original de Odoo
        super()._compute_show_payment_term_details()

        for invoice in self:
            # Forzar visualización si hay términos de pago y no está pagada
            if not invoice.show_payment_term_details and \
               invoice.move_type in (
                   'out_invoice', 'out_refund',
                   'in_invoice', 'in_refund',
                   'out_receipt', 'in_receipt'
               ) and \
               invoice.payment_state in ('not_paid', 'partial') and \
               invoice.invoice_payment_term_id:

                payment_term_lines = invoice.line_ids.filtered(
                    lambda l: l.display_type == 'payment_term'
                )
                if payment_term_lines:
                    invoice.show_payment_term_details = True
