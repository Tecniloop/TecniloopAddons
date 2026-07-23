# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import api, fields, models, _


class SuenlaceImportWizard(models.TransientModel):
    """Asistente para crear un lote de importación y encolar su parseo."""

    _name = "tl.suenlace.import.wizard"
    _description = "Asistente de importación SUENLACE"

    company_id = fields.Many2one(
        "res.company", required=True,
        default=lambda self: self.env.company)
    file_data = fields.Binary(string="Fichero SUENLACE", required=True)
    file_name = fields.Char(string="Nombre del fichero")
    encoding = fields.Char(string="Codificación")
    post_moves = fields.Boolean(string="Contabilizar asientos")
    associate_partners = fields.Boolean(
        string="Asociar terceros en asientos",
        default=lambda self: self.env.company.suenlace_associate_partners,
        help=(
            "Asigna tercero a asientos tipo 0 y a facturas importadas como "
            "asiento literal. Las facturas Odoo siempre requieren tercero."
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
        domain="[('type', '=', 'general')]")
    journal_sale_id = fields.Many2one(
        "account.journal", string="Diario ventas",
        domain="[('type', '=', 'sale')]")
    journal_purchase_id = fields.Many2one(
        "account.journal", string="Diario compras",
        domain="[('type', '=', 'purchase')]")

    @api.onchange("company_id")
    def _onchange_company_suenlace_options(self):
        if self.company_id:
            self.associate_partners = (
                self.company_id.suenlace_associate_partners
            )
            self.associate_taxes = self.company_id.suenlace_associate_taxes

    def _prepare_import_vals(self):
        self.ensure_one()
        return {
            "company_id": self.company_id.id,
            "file_data": self.file_data,
            "file_name": self.file_name,
            "encoding": self.encoding or False,
            "post_moves": self.post_moves,
            "associate_partners": self.associate_partners,
            "associate_taxes": self.associate_taxes,
            "journal_misc_id": self.journal_misc_id.id or False,
            "journal_sale_id": self.journal_sale_id.id or False,
            "journal_purchase_id": self.journal_purchase_id.id or False,
        }

    def action_create_and_parse(self):
        self.ensure_one()
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
