from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class CreateDateWizard(models.TransientModel):
    _name = 'create.date.wizard'
    _description = 'Wizard para informar de la fecha de alta'

    create_date_a3erp = fields.Datetime(string='Fecha de Alta', required=True)

    def confirm_button(self):
        objct = self.env['a3erp.button.import'].browse(self.env.context.get('active_id'))

        objct.with_context(
            button_name='importar_date', 
            fecha_alta=self.create_date_a3erp
        ).button_productos()

        return {"type": "ir.actions.act_window_close"}
