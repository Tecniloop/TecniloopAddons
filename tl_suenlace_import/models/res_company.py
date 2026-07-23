# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    suenlace_associate_partners = fields.Boolean(
        string="Asociar terceros en asientos SUENLACE",
        default=True,
        help=(
            "Valor predeterminado para asignar partner_id a los asientos "
            "tipo 0 y a las facturas importadas como asiento literal. Si se "
            "crean facturas Odoo, el tercero es obligatorio y siempre se "
            "identifica o crea."
        ),
    )
    suenlace_skip_vat_validation = fields.Boolean(
        string="Omitir validación del NIF de Odoo en SUENLACE",
        compute="_compute_suenlace_skip_vat_validation",
        inverse="_inverse_suenlace_skip_vat_validation",
        help=(
            "Permite crear o actualizar terceros desde SUENLACE aunque el "
            "NIF no supere la validación de formato o dígito de control de "
            "Odoo. Solo afecta a las operaciones realizadas por este "
            "importador; la validación estándar continúa activa en el resto "
            "de Odoo."
        ),
    )
    suenlace_associate_taxes = fields.Boolean(
        string="Interpretar impuestos y crear facturas SUENLACE",
        default=False,
        help=(
            "Desactivado: los registros 1/2+9 se crean como asientos "
            "literales y todas las cuentas del DAT se conservan. Activado: "
            "se crean facturas Odoo con account.tax y los asientos tipo 0 "
            "pueden interpretar subcuentas fiscales expresamente mapeadas."
        ),
    )

    @staticmethod
    def _suenlace_skip_vat_validation_param_key(company_id):
        return (
            "tl_suenlace_import.skip_vat_validation_company_%s"
            % company_id
        )

    @api.depends_context("company")
    def _compute_suenlace_skip_vat_validation(self):
        """Lee la preferencia sin añadir una columna a ``res_company``.

        ``res.company`` suele precargarse durante el arranque del registro.
        Mantener esta opción en ``ir.config_parameter`` evita que desplegar
        una nueva versión del addon bloquee la base antes de poder actualizar
        el módulo por faltar una columna recién añadida.
        """
        parameters = self.env["ir.config_parameter"].sudo()
        for company in self:
            value = parameters.get_param(
                self._suenlace_skip_vat_validation_param_key(company.id),
                default="False",
            )
            company.suenlace_skip_vat_validation = str(value).lower() in {
                "1",
                "true",
                "yes",
                "on",
            }

    def _inverse_suenlace_skip_vat_validation(self):
        parameters = self.env["ir.config_parameter"].sudo()
        for company in self:
            parameters.set_param(
                self._suenlace_skip_vat_validation_param_key(company.id),
                "True" if company.suenlace_skip_vat_validation else "False",
            )
