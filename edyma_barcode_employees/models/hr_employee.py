# -*- coding: utf-8 -*-

from odoo.exceptions import ValidationError
from odoo import models, fields, api

class HrEmployeePrivate(models.Model):
    _inherit = "hr.employee"


    application_code_barcode = fields.Integer(string='Código app barcode', store=True, unique=True)

    @api.constrains('application_code_barcode')
    def _check_unique_application_code_barcode(self):
        for record in self:
            if self.search_count([('application_code_barcode', '=', record.application_code_barcode)]) > 1:
                raise ValidationError("El código de aplicación de código de barras debe ser único.")

    
