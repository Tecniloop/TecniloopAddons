# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .fiebdc_parser import sanitize_text


class FiebdcImportBatch(models.Model):
    _name = 'fiebdc.import.batch'
    _description = 'FIEBDC Import Batch'
    _inherit = ['mail.thread']
    _order = 'create_date desc, id desc'

    name = fields.Char(required=True, default='FIEBDC Import', tracking=True)
    manufacturer_id = fields.Many2one('fiebdc.manufacturer', string='Fabricante', index=True)
    zip_filename = fields.Char(string='Archivo fuente')
    bc3_url = fields.Char(string='BC3 URL')
    bc3_url_base = fields.Char(string='URL base BC3')
    bc3_filename = fields.Char(string='BC3 File')
    bc3_encoding = fields.Char(string='BC3 Encoding')
    source_attachment_id = fields.Many2one(
        'ir.attachment',
        string='Archivo fuente guardado',
        readonly=True,
        ondelete='set null',
        help='Copia del BC3/ZIP/RAR usada para poder continuar una importacion por lotes.',
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('partial', 'Partial'),
        ('done', 'Done'),
        ('error', 'Error'),
    ], default='draft', tracking=True)
    batch_size = fields.Integer(string='Registros por lote', default=200)
    processed_concepts = fields.Integer(string='Processed Concepts')
    pending_concepts = fields.Integer(string='Pending Concepts', compute='_compute_line_counts')
    total_concepts = fields.Integer(string='Total Concepts')
    importable_concepts = fields.Integer(string='Importable Concepts')
    created_products = fields.Integer(string='Created Products')
    updated_products = fields.Integer(string='Updated Products')
    skipped_products = fields.Integer(string='Skipped Products')
    attachments_created = fields.Integer(string='Attachments Created')
    warning_count = fields.Integer(string='Warnings')
    error_count = fields.Integer(string='Errors')
    started_at = fields.Datetime(string='Started At')
    finished_at = fields.Datetime(string='Finished At')
    line_ids = fields.One2many('fiebdc.import.line', 'batch_id', string='Lineas de importacion')
    log_ids = fields.One2many('fiebdc.import.log', 'batch_id', string='Logs')

    def _compute_line_counts(self):
        Line = self.env['fiebdc.import.line'].sudo()
        for batch in self:
            batch.pending_concepts = Line.search_count([('batch_id', '=', batch.id), ('state', '=', 'pending')])

    def action_process_next_chunk(self):
        self.ensure_one()
        if not self.manufacturer_id:
            raise UserError(_('This batch is not linked to a manufacturer and cannot be resumed automatically.'))
        self.manufacturer_id._process_import_batch(self, limit=self.batch_size or 200)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'fiebdc.import.batch',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_process_ten_chunks(self):
        self.ensure_one()
        if not self.manufacturer_id:
            raise UserError(_('This batch is not linked to a manufacturer and cannot be resumed automatically.'))
        for _i in range(10):
            self.invalidate_recordset()
            if self.state not in ('queued', 'partial', 'running'):
                break
            self.manufacturer_id._process_import_batch(self, limit=self.batch_size or 200)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'fiebdc.import.batch',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def _cron_process_pending_batches(self):
        batches = self.sudo().search([
            ('state', 'in', ('queued', 'partial')),
            ('manufacturer_id', '!=', False),
        ], order='id', limit=3)
        for batch in batches:
            try:
                batch.manufacturer_id._process_import_batch(batch, limit=batch.batch_size or 200)
            except Exception as exc:
                self.env['fiebdc.import.log'].sudo().create({
                    'batch_id': batch.id,
                    'level': 'error',
                    'bc3_code': '',
                    'message': sanitize_text(_('Batch processor failed: %s') % exc),
                })
                batch.write({'state': 'error', 'error_count': batch.error_count + 1, 'finished_at': fields.Datetime.now()})
            self.env.cr.commit()


class FiebdcImportLine(models.Model):
    _name = 'fiebdc.import.line'
    _description = 'FIEBDC Import Line'
    _order = 'batch_id, sequence, id'

    batch_id = fields.Many2one('fiebdc.import.batch', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10, index=True)
    code = fields.Char(string='BC3 Code', index=True)
    name = fields.Char(string='Name')
    concept_json = fields.Text(required=True)
    state = fields.Selection([
        ('pending', 'Pending'),
        ('done', 'Done'),
        ('skipped', 'Skipped'),
        ('error', 'Error'),
    ], default='pending', required=True, index=True)
    product_id = fields.Many2one('product.template', string='Product')
    attachment_count = fields.Integer(string='Attachments')
    message = fields.Text()


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
