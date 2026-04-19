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

        error_count = self._extract_error_count(payload)
        explicit_messages = self._collect_explicit_error_messages(payload)
        if error_count or explicit_messages:
            message = '\n'.join(explicit_messages) if explicit_messages else self.dumps_payload(payload)[:4000]
            raise UserError(_('Respuesta de Catastro con error:\n%s') % message)

    def _extract_error_count(self, value):
        if isinstance(value, dict):
            control = value.get('control')
            if isinstance(control, dict):
                for key in ('cuerr', 'cuer', 'cuerror', 'numerr'):
                    raw = control.get(key)
                    if raw not in (None, '', False):
                        try:
                            return int(raw)
                        except Exception:
                            pass
            for child in value.values():
                count = self._extract_error_count(child)
                if count:
                    return count
        elif isinstance(value, list):
            for item in value:
                count = self._extract_error_count(item)
                if count:
                    return count
        return 0

    def _collect_explicit_error_messages(self, value):
        messages = []
        self._collect_error_messages_recursive(value, messages)
        cleaned = []
        seen = set()
        for msg in messages:
            msg = (msg or '').strip()
            if not msg:
                continue
            if msg not in seen:
                seen.add(msg)
                cleaned.append(msg)
        return cleaned

    def _collect_error_messages_recursive(self, value, messages):
        if isinstance(value, dict):
            for key, child in value.items():
                lowered = str(key).lower()
                if lowered in {'des', 'desc', 'descripcion', 'descripcionerr', 'err', 'error'} and isinstance(child, str):
                    lower_child = child.lower()
                    if any(token in lower_child for token in ('error', 'no existe', 'obligatoria', 'obligatorio', 'incorrect')):
                        messages.append(child)
                else:
                    self._collect_error_messages_recursive(child, messages)
        elif isinstance(value, list):
            for item in value:
                self._collect_error_messages_recursive(item, messages)

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
            while isinstance(cur, list):
                cur = cur[0] if cur else default
            if not isinstance(cur, dict):
                return default
            cur = cur.get(key, default)
            if cur is default:
                return default
        while isinstance(cur, list):
            cur = cur[0] if cur else default
        return cur

    def _first_value(self, data, candidate_paths, default=None):
        for path in candidate_paths:
            if isinstance(path, str):
                path = (path,)
            value = self._dig(data, *path, default=None)
            if value not in (None, '', [], {}):
                if isinstance(value, (list, dict)):
                    continue
                return value
        return default

    def _find_first_dict_with_any_keys(self, value, keys):
        wanted = set(keys)
        if isinstance(value, dict):
            if wanted.intersection(value.keys()):
                return value
            for child in value.values():
                found = self._find_first_dict_with_any_keys(child, keys)
                if found:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = self._find_first_dict_with_any_keys(item, keys)
                if found:
                    return found
        return {}

    def _extract_bi(self, payload):
        return self._dig(payload, 'consulta_dnp', 'bico', 'bi', default={}) or {}

    def _extract_address_dict(self, payload):
        bi = self._extract_bi(payload)

        for path in (
            ('dt', 'locs', 'lous', 'lourb'),
            ('dt', 'locs', 'lors', 'lourb'),
            ('dt', 'lourb'),
        ):
            value = self._dig(bi, *path, default=None)
            if isinstance(value, dict):
                return value
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value[0]

        return self._find_first_dict_with_any_keys(bi, {'tv', 'nv', 'pnp', 'dp', 'bq', 'es', 'pt', 'pu'}) or {}

    def _extract_geo_dict(self, coords):
        for path in (
            ('consulta_coordenadas', 'coordenadas', 'coord', 'geo'),
            ('coordenadas', 'coord', 'geo'),
            ('coord', 'geo'),
            ('geo',),
        ):
            value = self._dig(coords, *path, default=None)
            if isinstance(value, dict):
                return value
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value[0]

        return self._find_first_dict_with_any_keys(coords, {'xcen', 'ycen', 'srs'}) or {}

    def extract_summary(self, payload, coords=None):
        bi = self._extract_bi(payload)
        address = self._extract_address_dict(payload)
        geo = self._extract_geo_dict(coords or {}) if coords else {}

        summary = {
            'catastro_bi_type': self._first_value(bi, [
                ('idbi', 'cn'),
                ('cn',),
            ]),
            'catastro_province': self._first_value(bi, [
                ('dt', 'np'),
                ('np',),
            ]),
            'catastro_municipality': self._first_value(bi, [
                ('dt', 'nm'),
                ('nm',),
            ]),
            'catastro_street_type': self._first_value(address, [
                ('dir', 'tv'),
                ('tv',),
            ]),
            'catastro_street_name': self._first_value(address, [
                ('dir', 'nv'),
                ('nv',),
                ('ldt',),
            ]),
            'catastro_street_number': self._first_value(address, [
                ('dir', 'pnp'),
                ('pnp',),
            ]),
            'catastro_block': self._first_value(address, [
                ('loint', 'bq'),
                ('bq',),
            ]),
            'catastro_stair': self._first_value(address, [
                ('loint', 'es'),
                ('es',),
            ]),
            'catastro_floor': self._first_value(address, [
                ('loint', 'pt'),
                ('pt',),
            ]),
            'catastro_door': self._first_value(address, [
                ('loint', 'pu'),
                ('pu',),
            ]),
            'catastro_zip': self._first_value(address, [
                ('dp',),
            ]),
            'catastro_use': self._first_value(bi, [
                ('debi', 'luso'),
                ('luso',),
            ]),
            'catastro_surface': self._first_value(bi, [
                ('debi', 'sfc'),
                ('sfc',),
                ('lcons', 'cons', 'dfcons', 'stl'),
            ]),
            'catastro_coefficient': self._first_value(bi, [
                ('debi', 'cpt'),
                ('cpt',),
            ]),
            'catastro_antiquity': self._first_value(bi, [
                ('debi', 'ant'),
                ('ant',),
            ]),
        }

        if geo:
            summary.update({
                'catastro_coord_x': self._first_value(geo, [('xcen',)]),
                'catastro_coord_y': self._first_value(geo, [('ycen',)]),
                'catastro_srs': self._first_value(geo, [('srs',)]),
            })

        return summary
