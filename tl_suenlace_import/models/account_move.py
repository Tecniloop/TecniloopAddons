# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    suenlace_partner_needs_review = fields.Boolean(
        string="Revisión de tercero SUENLACE",
        copy=False,
        index=True,
        readonly=True,
    )
    suenlace_tax_needs_review = fields.Boolean(
        string="Revisión de impuestos SUENLACE",
        copy=False,
        index=True,
        readonly=True,
    )
    suenlace_associate_partners = fields.Boolean(
        string="SUENLACE asignó terceros al asiento",
        copy=False,
        readonly=True,
    )
    suenlace_associate_taxes = fields.Boolean(
        string="SUENLACE interpretó impuestos",
        copy=False,
        readonly=True,
    )
    suenlace_document_mode = fields.Selection(
        [
            ("entry_type_0", "Asiento tipo 0"),
            ("invoice_literal_entry", "Factura a3 como asiento literal"),
            ("odoo_invoice", "Factura Odoo con impuestos"),
        ],
        string="Modo de documento SUENLACE",
        copy=False,
        readonly=True,
        index=True,
    )
    suenlace_source_tax_accounts = fields.Text(
        string="Subcuentas fiscales de origen SUENLACE",
        copy=False,
        readonly=True,
    )
    suenlace_odoo_tax_accounts = fields.Text(
        string="Cuentas fiscales utilizadas por Odoo",
        copy=False,
        readonly=True,
    )

    suenlace_fiscal_needs_review = fields.Boolean(
        string="Revisión de posición fiscal SUENLACE",
        copy=False,
        index=True,
        readonly=True,
    )
    suenlace_has_recargo = fields.Boolean(
        string="SUENLACE con recargo de equivalencia",
        copy=False,
        readonly=True,
    )
    suenlace_has_retention = fields.Boolean(
        string="SUENLACE con retención",
        copy=False,
        readonly=True,
    )
    suenlace_invoice_subtype = fields.Char(
        string="Subtipo de factura SUENLACE",
        copy=False,
        readonly=True,
    )
    suenlace_retention_percent = fields.Float(
        string="Porcentaje de retención SUENLACE",
        digits=(6, 2),
        copy=False,
        readonly=True,
    )
    suenlace_retention_nature = fields.Selection(
        [
            ("none", "Sin retención"),
            ("generic", "Retención general/profesional"),
            ("lease", "Retención de arrendamientos"),
        ],
        string="Naturaleza de retención SUENLACE",
        default="none",
        copy=False,
        readonly=True,
    )

    suenlace_import_id = fields.Many2one(
        "tl.suenlace.import",
        string="Importación SUENLACE",
        copy=False,
        index=True,
        readonly=True,
    )
    suenlace_needs_review = fields.Boolean(
        string="Revisión de totales SUENLACE",
        copy=False,
        index=True,
        readonly=True,
    )
    suenlace_expected_total = fields.Monetary(
        string="Total esperado SUENLACE",
        currency_field="currency_id",
        copy=False,
        readonly=True,
    )
    suenlace_calculated_total = fields.Monetary(
        string="Total calculado Odoo",
        currency_field="currency_id",
        copy=False,
        readonly=True,
    )
    suenlace_total_difference = fields.Monetary(
        string="Diferencia Odoo/SUENLACE",
        currency_field="currency_id",
        copy=False,
        readonly=True,
    )
    suenlace_source_detail_total = fields.Monetary(
        string="Suma detalles SUENLACE",
        currency_field="currency_id",
        copy=False,
        readonly=True,
    )


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    suenlace_source_account_code = fields.Char(
        string="Cuenta de origen SUENLACE",
        copy=False,
        readonly=True,
        index=True,
        help=(
            "Cuenta exacta informada en el DAT antes de cualquier conversión "
            "opcional de una subcuenta fiscal a la cuenta del impuesto Odoo."
        ),
    )
