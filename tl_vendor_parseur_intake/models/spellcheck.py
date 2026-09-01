# Copyright 2026 Tecniloop
# License Other proprietary.

from odoo import fields, models

from .text_utils import normalize_text


def _levenshtein(left, right, max_dist=2):
    if left == right:
        return 0
    if abs(len(left) - len(right)) > max_dist:
        return max_dist + 1
    previous = list(range(len(right) + 1))
    for i, char_l in enumerate(left, start=1):
        current = [i]
        min_row = i
        for j, char_r in enumerate(right, start=1):
            insert = current[j - 1] + 1
            delete = previous[j] + 1
            replace = previous[j - 1] + (char_l != char_r)
            value = min(insert, delete, replace)
            current.append(value)
            if value < min_row:
                min_row = value
        if min_row > max_dist:
            return max_dist + 1
        previous = current
    return previous[-1]


class VendorDocumentIntake(models.Model):
    _inherit = "vendor.document.intake"

    supplier_name_corrected = fields.Char(copy=False)
    spellcheck_log = fields.Text(copy=False)

    def _spellcheck_enabled(self):
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("vendor_parseur_intake.spellcheck", "True")
            == "True"
        )

    def _spellcheck_dictionaries(self):
        Partner = self.env["res.partner"]
        Product = self.env["product.product"]
        Info = self.env["product.supplierinfo"]
        domain_company = [
            "|",
            ("company_id", "=", False),
            ("company_id", "=", self.company_id.id if self.company_id else self.env.company.id),
        ]
        partners = Partner.search(
            [("supplier_rank", ">", 0)] + domain_company, limit=200
        )
        products = Product.search([("purchase_ok", "=", True)], limit=400)
        infos = Info.search([], limit=400)
        partner_terms = {p.name: p for p in partners if p.name}
        product_terms = {p.name: p for p in products if p.name}
        sku_terms = {p.default_code: p for p in products if p.default_code}
        supplier_names = {i.product_name: i for i in infos if i.product_name}
        supplier_codes = {i.product_code: i for i in infos if i.product_code}
        return {
            "partner": partner_terms,
            "product": product_terms,
            "sku": sku_terms,
            "supplier_name": supplier_names,
            "supplier_code": supplier_codes,
        }

    def _correct_term(self, raw, dictionary, max_dist=2):
        if not raw:
            return raw, None
        exact = dictionary.get(raw)
        if exact:
            return raw, None
        norm = normalize_text(raw, ocr=True)
        best = None
        best_dist = max_dist + 1
        best_key = None
        for key in dictionary:
            key_norm = normalize_text(key, ocr=True)
            dist = _levenshtein(norm, key_norm, max_dist=max_dist)
            if dist < best_dist:
                best_dist = dist
                best = dictionary[key]
                best_key = key
            elif dist == best_dist and best_key and key != best_key:
                # Ambiguous correction: do not guess.
                best = None
                best_key = None
        if best is not None and best_dist and best_dist <= max_dist:
            return best_key, best
        return raw, None

    def _run_spellcheck(self):
        self.ensure_one()
        if not self._spellcheck_enabled():
            return
        dictionaries = self._spellcheck_dictionaries()
        notes = []
        if self.supplier_name:
            corrected, record = self._correct_term(
                self.supplier_name, dictionaries["partner"], max_dist=2
            )
            if record and corrected != self.supplier_name:
                self.supplier_name_corrected = corrected
                notes.append("vendor: %s → %s" % (self.supplier_name, corrected))
        for line in self.line_ids:
            if line.sku:
                corrected, record = self._correct_term(
                    line.sku, dictionaries["sku"], max_dist=1
                )
                if not record:
                    corrected, record = self._correct_term(
                        line.sku, dictionaries["supplier_code"], max_dist=1
                    )
                if record and corrected != line.sku:
                    line.sku_corrected = corrected
                    notes.append("sku %s → %s" % (line.sku, corrected))
            if line.description:
                corrected, record = self._correct_term(
                    line.description, dictionaries["supplier_name"], max_dist=2
                )
                if not record:
                    corrected, record = self._correct_term(
                        line.description, dictionaries["product"], max_dist=2
                    )
                if record and corrected != line.description:
                    line.description_corrected = corrected
                    notes.append(
                        "desc %s → %s" % (line.description, corrected)
                    )
        self.spellcheck_log = "\n".join(notes) if notes else False
        if notes:
            self.message_post(body="Spellcheck:\n%s" % "\n".join(notes))
