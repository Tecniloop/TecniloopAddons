from odoo import _, api, fields, models
from odoo.exceptions import UserError


class Bc3Budget(models.Model):
    _name = "bc3.budget"
    _description = "BC3 Budget"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(required=True, tracking=True)
    file_id = fields.Many2one("bc3.file", required=True, ondelete="restrict", tracking=True)
    root_concept_id = fields.Many2one("bc3.concept", string="Root Concept")
    state = fields.Selection(
        [("draft", "Draft"), ("ready", "Ready"), ("locked", "Locked")],
        default="draft",
        required=True,
        tracking=True,
    )
    line_ids = fields.One2many("bc3.budget.line", "budget_id", string="Lines")
    amount_total = fields.Float(compute="_compute_amount_total", store=True, digits="Product Price")
    work_unit_count = fields.Integer(compute="_compute_counts")
    chapter_count = fields.Integer(compute="_compute_counts")

    @api.depends("line_ids.amount_total", "line_ids.line_type")
    def _compute_amount_total(self):
        for budget in self:
            roots = budget.line_ids.filtered(lambda line: line.line_type == "root")
            if roots:
                budget.amount_total = sum(roots.mapped("amount_total"))
            else:
                budget.amount_total = sum(budget.line_ids.filtered(lambda line: line.line_type == "work_unit").mapped("amount_total"))

    def _compute_counts(self):
        for budget in self:
            budget.chapter_count = len(budget.line_ids.filtered(lambda line: line.line_type in ("root", "chapter")))
            budget.work_unit_count = len(budget.line_ids.filtered(lambda line: line.line_type == "work_unit"))

    @api.model
    def create_from_file(self, bc3_file):
        existing = self.search([("file_id", "=", bc3_file.id)], limit=1)
        if existing:
            existing.line_ids.unlink()
            budget = existing
        else:
            root = bc3_file.concept_ids.filtered(lambda concept: concept.category == "root")[:1]
            budget = self.create({
                "name": bc3_file.comment or bc3_file.name,
                "file_id": bc3_file.id,
                "root_concept_id": root.id if root else False,
            })
        builder = self.env["bc3.budget.line.builder"]
        builder.build_budget_lines(budget)
        budget.write({"state": "ready"})
        return budget

    def action_rebuild_lines(self):
        for budget in self:
            budget.line_ids.unlink()
            self.env["bc3.budget.line.builder"].build_budget_lines(budget)
            budget.state = "ready"
        return True


class Bc3BudgetLine(models.Model):
    _name = "bc3.budget.line"
    _description = "BC3 Budget Line"
    _order = "budget_id, sequence, id"
    _rec_name = "display_name"

    budget_id = fields.Many2one("bc3.budget", required=True, ondelete="cascade", index=True)
    file_id = fields.Many2one(related="budget_id.file_id", store=True, index=True)
    parent_id = fields.Many2one("bc3.budget.line", ondelete="cascade", index=True)
    child_ids = fields.One2many("bc3.budget.line", "parent_id", string="Children")
    sequence = fields.Integer(default=10, index=True)
    level = fields.Integer(default=0)
    position_path = fields.Char(index=True)
    concept_id = fields.Many2one("bc3.concept", index=True)
    code = fields.Char(required=True, index=True)
    display_name = fields.Char(compute="_compute_display_name", store=True)
    name = fields.Char(required=True)
    line_type = fields.Selection(
        [("root", "Root"), ("chapter", "Chapter"), ("work_unit", "Work Unit"), ("resource", "Resource"), ("percentage", "Percentage")],
        required=True,
        default="work_unit",
        index=True,
    )
    unit_name = fields.Char()
    uom_id = fields.Many2one("uom.uom")
    quantity = fields.Float(digits="Product Unit of Measure")
    price_unit = fields.Float(digits="Product Price")
    amount_total = fields.Float(compute="_compute_amount_total", store=True, digits="Product Price")
    text = fields.Text()
    sale_order_line_id = fields.Many2one("sale.order.line", copy=False, readonly=True)
    measurement_line_ids = fields.One2many("bc3.measurement.line", compute="_compute_measurement_lines", string="Measurements")

    @api.depends("code", "name")
    def _compute_display_name(self):
        for line in self:
            line.display_name = "[%s] %s" % (line.code or "", line.name or "")

    @api.depends("quantity", "price_unit", "child_ids.amount_total", "line_type")
    def _compute_amount_total(self):
        for line in self:
            if line.child_ids and line.line_type in ("root", "chapter"):
                line.amount_total = sum(line.child_ids.mapped("amount_total"))
            else:
                line.amount_total = (line.quantity or 0.0) * (line.price_unit or 0.0)

    def _compute_measurement_lines(self):
        Measurement = self.env["bc3.measurement.line"]
        for line in self:
            line.measurement_line_ids = Measurement.search([
                ("file_id", "=", line.file_id.id),
                ("child_code", "=", line.code),
                ("position_path", "=", line.position_path or ""),
            ])

    def action_open_measurements(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Measurements"),
            "res_model": "bc3.measurement.line",
            "view_mode": "list,form",
            "domain": [("file_id", "=", self.file_id.id), ("child_code", "=", self.code), ("position_path", "=", self.position_path or "")],
        }


class Bc3BudgetLineBuilder(models.AbstractModel):
    _name = "bc3.budget.line.builder"
    _description = "BC3 Budget Line Builder"

    def build_budget_lines(self, budget):
        file_rec = budget.file_id
        root = budget.root_concept_id or file_rec.concept_ids.filtered(lambda concept: concept.category == "root")[:1]
        if not root:
            root = file_rec.concept_ids.filtered(lambda concept: concept.category == "chapter")[:1]
        if not root:
            raise UserError(_("No root or chapter concept was found."))
        decomp_by_parent = {}
        empty_decomposition = self.env["bc3.decomposition.line"]
        for line in file_rec.decomposition_line_ids:
            key = line.parent_concept_id.id if line.parent_concept_id else line.parent_code
            decomp_by_parent.setdefault(key, empty_decomposition)
            decomp_by_parent[key] |= line
        visited = set()
        counter = [10]
        self._create_line_recursive(budget, root, False, 0, "", 1.0, decomp_by_parent, visited, counter)

    def _create_line_recursive(self, budget, concept, parent_line, level, position_path, quantity, decomp_by_parent, visited, counter):
        code = concept.code
        key = (code, position_path)
        if key in visited:
            return False
        visited.add(key)
        line_type = self._line_type(concept)
        line = self.env["bc3.budget.line"].create({
            "budget_id": budget.id,
            "parent_id": parent_line.id if parent_line else False,
            "sequence": counter[0],
            "level": level,
            "position_path": position_path,
            "concept_id": concept.id,
            "code": code,
            "name": concept.name,
            "line_type": line_type,
            "unit_name": concept.unit_name,
            "uom_id": concept.uom_id.id if concept.uom_id else False,
            "quantity": quantity if line_type == "work_unit" else 1.0,
            "price_unit": concept.price_unit,
            "text": concept.text,
        })
        counter[0] += 10
        children = decomp_by_parent.get(concept.id, self.env["bc3.decomposition.line"])
        if not children:
            children = decomp_by_parent.get(code, self.env["bc3.decomposition.line"])
        for child_rel in children.sorted(key=lambda item: (item.sequence, item.id)):
            child = child_rel.child_concept_id
            if not child:
                continue
            child_position = "%s/%s" % (position_path, child_rel.sequence) if position_path else str(child_rel.sequence)
            self._create_line_recursive(
                budget,
                child,
                line,
                level + 1,
                child_position,
                child_rel.performance,
                decomp_by_parent,
                visited,
                counter,
            )
        return line

    def _line_type(self, concept):
        if concept.category == "root":
            return "root"
        if concept.category == "chapter":
            return "chapter"
        if concept.category == "percentage":
            return "percentage"
        if concept.category == "resource":
            return "resource"
        return "work_unit"
