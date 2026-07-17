from odoo import fields, models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    purchase_variant_description = fields.Text(
        string='Descripción de compra adicional (variante)',
        translate=True,
        help='Texto adicional específico de esta variante que se añade, al seleccionarla en '
             'una línea de pedido de compra, a la descripción de compra de la plantilla de '
             'producto (que es común a todas sus variantes). No la sustituye, la complementa.')
