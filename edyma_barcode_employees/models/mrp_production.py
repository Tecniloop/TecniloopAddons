# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api
_logger = logging.getLogger(__name__)

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Empleado'
    )

    def button_mark_done(self):
        employee_id = self.env.context.get('employee_id', False)
        if employee_id:
            _logger.info("Producción marcada como completada por el empleado con ID: %s", employee_id)

        if employee_id and self.exists():
            self.write({'employee_id': employee_id})

        res = super(MrpProduction, self).button_mark_done()

        if employee_id and self.exists():
            _logger.info("Empleado %s registrado exitosamente en producción %s.", employee_id, self.id)
        return res
