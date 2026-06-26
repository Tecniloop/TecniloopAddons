# -*- coding: utf-8 -*-
from odoo import api, models


class ProductPricelist(models.Model):
    _inherit = "product.pricelist"

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        if "discount_policy" in self._fields and "discount_policy" not in fields_list:
            fields_list.append("discount_policy")
        return fields_list


class ProductPricelistItem(models.Model):
    _inherit = "product.pricelist.item"

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        for field_name in ("discount2", "discount3"):
            if field_name in self._fields and field_name not in fields_list:
                fields_list.append(field_name)
        return fields_list
