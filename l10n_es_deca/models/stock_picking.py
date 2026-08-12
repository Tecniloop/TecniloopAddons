# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    deca_required = fields.Boolean(
        string="DeCA required",
        copy=False,
        help=(
            "Enable when this road transport falls within the Spanish DeCA scope. "
            "Applicability and statutory exemptions remain an operator decision."
        ),
    )
    deca_document_ids = fields.One2many(
        "l10n.es.deca.document",
        "picking_id",
        string="DeCA documents",
        readonly=True,
    )
    deca_document_count = fields.Integer(compute="_compute_deca_document_count")
    deca_document_id = fields.Many2one(
        "l10n.es.deca.document",
        string="DeCA",
        compute="_compute_deca_document_id",
        store=True,
        readonly=True,
    )

    @api.depends("deca_document_ids")
    def _compute_deca_document_count(self):
        for picking in self:
            picking.deca_document_count = len(picking.deca_document_ids)

    @api.depends("deca_document_ids")
    def _compute_deca_document_id(self):
        for picking in self:
            picking.deca_document_id = picking.deca_document_ids[:1]

    def _deca_move_nature_line(self, move):
        """Describe one move as '<description> <quantity> <uom>'.

        The description is taken from the linked sale order line (its free-text
        description, as agreed with the customer) whenever the move originates
        from a sale, falling back to the picking's own product when there is no
        sale line — e.g. internal transfers or manually added moves.
        """
        sale_line = move.sale_line_id if "sale_line_id" in move._fields else False
        description = (sale_line.name or "").strip() if sale_line else ""
        if not description:
            description = move.product_id.display_name
        quantity = move.product_uom_qty
        if quantity == int(quantity):
            quantity_label = str(int(quantity))
        else:
            quantity_label = f"{quantity:g}"
        uom = move.product_uom.name or ""
        return f"{description} {quantity_label} {uom}".strip()

    def _deca_compute_goods_nature(self, moves):
        """Build the DeCA goods-nature text for a set of moves.

        Default behaviour: one line per move, using the description of the
        linked sale order line when there is one, otherwise the picking's own
        product, followed by quantity and unit of measure. Downstream modules
        (e.g. an Intrastat bridge) may override this to group differently,
        as long as they keep returning a single text blob ready for the
        ``goods_nature`` field.
        """
        self.ensure_one()
        return "\n".join(
            filter(None, (self._deca_move_nature_line(move) for move in moves))
        )

    def _prepare_deca_values(self):
        """Map stock data to a draft without asserting that it is legally correct.

        Stock locations and products are operational data, not authoritative legal
        declarations.  The user must review every prefilled value before sealing.
        Keeping this mapping in one method also gives downstream OCA modules a safe
        extension point for carrier, fleet, route or e-CMR integrations.
        """
        self.ensure_one()
        moves = self.move_ids.filtered(lambda move: move.state != "cancel")
        goods_nature = self._deca_compute_goods_nature(moves)
        weight = 0.0
        for move in moves:
            quantity = move.product_uom._compute_quantity(
                move.product_uom_qty, move.product_id.uom_id
            )
            weight += quantity * move.product_id.weight
        destination = self.location_dest_id.complete_name
        if self.partner_id:
            destination = self.partner_id._display_address(without_company=False)
        scheduled = fields.Datetime.to_datetime(self.scheduled_date)
        company_partner = self.company_id.partner_id
        return {
            "picking_id": self.id,
            "batch_id": self.batch_id.id,
            "company_id": self.company_id.id,
            "contractual_shipper_id": company_partner.id,
            "contractual_shipper_name": (
                company_partner.commercial_company_name or company_partner.name
            ),
            "contractual_shipper_vat": company_partner.vat,
            "contractual_shipper_address": company_partner._display_address(
                without_company=False
            ),
            "origin": self.location_id.complete_name,
            "destination": destination,
            "goods_nature": goods_nature,
            "goods_weight": weight,
            "weight_uom": "kg",
            "transport_date": (
                scheduled.date() if scheduled else fields.Date.context_today(self)
            ),
            "planned_start_at": self.scheduled_date,
        }

    def _create_or_open_deca(self):
        """Return the unique DeCA attached to this transfer, creating its draft."""
        self.ensure_one()
        if self.state in ("done", "cancel"):
            raise UserError(
                _("A DeCA draft cannot be created for a done or cancelled transfer.")
            )
        document = self.deca_document_ids[:1]
        if not document:
            document = self.env["l10n.es.deca.document"].create(
                self._prepare_deca_values()
            )
            self.deca_required = True
        elif document.state == "draft" and self.batch_id and not document.batch_id:
            # A still-unsealed draft may safely capture a batch assigned afterwards.
            document.batch_id = self.batch_id
        return document

    def action_create_deca(self):
        self.ensure_one()
        return self._create_or_open_deca().get_formview_action()

    def action_add_to_deca_multi(self):
        """List-view action: create a draft DeCA for every eligible picking.

        Pickings that already have a DeCA, or that are done/cancelled, are
        skipped and reported back in a notification instead of blocking the
        pickings that can still be processed.
        """
        already = self.filtered("deca_document_id")
        not_eligible = self.filtered(lambda p: p.state in ("done", "cancel"))
        to_create = self - already - not_eligible
        for picking in to_create:
            picking._create_or_open_deca()
        skipped = already | not_eligible
        if not skipped:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("DeCA"),
                    "message": _(
                        "%(count)s transfer(s) added to DeCA.", count=len(to_create)
                    ),
                    "type": "success",
                    "sticky": False,
                },
            }
        message = _(
            "The following transfers already have a DeCA or cannot have one "
            "and were skipped: %(names)s",
            names=", ".join(skipped.mapped("display_name")),
        )
        if not to_create:
            raise UserError(message)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("DeCA"),
                "message": message,
                "type": "warning",
                "sticky": True,
            },
        }

    def action_view_deca_documents(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "l10n_es_deca.action_deca_document"
        )
        action["domain"] = [("picking_id", "=", self.id)]
        action["context"] = {"default_picking_id": self.id}
        if self.deca_document_count == 1:
            action.update(
                {
                    "view_mode": "form",
                    "res_id": self.deca_document_ids.id,
                    "views": [(False, "form")],
                }
            )
        return action

    def _check_deca_before_validation(self):
        """Stop completion of opted-in transfers without current delivery evidence.

        This is a last-line operational guard.  It does not infer legal scope: the
        explicit ``deca_required`` flag is deliberately required to avoid applying
        Spanish domestic rules to exempt or international transports.
        """
        for picking in self.filtered("deca_required"):
            # A stock operator may validate transfers without DeCA model ACLs.  This
            # elevated read exposes no values and only evaluates the compliance gate.
            document = picking.sudo().deca_document_ids[:1]
            if (
                not document
                or document.state not in ("issued", "in_transit", "done")
                or not document.current_version_id.delivery_log_ids
            ):
                raise UserError(
                    _(
                        "Transfer %(transfer)s requires an issued DeCA whose current "
                        "PDF or QR has been delivered to the driver.",
                        transfer=picking.display_name,
                    )
                )

    def button_validate(self):
        self._check_deca_before_validation()
        return super().button_validate()
