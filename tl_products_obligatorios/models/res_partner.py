from odoo import api, fields, models

class ResPartner(models.Model):
    _inherit = 'res.partner'

    opcional_obligatorio = fields.Boolean(string="Activar Obligatorios/Canon", track_visibility='onchange', default=True)