from odoo import fields, api, models, _
from odoo.exceptions import UserError, ValidationError, MissingError
from datetime import datetime
from dateutil.relativedelta import relativedelta

class ExtraHoursAssignWizard(models.TransientModel):
    _name = 'extra.hours.assign.wizard'
    _description = 'Wizard para asignar horas extra'
    
    attendance_id = fields.Many2one('hr.attendance', string='Asistencia')

    def button_action_remuneration(self):
        attendance = self.attendance_id
        if attendance:
            attendance.sudo().write({
                'time_off_hours': False,
                'extra_hours_payroll': True,
            })
                
    def button_action_free_time(self):
        attendance = self.attendance_id
        if attendance:                            
            # Buscamos el tipo de ausencia "Horas Extra"
            hr_leave_type = self.env['hr.leave.type'].search([
                ('name', 'ilike', 'Horas Extra')
            ], limit=1)
            
            #Si no hay un tipo de ausencia de Horas Extra, no hacer nada.
            if not hr_leave_type:
                raise MissingError(_('No se encontró el tipo de ausencia "Horas Extra". Por favor, cree este tipo de ausencia antes de continuar.'))    
            
            # Factor por el que multiplicar las horas
            factor = self.env['ir.config_parameter'].sudo().get_param('tl_attendance_extra.extra_hours_factor_attendance') or 1.0
            # Recoger las horas a trabajar por dia según el calendario laboral del empleado
            hours_per_day= attendance.employee_id._get_hours_per_day(datetime.now())
            # Calcular los días equivalentes según las horas a trabajar y las horas extra
            dias_equivalentes = (attendance.real_extra_hours * factor) / hours_per_day
            
            hr_allocation = self.env['hr.leave.allocation'].create({
                #'name': _('Horas Extra'),
                'holiday_status_id': hr_leave_type.id,
                'allocation_type': 'regular',
                'date_from': datetime.now(),
                'date_to': datetime.now() + relativedelta(months=4),
                'employee_id': attendance.employee_id.id,
                'number_of_days': dias_equivalentes, 
            })  
            #Mensaje en el chatter de la asignación para saber el origen.
            hr_allocation.message_post_with_source(
                'mail.message_origin_link',
                render_values={'self': hr_allocation, 'origin': attendance},
                subtype_xmlid='mail.mt_note',
            )
            #Actualizar la asignación de la asistencia para tener la relación.
            attendance.sudo().write({
                'time_off_hours': True,
                'extra_hours_payroll': False,
                'hr_allocation_id': hr_allocation.id,
            })