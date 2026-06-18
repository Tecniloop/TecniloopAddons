# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    bc3_code = fields.Char(string='BC3 Code', index=True, copy=False)
    bc3_alias_codes = fields.Char(string='BC3 Alias Codes', copy=False)
    bc3_type = fields.Char(string='BC3 Type', copy=False)
    bc3_unit_code = fields.Char(string='BC3 Unit', copy=False)
    bc3_price_date = fields.Date(string='BC3 Price Date', copy=False)
    bc3_source_file = fields.Char(string='BC3 Source File', copy=False)
    bc3_raw_prices_json = fields.Text(string='BC3 Raw Prices', copy=False)
    bc3_technical_json = fields.Text(string='BC3 Technical Data', copy=False)
    bc3_long_description = fields.Html(string='BC3 Long Description', copy=False)


    def action_open_fiebdc_import_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Importar productos BC3 / FIEBDC',
            'res_model': 'fiebdc.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {},
        }
