# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    
    a3erp_token = fields.Text(
        string='Web Service Token',
        related='company_id.a3erp_token',
        readonly=False)
    a3erp_user = fields.Char(
        string='Usuario',
        related='company_id.a3erp_user',
        readonly=False)
    a3erp_password = fields.Char(
        string='Contraseña',
        related='company_id.a3erp_password',
        readonly=False)
    a3erp_url = fields.Char(
        string='URL WebService',
        related='company_id.a3erp_url',
        readonly=False)
    a3erp_company_id = fields.Integer(
        string='ID Empresa A3',
        related='company_id.a3erp_company_id',
        readonly=False)
    a3erp_note_product_id = fields.Many2one(
        string='Artículo Nota',
        related='company_id.a3erp_note_product_id',
        readonly=False,
        domain=[('cod_articulo_a3','!=', False)])
    a3erp_section_product_id = fields.Many2one(
        string='Artículo Seccion',
        related='company_id.a3erp_section_product_id',
        readonly=False,
        domain=[('cod_articulo_a3','!=', False)])
    a3erp_section_collapsed_product_id = fields.Many2one(
        string='Artículo Seccion Colapsada',
        related='company_id.a3erp_section_collapsed_product_id',
        readonly=False,
        domain=[('cod_articulo_a3','!=', False)])
    
    def authentication_webservice(self):
        return self.env.company.authentication_webservice()
    