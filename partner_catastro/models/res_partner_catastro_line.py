from odoo import fields, models


class ResPartnerCatastroLine(models.Model):
    _name = 'res.partner.catastro.line'
    _description = 'Campos Catastro del partner'
    _order = 'sequence, id'

    partner_id = fields.Many2one('res.partner', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    section = fields.Char(string='Sección')
    path = fields.Char(string='Ruta')
    label = fields.Char(string='Campo', required=True)
    value = fields.Text(string='Valor')
