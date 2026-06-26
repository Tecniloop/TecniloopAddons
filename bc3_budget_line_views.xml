import base64
import datetime as dt

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class Bc3Budget(models.Model):
    _name = "bc3.budget"
    _description = "Presupuesto BC3"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(required=True, tracking=True)
    file_id = fields.Many2one("bc3.file", required=True, ondelete="restrict", tracking=True)
    root_concept_id = fields.Many2one("bc3.concept", string="Concepto raíz")
    state = fields.Selection(
        [("draft", "Borrador"), ("ready", "Preparado"), ("locked", "Bloqueado")],
        default="draft",
        required=True,
        tracking=True,
    )
    line_ids = fields.One2many("bc3.budget.line", "budget_id", string="Líneas")
    amount_total = fields.Float(compute="_compute_amount_total", store=True, digits="Product Price")
    work_unit_count = fields.Integer(compute="_compute_counts")
    chapter_count = fields.Integer(compute="_compute_counts")
    ci_percent = fields.Float(string="% costes indirectos")
    gg_percent = fields.Float(string="% gastos generales")
    bi_percent = fields.Float(string="% beneficio industrial")
    baja_percent = fields.Float(string="% baja/alza")
    iva_percent = fields.Float(string="% IVA")
    currency_code = fields.Char(string="Divisa BC3")
    export_file = fields.Binary(string="Archivo BC3 exportado", attachment=True, readonly=True)
    export_filename = fields.Char(readonly=True)
    export_date = fields.Datetime(readonly=True)

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
        vals = {
            "name": bc3_file.comment or bc3_file.name,
            "file_id": bc3_file.id,
            "ci_percent": bc3_file.k_ci,
            "gg_percent": bc3_file.k_gg,
            "bi_percent": bc3_file.k_bi,
            "baja_percent": bc3_file.k_baja,
            "iva_percent": bc3_file.k_iva,
            "currency_code": bc3_file.k_currency or "EUR",
        }
        root = bc3_file.concept_ids.filtered(lambda concept: concept.category == "root")[:1]
        vals["root_concept_id"] = root.id if root else False
        if existing:
            existing.line_ids.unlink()
            existing.write(vals)
            budget = existing
        else:
            budget = self.create(vals)
        self.env["bc3.budget.line.builder"].build_budget_lines(budget)
        budget.write({"state": "ready"})
        return budget

    def action_rebuild_lines(self):
        for budget in self:
            budget.line_ids.unlink()
            self.env["bc3.budget.line.builder"].build_budget_lines(budget)
            budget.state = "ready"
        return True

    def action_update_quantities_from_measurements(self):
        for budget in self:
            for line in budget.line_ids.filtered(lambda item: item.line_type == "work_unit"):
                line.action_update_quantity_from_measurements()
        return True

    def action_export_bc3(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("El presupuesto BC3 no tiene líneas para exportar."))
        content = self._export_bc3_text()
        filename = "%s.bc3" % self._safe_filename(self.name or "presupuesto_bc3")
        self.write({
            "export_file": base64.b64encode(content.encode("cp1252", errors="replace")),
            "export_filename": filename,
            "export_date": fields.Datetime.now(),
        })
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/bc3.budget/%s/export_file/%s?download=true" % (self.id, filename),
            "target": "self",
        }

    def _safe_filename(self, value):
        return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in value).strip("_") or "presupuesto_bc3"

    def _export_bc3_text(self):
        today = fields.Date.context_today(self)
        date_raw = today.strftime("%d%m%Y") if isinstance(today, dt.date) else ""
        lines = []
        info_type = "2"
        lines.append("~V|Odoo|FIEBDC-3/2024|Odoo 19 - TL BC3||ANSI|%s|%s|||||" % (self.name or "", info_type))
        # Legacy K: keep essential decimals and economic coefficients. The second field is CI\GG\BI\BAJA\IVA.
        currency = self.currency_code or "EUR"
        lines.append("~K|\\2\\2\\2\\3\\2\\2\\2\\2\\%s\\|%s\\%s\\%s\\%s\\%s|" % (
            currency,
            self._fmt(self.ci_percent),
            self._fmt(self.gg_percent),
            self._fmt(self.bi_percent),
            self._fmt(self.baja_percent),
            self._fmt(self.iva_percent),
        ))
        exported = set()
        for line in self.line_ids.sorted(key=lambda item: (item.sequence, item.id)):
            if line.code in exported:
                continue
            exported.add(line.code)
            unit = line.unit_name or ""
            concept_type = line.concept_id.concept_type or ""
            price = line.amount_total if line.line_type in ("root", "chapter") else line.price_unit
            lines.append("~C|%s|%s|%s|%s\\|%s\\|%s|" % (
                self._escape(line.code),
                self._escape(unit),
                self._escape(line.name),
                self._fmt(price),
                date_raw,
                self._escape(concept_type),
            ))
            if line.text:
                lines.append("~T|%s|%s|" % (self._escape(line.code), self._escape(line.text)))
        for parent in self.line_ids.filtered(lambda item: item.child_ids).sorted(key=lambda item: (item.sequence, item.id)):
            chunks = []
            for child in parent.child_ids.sorted(key=lambda item: (item.sequence, item.id)):
                factor = child.factor if child.factor not in (0.0, None) else 1.0
                performance = child.performance if child.performance not in (0.0, None) else (child.quantity or 1.0)
                chunks.append("%s\\%s\\%s" % (self._escape(child.code), self._fmt(factor), self._fmt(performance)))
            if chunks:
                lines.append("~D|%s|%s\\|" % (self._escape(parent.code), "\\".join(chunks)))
        for bline in self.line_ids.filtered(lambda item: item.budget_measurement_line_ids).sorted(key=lambda item: (item.sequence, item.id)):
            parent_code = bline.parent_id.code if bline.parent_id else ""
            position = (bline.position_path or "").replace("/", "\\")
            items = []
            for mline in bline.budget_measurement_line_ids.sorted(key=lambda item: (item.sequence, item.id)):
                items.append("%s\\%s\\%s\\%s\\%s\\%s" % (
                    self._escape(mline.line_type or ""),
                    self._escape(mline.comment or ""),
                    self._fmt(mline.units),
                    self._fmt(mline.length),
                    self._fmt(mline.width),
                    self._fmt(mline.height),
                ))
            total = sum(bline.budget_measurement_line_ids.mapped("subtotal")) or bline.quantity
            lines.append("~M|%s\\%s|%s|%s|%s\\|%s|" % (
                self._escape(parent_code),
                self._escape(bline.code),
                self._escape(position),
                self._fmt(total),
                "\\".join(items),
                self._escape(bline.measurement_label or ""),
            ))
        return "\r\n".join(lines) + "\r\n"

    def _fmt(self, value):
        value = value or 0.0
        text = ("%.6f" % value).rstrip("0").rstrip(".")
        return text or "0"

    def _escape(self, value):
        return (value or "").replace("|", "/").replace("\r", " ").replace("\n", " ")


    def _report_title(self):
        self.ensure_one()
        root_line = self.line_ids.filtered(lambda line: line.line_type == "root")[:1]
        return root_line.name or self.root_concept_id.name or self.name or ""

    def _report_print_lines(self):
        self.ensure_one()
        return self.line_ids.filtered(lambda line: line.line_type in ("chapter", "work_unit")).sorted(key=lambda line: (line.sequence, line.id))

    def _report_format_amount(self, value):
        return self._report_format_number(value, 2, False, False)

    def _report_format_measure(self, value, blank_zero=True):
        return self._report_format_number(value, 2, blank_zero, True)

    def _report_format_number(self, value, decimals=2, blank_zero=False, trim=False):
        try:
            number = float(value or 0.0)
        except (TypeError, ValueError):
            number = 0.0
        if blank_zero and abs(number) < 0.0000001:
            return ""
        text = ("%%,.%sf" % int(decimals)) % number
        text = text.replace(",", "X").replace(".", ",").replace("X", ".")
        if trim and "," in text:
            text = text.rstrip("0").rstrip(",")
        return text

    def action_open_origin_file(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Fichero BC3"),
            "res_model": "bc3.file",
            "view_mode": "form",
            "res_id": self.file_id.id,
        }


class Bc3BudgetLine(models.Model):
    _name = "bc3.budget.line"
    _description = "Línea de presupuesto BC3"
    _order = "budget_id, sequence, id"
    _rec_name = "display_name"

    budget_id = fields.Many2one("bc3.budget", required=True, ondelete="cascade", index=True)
    file_id = fields.Many2one(related="budget_id.file_id", store=True, index=True)
    parent_id = fields.Many2one("bc3.budget.line", ondelete="cascade", index=True)
    child_ids = fields.One2many("bc3.budget.line", "parent_id", string="Hijos")
    sequence = fields.Integer(default=10, index=True)
    level = fields.Integer(default=0)
    position_path = fields.Char(index=True)
    concept_id = fields.Many2one("bc3.concept", index=True)
    code = fields.Char(required=True, index=True)
    display_name = fields.Char(compute="_compute_display_name", store=True)
    name = fields.Char(required=True)
    line_type = fields.Selection(
        [("root", "Raíz"), ("chapter", "Capítulo"), ("work_unit", "Partida"), ("resource", "Recurso"), ("percentage", "Porcentaje")],
        required=True,
        default="work_unit",
        index=True,
    )
    unit_name = fields.Char()
    uom_id = fields.Many2one("uom.uom")
    factor = fields.Float(default=1.0, digits="Product Unit of Measure")
    performance = fields.Float(default=1.0, digits="Product Unit of Measure")
    quantity = fields.Float(digits="Product Unit of Measure")
    price_unit = fields.Float(digits="Product Price")
    amount_total = fields.Float(compute="_compute_amount_total", store=True, digits="Product Price")
    text = fields.Text()
    measurement_label = fields.Char()
    measurement_line_ids = fields.One2many("bc3.measurement.line", compute="_compute_measurement_lines", string="Mediciones origen")
    budget_measurement_line_ids = fields.One2many("bc3.budget.measurement.line", "budget_line_id", string="Mediciones editables")

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

    @api.onchange("factor", "performance")
    def _onchange_factor_performance(self):
        for line in self:
            if line.line_type not in ("root", "chapter"):
                line.quantity = (line.factor or 1.0) * (line.performance or 1.0)

    def _compute_measurement_lines(self):
        Measurement = self.env["bc3.measurement.line"]
        Concept = self.env["bc3.concept"]
        for line in self:
            normalized_code = Concept._normalize_code(line.code)
            domain = [("file_id", "=", line.file_id.id)]
            candidates = Measurement.search(domain)
            line.measurement_line_ids = candidates.filtered(
                lambda item: Concept._normalize_code(item.child_code) == normalized_code
                and (not line.position_path or item.position_path == line.position_path)
            )


    def _report_nature(self):
        self.ensure_one()
        labels = dict(self._fields["line_type"].selection)
        return labels.get(self.line_type, self.line_type or "")

    def action_update_quantity_from_measurements(self):
        for line in self:
            total = sum(line.budget_measurement_line_ids.mapped("subtotal"))
            if total:
                line.quantity = total
                line.performance = total / (line.factor or 1.0)
        return True

    def action_open_measurements(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Mediciones"),
            "res_model": "bc3.budget.measurement.line",
            "view_mode": "list,form",
            "domain": [("budget_line_id", "=", self.id)],
            "context": {"default_budget_line_id": self.id},
        }


class Bc3BudgetMeasurementLine(models.Model):
    _name = "bc3.budget.measurement.line"
    _description = "Línea de medición editable BC3"
    _order = "budget_line_id, sequence, id"

    budget_line_id = fields.Many2one("bc3.budget.line", required=True, ondelete="cascade", index=True)
    budget_id = fields.Many2one(related="budget_line_id.budget_id", store=True, index=True)
    sequence = fields.Integer(default=10)
    line_type = fields.Selection(
        [("", "Normal"), ("1", "Subtotal parcial"), ("2", "Subtotal acumulado"), ("3", "Expresión")],
        default="",
    )
    comment = fields.Char(string="Comentario")
    bim_id = fields.Char(string="BIM ID")
    units = fields.Float(string="N", digits="Product Unit of Measure")
    length = fields.Float(string="Longitud", digits="Product Unit of Measure")
    width = fields.Float(string="Anchura", digits="Product Unit of Measure")
    height = fields.Float(string="Altura", digits="Product Unit of Measure")
    subtotal = fields.Float(compute="_compute_subtotal", store=True, digits="Product Unit of Measure")
    label = fields.Char(string="Etiqueta")

    @api.depends("line_type", "units", "length", "width", "height")
    def _compute_subtotal(self):
        for line in self:
            if line.line_type in ("1", "2"):
                line.subtotal = 0.0
                continue
            values = [value for value in (line.units, line.length, line.width, line.height) if value not in (0.0, None)]
            if not values:
                line.subtotal = 0.0
                continue
            subtotal = 1.0
            for value in values:
                subtotal *= value
            line.subtotal = subtotal


class Bc3BudgetLineBuilder(models.AbstractModel):
    _name = "bc3.budget.line.builder"
    _description = "Constructor de líneas de presupuesto BC3"

    def build_budget_lines(self, budget):
        file_rec = budget.file_id
        root = budget.root_concept_id or file_rec.concept_ids.filtered(lambda concept: concept.category == "root")[:1]
        if not root:
            root = file_rec.concept_ids.filtered(lambda concept: concept.category == "chapter")[:1]
        if not root:
            raise UserError(_("No se ha encontrado concepto raíz o capítulo."))
        decomp_by_parent = {}
        empty_decomposition = self.env["bc3.decomposition.line"]
        for line in file_rec.decomposition_line_ids:
            key = line.parent_concept_id.id if line.parent_concept_id else line.parent_code
            decomp_by_parent.setdefault(key, empty_decomposition)
            decomp_by_parent[key] |= line
        visited = set()
        counter = [10]
        self._create_line_recursive(budget, root, False, 0, "", 1.0, 1.0, 1.0, decomp_by_parent, visited, counter)

    def _create_line_recursive(self, budget, concept, parent_line, level, position_path, factor, performance, quantity, decomp_by_parent, visited, counter):
        code = concept.code
        key = (code, position_path)
        if key in visited:
            return False
        visited.add(key)
        line_type = self._line_type(concept)
        if line_type in ("root", "chapter"):
            factor = 1.0
            performance = 1.0
            quantity = 1.0
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
            "factor": factor,
            "performance": performance,
            "quantity": quantity,
            "price_unit": concept.price_unit,
            "text": concept.text,
        })
        self._copy_measurements(line)
        counter[0] += 10
        children = decomp_by_parent.get(concept.id, self.env["bc3.decomposition.line"])
        if not children:
            children = decomp_by_parent.get(code, self.env["bc3.decomposition.line"])
        for child_rel in children.sorted(key=lambda item: (item.sequence, item.id)):
            child = child_rel.child_concept_id
            if not child:
                continue
            child_position = "%s/%s" % (position_path, child_rel.sequence) if position_path else str(child_rel.sequence)
            child_factor = child_rel.factor or 1.0
            child_performance = child_rel.performance or 1.0
            child_quantity = child_factor * child_performance
            self._create_line_recursive(
                budget,
                child,
                line,
                level + 1,
                child_position,
                child_factor,
                child_performance,
                child_quantity,
                decomp_by_parent,
                visited,
                counter,
            )
        return line

    def _copy_measurements(self, budget_line):
        if budget_line.line_type != "work_unit":
            return
        Concept = self.env["bc3.concept"]
        normalized_code = Concept._normalize_code(budget_line.code)
        candidates = self.env["bc3.measurement.line"].search([("file_id", "=", budget_line.file_id.id)])
        measurements = candidates.filtered(
            lambda item: Concept._normalize_code(item.child_code) == normalized_code
            and (not budget_line.position_path or item.position_path == budget_line.position_path)
        )
        if not measurements:
            measurements = candidates.filtered(lambda item: Concept._normalize_code(item.child_code) == normalized_code)
        vals = []
        for item in measurements.sorted(key=lambda m: (m.position_path or "", m.sequence, m.id)):
            vals.append({
                "budget_line_id": budget_line.id,
                "sequence": item.sequence,
                "line_type": item.line_type or "",
                "comment": item.comment,
                "bim_id": item.bim_id,
                "units": item.units,
                "length": item.length,
                "width": item.width,
                "height": item.height,
                "label": item.label,
            })
        if vals:
            self.env["bc3.budget.measurement.line"].create(vals)
            label = measurements[:1].label if measurements[:1] else ""
            total = sum(self.env["bc3.budget.measurement.line"].search([("budget_line_id", "=", budget_line.id)]).mapped("subtotal"))
            budget_line.write({"measurement_label": label, "quantity": total or budget_line.quantity, "performance": (total or budget_line.quantity) / (budget_line.factor or 1.0)})

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
