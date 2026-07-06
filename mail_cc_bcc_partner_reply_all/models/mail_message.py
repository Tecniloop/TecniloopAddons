from odoo import models
from odoo.addons.mail.tools.discuss import Store


class MailMessage(models.Model):
    _inherit = "mail.message"

    def _to_store_defaults(self, target):
        """Expose OCA CC/BCC partner fields to the chatter recipient popover."""
        field_names = super()._to_store_defaults(target)
        field_names.append(
            Store.Many(
                "recipient_cc_ids",
                "avatar_128",
                dynamic_fields=lambda message: message._get_store_partner_name_fields(),
                sort="id",
                sudo=True,
            )
        )
        # BCC is sensitive.  Only internal users should receive it in the web
        # client store.  Portal/public users can still see normal To/Cc data.
        if target.is_internal(self.env):
            field_names.append(
                Store.Many(
                    "recipient_bcc_ids",
                    "avatar_128",
                    dynamic_fields=lambda message: message._get_store_partner_name_fields(),
                    sort="id",
                    sudo=True,
                )
            )
        return field_names
