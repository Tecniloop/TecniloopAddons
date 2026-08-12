# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    deca_goods_nature_source = fields.Selection(
        [
            ("sale_line", "Sale order line / picking description"),
            ("cn8", "Intrastat CN8 code, grouped by code and quantity"),
        ],
        string="DeCA goods nature",
        config_parameter="l10n_es_deca.goods_nature_source",
        default="sale_line",
        help=(
            "How the 'Naturaleza' text of new DeCA drafts is built.\n"
            "- Sale order line / picking description: one line per stock move, "
            "using the linked sale order line's description, or the picking's "
            "own product when there is no sale line.\n"
            "- Intrastat CN8 code: one line per CN8 code found in the transfer, "
            "using the CN8 code and its description, with quantities of all "
            "moves sharing that code (and unit of measure) added together."
        ),
    )
