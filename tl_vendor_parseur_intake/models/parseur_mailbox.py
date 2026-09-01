# Copyright 2026 Tecniloop
# License Other proprietary.

from odoo import api, fields, models


class VendorParseurMailbox(models.Model):
    _name = "vendor.parseur.mailbox"
    _description = "Parseur mailbox mapping"
    _order = "name"

    name = fields.Char(required=True)
    code = fields.Char(
        required=True,
        index=True,
        help="Used in the webhook URL: /parseur/vendor/intake/<code>",
    )
    parseur_mailbox_id = fields.Char(
        string="Parseur mailbox ID",
        help="Optional ID shown in Parseur. Used if the payload sends mailbox_id.",
    )
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
        index=True,
    )
    default_document_type = fields.Selection(
        [
            ("delivery_note", "Delivery Note"),
            ("vendor_bill", "Vendor Bill"),
            ("return", "Vendor return"),
            ("vendor_refund", "Vendor refund"),
        ],
        required=True,
        default="vendor_bill",
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Default vendor",
        help="Used when this mailbox is dedicated to one supplier and the VAT is missing.",
    )
    webhook_token = fields.Char(
        help="If set, this mailbox URL only accepts this token. "
        "Otherwise the company Parseur token is used.",
    )
    active = fields.Boolean(default=True)
    note = fields.Text()

    webhook_path = fields.Char(compute="_compute_webhook_path")

    _sql_constraints = [
        ("code_uniq", "unique(code)", "Mailbox code must be unique."),
    ]

    @api.depends("code")
    def _compute_webhook_path(self):
        for rec in self:
            rec.webhook_path = "/parseur/vendor/intake/%s" % (rec.code or "")

    @api.model
    def _from_request(self, code=None, payload=None):
        payload = payload or {}
        Mailbox = self.sudo()
        if code:
            mailbox = Mailbox.search([("code", "=", code), ("active", "=", True)], limit=1)
            if mailbox:
                return mailbox
        raw = (
            payload.get("mailbox_id")
            or payload.get("MailboxID")
            or payload.get("mailbox")
            or payload.get("Mailbox")
        )
        if raw:
            mailbox = Mailbox.search(
                [
                    "|",
                    ("parseur_mailbox_id", "=", str(raw)),
                    ("code", "=", str(raw)),
                    ("active", "=", True),
                ],
                limit=1,
            )
            if mailbox:
                return mailbox
        return Mailbox.browse()
