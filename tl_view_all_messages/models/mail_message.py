from odoo import models, fields


class MailMessage(models.Model):
    _inherit = "mail.message"

    model_name = fields.Char(string="Tipo de documento", compute="_compute_model_name")
    message_category = fields.Char(string="Tipo", compute="_compute_message_category")
    is_internal_note = fields.Boolean(compute="_compute_message_category")

    def _compute_model_name(self):
        model_names = {
            model.model: model.name
            for model in self.env['ir.model'].sudo().search([])
        }

        for rec in self:
            rec.model_name = model_names.get(rec.model, rec.model)

    def _compute_message_category(self):
        for rec in self:
            if rec.subtype_id and rec.subtype_id.internal:
                rec.message_category = "Nota interna"
                rec.is_internal_note = True
            elif rec.message_type == 'email':
                rec.message_category = "Email"
                rec.is_internal_note = False
            else:
                rec.message_category = "Mensaje"
                rec.is_internal_note = False

    def _search(self, domain, offset=0, limit=None, order=None):
        if self._context.get('tl_bypass_mail_security'):
            return models.Model._search(self.sudo(), domain, offset=offset, limit=limit, order=order)
        return super()._search(domain, offset=offset, limit=limit, order=order)
