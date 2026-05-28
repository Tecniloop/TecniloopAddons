from odoo import api, fields, models

class ResCompany(models.Model):
    _inherit = 'res.company'

    activate_obliagtori_products = fields.Boolean(string="Activar Obligatoriedad Opionales Ventas")