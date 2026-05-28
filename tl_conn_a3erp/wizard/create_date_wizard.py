from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
import re

class CreateDateWizard(models.TransientModel):
    _name = 'create.date.wizard'
    _description = 'Wizard para informar de la fecha de alta y modificación'

    create_date_a3erp = fields.Datetime(string='Fecha de Alta')
    update_date_a3erp = fields.Datetime(string='Fecha de Modificación')    
    date_field_a3erp = fields.Char(string='Campo por el que buscar', help="Ejemplo: 'CAR1', 'CAR3', 'CAR7'")    
    
    @api.constrains('date_field_a3erp')
    def _check_date_field_a3erp(self):
        pattern = r'^CAR\d+$'
        for rec in self:
            if rec.date_field_a3erp and not re.match(pattern, rec.date_field_a3erp):
                raise ValidationError(
                    "El campo debe tener formato 'CAR' seguido de un número. Ejemplo: CAR1, CAR3, CAR7."
                )

    def confirm_button(self):
        objct = self.env['a3erp.button.import'].browse(self._context.get('active_id'))
        if self.create_date_a3erp and not self.update_date_a3erp:
            objct.with_context(
                button_name='importar_date', 
                fecha_alta=self.create_date_a3erp
            ).button_productos()
        elif self.update_date_a3erp:
            objct.with_context(
                button_name='importar_date_mod', 
                fecha_mod=self.update_date_a3erp,
                campo=self.date_field_a3erp
            ).button_productos()

        return {"type": "ir.actions.act_window_close"}
