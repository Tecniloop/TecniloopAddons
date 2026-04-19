from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    catastro_base_url_callejero = fields.Char(
        string='URL base servicio Callejero',
        config_parameter='partner_catastro.base_url_callejero',
        default='https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/COVCCallejero.svc',
    )
    catastro_base_url_coord = fields.Char(
        string='URL base servicio Coordenadas',
        config_parameter='partner_catastro.base_url_coord',
        default='https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/COVCCoordenadas.svc',
    )
    catastro_http_timeout = fields.Integer(
        string='Timeout HTTP Catastro (segundos)',
        config_parameter='partner_catastro.http_timeout',
        default=20,
    )
