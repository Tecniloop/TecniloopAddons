# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    deca_is_carrier = fields.Boolean(
        string="DeCA carrier",
        help="Mark this contact as a carrier available for Spanish DeCA documents.",
    )
    deca_vehicle_ids = fields.One2many(
        "l10n.es.deca.vehicle",
        "carrier_id",
        string="DeCA vehicles",
    )

    def _deca_default_vehicle_plate(self, vehicle_type):
        self.ensure_one()
        vehicle = self.deca_vehicle_ids.filtered(
            lambda item: item.active and item.vehicle_type == vehicle_type
        ).sorted(lambda item: (not item.is_default, item.sequence, item.id))[:1]
        return vehicle.license_plate if vehicle else ""


class DecaVehicle(models.Model):
    _name = "l10n.es.deca.vehicle"
    _description = "DeCA Carrier Vehicle"
    _order = "carrier_id, vehicle_type, sequence, id"

    carrier_id = fields.Many2one(
        "res.partner",
        required=True,
        ondelete="cascade",
        index=True,
        domain="[('deca_is_carrier', '=', True)]",
    )
    company_id = fields.Many2one(
        "res.company",
        related="carrier_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    vehicle_type = fields.Selection(
        [("tractor", "Tractor"), ("trailer", "Trailer")],
        required=True,
        default="tractor",
        index=True,
    )
    license_plate = fields.Char(required=True, index=True)
    name = fields.Char(compute="_compute_name", store=True)
    is_default = fields.Boolean(string="Default for DeCA")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _carrier_plate_unique = models.Constraint(
        "UNIQUE(carrier_id, vehicle_type, license_plate)",
        "The same plate cannot be repeated for this carrier and vehicle type.",
    )

    @api.depends("license_plate", "vehicle_type")
    def _compute_name(self):
        labels = dict(self._fields["vehicle_type"].selection)
        for record in self:
            record.name = (
                f"{record.license_plate or ''} - "
                f"{labels.get(record.vehicle_type, '')}"
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("license_plate"):
                vals["license_plate"] = vals["license_plate"].strip().upper()
        records = super().create(vals_list)
        records._enforce_single_default()
        return records

    def write(self, vals):
        if vals.get("license_plate"):
            vals["license_plate"] = vals["license_plate"].strip().upper()
        result = super().write(vals)
        if "is_default" in vals or "vehicle_type" in vals or "carrier_id" in vals:
            self._enforce_single_default()
        return result

    def _enforce_single_default(self):
        for record in self.filtered("is_default"):
            others = self.search([
                ("carrier_id", "=", record.carrier_id.id),
                ("vehicle_type", "=", record.vehicle_type),
                ("id", "!=", record.id),
                ("is_default", "=", True),
            ])
            if others:
                others.write({"is_default": False})
