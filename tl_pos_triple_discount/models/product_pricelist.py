# -*- coding: utf-8 -*-
from odoo import api, models


class ProductPricelistItem(models.Model):
    _inherit = "product.pricelist.item"

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        for field_name in ("discount2", "discount3"):
            if field_name in self._fields and field_name not in fields_list:
                fields_list.append(field_name)
        return fields_list
