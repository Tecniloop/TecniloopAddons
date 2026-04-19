from requests import exceptions as requests_exceptions

from odoo import _, fields, models
from odoo.exceptions import UserError


class ResPartnerCatastroFetch(models.TransientModel):
    _name = 'res.partner.catastro.fetch'
    _description = 'Importar Catastro para partner'

    partner_id = fields.Many2one('res.partner', string='Contacto', required=True)
    refcat = fields.Char(string='Referencia catastral', required=True)
    province = fields.Char(string='Provincia')
    municipality = fields.Char(string='Municipio')
    fetch_coordinates = fields.Boolean(string='Traer coordenadas', default=True)
    srs = fields.Char(string='SRS', default='EPSG:4326')

    def action_fetch(self):
        self.ensure_one()
        refcat = (self.refcat or '').strip().upper()
        if not refcat:
            raise UserError(_('La referencia catastral es obligatoria.'))

        service = self.env['partner.catastro.service']
        try:
            payload = service.consulta_dnprc(
                refcat=refcat,
                province=self.province,
                municipality=self.municipality,
            )

            coords = False
            if self.fetch_coordinates:
                coords = service.consulta_cpmrc(
                    refcat14=refcat[:14],
                    province=self.province,
                    municipality=self.municipality,
                    srs=self.srs,
                )

            self.partner_id._write_catastro_data(
                refcat=refcat,
                payload=payload,
                coords=coords,
            )
        except requests_exceptions.HTTPError as exc:
            message = _('Error HTTP consultando Catastro: %s') % str(exc)
            self.partner_id._write_catastro_error(message)
            raise UserError(message) from exc
        except requests_exceptions.RequestException as exc:
            message = _('No se pudo conectar con Catastro: %s') % str(exc)
            self.partner_id._write_catastro_error(message)
            raise UserError(message) from exc
        except Exception as exc:
            message = str(exc)
            self.partner_id._write_catastro_error(message)
            raise

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'view_mode': 'form',
            'res_id': self.partner_id.id,
            'target': 'current',
        }
