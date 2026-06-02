from odoo import api, fields, models, _


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    parseur_qty_count = fields.Integer(string='Cantidad de Parseur', help="Cantidad real que se ha importado desde el parseur, cuando se pasa de la qty ofertada, ya no entra como linia normal.", copy=False)
    
    is_extra_parseur = fields.Boolean(
        default=False,
        help="Indica que la línea fue creada como extra desde Parseur con precio 0. Solo sirve para identificar linias ofertadas."
    )