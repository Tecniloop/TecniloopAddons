from odoo import fields, api, models, _

class UndoAllocationWizard(models.TransientModel):
    _name = 'undo.allocation.wizard'
    _description = 'Wizard para revertir asignacion erronea.'
    
    employee_id = fields.Many2one(
        'hr.employee',
        string='Empleado',
    )    
    
    hr_leave_allocation_id = fields.Many2one(
        'hr.leave.allocation',
        string='Asignación',
        domain="[('employee_id', '=', employee_id),('name', 'ilike', 'Horas Extra'), ('state', 'in', ('validate', 'confirm'))]",
    )   
    
    attendance_id = fields.Many2one('hr.attendance', string='Asistencia') 
    
    def button_undo_allocation(self):
        self.hr_leave_allocation_id.action_refuse()
        self.attendance_id.time_off_hours = False
        self.attendance_id.hr_allocation_id = False
        
    