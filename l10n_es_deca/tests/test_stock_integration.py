# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged("post_install", "-at_install")
class TestDecaStockIntegration(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.deca_user = new_test_user(
            cls.env,
            login="deca_stock_test_user",
            groups="l10n_es_deca.group_deca_manager,stock.group_stock_user",
        )
        cls.customer = cls.env["res.partner"].create(
            {"name": "Cliente DeCA", "street": "Calle Destino 1", "city": "Madrid"}
        )
        cls.picking_type = cls.env["stock.picking.type"].search(
            [
                ("code", "=", "outgoing"),
                ("warehouse_id.company_id", "=", cls.env.company.id),
            ],
            limit=1,
        )

    def _new_picking(self):
        return self.env["stock.picking"].with_user(self.deca_user).create(
            {
                "picking_type_id": self.picking_type.id,
                "location_id": self.picking_type.default_location_src_id.id,
                "location_dest_id": self.picking_type.default_location_dest_id.id,
                "partner_id": self.customer.id,
            }
        )

    def test_picking_action_creates_reviewable_linked_draft(self):
        picking = self._new_picking()
        action = picking.action_create_deca()
        document = picking.deca_document_ids
        self.assertEqual(action["res_id"], document.id)
        self.assertEqual(document.picking_id, picking)
        self.assertEqual(document.company_id, picking.company_id)
        self.assertEqual(document.state, "draft")
        self.assertTrue(picking.deca_required)

    def test_batch_action_creates_one_document_per_picking(self):
        pickings = self._new_picking() | self._new_picking()
        batch = self.env["stock.picking.batch"].with_user(self.deca_user).create(
            {
                "company_id": self.env.company.id,
                "picking_type_id": self.picking_type.id,
                "picking_ids": [Command.set(pickings.ids)],
            }
        )
        batch.action_create_deca_documents()
        self.assertEqual(len(batch.deca_document_ids), 2)
        self.assertEqual(
            set(batch.deca_document_ids.picking_id.ids), set(pickings.ids)
        )
        self.assertEqual(batch.deca_document_ids.batch_id, batch)

    def test_required_transfer_cannot_validate_without_delivered_deca(self):
        picking = self._new_picking()
        picking.deca_required = True
        with self.assertRaises(UserError):
            picking.button_validate()

    def test_company_default_carrier_and_lightweight_vehicle_catalog_prefill(self):
        carrier = self.env["res.partner"].create(
            {"name": "Carrier DeCA", "vat": "ESB11223344", "deca_is_carrier": True}
        )
        self.env["l10n.es.deca.vehicle"].create(
            {
                "carrier_id": carrier.id,
                "vehicle_type": "tractor",
                "license_plate": "1234 abc",
                "is_default": True,
            }
        )
        self.env.company.deca_default_carrier_id = carrier
        picking = self._new_picking()
        values = picking._prepare_deca_values()
        self.assertEqual(values["effective_carrier_id"], carrier.id)
        self.assertEqual(values["tractor_plate"], "1234 ABC")
