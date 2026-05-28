from odoo import api, fields, models, _
from odoo.exceptions import MissingError, UserError, AccessError

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    activate_obliagtori_products = fields.Boolean(string="", related="company_id.activate_obliagtori_products", readonly=False)
    