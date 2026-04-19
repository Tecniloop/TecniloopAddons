import json

import requests

from odoo import _, models
from odoo.exceptions import UserError


class PartnerCatastroService(models.AbstractModel):
    _name = 'partner.catastro.service'
    _description = 'Servicio Catastro'

    def _base_url_callejero(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'partner_catastro.base_url_callejero',
            'https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/COVCCallejero.svc',
        )

    def _base_url_coord(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'partner_catastro.base_url_coord',
            'https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/COVCCoordenadas.svc',
        )

    def _timeout(self):
        value = self.env['ir.config_parameter'].sudo().get_param(
            'partner_catastro.http_timeout',
            default='20',
        )
        try:
            return int(value)
        except Exception:
            return 20

    def dumps_payload(self, payload):
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def consulta_dnprc(self, refcat, province=None, municipality=None):
        refcat = (refcat or '').strip().upper()
        if not refcat:
            raise UserError(_('La referencia catastral es obligatoria.'))

        params = {'RefCat': refcat}
        if province:
            params['Provincia'] = province.strip()
        if municipality:
            params['Municipio'] = municipality.strip()

        response = requests.get(
            f"{self._base_url_callejero()}/json/Consulta_DNPRC",
            params=params,
            timeout=self._timeout(),
        )
        response.raise_for_status()
        payload = response.json()
        self._raise_if_catastro_error(payload)
        return payload

    def consulta_cpmrc(self, refcat14, province=None, municipality=None, srs=None):
        refcat14 = (refcat14 or '').strip().upper()[:14]
        if not refcat14:
            raise UserError(_('La referencia catastral/finca es obligatoria.'))

        params = {'RefCat': refcat14}
        if province:
            params['Provincia'] = province.strip()
        if municipality:
            params['Municipio'] = municipality.strip()
        if srs:
            params['SRS'] = srs.strip()

        response = requests.get(
            f"{self._base_url_coord()}/json/Consulta_CPMRC",
            params=params,
            timeout=self._timeout(),
        )
        response.raise_for_status()
        payload = response.json()
        self._raise_if_catastro_error(payload)
        return payload

    def _raise_if_catastro_error(self, payload):
        if not isinstance(payload, dict):
            raise UserError(_('Respuesta inesperada del servicio Catastro.'))

        text = json.dumps(payload, ensure_ascii=False)
        lowered = text.lower()
        error_markers = ['"err"', '"error"', 'cuerr', 'lerr']
        if any(marker in lowered for marker in error_markers):
            if 'no existe' in lowered or 'error' in lowered or 'err' in lowered:
                raise UserError(_('Respuesta de Catastro con error:\n%s') % text[:4000])

    def flatten_payload(self, data, prefix=''):
        rows = []
        self._flatten(data, rows, prefix=prefix, seq=[0])
        return rows

    def _flatten(self, value, rows, prefix='', seq=None):
        if seq is None:
            seq = [0]

        if isinstance(value, dict):
            for key, val in value.items():
                path = f'{prefix}.{key}' if prefix else key
                self._flatten(val, rows, prefix=path, seq=seq)
            return

        if isinstance(value, list):
            for idx, item in enumerate(value, start=1):
                path = f'{prefix}[{idx}]'
                self._flatten(item, rows, prefix=path, seq=seq)
            return

        seq[0] += 10
        section = prefix.split('.')[0] if prefix else ''
        label = prefix.split('.')[-1] if prefix else 'value'
        rows.append({
            'sequence': seq[0],
            'section': section,
            'path': prefix,
            'label': label,
            'value': '' if value is None else str(value),
        })

    def _dig(self, data, *path, default=None):
        cur = data
        for key in path:
            if isinstance(cur, list):
                cur = cur[0] if cur else default
            if not isinstance(cur, dict):
                return default
            cur = cur.get(key, default)
            if cur is default:
                return default
        if isinstance(cur, list):
            return cur[0] if cur else default
        return cur

    def extract_summary(self, payload, coords=None):
        summary = {
            'catastro_bi_type': self._dig(payload, 'consulta_dnp', 'bico', 'bi', 'idbi', 'cn'),
            'catastro_province': self._dig(payload, 'consulta_dnp', 'bico', 'bi', 'dt', 'np'),
            'catastro_municipality': self._dig(payload, 'consulta_dnp', 'bico', 'bi', 'dt', 'nm'),
            'catastro_street_type': self._dig(payload, 'consulta_dnp', 'bico', 'bi', 'dt', 'locs', 'lous', 'lourb', 'dir', 'tv'),
            'catastro_street_name': self._dig(payload, 'consulta_dnp', 'bico', 'bi', 'dt', 'locs', 'lous', 'lourb', 'dir', 'nv'),
            'catastro_street_number': self._dig(payload, 'consulta_dnp', 'bico', 'bi', 'dt', 'locs', 'lous', 'lourb', 'dir', 'pnp'),
            'catastro_block': self._dig(payload, 'consulta_dnp', 'bico', 'bi', 'dt', 'locs', 'lous', 'lourb', 'loint', 'bq'),
            'catastro_stair': self._dig(payload, 'consulta_dnp', 'bico', 'bi', 'dt', 'locs', 'lous', 'lourb', 'loint', 'es'),
            'catastro_floor': self._dig(payload, 'consulta_dnp', 'bico', 'bi', 'dt', 'locs', 'lous', 'lourb', 'loint', 'pt'),
            'catastro_door': self._dig(payload, 'consulta_dnp', 'bico', 'bi', 'dt', 'locs', 'lous', 'lourb', 'loint', 'pu'),
            'catastro_zip': self._dig(payload, 'consulta_dnp', 'bico', 'bi', 'dt', 'locs', 'lous', 'lourb', 'dp'),
            'catastro_use': self._dig(payload, 'consulta_dnp', 'bico', 'bi', 'debi', 'luso'),
            'catastro_surface': self._dig(payload, 'consulta_dnp', 'bico', 'bi', 'debi', 'sfc'),
            'catastro_coefficient': self._dig(payload, 'consulta_dnp', 'bico', 'bi', 'debi', 'cpt'),
            'catastro_antiquity': self._dig(payload, 'consulta_dnp', 'bico', 'bi', 'debi', 'ant'),
        }

        if coords:
            summary.update({
                'catastro_coord_x': self._dig(coords, 'consulta_coordenadas', 'coordenadas', 'coord', 'geo', 'xcen'),
                'catastro_coord_y': self._dig(coords, 'consulta_coordenadas', 'coordenadas', 'coord', 'geo', 'ycen'),
                'catastro_srs': self._dig(coords, 'consulta_coordenadas', 'coordenadas', 'coord', 'geo', 'srs'),
            })

        return summary
