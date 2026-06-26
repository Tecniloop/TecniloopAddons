# -*- coding: utf-8 -*-
from odoo import api, models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    @api.model
    def _tl_pos_triple_discount_sale_fields(self):
        """Return sale triple discount fields only when provided by another module.

        This keeps the POS module installable even if the sales triple discount
        module is not installed yet, while automatically using its fields when
        available on sale.order.line.
        """
        return [
            field_name
            for field_name in ("discount1", "discount2", "discount3", "discounting_type")
            if field_name in self._fields
        ]

    @api.model
    def _load_pos_data_fields(self, config):
        fields = super()._load_pos_data_fields(config)
        for field_name in self._tl_pos_triple_discount_sale_fields():
            if field_name not in fields:
                fields.append(field_name)
        return fields

    def _get_sale_order_fields(self):
        fields = super()._get_sale_order_fields()
        for field_name in self._tl_pos_triple_discount_sale_fields():
            if field_name not in fields:
                fields.append(field_name)
        return fields
