from odoo import models
from odoo.tools.mail import email_normalize, email_split_and_format_normalize


class MailThread(models.AbstractModel):
    _inherit = "mail.thread"

    def _mail_cc_bcc_partner_creation_values(self, email_inputs):
        """Return additional values for partners auto-created from CC addresses.

        _partner_find_from_emails_single expects a dict keyed by normalized email.
        """
        additional_values = {}
        for email_input in email_inputs:
            normalized = email_normalize(email_input, strict=False) or email_input
            if normalized:
                additional_values[normalized] = {"mail_cc_bcc_auto_created": True}
        return additional_values

    def _mail_cc_bcc_get_link_doc(self, routes):
        """Pick a routed document/environment for partner creation rules.

        This mirrors the link_doc logic used by mail.thread itself so that model-
        specific partner lookup hooks still apply when present.
        """
        for model, thread_id, _custom_values, _user_id, alias in routes or ():
            link_doc = self.env[model].browse(thread_id) if thread_id else self.env[model]
            if (
                not link_doc
                and alias
                and alias.alias_parent_model_id
                and alias.alias_parent_thread_id
            ):
                link_doc = self.env[alias.alias_parent_model_id.model].browse(
                    alias.alias_parent_thread_id
                )
            if link_doc and hasattr(link_doc, "_partner_find_from_emails_single"):
                return link_doc
        return self.env["mail.thread"]

    def _mail_cc_bcc_find_or_create_partners_from_emails(self, email_inputs, routes=None):
        """Find or create partners for normalized email strings."""
        if not email_inputs:
            return self.env["res.partner"]

        link_doc = self._mail_cc_bcc_get_link_doc(routes)
        return link_doc._partner_find_from_emails_single(
            email_inputs,
            no_create=False,
            additional_values=self._mail_cc_bcc_partner_creation_values(email_inputs),
        )

    def _message_parse_post_process(self, message, message_dict, routes):
        """Create partners for incoming CC addresses and store them as OCA CC.

        Core Odoo stores raw incoming CC in incoming_email_cc, and searches
        partners with no_create=True.  This bridge keeps core behavior but also
        creates missing partner records, then stores them in recipient_cc_ids so
        OCA mail_composer_cc_bcc can reuse them in replies.
        """
        values = super()._message_parse_post_process(message, message_dict, routes)

        cc_raw = message_dict.get("cc_filtered") or message_dict.get("cc") or ""
        cc_inputs = email_split_and_format_normalize(cc_raw)
        if not cc_inputs:
            return values

        cc_partners = self._mail_cc_bcc_find_or_create_partners_from_emails(
            cc_inputs,
            routes=routes,
        )
        if not cc_partners:
            return values

        partner_ids = set(values.get("partner_ids") or [])
        partner_ids.update(cc_partners.ids)
        values["partner_ids"] = list(partner_ids)

        recipient_cc_ids = set(values.get("recipient_cc_ids") or [])
        recipient_cc_ids.update(cc_partners.ids)
        values["recipient_cc_ids"] = list(recipient_cc_ids)

        return values
