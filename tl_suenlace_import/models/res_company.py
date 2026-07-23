# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import fields, models


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
        default=False,
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
