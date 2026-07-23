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
