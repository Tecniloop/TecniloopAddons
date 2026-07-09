# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models
from odoo.tools import float_compare


class PosOrder(models.Model):
    _inherit = "pos.order"

    is_l10n_es_simplified_invoice = fields.Boolean(
        "Simplified invoice",
        copy=False,
        default=False,
    )
    l10n_es_unique_id = fields.Char(
        "Simplified invoice number",
        copy=False,
    )
    l10n_es_simplified_number = fields.Integer(
        "Simplified invoice sequence number",
        copy=False,
    )

    @api.model
    def _simplified_limit_check(self, amount_total, limit=3000):
        precision_digits = self.env["decimal.precision"].precision_get("Account")
        # -1 or 0: amount_total <= limit, simplified
        #       1: amount_total > limit, can not be simplified
        return float_compare(amount_total, limit, precision_digits=precision_digits) < 0

    @api.model
    def _update_sequence_number(self, pos):
        pos.l10n_es_simplified_invoice_sequence_id.next_by_id()

    @api.model
    def _process_order(self, order, existing_order):
        simplified_invoice_number = order.get("l10n_es_unique_id")
        if not simplified_invoice_number:
            return super()._process_order(order, existing_order)

        pos = self.env["pos.session"].browse(order.get("session_id")).config_id
        if self._simplified_limit_check(
            order.get("amount_total", 0), pos.l10n_es_simplified_invoice_limit
        ):
            order.update(
                {
                    "l10n_es_unique_id": simplified_invoice_number,
                    "is_l10n_es_simplified_invoice": True,
                }
            )
            self._update_sequence_number(pos)
        else:
            # Server-side guard for orders above the legal simplified-invoice limit.
            # The PoS UI already forces a full invoice, but the backend must not trust
            # client payloads coming from offline cache or custom clients.
            order.update(
                {
                    "l10n_es_unique_id": False,
                    "l10n_es_simplified_number": 0,
                    "is_l10n_es_simplified_invoice": False,
                    "to_invoice": True,
                }
            )
        return super()._process_order(order, existing_order)

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        return fields_list + [
            "is_l10n_es_simplified_invoice",
            "l10n_es_unique_id",
            "l10n_es_simplified_number",
        ]
