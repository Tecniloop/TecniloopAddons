from odoo import api, models
from odoo.tools.mail import email_normalize, email_split_and_format_normalize


class MailComposeMessage(models.TransientModel):
    _inherit = "mail.compose.message"

    def _mail_cc_bcc_partner_creation_values(self, email_inputs):
        additional_values = {}
        for email_input in email_inputs:
            normalized = email_normalize(email_input, strict=False) or email_input
            if normalized:
                additional_values[normalized] = {"mail_cc_bcc_auto_created": True}
        return additional_values

    def _mail_cc_bcc_partners_from_raw(self, emails_raw):
        """Find/create partners from raw mail.message incoming_email_cc strings."""
        email_inputs = email_split_and_format_normalize(emails_raw or "")
        if not email_inputs:
            return self.env["res.partner"]
        partners = self.env["res.partner"]._find_or_create_from_emails(
            email_inputs,
            additional_values=self._mail_cc_bcc_partner_creation_values(email_inputs),
        )
        if not isinstance(partners, list):
            partners = [partners]
        partner_records = self.env["res.partner"]
        for partner in partners:
            partner_records |= partner
        return partner_records

    def _mail_cc_bcc_reply_recipients_from_parent(self):
        """Return CC/BCC partner recordsets to reuse for a reply composer."""
        self.ensure_one()
        parent = self.parent_id
        cc_partners = parent.recipient_cc_ids
        # Backward compatibility for messages received before this module was
        # installed: use the raw core incoming_email_cc field as fallback.
        cc_partners |= self._mail_cc_bcc_partners_from_raw(parent.incoming_email_cc)
        bcc_partners = parent.recipient_bcc_ids
        return cc_partners, bcc_partners

    @api.depends(
        "composition_mode",
        "composition_comment_option",
        "parent_id",
        "parent_id.recipient_cc_ids",
        "parent_id.recipient_bcc_ids",
        "parent_id.incoming_email_cc",
        "template_id",
    )
    def _compute_partner_cc_bcc_ids(self):
        """Fix reply prefill for OCA CC/BCC fields.

        mail_composer_cc_bcc already handles template CC/BCC.  For replies, this
        module reuses the parent mail.message recipient_cc_ids/recipient_bcc_ids,
        plus raw incoming_email_cc as a migration fallback.
        """
        reply_composers = self.filtered(
            lambda composer: composer.composition_mode == "comment"
            and composer.parent_id
            and not composer.template_id
        )
        other_composers = self - reply_composers
        if other_composers:
            super(MailComposeMessage, other_composers)._compute_partner_cc_bcc_ids()

        for composer in reply_composers:
            cc_partners, bcc_partners = composer._mail_cc_bcc_reply_recipients_from_parent()
            composer.partner_cc_ids = cc_partners
            composer.partner_bcc_ids = bcc_partners

    @api.depends(
        "composition_mode",
        "composition_comment_option",
        "model",
        "parent_id",
        "partner_cc_ids",
        "partner_bcc_ids",
        "res_domain",
        "res_ids",
        "template_id",
    )
    def _compute_partner_ids(self):
        """Avoid duplicated recipients in To when they are already in CC/BCC."""
        super()._compute_partner_ids()
        for composer in self.filtered(lambda composer: composer.composition_mode == "comment"):
            cc_bcc_partners = composer.partner_cc_ids | composer.partner_bcc_ids
            if cc_bcc_partners:
                composer.partner_ids = composer.partner_ids - cc_bcc_partners

    def _mail_cc_bcc_apply_parent_reply_recipients(self):
        """Ensure values are correct at send time even if computes were stale."""
        for composer in self.filtered(
            lambda item: item.composition_mode == "comment" and item.parent_id
        ):
            cc_partners, bcc_partners = composer._mail_cc_bcc_reply_recipients_from_parent()
            composer.partner_cc_ids = composer.partner_cc_ids | cc_partners
            composer.partner_bcc_ids = composer.partner_bcc_ids | bcc_partners
            composer.partner_ids = composer.partner_ids - (
                composer.partner_cc_ids | composer.partner_bcc_ids
            )

    def _action_send_mail_comment(self, res_ids):
        self._mail_cc_bcc_apply_parent_reply_recipients()
        return super()._action_send_mail_comment(res_ids)
