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

from odoo import api, fields, models


################
# Res.Partner #
################
class Partner(models.Model):
    _inherit = "res.partner"

    messages_from_count = fields.Integer(
        string="Messages From", compute="_compute_messages_count"
    )
    messages_to_count = fields.Integer(
        string="Messages To", compute="_compute_messages_count"
    )

    def _compute_messages_count(self):
        """Compute count messages from/to"""
        MailMessage = self.env["mail.message"]
        message_from = MailMessage._read_group(
            self._prepare_message_domain(record_from_id=self.ids),
            groupby=["author_id"],
            aggregates=["id:recordset"],
        )
        message_from_partner_count = {
            partner.id: len(messages) for partner, messages in message_from
        }
        messages_to = MailMessage._read_group(
            self._prepare_message_domain(record_to_ids=self.ids),
            groupby=["partner_ids"],
            aggregates=["id:recordset"],
        )
        messages_to_partner_count = {
            partner.id: len(messages) for partner, messages in messages_to
        }
        for rec in self:
            rec.update(
                {
                    "messages_from_count": message_from_partner_count.get(rec.id, 0),
                    "messages_to_count": messages_to_partner_count.get(rec.id, 0),
                }
            )

    @api.model
    def _prepare_message_domain(self, record_to_ids=None, record_from_id=None):
        """
        Prepare message domain to display
        :param record_to_ids: recipients partner ids
        :param record_from_id: authors partner ids
        :return: domain
        """
        domain = [
            ("message_type", "in", ["email", "comment", "email_outgoing"]),
            ("model", "!=", "discuss.channel"),
        ]
        author_id_domain = ("author_id", "child_of", record_from_id)
        partner_ids_domain = ("partner_ids", "in", record_to_ids)
        if record_to_ids and record_from_id:
            return [*domain, "|", partner_ids_domain, author_id_domain]
        if record_from_id:
            return [*domain, author_id_domain]
        if record_to_ids:
            return [*domain, partner_ids_domain]
        return domain

    def _domain_by_open_mode(self):
        """Choose what messages to display"""
        return {
            "from": self._prepare_message_domain(record_from_id=self.id),
            "to": self._prepare_message_domain(record_to_ids=self.ids),
            "all": self._prepare_message_domain(self.ids, self.id),
        }

    def partner_messages(self):
        """Open partner related messages"""
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "prt_mail_messages.action_prt_mail_messages"
        )
        action.update(
            context={"check_messages_access": True},
            domain=self._domain_by_open_mode().get(
                self._context.get("open_mode", "all")
            ),
            target="current",
        )
        return action
