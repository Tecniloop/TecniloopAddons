# Copyright 2026 Custom Development
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import fields, models
from odoo.exceptions import UserError

from .icecat_api import IcecatClient, IcecatError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    icecat_username = fields.Char(
        config_parameter="product_icecat.username",
    )
    icecat_password = fields.Char(
        config_parameter="product_icecat.password",
    )
    icecat_language = fields.Selection(
        selection=[
            ("EN", "English"),
            ("ES", "Spanish"),
            ("FR", "French"),
            ("DE", "German"),
            ("IT", "Italian"),
            ("NL", "Dutch"),
            ("PT", "Portuguese"),
        ],
        string="Icecat Data Language",
        config_parameter="product_icecat.language",
        default="EN",
        help="Language requested from Icecat for product titles, "
        "descriptions and technical features. The category taxonomy sync "
        "is always kept in English regardless of this setting.",
    )

    def action_icecat_test_connection(self):
        self.ensure_one()
        if not self.icecat_username or not self.icecat_password:
            raise UserError(
                self.env._("Please enter both the Icecat username and password first.")
            )
        client = IcecatClient(
            username=self.icecat_username,
            password=self.icecat_password,
            language=self.icecat_language or "EN",
        )
        try:
            client.test_connection()
        except IcecatError as exc:
            raise UserError(str(exc)) from exc

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Success"),
                "message": self.env._("The Icecat account credentials are valid."),
                "type": "success",
                "sticky": False,
            },
        }
