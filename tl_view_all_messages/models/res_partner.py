from odoo import models, fields, api

class ResPartner(models.Model):
    _inherit = 'res.partner'

    message_count_all = fields.Integer(
        string="Mensajes",
        compute="_compute_message_count_all"
    )

    def _get_all_messages_domain(self, partner_ids):
        return [
            '|', '|',
            ('author_id', 'in', partner_ids),
            ('notification_ids.res_partner_id', 'in', partner_ids),
            '&', ('model', '=', 'res.partner'), ('res_id', 'in', partner_ids),
        ]

    def _compute_message_count_all(self):
        for partner in self:
            partner_ids = [partner.commercial_partner_id.id] + partner.commercial_partner_id.child_ids.ids
            partner.message_count_all = self.env['mail.message'].sudo().search_count(
                self._get_all_messages_domain(partner_ids)
            )

    def action_view_all_messages(self):
        self.ensure_one()

        partner_ids = [self.commercial_partner_id.id] + self.commercial_partner_id.child_ids.ids

        action = self.env.ref("tl_view_all_messages.action_tl_partner_messages").sudo().read()[0]
        action["domain"] = self._get_all_messages_domain(partner_ids)
        action["context"] = {"tl_bypass_mail_security": True}

        return action