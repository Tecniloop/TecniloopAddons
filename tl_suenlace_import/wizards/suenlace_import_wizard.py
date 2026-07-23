# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import api, fields, models, _
from odoo.exceptions import UserError


def _background_default(env):
    value = env["ir.config_parameter"].sudo().get_param(
        "tl_suenlace_import.background_mode", "True"
    )
    return str(value).lower() in {"1", "true", "yes", "on"}


def _integer_default(env, key, default):
    value = env["ir.config_parameter"].sudo().get_param(key, str(default))
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


class SuenlaceImportWizard(models.TransientModel):
    """Asistente para crear un lote de importación y encolar su parseo."""

    _name = "tl.suenlace.import.wizard"
    _description = "Asistente de importación SUENLACE"

    company_id = fields.Many2one(
        "res.company", required=True,
        default=lambda self: self.env.company)
    company_suenlace_code = fields.Char(
        related="company_id.suenlace_company_code",
        string="Código empresa SUENLACE",
        readonly=True,
    )
    file_data = fields.Binary(string="Fichero SUENLACE", required=True)
    file_name = fields.Char(string="Nombre del fichero")
    encoding = fields.Char(string="Codificación")
    post_moves = fields.Boolean(string="Contabilizar asientos")
    background_mode = fields.Boolean(
        string="Procesar en segundo plano",
        default=lambda self: _background_default(self.env),
        help="Evita el timeout HTTP ejecutando la importación por lotes.",
    )
    batch_size = fields.Integer(
        string="Documentos por lote",
        default=lambda self: _integer_default(
            self.env, "tl_suenlace_import.batch_size", 25
        ),
    )
    parse_batch_size = fields.Integer(
        string="Registros por lote de parseo",
        default=lambda self: _integer_default(
            self.env, "tl_suenlace_import.parse_batch_size", 2000
        ),
    )
    associate_partners = fields.Boolean(
        string="Asociar terceros en asientos",
        default=lambda self: self.env.company.suenlace_associate_partners,
        help=(
            "Asigna tercero a asientos tipo 0 y a facturas importadas como "
            "asiento literal. Las facturas Odoo siempre requieren tercero."
        ),
    )
    skip_vat_validation = fields.Boolean(
        string="Omitir validación del NIF de Odoo",
        default=lambda self: self.env.company.suenlace_skip_vat_validation,
        help=(
            "Permite crear o actualizar terceros de este lote aunque el NIF "
            "no supere la validación estándar de Odoo. Solo afecta a esta "
            "importación SUENLACE."
        ),
    )
    associate_taxes = fields.Boolean(
        string="Interpretar impuestos y crear facturas",
        default=lambda self: self.env.company.suenlace_associate_taxes,
        help=(
            "Desactivado importa las facturas como asientos literales con "
            "sus cuentas a3. Activado crea facturas Odoo con impuestos."
        ),
    )
    journal_misc_id = fields.Many2one(
        "account.journal", string="Diario asientos varios",
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        check_company=True)
    journal_sale_id = fields.Many2one(
        "account.journal", string="Diario ventas",
        domain="[('type', '=', 'sale'), ('company_id', '=', company_id)]",
        check_company=True)
    journal_purchase_id = fields.Many2one(
        "account.journal", string="Diario compras",
        domain="[('type', '=', 'purchase'), ('company_id', '=', company_id)]",
        check_company=True)

    @api.onchange("company_id")
    def _onchange_company_suenlace_options(self):
        if self.company_id:
            self.associate_partners = (
                self.company_id.suenlace_associate_partners
            )
            self.skip_vat_validation = (
                self.company_id.suenlace_skip_vat_validation
            )
            self.associate_taxes = self.company_id.suenlace_associate_taxes
            self.journal_misc_id = False
            self.journal_sale_id = False
            self.journal_purchase_id = False

    def _prepare_import_vals(self):
        self.ensure_one()
        return {
            "company_id": self.company_id.id,
            "file_data": self.file_data,
            "file_name": self.file_name,
            "encoding": self.encoding or False,
            "post_moves": self.post_moves,
            "background_mode": self.background_mode,
            "batch_size": max(1, self.batch_size or 25),
            "parse_batch_size": max(1, self.parse_batch_size or 2000),
            "associate_partners": self.associate_partners,
            "skip_vat_validation": self.skip_vat_validation,
            "associate_taxes": self.associate_taxes,
            "journal_misc_id": self.journal_misc_id.id or False,
            "journal_sale_id": self.journal_sale_id.id or False,
            "journal_purchase_id": self.journal_purchase_id.id or False,
        }

    def action_create_and_parse(self):
        self.ensure_one()
        if not self.company_suenlace_code:
            raise UserError(_(
                "Configure el Código de empresa SUENLACE de la compañía "
                "antes de iniciar la importación."
            ))
        record = self.env["tl.suenlace.import"].create(
            self._prepare_import_vals()
        )
        record.action_parse()
        return {
            "type": "ir.actions.act_window",
            "name": _("Importación SUENLACE"),
            "res_model": "tl.suenlace.import",
            "res_id": record.id,
            "view_mode": "form",
            "target": "current",
        }
