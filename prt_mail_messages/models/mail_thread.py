###################################################################################
#
#    Copyright (C) 2020 Cetmix OÜ
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU LESSER GENERAL PUBLIC LICENSE as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###################################################################################

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


##############################
# Mail.Thread
##############################
class MailThread(models.AbstractModel):
    _inherit = "mail.thread"

    def unlink(self):
        # Remove all messages related to record including trash/archive messages
        self.env["mail.message"].sudo().search(
            [
                ("model", "=", self._name),
                ("res_id", "in", self.ids),
                ("active", "=", False),
            ]
        ).unlink()
        return super().unlink()

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        return super(MailThread, self.with_context(skip_notification=True)).message_new(
            msg_dict, custom_values=custom_values
        )

    def _notify_get_recipients(self, message, msg_vals, **kwargs):
        ICPSudo = self.env["ir.config_parameter"].sudo()
        smart_notify = ICPSudo.get_param("cetmix.mail_incoming_smart_notify")
        if smart_notify and self._context.get("skip_notification"):
            # Skip all notification
            return []
        recipients_data = super()._notify_get_recipients(message, msg_vals, **kwargs)
        recipients = self._context.get("message_recipients")
        # Filtering notification recipients
        # by message recipients from input mail message
        if smart_notify and recipients:
            recipients_data = list(
                filter(lambda p: p.get("id") not in recipients, recipients_data)
            )
        return recipients_data

    @api.model
    def _message_route_process(self, message, message_dict, routes):
        partner_ids = message_dict.pop("partner_ids", [])
        return super(
            MailThread, self.with_context(message_recipients=partner_ids)
        )._message_route_process(message, message_dict, routes)

    @api.model
    def _detect_write_to_catchall(self, msg_dict):
        if (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("cetmix.allow_direct_messages_to_catchall", False)
        ):
            return False
        return super()._detect_write_to_catchall(msg_dict)
