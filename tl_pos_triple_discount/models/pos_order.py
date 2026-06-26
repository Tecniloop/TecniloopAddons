# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    discount2 = fields.Float(string="Disc. 2 (%)", default=0.0)
    discount3 = fields.Float(string="Disc. 3 (%)", default=0.0)
    discounting_type = fields.Selection(
        selection=[
            ("multiplicative", "Multiplicative"),
            ("additive", "Additive"),
        ],
        string="Discounting Type",
        default="multiplicative",
        required=True,
    )

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        for field_name in ("discount2", "discount3", "discounting_type"):
            if field_name not in fields_list:
                fields_list.append(field_name)
        return fields_list

    def _discount_fields(self):
        return ["discount", "discount2", "discount3"]

    def _additive_discount(self):
        self.ensure_one()
        discount = sum(self[field_name] or 0.0 for field_name in self._discount_fields())
        if discount <= 0:
            return 0.0
        if discount >= 100:
            return 100.0
        return discount

    def _multiplicative_discount(self):
        self.ensure_one()
        discount_factor = 1.0
        for field_name in self._discount_fields():
            discount_factor *= 1.0 - ((self[field_name] or 0.0) / 100.0)
        return 100.0 * (1.0 - discount_factor)

    def _get_final_discount(self):
        self.ensure_one()
        if self.discounting_type == "additive":
            return self._additive_discount()
        return self._multiplicative_discount()

    def _prepare_tax_base_line_values(self):
        base_lines = super()._prepare_tax_base_line_values()
        for base_line in base_lines:
            record = base_line.get("record")
            if getattr(record, "_name", None) == "pos.order.line":
                base_line["discount"] = record._get_final_discount()
        return base_lines


class PosOrder(models.Model):
    _inherit = "pos.order"

    def _get_fields_for_order_line(self):
        fields_list = super()._get_fields_for_order_line()
        for field_name in ("discount2", "discount3", "discounting_type"):
            if field_name not in fields_list:
                fields_list.append(field_name)
        return fields_list

    def _get_invoice_lines_values(self, line_values, pos_line, move_type):
        vals = super()._get_invoice_lines_values(line_values, pos_line, move_type)
        if vals.get("display_type"):
            return vals

        # If account_invoice_triple_discount is installed, preserve the split
        # discounts on invoice lines. For additive lines, write the final
        # discount in discount1 to keep invoice totals aligned because the OCA
        # invoice module only aggregates multiplicatively.
        invoice_line_fields = self.env["account.move.line"]._fields
        if all(field_name in invoice_line_fields for field_name in ("discount1", "discount2", "discount3")):
            if pos_line.discounting_type == "additive":
                vals["discount1"] = pos_line._get_final_discount()
                vals["discount2"] = 0.0
                vals["discount3"] = 0.0
            else:
                vals["discount1"] = pos_line.discount
                vals["discount2"] = pos_line.discount2
                vals["discount3"] = pos_line.discount3
            vals.pop("discount", None)
        else:
            vals["discount"] = pos_line._get_final_discount()
        return vals
