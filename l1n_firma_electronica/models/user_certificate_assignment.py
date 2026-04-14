# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class UserCertificateAssignment(models.Model):
    _name = 'user.certificate.assignment'
    _description = 'User Certificate Assignment'
    _rec_name = 'certificate_id'

    user_id = fields.Many2one('res.users', string='User', required=True, ondelete='cascade')
    certificate_id = fields.Many2one('digital.certificate', string='Certificate', required=True, ondelete='cascade')
    assigned_date = fields.Datetime(string='Assigned Date', default=fields.Datetime.now, readonly=True)
    pin = fields.Char(string='PIN')
    active = fields.Boolean(string='Active', default=True)

    def validate_access(self, pin):
        if not pin:
            raise ValueError(_('PIN is required.'))
        return True
