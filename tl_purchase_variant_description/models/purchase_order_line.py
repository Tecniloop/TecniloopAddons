from odoo import models


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    def _get_product_purchase_description(self, product_lang):
        """Amplía el método que ya usa el núcleo de Odoo para construir la descripción de
        la línea (nombre del producto + "Descripción para el proveedor" de la plantilla).
        Aquí solo se añade, al final, la descripción adicional propia de la VARIANTE
        (product_lang es un product.product, no un product.template), si la tiene.

        product_lang llega con el contexto de idioma/proveedor ya aplicado por el propio
        Odoo (ver purchase.order.line.onchange_product_id / _compute_name en el núcleo),
        así que leer aquí el campo traducible ya devuelve el idioma correcto sin más.
        """
        description = super()._get_product_purchase_description(product_lang)
        if product_lang.purchase_variant_description:
            description += '\n' + product_lang.purchase_variant_description
        return description
