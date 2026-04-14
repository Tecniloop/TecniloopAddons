# -*- coding: utf-8 -*-
from odoo import models, fields


class ElectronicSignature(models.Model):
    _name = 'electronic.signature'
    _description = 'Electronic Signature'
    _order = 'sign_date desc'

    name = fields.Char(string='Name')
    certificate_id = fields.Many2one(
        'digital.certificate',
        string='Certificate',
        readonly=True,
        ondelete='set null',
    )
    user_id = fields.Many2one(
        'res.users',
        string='Signed by',
        readonly=True,
        ondelete='set null',
    )
    report_ref = fields.Char(string='Report', readonly=True)
    res_model = fields.Char(string='Source Model', readonly=True)
    res_ids = fields.Char(string='Signed Records', readonly=True)
    document_hash = fields.Char(string='SHA256 Hash', readonly=True)
    document = fields.Binary(string='Document')
    sign_date = fields.Datetime(string='Sign Date', default=fields.Datetime.now)
