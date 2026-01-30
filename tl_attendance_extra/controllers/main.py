# controllers/main.py
from odoo import http
from odoo.http import request
from odoo import fields
from odoo.tools import float_round
from odoo.tools.image import image_data_uri
import datetime
from odoo.addons.hr_attendance.controllers.main import HrAttendance

class HrAttendanceInherit(HrAttendance):
    """
    Heredamos el controlador de asistencias para inyectar datos personalizados
    en el menú superior (systray) de la aplicación.
    """
    
    @staticmethod
    def _get_user_attendance_data(employee):
        """
        Sobreescribimos este método para incluir el saldo de la bolsa de horas
        en el paquete de datos inicial que recibe el frontend.
        Esto evita problemas de permisos y asegura la visibilidad de saldos negativos.
        """
        res = HrAttendance._get_user_attendance_data(employee)
        if employee:
            res.update({
                'overtime_balance_display': employee.overtime_balance_display,
                'overtime_balance': employee.sudo().total_overtime or 0.0,
            })
        return res

    @http.route('/tl_attendance_extra/custom_check_in_out', type='json', auth='user')
    def custom_check_in(self, work_location, extra_hours_required=False, latitude=False, longitude=False):
        employee = request.env.user.employee_id
        #geo_info = None
        #if latitude and longitude:
        geo_info = HrAttendance._get_geoip_response(
            mode='systray',
            latitude=latitude,
            longitude=longitude,
        )

        custom_vals = {
            'work_location': work_location,
        }
        
        if extra_hours_required:
            custom_vals['extra_hours_required'] = True

        employee.with_context(custom_vals=custom_vals)._attendance_action_change(
            geo_information=geo_info
        )
        
        return HrAttendance._get_employee_info_response(employee)