# -*- coding: utf-8 -*-
from odoo import _, models, fields, exceptions


class CertificatePasswordWizard(models.TransientModel):
    _name = 'certificate.password.wizard'
    _description = 'Validate Certificate Password'

    certificate_id = fields.Many2one('digital.certificate', string='Certificate', required=True, readonly=True)
    password = fields.Char(string='Certificate Password', required=True)

    def action_confirm(self):
        self.ensure_one()
        if not self.certificate_id.file:
            raise exceptions.ValidationError(_('You must first upload a .p12 or .pfx file.'))

        self.certificate_id.action_set_password_and_expiry(self.password)
        return {'type': 'ir.actions.act_window_close'}
