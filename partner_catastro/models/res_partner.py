from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    catastro_ref = fields.Char(string='Referencia catastral', copy=False, index=True)
    catastro_last_sync = fields.Datetime(string='Última sincronización', copy=False, readonly=True)
    catastro_sync_state = fields.Selection([
        ('empty', 'Sin datos'),
        ('ok', 'OK'),
        ('error', 'Error'),
    ], string='Estado Catastro', default='empty', copy=False, readonly=True)
    catastro_error = fields.Text(string='Error Catastro', copy=False, readonly=True)
    catastro_raw_payload = fields.Text(string='Payload Catastro', copy=False, readonly=True)
    catastro_url = fields.Char(string='URL Catastro', copy=False, readonly=True)

    catastro_bi_type = fields.Char(string='Tipo de bien', copy=False, readonly=True)
    catastro_province = fields.Char(string='Provincia Catastro', copy=False, readonly=True)
    catastro_municipality = fields.Char(string='Municipio Catastro', copy=False, readonly=True)
    catastro_zip = fields.Char(string='Código postal', copy=False, readonly=True)
    catastro_district = fields.Char(string='Distrito municipal', copy=False, readonly=True)

    # Dirección Catastro simplificada
    catastro_street_type = fields.Char(string='Tipo vía', copy=False, readonly=True)
    catastro_street_name = fields.Char(string='Nombre vía', copy=False, readonly=True)
    catastro_street_number = fields.Char(string='Número', copy=False, readonly=True)
    catastro_block = fields.Char(string='Bloque', copy=False, readonly=True)
    catastro_stair = fields.Char(string='Escalera', copy=False, readonly=True)
    catastro_floor = fields.Char(string='Planta', copy=False, readonly=True)
    catastro_door = fields.Char(string='Puerta', copy=False, readonly=True)

    # Dirección Catastro estructurada
    catastro_street_code = fields.Char(string='Código de vía', copy=False, readonly=True)
    catastro_number_first = fields.Char(string='Primer número', copy=False, readonly=True)
    catastro_number_first_letter = fields.Char(string='Letra primer número', copy=False, readonly=True)
    catastro_number_second = fields.Char(string='Segundo número', copy=False, readonly=True)
    catastro_number_second_letter = fields.Char(string='Letra segundo número', copy=False, readonly=True)
    catastro_km = fields.Char(string='Kilómetro', copy=False, readonly=True)
    catastro_unstructured_address = fields.Char(string='Dirección no estructurada', copy=False, readonly=True)
    catastro_literal_address = fields.Char(string='Domicilio tributario literal', copy=False, readonly=True)
    catastro_finca_literal_address = fields.Char(string='Domicilio de finca', copy=False, readonly=True)

    catastro_use = fields.Char(string='Uso', copy=False, readonly=True)
    catastro_surface = fields.Char(string='Superficie', copy=False, readonly=True)
    catastro_coefficient = fields.Char(string='Coef. participación', copy=False, readonly=True)
    catastro_antiquity = fields.Char(string='Antigüedad', copy=False, readonly=True)

    catastro_coord_x = fields.Char(string='Coord. X', copy=False, readonly=True)
    catastro_coord_y = fields.Char(string='Coord. Y', copy=False, readonly=True)
    catastro_srs = fields.Char(string='SRS', copy=False, readonly=True)

    catastro_line_ids = fields.One2many(
        'res.partner.catastro.line',
        'partner_id',
        string='Campos Catastro',
        copy=False,
    )

    def action_open_catastro_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Importar Catastro',
            'res_model': 'res.partner.catastro.fetch',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': self.id,
                'default_refcat': self.catastro_ref or '',
                'default_province': self.catastro_province or self.state_id.name or '',
                'default_municipality': self.catastro_municipality or self.city or '',
            },
        }

    def _write_catastro_data(self, refcat, payload, coords=None):
        self.ensure_one()
        service = self.env['partner.catastro.service']

        summary = service.extract_summary(payload, coords=coords)
        lines = service.flatten_payload(payload)
        if coords:
            lines += service.flatten_payload(coords, prefix='coordenadas')

        self.write({
            'catastro_ref': refcat,
            'catastro_last_sync': fields.Datetime.now(),
            'catastro_sync_state': 'ok',
            'catastro_error': False,
            'catastro_raw_payload': service.dumps_payload({
                'payload': payload,
                'coords': coords or {},
            }),
            'catastro_url': summary.get('catastro_url'),
            'catastro_bi_type': summary.get('catastro_bi_type'),
            'catastro_province': summary.get('catastro_province'),
            'catastro_municipality': summary.get('catastro_municipality'),
            'catastro_zip': summary.get('catastro_zip'),
            'catastro_district': summary.get('catastro_district'),
            'catastro_street_type': summary.get('catastro_street_type'),
            'catastro_street_name': summary.get('catastro_street_name'),
            'catastro_street_number': summary.get('catastro_street_number'),
            'catastro_block': summary.get('catastro_block'),
            'catastro_stair': summary.get('catastro_stair'),
            'catastro_floor': summary.get('catastro_floor'),
            'catastro_door': summary.get('catastro_door'),
            'catastro_street_code': summary.get('catastro_street_code'),
            'catastro_number_first': summary.get('catastro_number_first'),
            'catastro_number_first_letter': summary.get('catastro_number_first_letter'),
            'catastro_number_second': summary.get('catastro_number_second'),
            'catastro_number_second_letter': summary.get('catastro_number_second_letter'),
            'catastro_km': summary.get('catastro_km'),
            'catastro_unstructured_address': summary.get('catastro_unstructured_address'),
            'catastro_literal_address': summary.get('catastro_literal_address'),
            'catastro_finca_literal_address': summary.get('catastro_finca_literal_address'),
            'catastro_use': summary.get('catastro_use'),
            'catastro_surface': summary.get('catastro_surface'),
            'catastro_coefficient': summary.get('catastro_coefficient'),
            'catastro_antiquity': summary.get('catastro_antiquity'),
            'catastro_coord_x': summary.get('catastro_coord_x'),
            'catastro_coord_y': summary.get('catastro_coord_y'),
            'catastro_srs': summary.get('catastro_srs'),
            'catastro_line_ids': [(5, 0, 0)] + [(0, 0, vals) for vals in lines],
        })

    def _write_catastro_error(self, message):
        self.ensure_one()
        self.write({
            'catastro_last_sync': fields.Datetime.now(),
            'catastro_sync_state': 'error',
            'catastro_error': message,
        })
