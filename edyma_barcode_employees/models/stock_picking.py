# -*- coding: utf-8 -*-


import logging
from odoo import models, fields, api
_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Empleados',
        store=True
    )

    def button_validate(self):
        employee_id = self.env.context.get('employee_id', False)
        if employee_id:
            _logger.info("Validación iniciada por el empleado con ID: %s", employee_id)

        if employee_id and self.exists():
            self.write({'employee_id': employee_id})

        res = super(StockPicking, self).button_validate()

        if employee_id and self.exists():
            _logger.info("Empleado %s registrado exitosamente en picking %s.", employee_id, self.id)
        return res
