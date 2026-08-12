# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class DecaRevisionWizard(models.TransientModel):
    _name = "l10n.es.deca.revision.wizard"
    _description = "Create a Traced DeCA Revision"

    document_id = fields.Many2one("l10n.es.deca.document", required=True, readonly=True)
    source_version_id = fields.Many2one(
        "l10n.es.deca.version", required=True, readonly=True
    )
    reason = fields.Text(required=True)
    purpose = fields.Selection(
        related="document_id.purpose", string="Document purpose", readonly=True
    )
    contractual_shipper_id = fields.Many2one("res.partner")
    contractual_shipper_name = fields.Char(required=True)
    contractual_shipper_vat = fields.Char(required=True)
    contractual_shipper_address = fields.Text(required=True)
    effective_carrier_id = fields.Many2one("res.partner")
    effective_carrier_name = fields.Char(required=True)
    effective_carrier_vat = fields.Char(required=True)
    origin = fields.Char(required=True)
    destination = fields.Char(required=True)
    goods_nature = fields.Text(required=True)
    goods_weight = fields.Float()
    weight_uom = fields.Char()
    alternative_weight_measure = fields.Char()
    special_permit_required = fields.Boolean()
    special_permit_ref = fields.Char()
    transport_date = fields.Date(required=True)
    tractor_plate = fields.Char(required=True)
    trailer_plate = fields.Char()
    observations = fields.Text()
    driver_id = fields.Many2one("res.partner")
    driver_name = fields.Char()
    planned_start_at = fields.Datetime()

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        document = self.env["l10n.es.deca.document"].browse(
            values.get("document_id") or self.env.context.get("default_document_id")
        )
        if document.exists():
            if "source_version_id" in field_names:
                values["source_version_id"] = document.current_version_id.id
            for name in document._get_legal_fields():
                if name in self._fields and name in field_names:
                    value = document[name]
                    values[name] = (
                        value.id if self._fields[name].type == "many2one" else value
                    )
        return values

    @api.onchange("contractual_shipper_id")
    def _onchange_contractual_shipper_id(self):
        partner = self.contractual_shipper_id
        if partner:
            self.contractual_shipper_name = (
                partner.commercial_company_name or partner.name
            )
            self.contractual_shipper_vat = partner.vat
            self.contractual_shipper_address = partner._display_address(
                without_company=True
            )

    @api.onchange("effective_carrier_id")
    def _onchange_effective_carrier_id(self):
        partner = self.effective_carrier_id
        if partner:
            self.effective_carrier_name = (
                partner.commercial_company_name or partner.name
            )
            self.effective_carrier_vat = partner.vat

    @api.onchange("driver_id")
    def _onchange_driver_id(self):
        if self.driver_id:
            self.driver_name = self.driver_id.name

    def action_apply(self):
        self.ensure_one()
        field_names = self.document_id._get_legal_fields() & self._fields.keys()
        values = {}
        for name in field_names:
            value = self[name]
            values[name] = value.id if self._fields[name].type == "many2one" else value
        version = self.document_id._apply_revision(
            values, self.reason, expected_version=self.source_version_id
        )
        return version.action_download()
