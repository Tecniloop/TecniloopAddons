
from odoo import api, fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    extra_hours_factor_attendance = fields.Float(
        string="Factor Dia Libre", 
        default=1.0,
        help="Número al que multiplicar las horas extra asignadas a Vacaciones."
    )
    
    @api.model
    def get_values(self):
        """Get the values from settings."""
        res = super(ResConfigSettings, self).get_values()
        icp_sudo = self.env['ir.config_parameter'].sudo()
        extra_hours_factor_attendance = icp_sudo.get_param('res.config.settings.extra_hours_factor_attendance')
        res.update(
            extra_hours_factor_attendance=extra_hours_factor_attendance,
        )
        return res
    
    def set_values(self):
        """Set the values. The new values are stored in the configuration parameters."""
        res = super(ResConfigSettings, self).set_values()
        self.env['ir.config_parameter'].sudo().set_param(
            'res.config.settings.extra_hours_factor_attendance', self.extra_hours_factor_attendance)
        return res