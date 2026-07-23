# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


class SuenlaceFiscalPositionMapping(models.Model):
    """Mapea el perfil fiscal SUENLACE a una posición fiscal de Odoo."""

    _name = "tl.suenlace.fiscal.position.mapping"
    _description = "Mapeo de posiciones fiscales SUENLACE"
    _order = (
        "company_id, application, invoice_subtype, has_recargo desc, "
        "has_retention desc, retention_nature, retention_percent, sequence, id"
    )

    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
    )
    application = fields.Selection(
        [("sale", "Ventas"), ("purchase", "Compras")],
        string="Ámbito",
        required=True,
    )
    invoice_subtype = fields.Char(
        string="Subtipo SUENLACE",
        size=2,
        help=(
            "Subtipo de factura de las posiciones 100-101 del registro 9. "
            "Déjelo vacío para una regla genérica del mismo ámbito y perfil."
        ),
    )
    has_recargo = fields.Boolean(string="Con recargo de equivalencia")
    has_retention = fields.Boolean(string="Con retención")
    retention_nature = fields.Selection(
        [
            ("none", "No aplicable"),
            ("generic", "Retención general/profesional"),
            ("lease", "Retención de arrendamientos"),
        ],
        string="Naturaleza de retención",
        required=True,
        default="none",
    )
    retention_percent = fields.Float(
        string="% retención",
        digits=(6, 2),
        default=0.0,
        help=(
            "Porcentaje exacto de retención. El valor 0 actúa como regla "
            "genérica para la misma naturaleza."
        ),
    )
    fiscal_position_id = fields.Many2one(
        "account.fiscal.position",
        string="Posición fiscal Odoo",
        required=True,
        domain="[('company_id', 'in', [False, company_id])]",
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "tl_suenlace_fiscal_position_mapping_uniq_v2",
            "unique(company_id, application, invoice_subtype, has_recargo, "
            "has_retention, retention_nature, retention_percent)",
            "Ya existe un mapeo para esa combinación de ámbito, subtipo, "
            "recargo, retención, naturaleza y porcentaje.",
        ),
    ]

    def _auto_init(self):
        self.env.cr.execute(
            "SELECT to_regclass('public.tl_suenlace_fiscal_position_mapping')"
        )
        if self.env.cr.fetchone()[0]:
            self.env.cr.execute(
                "ALTER TABLE tl_suenlace_fiscal_position_mapping "
                "DROP CONSTRAINT IF EXISTS "
                "tl_suenlace_fiscal_position_mapping_uniq"
            )
        return super()._auto_init()

    @api.onchange("has_retention")
    def _onchange_has_retention(self):
        for rec in self:
            if not rec.has_retention:
                rec.retention_nature = "none"
                rec.retention_percent = 0.0
            elif rec.retention_nature == "none":
                rec.retention_nature = "generic"

    @api.constrains(
        "has_retention", "retention_nature", "retention_percent"
    )
    def _check_retention_profile(self):
        for rec in self:
            if rec.has_retention and rec.retention_nature == "none":
                raise ValidationError(
                    "Las posiciones con retención deben indicar su naturaleza."
                )
            if not rec.has_retention and (
                rec.retention_nature != "none"
                or float_compare(
                    rec.retention_percent, 0.0, precision_digits=2
                )
                != 0
            ):
                raise ValidationError(
                    "La naturaleza y el porcentaje solo pueden informarse "
                    "cuando la regla tiene retención."
                )

    @api.constrains(
        "company_id",
        "application",
        "invoice_subtype",
        "has_recargo",
        "has_retention",
        "retention_nature",
        "retention_percent",
    )
    def _check_unique_profile(self):
        for rec in self:
            subtype = (
                (rec.invoice_subtype or "").strip().zfill(2)
                if rec.invoice_subtype
                else False
            )
            subtype_domain = (
                [("invoice_subtype", "=", subtype)]
                if subtype
                else [("invoice_subtype", "in", [False, ""])]
            )
            duplicate = self.with_context(active_test=False).search_count(
                [
                    ("id", "!=", rec.id),
                    ("company_id", "=", rec.company_id.id),
                    ("application", "=", rec.application),
                    ("has_recargo", "=", rec.has_recargo),
                    ("has_retention", "=", rec.has_retention),
                    ("retention_nature", "=", rec.retention_nature),
                    ("retention_percent", "=", rec.retention_percent),
                ]
                + subtype_domain
            )
            if duplicate:
                raise ValidationError(
                    "Ya existe un mapeo para esa combinación de perfil fiscal."
                )

    @api.model
    def find_fiscal_position(
        self,
        company,
        application,
        invoice_subtype,
        has_recargo,
        has_retention,
        retention_percent=0.0,
        retention_nature="none",
    ):
        """Busca reglas exactas y después alternativas genéricas seguras."""
        subtype = (
            (invoice_subtype or "").strip().zfill(2)
            if invoice_subtype
            else False
        )
        nature = retention_nature if has_retention else "none"
        percent = abs(retention_percent or 0.0) if has_retention else 0.0
        base_domain = [
            ("company_id", "=", company.id),
            ("application", "=", application),
            ("has_recargo", "=", bool(has_recargo)),
            ("has_retention", "=", bool(has_retention)),
            ("active", "=", True),
        ]

        subtype_domains = []
        if subtype:
            subtype_domains.append([("invoice_subtype", "=", subtype)])
        subtype_domains.append([("invoice_subtype", "in", [False, ""])])

        retention_profiles = [(nature, percent)]
        if has_retention and percent:
            retention_profiles.append((nature, 0.0))

        for subtype_domain in subtype_domains:
            for profile_nature, profile_percent in retention_profiles:
                rule = self.search(
                    base_domain
                    + subtype_domain
                    + [
                        ("retention_nature", "=", profile_nature),
                        ("retention_percent", "=", profile_percent),
                    ],
                    order="sequence, id",
                    limit=1,
                )
                if rule:
                    return rule.fiscal_position_id
        return self.env["account.fiscal.position"]

    @api.model
    def _chart_ref(self, company, xmlid):
        chart = (
            self.env["account.chart.template"]
            .with_company(company)
            .with_context(allowed_company_ids=[company.id])
        )
        return chart.ref(xmlid, raise_if_not_found=False)

    @api.model
    def _create_default_rule(self, company, values):
        domain = [
            ("company_id", "=", company.id),
            ("application", "=", values["application"]),
            ("invoice_subtype", "=", values.get("invoice_subtype") or False),
            ("has_recargo", "=", values.get("has_recargo", False)),
            ("has_retention", "=", values.get("has_retention", False)),
            ("retention_nature", "=", values.get("retention_nature", "none")),
            ("retention_percent", "=", values.get("retention_percent", 0.0)),
        ]
        if self.with_context(active_test=False).search_count(domain):
            return self.browse()
        return self.create({"company_id": company.id, **values})

    @api.model
    def load_default_mappings(self, company):
        """Carga los casos habituales sin sobrescribir configuración manual."""
        created = self.browse()
        skipped = []

        def add_rule(application, subtype, fp_xmlid, **profile):
            nonlocal created
            fiscal_position = self._chart_ref(company, fp_xmlid)
            if not fiscal_position or not fiscal_position.active:
                skipped.append(
                    "%s/%s -> %s" % (application, subtype, fp_xmlid)
                )
                return
            created |= self._create_default_rule(
                company,
                {
                    "application": application,
                    "invoice_subtype": subtype,
                    "has_recargo": profile.get("has_recargo", False),
                    "has_retention": profile.get("has_retention", False),
                    "retention_nature": profile.get(
                        "retention_nature", "none"
                    ),
                    "retention_percent": profile.get(
                        "retention_percent", 0.0
                    ),
                    "fiscal_position_id": fiscal_position.id,
                    "sequence": profile.get("sequence", 10),
                },
            )

        # Operaciones habituales y no ambiguas del registro tipo 9.
        add_rule("sale", "01", "l10n_es_domestic_fiscal_position")
        add_rule("purchase", "01", "l10n_es_domestic_fiscal_position")
        add_rule("sale", "03", "fp_intra")
        add_rule("sale", "04", "fp_intra")
        add_rule("purchase", "03", "fp_intra")
        add_rule("purchase", "08", "fp_intra")
        add_rule("sale", "05", "fp_not_subject_tai")
        add_rule("sale", "06", "fp_extra")
        add_rule("purchase", "06", "fp_dua")
        add_rule("purchase", "04", "fp_ispn")
        add_rule("sale", "01", "fp_recargo", has_recargo=True)
        add_rule("purchase", "01", "fp_recargo", has_recargo=True)

        tax_mapping = self.env["tl.suenlace.tax.mapping"]
        generic_retention_refs = {
            1.0: "fp_irpf1",
            2.0: "fp_irpf2",
            7.0: "fp_irpf7",
            9.0: "fp_irpf9",
            15.0: "fp_irpf15",
            18.0: "fp_irpf18",
            19.0: "fp_irpf19",
            20.0: "fp_irpf20",
            21.0: "fp_irpf21",
            24.0: "fp_irpf24",
        }
        lease_retention_refs = {
            19.0: "fp_irpf19a",
            19.5: "fp_irpf195a",
            20.0: "fp_irpf20a",
            21.0: "fp_irpf21a",
        }
        for application in ("sale", "purchase"):
            for nature, refs in (
                ("generic", generic_retention_refs),
                ("lease", lease_retention_refs),
            ):
                for percent, fp_xmlid in refs.items():
                    has_tax = tax_mapping.search_count(
                        [
                            ("company_id", "=", company.id),
                            ("application", "=", application),
                            ("tax_kind", "=", "retencion"),
                            ("retention_nature", "=", nature),
                            ("percent", "=", percent),
                            ("active", "=", True),
                        ]
                    )
                    if not has_tax:
                        continue
                    add_rule(
                        application,
                        "01",
                        fp_xmlid,
                        has_retention=True,
                        retention_nature=nature,
                        retention_percent=percent,
                    )

        return {"created": len(created), "skipped": skipped}
