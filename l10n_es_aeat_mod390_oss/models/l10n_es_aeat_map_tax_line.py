# Copyright 2022 Sygel - Manuel Regidor
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0

from odoo import models


class L10nEsAeatMapTaxLine(models.Model):
    _inherit = "l10n.es.aeat.map.tax.line"

    def _get_oss_map_lines(self):
        """Return OSS-specific Modelo 390 map lines provided by this module."""
        oss_map_lines = self.browse()
        for xmlid in (
            "l10n_es_aeat_mod390_oss.aeat_mod390_map_line_126",
            "l10n_es_aeat_mod390_oss.aeat_mod390_2024_map_line_126",
        ):
            map_line = self.env.ref(xmlid, raise_if_not_found=False)
            if map_line:
                oss_map_lines |= map_line
        return oss_map_lines

    def get_taxes_for_company(self, company):
        self.ensure_one()
        if self in self._get_oss_map_lines():
            return self.env["account.tax"].search(
                [
                    ("oss_country_id", "!=", False),
                    ("company_id", "=", company.id),
                ]
            )
        return super().get_taxes_for_company(company)
