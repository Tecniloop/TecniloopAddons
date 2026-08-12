# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    l10n_es_deca_public_base_url = fields.Char(
        string="DeCA public URL",
        config_parameter="l10n_es_deca.public_base_url",
        help=(
            "Clean HTTPS URL used to build each DeCA's public download link "
            "and QR code (TLS 1.2 or newer; no credentials, query or fragment). "
            "Falls back to the general Odoo base URL when left empty."
        ),
    )
