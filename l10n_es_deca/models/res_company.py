# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    deca_default_carrier_id = fields.Many2one(
        "res.partner",
        string="Default DeCA carrier",
        domain="[('deca_is_carrier', '=', True)]",
        check_company=False,
        help=(
            "Carrier proposed by default when a transfer has no more specific "
            "carrier. The company's own partner can be selected for own-fleet "
            "transport."
        ),
    )
    deca_public_retention_days = fields.Integer(
        string="DeCA public access days after completion",
        default=7,
        help=(
            "Number of natural days the public QR URL remains available after "
            "transport completion."
        ),
    )
