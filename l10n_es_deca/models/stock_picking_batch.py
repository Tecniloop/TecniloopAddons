# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockPickingBatch(models.Model):
    _inherit = "stock.picking.batch"

    deca_document_ids = fields.Many2many(
        "l10n.es.deca.document",
        string="DeCA documents",
        compute="_compute_deca_documents",
        readonly=True,
    )
    deca_document_count = fields.Integer(compute="_compute_deca_documents")
    deca_document_id = fields.Many2one(
        "l10n.es.deca.document",
        string="DeCA",
        compute="_compute_deca_documents",
        readonly=True,
        help=(
            "Direct link to the batch's DeCA when it groups a single transfer. "
            "A batch with several transfers can hold several DeCA documents (one "
            "per transfer by design); this field then points to the first one — "
            "use the DeCA smart button to see them all."
        ),
    )

    @api.depends("picking_ids.deca_document_ids")
    def _compute_deca_documents(self):
        for batch in self:
            batch.deca_document_ids = batch.picking_ids.deca_document_ids
            batch.deca_document_count = len(batch.deca_document_ids)
            batch.deca_document_id = batch.deca_document_ids[:1]

    def action_create_deca_documents(self):
        """Create one DeCA per picking and retain the batch as grouping evidence.

        A batch may contain several destinations.  Aggregating it into one DeCA
        could therefore misstate the mandatory origin/destination and goods data.
        The one-document-per-picking rule is intentional and documented for review.
        """
        self.ensure_one()
        eligible = self.picking_ids.filtered(
            lambda picking: picking.state not in ("done", "cancel")
        )
        if not eligible:
            raise UserError(_("The batch has no eligible transfers for DeCA creation."))
        for picking in eligible:
            picking._create_or_open_deca()
        return self.action_view_deca_documents()

    def action_view_deca_documents(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "l10n_es_deca.action_deca_document"
        )
        action["domain"] = [("picking_id", "in", self.picking_ids.ids)]
        action["context"] = {"search_default_batch_id": self.id}
        if self.deca_document_count == 1:
            action.update(
                {
                    "view_mode": "form",
                    "res_id": self.deca_document_ids.id,
                    "views": [(False, "form")],
                }
            )
        return action
