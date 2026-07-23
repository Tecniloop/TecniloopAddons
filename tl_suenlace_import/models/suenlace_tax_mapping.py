# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import re
import unicodedata

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


LEASE_PRINT_CODES = {"03", "04", "28", "29", "32", "33"}


class SuenlaceTaxMapping(models.Model):
    """Mapeo configurable de impuestos a3 -> account.tax de Odoo.

    La naturaleza de la retención permite distinguir, entre otros, el IRPF
    general del IRPF de arrendamientos cuando ambos tienen el mismo porcentaje.
    """

    _name = "tl.suenlace.tax.mapping"
    _description = "Mapeo de impuestos SUENLACE (a3) a Odoo"
    _order = (
        "company_id, application, tax_kind, retention_nature, percent"
    )

    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
    )
    application = fields.Selection(
        [
            ("sale", "Ventas (repercutido)"),
            ("purchase", "Compras (soportado)"),
        ],
        string="Ámbito",
        required=True,
    )
    tax_kind = fields.Selection(
        [
            ("iva", "IVA"),
            ("recargo", "Recargo de equivalencia"),
            ("retencion", "Retención (IRPF)"),
        ],
        string="Tipo de impuesto",
        required=True,
        default="iva",
    )
    retention_nature = fields.Selection(
        [
            ("none", "No aplicable"),
            ("generic", "Retención general/profesional"),
            ("lease", "Retención de arrendamientos"),
        ],
        string="Naturaleza de retención",
        required=True,
        default="none",
        help=(
            "Solo se utiliza para las retenciones. Los códigos de impreso "
            "SUENLACE vinculados a arrendamientos se tratan de forma separada."
        ),
    )
    percent = fields.Float(
        string="Porcentaje a3", digits=(6, 2), required=True
    )
    tax_id = fields.Many2one(
        "account.tax",
        string="Impuesto Odoo",
        required=True,
        domain="[('company_id', '=', company_id)]",
    )
    entry_account_codes = fields.Char(
        string="Subcuentas a3 en asientos",
        help=(
            "Códigos exactos de subcuentas fiscales de a3, separados por "
            "comas. Solo se usan para interpretar registros tipo 0. Si la "
            "opción de interpretar impuestos está desactivada, estas cuentas "
            "se conservan literalmente y este campo se ignora."
        ),
    )
    active = fields.Boolean(default=True)

    _unique_tax_profile = models.Constraint(
        "UNIQUE(company_id, application, tax_kind, retention_nature, percent)",
        "Ya existe un mapeo para esa combinación de ámbito, tipo, "
        "naturaleza y porcentaje.",
    )

    def _auto_init(self):
        # La versión anterior no incluía retention_nature en la restricción.
        self.env.cr.execute(
            "SELECT to_regclass('public.tl_suenlace_tax_mapping')"
        )
        if self.env.cr.fetchone()[0]:
            self.env.cr.execute(
                "ALTER TABLE tl_suenlace_tax_mapping "
                "DROP CONSTRAINT IF EXISTS tl_suenlace_tax_mapping_uniq"
            )
            self.env.cr.execute(
                "ALTER TABLE tl_suenlace_tax_mapping "
                "DROP CONSTRAINT IF EXISTS tl_suenlace_tax_mapping_uniq_v2"
            )
        return super()._auto_init()

    @api.onchange("tax_kind")
    def _onchange_tax_kind(self):
        for rec in self:
            if rec.tax_kind != "retencion":
                rec.retention_nature = "none"
            elif rec.retention_nature == "none":
                rec.retention_nature = "generic"

    @api.constrains("tax_kind", "retention_nature")
    def _check_retention_nature(self):
        for rec in self:
            if rec.tax_kind == "retencion" and rec.retention_nature == "none":
                raise ValidationError(
                    "Las retenciones deben indicar su naturaleza."
                )
            if rec.tax_kind != "retencion" and rec.retention_nature != "none":
                raise ValidationError(
                    "La naturaleza de retención solo puede utilizarse en "
                    "mapeos de retenciones."
                )

    @api.constrains("company_id", "entry_account_codes", "active")
    def _check_entry_account_codes_unique(self):
        for rec in self:
            if not rec.active or not rec.entry_account_codes:
                continue
            raw_codes = [
                rec._normalize_entry_account_code(code)
                for code in re.split(r"[,;\n]+", rec.entry_account_codes)
                if rec._normalize_entry_account_code(code)
            ]
            if len(raw_codes) != len(set(raw_codes)):
                raise ValidationError(
                    "Una misma subcuenta a3 no puede repetirse dentro del "
                    "mismo mapeo."
                )
            other_mappings = self.search([
                ("id", "!=", rec.id),
                ("company_id", "=", rec.company_id.id),
                ("active", "=", True),
                ("entry_account_codes", "!=", False),
            ])
            clashes = set(raw_codes)
            for other in other_mappings:
                clashes &= other._entry_account_code_set()
                if clashes:
                    raise ValidationError(
                        "La subcuenta a3 %s ya está asignada a otro mapeo "
                        "de impuestos." % sorted(clashes)[0]
                    )
                clashes = set(raw_codes)

    @api.model
    def retention_nature_from_detail(self, detail):
        return (
            "lease"
            if str(detail.get("impreso") or "").strip() in LEASE_PRINT_CODES
            else "generic"
        )

    @staticmethod
    def _normalize_entry_account_code(code):
        return re.sub(r"[^0-9A-Z]", "", (code or "").upper())

    def _entry_account_code_set(self):
        self.ensure_one()
        return {
            self._normalize_entry_account_code(code)
            for code in re.split(r"[,;\n]+", self.entry_account_codes or "")
            if self._normalize_entry_account_code(code)
        }

    @api.model
    def find_for_entry_account(self, company, account_code):
        """Busca un mapeo explícito para una subcuenta fiscal tipo 0.

        El registro tipo 0 no contiene porcentaje ni naturaleza de impuesto.
        Por ello no se realizan deducciones a partir del sufijo de la cuenta:
        solo se convierte una línea cuando la subcuenta figura expresamente
        en ``entry_account_codes``.
        """
        normalized = self._normalize_entry_account_code(account_code)
        if not normalized:
            return self.browse()
        mappings = self.search([
            ("company_id", "=", company.id),
            ("active", "=", True),
            ("entry_account_codes", "!=", False),
        ])
        return mappings.filtered(
            lambda mapping: normalized in mapping._entry_account_code_set()
        )[:1]

    def _entry_repartition_data(self, balance):
        """Devuelve la distribución fiscal adecuada para una línea tipo 0."""
        self.ensure_one()
        tax = self.tax_id
        if not tax or not balance:
            return {}

        # Signo normal de una factura: ventas al Haber, compras al Debe.
        base_sign = -1.0 if self.application == "sale" else 1.0
        tax_rate = tax.amount if tax.amount_type in ("percent", "division") else 0.0
        rate_sign = -1.0 if tax_rate < 0.0 else 1.0
        expected_tax_sign = base_sign * rate_sign
        actual_sign = 1.0 if balance > 0.0 else -1.0
        is_refund = actual_sign != expected_tax_sign

        repartition_lines = (
            tax.refund_repartition_line_ids
            if is_refund
            else tax.invoice_repartition_line_ids
        )
        tax_lines = repartition_lines.filtered(
            lambda line: line.repartition_type == "tax"
            and abs(line.factor_percent or 0.0) > 0.0
        ).sorted(key=lambda line: (not bool(line.account_id), line.sequence, line.id))
        tax_line = tax_lines[:1]
        if not tax_line:
            return {}
        base_lines = repartition_lines.filtered(
            lambda line: line.repartition_type == "base"
        ).sorted(key=lambda line: (line.sequence, line.id))
        base_line = base_lines[:1]

        denominator = (tax_rate / 100.0) * (
            (tax_line.factor_percent or 100.0) / 100.0
        )
        base_amount = balance / denominator if denominator else 0.0
        return {
            "tax": tax,
            "tax_line": tax_line,
            "base_line": base_line,
            "base_amount": base_amount,
            "is_refund": is_refund,
        }

    @api.model
    def find_tax(
        self,
        company,
        application,
        tax_kind,
        percent,
        retention_nature="none",
    ):
        """Devuelve el ``account.tax`` para la combinación dada.

        1) Busca un override manual exacto.
        2) Si no hay regla, cae a una búsqueda automática conservadora.

        Nunca mezcla retenciones generales y de arrendamientos.
        """
        nature = retention_nature if tax_kind == "retencion" else "none"
        domain = [
            ("company_id", "=", company.id),
            ("application", "=", application),
            ("tax_kind", "=", tax_kind),
            ("retention_nature", "=", nature),
            ("percent", "=", percent),
            ("active", "=", True),
        ]
        rule = self.search(domain, limit=1)
        if rule:
            return rule.tax_id
        return self._auto_find_tax(
            company,
            application,
            tax_kind,
            percent,
            retention_nature=nature,
        )

    @api.model
    def _auto_find_tax(
        self,
        company,
        application,
        tax_kind,
        percent,
        retention_nature="none",
    ):
        tax_model = self.env["account.tax"].with_context(active_test=False)
        type_use = "sale" if application == "sale" else "purchase"
        l10n_type = {
            "iva": "sujeto",
            "recargo": "recargo",
            "retencion": "retencion",
        }[tax_kind]
        candidates = tax_model.search(
            [
                ("company_id", "=", company.id),
                ("type_tax_use", "=", type_use),
                ("amount_type", "=", "percent"),
                ("l10n_es_type", "=", l10n_type),
                ("active", "=", True),
            ]
        )
        target = abs(percent)
        candidates = candidates.filtered(
            lambda tax: float_compare(
                abs(tax.amount), target, precision_digits=2
            )
            == 0
        )
        if tax_kind == "retencion":
            candidates = self._filter_retention_candidates(
                candidates, retention_nature
            )
        elif tax_kind == "iva":
            candidates = self._filter_domestic_vat_candidates(candidates)
        return candidates[:1]

    @api.model
    def _filter_retention_candidates(self, candidates, nature):
        def normalized_name(tax):
            return self._normalize_text(
                "%s %s" % (tax.name or "", tax.description or "")
            )

        lease_words = ("ARREND", "ALQUILER", "LEASE")
        if nature == "lease":
            lease_taxes = candidates.filtered(
                lambda tax: any(
                    word in normalized_name(tax) for word in lease_words
                )
            )
            return lease_taxes
        generic = candidates.filtered(
            lambda tax: not any(
                word in normalized_name(tax) for word in lease_words
            )
        )
        return generic

    @api.model
    def _filter_domestic_vat_candidates(self, candidates):
        """Descarta impuestos EU, importación e ISP si existe uno nacional."""
        blocked = (
            " EU ",
            " UE ",
            " INTRA",
            " IMPORT",
            " EXTRACOM",
            " ISP",
            " INVERSION",
            " DUA",
        )

        def is_domestic(tax):
            name = " %s " % self._normalize_text(
                "%s %s" % (tax.name or "", tax.description or "")
            )
            return not any(word in name for word in blocked)

        domestic = candidates.filtered(is_domestic)
        if not domestic:
            return candidates
        # Para una línea sin producto, el impuesto de bienes corrientes es la
        # alternativa más neutra; después, impuesto sin ámbito y servicios.
        return domestic.sorted(
            key=lambda tax: (
                0 if tax.tax_scope == "consu" else 1,
                0 if not tax.tax_scope else 1,
                tax.sequence,
                tax.id,
            )
        )

    @staticmethod
    def _normalize_text(value):
        value = unicodedata.normalize("NFKD", value or "")
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", value.upper()).strip()

    @api.model
    def load_default_mappings(self, company):
        """Crea únicamente mapeos seguros y ausentes para una compañía.

        No modifica registros existentes. Los porcentajes se obtienen de los
        impuestos realmente instalados en el plan contable español.
        """
        created = self.browse()
        skipped = []
        common_rates = {
            "iva": {4.0, 10.0, 21.0},
            "recargo": {0.0, 0.5, 1.4, 5.2},
            "retencion": {
                1.0, 2.0, 7.0, 15.0, 18.0, 19.0, 19.5, 20.0, 21.0, 24.0
            },
        }
        for application in ("sale", "purchase"):
            for tax_kind in ("iva", "recargo", "retencion"):
                natures = (
                    ("generic", "lease")
                    if tax_kind == "retencion"
                    else ("none",)
                )
                for nature in natures:
                    for percent in sorted(common_rates[tax_kind]):
                        if nature == "lease" and percent not in {
                            19.0,
                            19.5,
                            20.0,
                            21.0,
                        }:
                            continue
                        if nature == "generic" and percent == 19.5:
                            # La localización estándar solo define este tipo
                            # histórico como retención de arrendamientos.
                            continue
                        domain = [
                            ("company_id", "=", company.id),
                            ("application", "=", application),
                            ("tax_kind", "=", tax_kind),
                            ("retention_nature", "=", nature),
                            ("percent", "=", percent),
                        ]
                        if self.with_context(active_test=False).search_count(domain):
                            continue
                        tax = self._auto_find_tax(
                            company,
                            application,
                            tax_kind,
                            percent,
                            retention_nature=nature,
                        )
                        if not tax:
                            skipped.append(
                                "%s/%s/%s %.2f%%"
                                % (application, tax_kind, nature, percent)
                            )
                            continue
                        created |= self.create(
                            {
                                "company_id": company.id,
                                "application": application,
                                "tax_kind": tax_kind,
                                "retention_nature": nature,
                                "percent": percent,
                                "tax_id": tax.id,
                            }
                        )
        return {"created": len(created), "skipped": skipped}
