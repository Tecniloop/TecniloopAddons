# -*- coding: utf-8 -*-
from odoo import fields, models


class FiebdcImportBatch(models.Model):
    _name = 'fiebdc.import.batch'
    _description = 'FIEBDC Import Batch'
    _inherit = ['mail.thread']
    _order = 'create_date desc, id desc'

    name = fields.Char(required=True, default='FIEBDC Import', tracking=True)
    manufacturer_id = fields.Many2one('fiebdc.manufacturer', string='Fabricante', index=True)
    zip_filename = fields.Char(string='ZIP File')
    bc3_url = fields.Char(string='BC3 URL')
    bc3_filename = fields.Char(string='BC3 File')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
        ('error', 'Error'),
    ], default='draft', tracking=True)
    total_concepts = fields.Integer(string='Total Concepts')
    importable_concepts = fields.Integer(string='Importable Concepts')
    created_products = fields.Integer(string='Created Products')
    updated_products = fields.Integer(string='Updated Products')
    skipped_products = fields.Integer(string='Skipped Products')
    attachments_created = fields.Integer(string='Attachments Created')
    warning_count = fields.Integer(string='Warnings')
    error_count = fields.Integer(string='Errors')
    log_ids = fields.One2many('fiebdc.import.log', 'batch_id', string='Logs')


class FiebdcImportLog(models.Model):
    _name = 'fiebdc.import.log'
    _description = 'FIEBDC Import Log'
    _order = 'id desc'

    batch_id = fields.Many2one('fiebdc.import.batch', required=True, ondelete='cascade')
    level = fields.Selection([
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ], required=True, default='info')
    bc3_code = fields.Char(string='BC3 Code')
    message = fields.Text(required=True)
