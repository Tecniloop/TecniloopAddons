from odoo import models, fields, api
from dateutil.relativedelta import relativedelta


class SaleOrder(models.Model):

    _inherit = 'sale.order'

    client_delivery_date = fields.Date(string="Fecha entrega cliente", store=True)
    
    confirmation_date = fields.Date(string="Fecha de confirmación", store=True)

    week_commitment_date = fields.Integer(string="Plazo estàndar de entrega (Semanas)", store=True)

    production_confirmation_date = fields.Date(string="Fecha Confirmación Fábrica", store=True)

    #camp check box para bloquear precio oferta
    lock_price = fields.Boolean(string="Bloquear Precio", default=False)

    #heredar camp del modulo OCA sale_global_discount per cambiar com es mostra a la vista de venta.
    amount_global_discount = fields.Monetary(string="Coste envío")



    @api.onchange('week_commitment_date', 'date_order')
    def _onchange_week_commitment_date(self):
        for order in self:
            if order.week_commitment_date and order.date_order:
                order.commitment_date = order.date_order + relativedelta(weeks=order.week_commitment_date)

    @api.onchange('commitment_date')
    def _onchange_commitment_date(self):
        for order in self:
            if order.commitment_date and order.date_order:
                delta = order.commitment_date.date() - order.date_order.date()
                order.week_commitment_date = delta.days // 7

