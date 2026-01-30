from odoo import models, fields, exceptions, _, api
from datetime import datetime
import calendar
import pytz

class HrEmployee(models.Model):
    _inherit = 'hr.employee'
    
    home_work_count = fields.Integer(
        string='Contador teletrabajo',
        help="Acumula el número de dias que se teletrabaja.",
        store=True,
        default=0
    )
    
    hours_current_year = fields.Float(compute='_compute_hours_current_year', groups="hr_attendance.group_hr_attendance_officer,hr.group_hr_user")
    hours_current_year_display = fields.Char(compute='_compute_hours_current_year')

    def _attendance_action_change(self, geo_information=None):
        """ Herdado para actualizar la asistencia con los valores según el boton."""
        attendance = super()._attendance_action_change(geo_information=geo_information)
        
        if self.attendance_state == 'checked_in':
            custom_vals = self.env.context.get('custom_vals', {})            
            # Si no nos llegan valores en custom_vals, es el boton estandard de fichaje.
            if not custom_vals:
                custom_vals.update({
                    'work_location': 'office'
                })                
            
            self._compute_work_location_count(custom_vals)
            
            attendance.update(custom_vals)
        
        return attendance
    
    def _compute_work_location_count(self, values):
        """ Método para actualizar la ubicación de trabajo del empleado al fichar y el contador de teletrabajo."""
        try:
            work_location = values.get('work_location') if values else 'office'
            if work_location in ('office', 'home'):
                work_location_name = 'Oficina' if work_location == 'office' else 'Teletrabajo'

                location = self.env['hr.work.location'].search([('name', 'ilike', work_location_name)], limit=1)
                if location:
                    # Día actual en formato: 'monday', 'tuesday', etc.
                    day_name = datetime.now().strftime('%A').lower()  # Monday → 'monday'

                    # Construimos el nombre del campo ej: monday_location_id
                    location_field = f'{day_name}_location_id'

                    if hasattr(self, location_field):
                        self.write({location_field: location.id})
            
            # Si es teletrabajo añadir al contador de teletrabajo.
            if work_location == 'home':
                self.home_work_count += 1
                
        except Exception as e:
            raise exceptions.UserError(_("Error actualizando el contador y la ubicacion de trabajo: %s") % str(e))
    
    def _compute_hours_current_year(self):
        """
        Computar las horas trabajadas por el empleado desde el 1 de enero hasta la fecha actual.
        """
        now = fields.Datetime.now()
        now_utc = pytz.utc.localize(now)

        for employee in self:
            tz = pytz.timezone(employee.tz or 'UTC')
            now_tz = now_utc.astimezone(tz)

            # Fecha de inicio: 1 de enero a las 00:00 en la zona horaria del empleado
            start_tz = now_tz.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

            # Convertir ambas fechas a UTC naive
            start_naive = start_tz.astimezone(pytz.utc).replace(tzinfo=None)
            end_tz = now_tz.replace(month=12, day=31, hour=23, minute=59, second=59, microsecond=999999)
            end_naive = end_tz.astimezone(pytz.utc).replace(tzinfo=None)

            # Sumar horas trabajadas
            hours = sum(
                att.worked_hours or 0
                for att in employee.attendance_ids.filtered(
                    lambda att: att.check_in >= start_naive and att.check_out and att.check_out <= end_naive
                )
            )

            employee.hours_current_year = round(hours, 2)
            employee.hours_current_year_display = "%g" % employee.hours_current_year
            
    def action_open_last_year_attendances(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Attendances This Year"),
            "res_model": "hr.attendance",
            "views": [[self.env.ref('hr_attendance.hr_attendance_employee_simple_tree_view').id, "list"]],
            "context": {
                "create": 0
            },
            "domain": [
                ('employee_id', '=', self.id),
                ('check_in', ">=", fields.datetime.today().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0))
            ]
        }
    def action_show_home_work_attendances(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Asistencias en Teletrabajo'),
            'res_model': 'hr.attendance',
            "views": [[self.env.ref('hr_attendance.hr_attendance_employee_simple_tree_view').id, "list"]],
            'context': {
                'create': 0,
            },
            'domain': [
                ('employee_id', '=', self.id),
                ('work_location', '=', 'home')
            ],
        }

    # Campo para mostrar el saldo de la bolsa de horas en formato HH:mm.
    # Se calcula con sudo() para que los empleados sin permisos de RRHH puedan ver su propio saldo.
    # No se guarda en base de datos (store=False) para asegurar que siempre esté actualizado con total_overtime.
    overtime_balance_display = fields.Char(
        string='Saldo Bolsa de Horas',
        compute='_compute_overtime_balance_display',
        compute_sudo=True,
        help="Muestra el saldo de 'Bolsa de horas' formateado (HH:mm), permitiendo negativos."
    )

    @api.depends('total_overtime')
    def _compute_overtime_balance_display(self):
        """
        Calcula el saldo de la 'Bolsa de horas' para el empleado basándose en el campo nativo 'total_overtime'.
        Soporta valores negativos y los formatea como una cadena de texto (ej: -2h 15m).
        """
        for employee in self:
            # Usamos sudo() para acceder a total_overtime sin importar los permisos del usuario actual.
            balance_hours = employee.sudo().total_overtime or 0.0

            # Determinamos si el saldo es negativo para aplicar el signo manualmente.
            is_negative = balance_hours < 0
            total_minutes = abs(int(round(balance_hours * 60)))
            hours = total_minutes // 60
            minutes = total_minutes % 60
            
            sign = "-" if is_negative else ""
            employee.overtime_balance_display = f"{sign}{hours}h {minutes:02d}m"
