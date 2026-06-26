from odoo import _, api, fields, models
from odoo.exceptions import UserError


class Bc3BudgetCatalogInsertWizard(models.TransientModel):
    _name = "bc3.budget.catalog.insert.wizard"
    _description = "Insertar conceptos BC3 desde banco de precios"

    mode = fields.Selection(
        [("insert", "Insertar"), ("replace", "Sustituir")],
        default="insert",
        required=True,
    )
    budget_id = fields.Many2one("bc3.budget", required=True, readonly=True)
    parent_id = fields.Many2one(
        "bc3.budget.line",
        string="Insertar debajo de",
        required=True,
        domain="[('budget_id', '=', budget_id), ('line_type', 'in', ['root', 'chapter', 'work_unit'])]",
    )
    replace_line_id = fields.Many2one(
        "bc3.budget.line",
        string="Línea a sustituir",
        domain="[('budget_id', '=', budget_id)]",
    )
    catalog_file_id = fields.Many2one(
        "bc3.file",
        string="Banco de precios / referencia",
        required=True,
        domain="[('state', '=', 'parsed')]",
    )
    concept_id = fields.Many2one(
        "bc3.concept",
        string="Concepto",
        required=True,
        domain="[('file_id', '=', catalog_file_id), ('category', 'in', ['chapter', 'work_unit', 'resource', 'percentage'])]",
    )
    concept_category = fields.Selection(related="concept_id.category", string="Tipo", readonly=True)
    concept_unit_name = fields.Char(related="concept_id.unit_name", string="Ud", readonly=True)
    concept_price_unit = fields.Float(related="concept_id.price_unit", string="Precio", readonly=True)
    concept_text = fields.Text(related="concept_id.text", string="Texto", readonly=True)
    quantity = fields.Float(string="Cantidad", default=1.0, digits="Product Unit of Measure")
    sequence = fields.Integer(string="Secuencia")
    copy_measurements = fields.Boolean(
        string="Copiar mediciones del banco",
        help="Normalmente se deja desactivado: se copia la definición de la partida y sus recursos, pero las mediciones son propias de la obra.",
    )
    keep_measurements = fields.Boolean(string="Conservar mediciones", default=True)

    @api.onchange("budget_id")
    def _onchange_budget_id(self):
        for wizard in self:
            if wizard.budget_id and not wizard.catalog_file_id:
                wizard.catalog_file_id = wizard.budget_id.catalog_file_ids[:1]

    @api.onchange("catalog_file_id")
    def _onchange_catalog_file_id(self):
        for wizard in self:
            wizard.concept_id = False

    @api.onchange("replace_line_id")
    def _onchange_replace_line_id(self):
        for wizard in self:
            if wizard.replace_line_id:
                wizard.parent_id = wizard.replace_line_id.parent_id
                wizard.quantity = wizard.replace_line_id.quantity

    def _validate(self):
        self.ensure_one()
        if self.parent_id and self.parent_id.budget_id != self.budget_id:
            raise UserError(_("La línea superior no pertenece al presupuesto."))
        if self.replace_line_id and self.replace_line_id.budget_id != self.budget_id:
            raise UserError(_("La línea a sustituir no pertenece al presupuesto."))
        if self.concept_id.file_id != self.catalog_file_id:
            raise UserError(_("El concepto no pertenece al banco de precios seleccionado."))

    def action_apply(self):
        self.ensure_one()
        self._validate()
        if self.mode == "replace":
            if not self.replace_line_id:
                raise UserError(_("Debe indicar la línea a sustituir."))
            self.replace_line_id._apply_catalog_concept(self.concept_id, keep_measurements=self.keep_measurements)
            new_line = self.replace_line_id
        else:
            new_line = self.budget_id._insert_catalog_concept(
                self.concept_id,
                self.parent_id,
                quantity=self.quantity,
                sequence=self.sequence,
                copy_measurements=self.copy_measurements,
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("Línea BC3"),
            "res_model": "bc3.budget.line",
            "view_mode": "form",
            "res_id": new_line.id,
        }
