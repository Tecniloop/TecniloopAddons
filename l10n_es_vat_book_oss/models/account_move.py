# Copyright 2025 Tecnativa - Pedro M. Baeza
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def _process_aeat_tax_fee_info(self, res, tax, sign):
        # Nullify tax fee for OSS taxes in the Spanish VAT book.
        result = super()._process_aeat_tax_fee_info(res, tax, sign)
        if not self.env.context.get("calculate_vat_book", False):
            return result
        taxes = tax.children_tax_ids if tax.amount_type == "group" else tax
        company = self.company_id or self.env.company
        for oss_tax in taxes.filtered(
            lambda item: item.oss_country_id
            and (not item.company_id or item.company_id == company)
        ):
            if oss_tax in res:
                res[oss_tax]["amount"] = 0
                res[oss_tax]["deductible_amount"] = 0
        return result
