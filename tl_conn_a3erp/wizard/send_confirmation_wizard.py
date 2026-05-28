from odoo import models, fields

class A3ERPSendConfirmWizard(models.TransientModel):
    _name = 'a3erp.send.confirm.wizard'
    _description = 'Confirmación envío a3ERP'

    message = fields.Text(default="¿Seguro que quieres enviar el documento a a3ERP?")

    def action_confirm(self):
        record = self.env[self.env.context.get('active_model')].browse(self.env.context.get('active_id'))
        return record.action_a3erp_send()

    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}