from odoo import models, fields, exceptions, _
from datetime import datetime
import calendar

class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'
    
    home_work_count = fields.Integer(
        string='Contador teletrabajo',
        help="Acumula el número de dias que se teletrabaja.",
        store=True,
        default=0
    )