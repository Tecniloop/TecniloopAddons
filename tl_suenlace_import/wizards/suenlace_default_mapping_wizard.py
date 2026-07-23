# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import _, fields, models
from odoo.exceptions import UserError


class SuenlaceDefaultMappingWizard(models.TransientModel):
    _name = "tl.suenlace.default.mapping.wizard"
    _description = "Cargar mapeos predeterminados SUENLACE"

    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
    )
    load_tax_mappings = fields.Boolean(
        string="Mapeos de impuestos",
        default=True,
    )
    load_fiscal_position_mappings = fields.Boolean(
        string="Mapeos de posiciones fiscales",
        default=True,
    )

    def action_load(self):
        self.ensure_one()
        if not self.load_tax_mappings and not self.load_fiscal_position_mappings:
            raise UserError(_("Seleccione al menos un tipo de mapeo."))

        loader = self.env["tl.suenlace.mapping.loader"]
        if not loader._is_spanish_company(self.company_id):
            raise UserError(
                _(
                    "La compañía debe tener país fiscal España y un plan "
                    "contable instalado."
                )
            )

        context = {
            **self.env.context,
            "allowed_company_ids": [self.company_id.id],
            "company_id": self.company_id.id,
        }
        tax_stats = {"created": 0, "skipped": []}
        fiscal_stats = {"created": 0, "skipped": []}
        if self.load_tax_mappings:
            tax_stats = (
                self.env["tl.suenlace.tax.mapping"]
                .with_company(self.company_id)
                .with_context(context)
                .sudo()
                .load_default_mappings(self.company_id)
            )
        if self.load_fiscal_position_mappings:
            fiscal_stats = (
                self.env["tl.suenlace.fiscal.position.mapping"]
                .with_company(self.company_id)
                .with_context(context)
                .sudo()
                .load_default_mappings(self.company_id)
            )

        skipped_count = len(tax_stats["skipped"]) + len(
            fiscal_stats["skipped"]
        )
        message = _(
            "Se han creado %(tax)d mapeos de impuestos y %(fiscal)d mapeos "
            "de posiciones fiscales."
        ) % {
            "tax": tax_stats["created"],
            "fiscal": fiscal_stats["created"],
        }
        if skipped_count:
            message += " " + _(
                "%(count)d combinaciones no se cargaron porque el impuesto o "
                "la posición fiscal correspondiente no existe en esta compañía."
            ) % {"count": skipped_count}
        else:
            message += " " + _(
                "Las configuraciones manuales existentes se han conservado."
            )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Mapeos SUENLACE"),
                "message": message,
                "type": "success" if not skipped_count else "warning",
                "sticky": bool(skipped_count),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
