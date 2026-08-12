# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _prepare_deca_values(self):
        """Prefill the effective carrier (and tractor plate) from the delivery.

        ``delivery_carrier_partner`` adds ``partner_id`` on ``delivery.carrier``:
        when the picking's carrier has one, it becomes the DeCA effective
        carrier. When the optional ``fleet`` module is also installed, we look
        for a vehicle whose driver is that same partner (or one of its
        contacts/employees) and reuse its plate as a suggested tractor plate.
        Every value stays a draft suggestion: the user still reviews and can
        change it before the DeCA is issued, exactly like the other prefilled
        stock data.
        """
        self.ensure_one()
        values = super()._prepare_deca_values()
        carrier = self.carrier_id
        carrier_partner = carrier.partner_id if carrier else False
        if carrier_partner:
            values.update(
                {
                    "effective_carrier_id": carrier_partner.id,
                    "effective_carrier_name": (
                        carrier_partner.commercial_company_name
                        or carrier_partner.name
                    ),
                    "effective_carrier_vat": carrier_partner.vat,
                }
            )
            plate = self._deca_find_carrier_vehicle_plate(carrier_partner)
            if plate:
                values["tractor_plate"] = plate
        return values

    def _deca_find_carrier_vehicle_plate(self, carrier_partner):
        """Return the plate of a Fleet vehicle driven by the carrier's partner.

        A driver "belongs to" the carrier partner either directly (the carrier
        partner drives itself) or as one of its contacts/employees, i.e. shares
        the same commercial partner. Returns an empty string when the Fleet
        module is not installed or no matching vehicle is found.
        """
        self.ensure_one()
        Vehicle = self.env.get("fleet.vehicle")
        if Vehicle is None:
            return ""
        vehicle = Vehicle.sudo().search(
            [
                ("driver_id.commercial_partner_id", "=", carrier_partner.commercial_partner_id.id),
            ],
            limit=1,
        )
        return vehicle.license_plate or "" if vehicle else ""
