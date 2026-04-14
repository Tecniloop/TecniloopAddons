# -*- coding: utf-8 -*-
import base64
import logging
from urllib.request import urlopen
from odoo import _, api, exceptions, fields, models

try:
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography import x509
except Exception:
    pkcs12 = None
    x509 = None

_logger = logging.getLogger(__name__)

ALLOWED_CERTIFICATE_EXTENSIONS = ('.p12', '.pfx')


class DigitalCertificate(models.Model):
    _name = 'digital.certificate'
    _description = 'Digital Certificates'

    name = fields.Char(string='Alias', required=True)
    file = fields.Binary(string='File', required=True)
    internal_filename = fields.Char(string='Internal Filename')
    master_password = fields.Char(string='Master Password')
    expiry_date = fields.Date(string='Expiry Date', readonly=True, copy=False)
    revoked = fields.Boolean(string='Revoked', readonly=True, copy=False, default=False)
    revocation_check_date = fields.Datetime(
        string='Last Revocation Check',
        readonly=True,
        copy=False,
    )
    state = fields.Selection(
        [
            ('active', 'Active'),
            ('expired', 'Expired'),
            ('revoked', 'Revoked'),
        ],
        string='State',
        compute='_compute_state',
        store=True,
    )
    type = fields.Selection([
        ('company', 'Company Certificate'),
        ('personal', 'Personal Certificate')
    ], string='Type', default='personal', required=True)

    @api.depends('revoked', 'expiry_date')
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for certificate in self:
            if certificate.revoked:
                certificate.state = 'revoked'
            elif certificate.expiry_date and certificate.expiry_date < today:
                certificate.state = 'expired'
            else:
                certificate.state = 'active'

    @staticmethod
    def _is_valid_certificate_filename(file_name):
        return bool(file_name and file_name.lower().endswith(ALLOWED_CERTIFICATE_EXTENSIONS))

    def _load_x509_certificate(self, password):
        self.ensure_one()
        if not self.file:
            raise exceptions.ValidationError(_("You must upload a .p12 or .pfx file before validating."))
        if pkcs12 is None:
            raise exceptions.UserError(
                _("Cannot read the certificate because the 'cryptography' dependency is missing.")
            )

        password_bytes = password.encode('utf-8') if password else None
        try:
            _, x509_certificate, _ = pkcs12.load_key_and_certificates(
                base64.b64decode(self.file),
                password_bytes,
            )
        except Exception as error:
            raise exceptions.ValidationError(
                _("Incorrect password or invalid certificate.")
            ) from error

        if not x509_certificate:
            raise exceptions.ValidationError(_("No valid certificate found in the uploaded file."))
        return x509_certificate

    def _get_expiry_date_from_certificate(self, x509_certificate):
        expiry_dt = getattr(x509_certificate, 'not_valid_after_utc', None) or x509_certificate.not_valid_after
        return fields.Date.to_date(expiry_dt)

    def _extract_crl_urls(self, x509_certificate):
        if x509 is None:
            return []
        try:
            extension = x509_certificate.extensions.get_extension_for_class(x509.CRLDistributionPoints)
        except Exception:
            return []

        urls = []
        for distribution_point in extension.value:
            full_name = getattr(distribution_point, 'full_name', None)
            if not full_name:
                continue
            for general_name in full_name:
                if isinstance(general_name, x509.UniformResourceIdentifier):
                    crl_url = (general_name.value or '').strip()
                    if crl_url:
                        urls.append(crl_url)
        return urls

    def _is_certificate_revoked(self, x509_certificate):
        if x509 is None:
            return False

        serial_number = x509_certificate.serial_number
        for crl_url in self._extract_crl_urls(x509_certificate):
            if not crl_url.lower().startswith(('http://', 'https://')):
                continue
            try:
                with urlopen(crl_url, timeout=6) as response:
                    crl_bytes = response.read()
                try:
                    crl = x509.load_der_x509_crl(crl_bytes)
                except Exception:
                    crl = x509.load_pem_x509_crl(crl_bytes)

                revoked = crl.get_revoked_certificate_by_serial_number(serial_number)
                if revoked:
                    return True
            except Exception as error:
                _logger.debug("Could not query CRL %s: %s", crl_url, error)
        return False

    def action_open_password_wizard(self):
        self.ensure_one()
        if not self.file:
            raise exceptions.UserError(_("You must first upload the certificate file."))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Validate certificate password'),
            'res_model': 'certificate.password.wizard',
            'view_mode': 'form',
            'view_id': self.env.ref('l10n_firma_electronica.view_certificate_password_wizard_form').id,
            'target': 'new',
            'context': {
                'default_certificate_id': self.id,
            },
        }

    def action_validate_password(self):
        self.ensure_one()
        if not self.master_password:
            raise exceptions.ValidationError(_("You must enter the password before validating."))
        self.action_set_password_and_expiry(self.master_password)
        return True

    def action_set_password_and_expiry(self, password):
        self.ensure_one()
        x509_certificate = self._load_x509_certificate(password)
        is_revoked = self._is_certificate_revoked(x509_certificate)
        self.write({
            'master_password': password,
            'expiry_date': self._get_expiry_date_from_certificate(x509_certificate),
            'revoked': is_revoked,
            'revocation_check_date': fields.Datetime.now(),
        })
        return True

    def action_check_revocation_status(self):
        for certificate in self:
            if not certificate.file or not certificate.master_password:
                raise exceptions.UserError(_("You must have a file and validated password to check revocation."))
            x509_certificate = certificate._load_x509_certificate(certificate.master_password)
            certificate.write({
                'revoked': certificate._is_certificate_revoked(x509_certificate),
                'revocation_check_date': fields.Datetime.now(),
            })
        return True

    @api.constrains('internal_filename')
    def _validate_file_extension(self):
        for certificate in self:
            if certificate.internal_filename and not self._is_valid_certificate_filename(certificate.internal_filename):
                raise exceptions.ValidationError(
                    _("Only certificates with .p12 or .pfx extension are allowed.")
                )

    def _update_expiry_date(self):
        for certificate in self:
            if not certificate.file or not certificate.master_password:
                certificate.expiry_date = False
                certificate.revoked = False
                certificate.revocation_check_date = False
                continue
            x509_certificate = certificate._load_x509_certificate(certificate.master_password)
            certificate.expiry_date = certificate._get_expiry_date_from_certificate(x509_certificate)
            certificate.revoked = certificate._is_certificate_revoked(x509_certificate)
            certificate.revocation_check_date = fields.Datetime.now()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            file_name = vals.get('internal_filename')
            if file_name and not self._is_valid_certificate_filename(file_name):
                raise exceptions.ValidationError(
                    _("Only certificates with .p12 or .pfx extension are allowed.")
                )
        return super().create(vals_list)

    def write(self, vals):
        file_name = vals.get('internal_filename')
        if file_name and not self._is_valid_certificate_filename(file_name):
            raise exceptions.ValidationError(
                _("Only certificates with .p12 or .pfx extension are allowed.")
            )

        if 'file' in vals and 'master_password' not in vals:
            vals['master_password'] = False
            vals['expiry_date'] = False
            vals['revoked'] = False
            vals['revocation_check_date'] = False

        result = super().write(vals)
        if vals.get('master_password'):
            self._update_expiry_date()
        return result

    @api.onchange('file', 'internal_filename')
    def _onchange_file_certificate(self):
        if self.internal_filename and not self._is_valid_certificate_filename(self.internal_filename):
            raise exceptions.ValidationError(
                _("Only certificates with .p12 or .pfx extension are allowed.")
            )

        self.master_password = False
        self.expiry_date = False
        self.revoked = False
        self.revocation_check_date = False

    def action_get_pfx_bytes(self):
        self.ensure_one()
        if not self.file:
            raise exceptions.UserError(_("The certificate has no attached file."))
        return base64.b64decode(self.file)


class ResUsers(models.Model):
    _inherit = 'res.users'

    user_certificate_assignment_ids = fields.One2many(
        'user.certificate.assignment', 'user_id', string='Certificate Assignments')

    @api.model
    def get_my_assigned_certificates(self):
        current_user = self.env.user
        user_assignments = self.env['user.certificate.assignment'].sudo().search([
            ('user_id', '=', current_user.id)
        ])

        _logger.debug(
            "User %s (%s) has %s assigned certificates",
            current_user.name,
            current_user.id,
            len(user_assignments),
        )

        available_certificates = []
        for assignment in user_assignments:
            certificate = assignment.certificate_id
            type_code = certificate.type
            type_selection = dict(certificate._fields['type']._description_selection(self.env))
            available_certificates.append({
                'id': certificate.id,
                'name': certificate.name,
                'type': type_code,
                'type_label': type_selection.get(type_code, type_code),
            })
        return available_certificates

    @api.model
    def get_my_certificates(self):
        return self.get_my_assigned_certificates()
