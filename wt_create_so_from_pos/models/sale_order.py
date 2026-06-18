from odoo import models, fields, api
import logging


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    is_pos_created = fields.Boolean(string='Create from POS')

    @api.model
    def create_saleorder_from_pos(self, order_data):
        print("/////////////////////")
        _logger = logging.getLogger(__name__)
        _logger.info("🟢 POS Sale Order API called with: %s", order_data)

        order = self.create({
            "partner_id": order_data.get("partner_id"),
            "order_line": [
                (0, 0, {
                    "product_id": line.get("product_id"),
                    "product_uom_qty": line.get("qty", 0),
                    "price_unit": line.get("price", 0),
                    "discount": line.get("discount", 0),
                }) for line in order_data.get("lines", [])
            ],
        })

        print("✅ Created Sale Order %s (ID %s)", order.name, order.id)

        return {
            "id": order.id,
            "name": order.name,
            "debug": "returned from backend",  # extra field for testing
        }
