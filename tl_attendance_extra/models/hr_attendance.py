from odoo import models, fields, api, exceptions, _
import datetime
from datetime import datetime
from dateutil.relativedelta import relativedelta

class HrAttendance(models.Model):
    _inherit = "hr.attendance"
    
    extra_hours_required = fields.Boolean(string="Horas extra requeridas")
    work_location = fields.Selection([
        ('office', 'Oficina'),
        ('home', 'Teletrabajo'),
    ], string="Ubicación", track_visibility='onchange')
    real_extra_hours = fields.Float(string="Horas extras reales", compute="_compute_real_extra_hours", inverse="_inverse_real_extra_hours", store=True, readonly=False, track_visibility='onchange')
    extra_hours_payroll = fields.Boolean(string='En nómina', help="Indica si esta hora extra se paga en nómina")
    validated_attendance = fields.Boolean(string="Asistencia Validada", default=False, track_visibility='onchange')
    time_off_hours = fields.Boolean(help="Se ha seleccionado las horas para bolsa de horas.", default=False)    
    hr_allocation_id = fields.Many2one(
        'hr.leave.allocation',
        string='Asignación de horas extra',
    )    
    
    def _cron_auto_check_out_all(self, checkout_time=None):
        """Metodo para cerrar automaticamente las asistencias abiertas. Se ejecuta con una accion planificada."""
        to_verify = self.env['hr.attendance'].search(
            [
                ('check_out', '=', False),
                ('employee_id.active', '=', True)
            ]
        )
        if not to_verify:
            return
        
        checkout_hour = datetime.strptime(checkout_time, "%H:%M").time() if checkout_time else datetime.strptime(datetime.now().strftime('%H:%M'), "%H:%M").time()
        
        check_out = datetime.combine(fields.Date.today(), checkout_hour) or fields.Datetime.now()
        
        body = _('Esta asistencia se ha cerrado automáticamente porque no se realizó el cierre manual.')
        for openatt in to_verify:
            openatt.sudo().write({
                "check_out": (check_out + relativedelta(hours=-1)).strftime('%Y-%m-%d %H:%M:%S'),
                "out_mode": "auto_check_out"
            })
            
            openatt.message_post(body=body)
    
    @api.onchange('work_location')
    def _onchange_work_location(self):
        if self.work_location:
            self.employee_id._compute_work_location_count({'work_location': self.work_location})
    
    @api.depends('check_in', 'check_out', 'extra_hours_required')
    def _compute_real_extra_hours(self):
        for attendance in self:
            if attendance.check_in and attendance.check_out:
                if attendance.extra_hours_required:
                    attendance.real_extra_hours = attendance.worked_hours
                    attendance.update({
                        'overtime_hours': 0.0,
                        'validated_overtime_hours': 0.0
                    })
                else:
                    attendance.real_extra_hours = 0.0
            else:
                attendance.real_extra_hours = 0.0

    def _inverse_real_extra_hours(self):
        for attendance in self:
            if attendance.extra_hours_required:
                attendance.write({
                    'overtime_hours': 0.0,
                    'validated_overtime_hours': 0.0
                })
                
    def button_asing_extra_hours(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Asignar Horas Extra'),
            'res_model': 'extra.hours.assign.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_attendance_id': self.id
            }
        }
    
    def button_undo_free_time_assign(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Deshacer Assignacón Erronea'),
            'res_model': 'undo.allocation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_employee_id': self.employee_id.id,
                'default_attendance_id': self.id,
                'default_hr_leave_allocation_id': self.hr_allocation_id.id
            }
        }