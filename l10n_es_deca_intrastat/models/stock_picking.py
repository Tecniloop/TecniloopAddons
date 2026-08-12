# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from collections import OrderedDict

from odoo import models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _deca_compute_goods_nature(self, moves):
        source = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("l10n_es_deca.goods_nature_source", default="sale_line")
        )
        if source != "cn8":
            return super()._deca_compute_goods_nature(moves)
        return self._deca_goods_nature_by_cn8(moves)

    def _deca_goods_nature_by_cn8(self, moves):
        """Group moves by CN8 code and sum quantities per code and UoM.

        A move without a resolvable CN8 code (no H.S. code on the product nor
        on its category) falls back to the product's own description, so the
        text always covers every move even on a partially-classified catalog.
        """
        self.ensure_one()
        groups = OrderedDict()
        for move in moves:
            hs_code = move.product_id.get_hs_code_recursively()
            uom = move.product_uom
            if hs_code:
                key = (hs_code.id, uom.id)
                label = f"{hs_code.local_code} {hs_code.description or ''}".strip()
            else:
                key = (f"product-{move.product_id.id}", uom.id)
                label = move.product_id.display_name
            entry = groups.setdefault(key, {"label": label, "quantity": 0.0, "uom": uom})
            entry["quantity"] += move.product_uom_qty
        lines = []
        for entry in groups.values():
            quantity = entry["quantity"]
            quantity_label = (
                str(int(quantity)) if quantity == int(quantity) else f"{quantity:g}"
            )
            lines.append(f"{entry['label']} {quantity_label} {entry['uom'].name}".strip())
        return "\n".join(lines)
