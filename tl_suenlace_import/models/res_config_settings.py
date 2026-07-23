# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    suenlace_associate_partners = fields.Boolean(
        related="company_id.suenlace_associate_partners",
        readonly=False,
    )
    suenlace_skip_vat_validation = fields.Boolean(
        related="company_id.suenlace_skip_vat_validation",
        readonly=False,
    )
    suenlace_associate_taxes = fields.Boolean(
        related="company_id.suenlace_associate_taxes",
        readonly=False,
    )

    suenlace_background_mode = fields.Boolean(
        string="Procesar SUENLACE en segundo plano",
        config_parameter="tl_suenlace_import.background_mode",
        default=True,
    )
    suenlace_batch_size = fields.Integer(
        string="Documentos SUENLACE por lote",
        config_parameter="tl_suenlace_import.batch_size",
        default=25,
    )
    suenlace_parse_batch_size = fields.Integer(
        string="Registros SUENLACE por lote de parseo",
        config_parameter="tl_suenlace_import.parse_batch_size",
        default=2000,
    )
