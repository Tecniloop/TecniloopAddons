# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    @api.depends(
        "l10n_es_simplified_invoice_sequence_id.number_next_actual",
        "l10n_es_simplified_invoice_sequence_id.prefix",
        "l10n_es_simplified_invoice_sequence_id.padding",
    )
    def _compute_simplified_invoice_sequence(self):
        for pos in self:
            seq = pos.l10n_es_simplified_invoice_sequence_id
            if not seq:
                pos.l10n_es_simplified_invoice_number = 0
                pos.l10n_es_simplified_invoice_prefix = False
                pos.l10n_es_simplified_invoice_padding = 0
                continue
            pos.l10n_es_simplified_invoice_number = (
                seq._get_current_sequence().number_next_actual
            )
            pos.l10n_es_simplified_invoice_prefix = seq._get_prefix_suffix()[0]
            pos.l10n_es_simplified_invoice_padding = seq.padding

    iface_l10n_es_simplified_invoice = fields.Boolean(
        string="Use simplified invoices for this POS",
    )
    is_simplified_config = fields.Boolean(
        store=False, compute="_compute_simplified_config"
    )
    l10n_es_simplified_invoice_sequence_id = fields.Many2one(
        "ir.sequence",
        string="Simplified Invoice IDs Sequence",
        help="Autogenerate for each POS created",
        copy=False,
    )
    l10n_es_simplified_invoice_limit = fields.Float(
        string="Sim.Inv limit amount",
        digits="Account",
        help="Over this amount is not legally posible to create "
        "a simplified invoice",
        default=3000,  # Spanish legal limit
    )
    l10n_es_simplified_invoice_prefix = fields.Char(
        "Simplified Invoice prefix",
        compute="_compute_simplified_invoice_sequence",
    )
    l10n_es_simplified_invoice_padding = fields.Integer(
        "Simplified Invoice padding",
        compute="_compute_simplified_invoice_sequence",
    )
    l10n_es_simplified_invoice_number = fields.Integer(
        "Sim.Inv number",
        compute="_compute_simplified_invoice_sequence",
    )
    simplified_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Simplified invoice partner",
        compute="_compute_simplified_partner_id",
    )
    prevent_offline_validation = fields.Boolean(
        help="Prevent order validation when the POS is offline. "
        "This helps ensure data integrity and prevents synchronization issues.",
    )

    @api.depends("iface_l10n_es_simplified_invoice")
    def _compute_simplified_config(self):
        for pos in self:
            pos.is_simplified_config = pos.iface_l10n_es_simplified_invoice

    def _compute_simplified_partner_id(self):
        simplified_partner = self.env.ref("l10n_es.partner_simplified")
        for config in self:
            config.simplified_partner_id = simplified_partner

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            pos_name = vals.get("name") or _("Point of Sale")
            # Auto create simp. inv. sequence
            prefix = initial_prefix = f"{pos_name}{self._get_default_prefix()}"
            ith = 0
            while self.env["ir.sequence"].search_count([("prefix", "=", prefix)]):
                ith += 1
                prefix = f"{initial_prefix}_{ith}"
            simp_inv_seq_id = self.env["ir.sequence"].create(
                {
                    "name": _("Simplified Invoice %s") % pos_name,
                    "implementation": "standard",
                    "padding": self._get_default_padding(),
                    "prefix": prefix,
                    "code": "pos.config.simplified_invoice",
                    "company_id": vals.get("company_id") or self.env.company.id,
                }
            )
            vals["l10n_es_simplified_invoice_sequence_id"] = simp_inv_seq_id.id
        return super().create(vals_list)

    @api.onchange("iface_l10n_es_simplified_invoice")
    def _onchange_l10n_iface_l10n_es_simplified_invoice(self):
        if self.iface_l10n_es_simplified_invoice and not self.invoice_journal_id:
            self.invoice_journal_id = self._default_invoice_journal()

    def copy(self, default=None):
        return super(
            PosConfig,
            self.with_context(copy_pos_config=True),
        ).copy(default)

    def write(self, vals):
        if not self._context.get("copy_pos_config") and "name" not in vals:
            for pos in self:
                sequence = pos.l10n_es_simplified_invoice_sequence_id
                sequence.check_simplified_invoice_unique_prefix()
        if "name" in vals:
            for pos in self:
                prefix = pos.l10n_es_simplified_invoice_prefix or ""
                new_prefix = prefix.replace(pos.name, vals["name"], 1)
                sequence = pos.l10n_es_simplified_invoice_sequence_id
                if sequence and new_prefix != prefix:
                    sequence.update(
                        {
                            "prefix": new_prefix,
                            "name": sequence.name.replace(pos.name, vals["name"], 1),
                        }
                    )
        return super().write(vals)

    def unlink(self):
        self.mapped("l10n_es_simplified_invoice_sequence_id").unlink()
        return super().unlink()

    def _get_default_padding(self):
        return int(
            self.env["ir.config_parameter"].get_param(
                "l10n_es_pos.simplified_invoice_sequence.padding", 4
            )
        )

    def _get_default_prefix(self):
        return self.env["ir.config_parameter"].get_param(
            "l10n_es_pos.simplified_invoice_sequence.prefix", ""
        )

    def _get_l10n_es_sequence_name(self):
        """HACK: This is done for getting the proper translation."""
        return _("Simplified Invoice %s")

    def _l10n_es_pos_oca_fields_to_load(self):
        return [
            "iface_l10n_es_simplified_invoice",
            "is_simplified_config",
            "l10n_es_simplified_invoice_limit",
            "l10n_es_simplified_invoice_prefix",
            "l10n_es_simplified_invoice_padding",
            "l10n_es_simplified_invoice_number",
            "simplified_partner_id",
            "prevent_offline_validation",
        ]

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        # In POS 19, an empty list has a special meaning: load the default/full
        # model schema. Do not replace it with only our fields, otherwise the
        # frontend loses core properties such as currency_id, payment_method_ids,
        # etc. If another addon already returned an explicit list, extend it.
        if not fields_list:
            return fields_list
        return fields_list + [
            field for field in self._l10n_es_pos_oca_fields_to_load() if field not in fields_list
        ]

    @api.model
    def _load_pos_data_read(self, records, config):
        data = super()._load_pos_data_read(records, config)
        if not data:
            return data
        records_by_id = {record.id: record for record in records}
        for values in data:
            record = records_by_id.get(values.get("id"))
            if not record:
                continue
            values.update(
                {
                    "iface_l10n_es_simplified_invoice": record.iface_l10n_es_simplified_invoice,
                    "is_simplified_config": record.is_simplified_config,
                    "l10n_es_simplified_invoice_limit": record.l10n_es_simplified_invoice_limit,
                    "l10n_es_simplified_invoice_prefix": record.l10n_es_simplified_invoice_prefix,
                    "l10n_es_simplified_invoice_padding": record.l10n_es_simplified_invoice_padding,
                    "l10n_es_simplified_invoice_number": record.l10n_es_simplified_invoice_number,
                    "simplified_partner_id": record.simplified_partner_id.id,
                    "prevent_offline_validation": record.prevent_offline_validation,
                }
            )
        return data
