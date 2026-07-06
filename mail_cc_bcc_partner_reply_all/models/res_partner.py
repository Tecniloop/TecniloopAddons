from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    mail_cc_bcc_auto_created = fields.Boolean(
        string="Created from Mail CC/BCC",
        default=False,
        index=True,
        copy=False,
        help="Technical flag set when the contact was automatically created from "
        "an incoming email CC address so that CC can be stored as a partner and "
        "reused by the OCA CC/BCC composer.",
    )
