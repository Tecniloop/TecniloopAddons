# Copyright 2026 Tecniloop
# License Other proprietary.

from odoo import api, fields, models


def _param_float(env, key, default):
    try:
        return float(env["ir.config_parameter"].sudo().get_param(key, default))
    except (TypeError, ValueError):
        return float(default)


class ResPartner(models.Model):
    _inherit = "res.partner"

    tl_auto_validate_receipt = fields.Boolean(
        string="Auto-validate Parseur receipts",
        help="If enabled, delivery notes applied for this vendor validate the "
        "incoming picking automatically.",
    )
    tl_price_tolerance_pct = fields.Float(
        string="Price tolerance (%)",
        help="0 = use company default (Purchase settings).",
    )
    tl_price_tolerance_abs = fields.Float(
        string="Price tolerance (amount)",
        help="0 = use company default (Purchase settings).",
    )
    tl_qty_tolerance_pct = fields.Float(
        string="Quantity tolerance (%)",
        help="0 = use company default. Extra qty within the band is not an exception.",
    )
    tl_qty_tolerance_abs = fields.Float(
        string="Quantity tolerance (units)",
        help="0 = use company default.",
    )
    tl_min_shelf_life_days = fields.Integer(
        string="Minimum remaining shelf life (days)",
        help="0 = use company default. Receipts below this remaining life are blocked.",
    )
    tl_effective_price_tolerance_pct = fields.Float(
        string="Effective price tolerance (%)",
        compute="_compute_tl_effective_tolerances",
    )
    tl_effective_price_tolerance_abs = fields.Float(
        string="Effective price tolerance (amount)",
        compute="_compute_tl_effective_tolerances",
    )
    tl_effective_qty_tolerance_pct = fields.Float(
        string="Effective quantity tolerance (%)",
        compute="_compute_tl_effective_tolerances",
    )
    tl_effective_qty_tolerance_abs = fields.Float(
        string="Effective quantity tolerance (units)",
        compute="_compute_tl_effective_tolerances",
    )

    @api.depends(
        "tl_price_tolerance_pct",
        "tl_price_tolerance_abs",
        "tl_qty_tolerance_pct",
        "tl_qty_tolerance_abs",
    )
    def _compute_tl_effective_tolerances(self):
        for partner in self:
            values = partner._tl_parseur_tolerances()
            partner.tl_effective_price_tolerance_pct = values["price_pct"]
            partner.tl_effective_price_tolerance_abs = values["price_abs"]
            partner.tl_effective_qty_tolerance_pct = values["qty_pct"]
            partner.tl_effective_qty_tolerance_abs = values["qty_abs"]

    def _tl_parseur_tolerances(self):
        """Effective price/qty bands: partner value or company default."""
        self.ensure_one()
        env = self.env
        return {
            "price_pct": self.tl_price_tolerance_pct
            or _param_float(env, "vendor_parseur_intake.price_tolerance_pct", 2.0),
            "price_abs": self.tl_price_tolerance_abs
            or _param_float(env, "vendor_parseur_intake.price_tolerance_abs", 0.05),
            "qty_pct": self.tl_qty_tolerance_pct
            or _param_float(env, "vendor_parseur_intake.qty_tolerance_pct", 0.0),
            "qty_abs": self.tl_qty_tolerance_abs
            or _param_float(env, "vendor_parseur_intake.qty_tolerance_abs", 0.0),
        }
