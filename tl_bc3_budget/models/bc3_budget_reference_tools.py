import fnmatch
import math
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval


class Bc3ConceptPriceLine(models.Model):
    _name = "bc3.concept.price.line"
    _description = "Precio alternativo de concepto BC3"
    _order = "concept_id, sequence, id"

    sequence = fields.Integer(default=10)
    concept_id = fields.Many2one("bc3.concept", required=True, ondelete="cascade", index=True)
    file_id = fields.Many2one(related="concept_id.file_id", store=True, index=True)
    name = fields.Char(string="Tarifa / referencia", required=True, default="Precio alternativo")
    partner_id = fields.Many2one("res.partner", string="Proveedor / ofertante")
    zone = fields.Char(string="Zona")
    currency_id = fields.Many2one("res.currency", string="Divisa", default=lambda self: self.env.company.currency_id)
    price_unit = fields.Float(string="Precio", digits="Product Price", required=True)
    date = fields.Date(string="Fecha", default=fields.Date.context_today)
    active = fields.Boolean(default=True)
    note = fields.Char(string="Nota")


class Bc3ConceptReferenceTools(models.Model):
    _inherit = "bc3.concept"

    is_locked = fields.Boolean(string="Bloqueado")
    is_inactive = fields.Boolean(string="Anulado")
    price_locked = fields.Boolean(string="Precio bloqueado")
    default_measure_formula = fields.Char(string="Fórmula de medición por defecto")
    measure_header_comment = fields.Char(string="Cabecera comentario", default="Comentario")
    measure_header_units = fields.Char(string="Cabecera N", default="N")
    measure_header_length = fields.Char(string="Cabecera longitud", default="Longitud")
    measure_header_width = fields.Char(string="Cabecera anchura", default="Anchura")
    measure_header_height = fields.Char(string="Cabecera altura", default="Altura")
    price_line_ids = fields.One2many("bc3.concept.price.line", "concept_id", string="Precios alternativos")
    attachment_count = fields.Integer(compute="_compute_attachment_count", string="Adjuntos")

    def _compute_attachment_count(self):
        Attachment = self.env["ir.attachment"]
        for concept in self:
            concept.attachment_count = Attachment.search_count([
                ("res_model", "=", "bc3.concept"),
                ("res_id", "=", concept.id),
            ])

    def action_open_attachments(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Adjuntos del concepto"),
            "res_model": "ir.attachment",
            "view_mode": "list,form",
            "domain": [("res_model", "=", "bc3.concept"), ("res_id", "=", self.id)],
            "context": {"default_res_model": "bc3.concept", "default_res_id": self.id},
        }

    def action_open_duplicate_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Duplicar concepto BC3"),
            "res_model": "bc3.concept.duplicate.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_concept_id": self.id, "default_target_file_id": self.file_id.id},
        }

    def action_open_rename_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Renombrar concepto BC3"),
            "res_model": "bc3.concept.rename.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_concept_id": self.id, "default_new_code": self.code},
        }

    def _bc3_copy_to_file(self, target_file, new_code=False, copy_decomposition=True, copy_prices=True, copied=None):
        self.ensure_one()
        copied = copied if copied is not None else {}
        target_code = new_code or self.code
        key = (self.file_id.id, self.code, target_file.id, target_code)
        if key in copied:
            return copied[key]
        existing = self.search([
            ("file_id", "=", target_file.id),
            ("normalized_code", "=", self._normalize_code(target_code)),
        ], limit=1)
        if existing:
            copied[key] = existing
            return existing
        vals = {
            "file_id": target_file.id,
            "code": target_code,
            "normalized_code": self._normalize_code(target_code),
            "name": self.name,
            "unit_name": self.unit_name,
            "uom_id": self.uom_id.id if self.uom_id else False,
            "concept_type": self.concept_type,
            "category": self.category,
            "price_unit": self.price_unit,
            "price_date_raw": self.price_date_raw,
            "text": self.text,
            "technical_json": self.technical_json,
            "is_locked": self.is_locked,
            "is_inactive": self.is_inactive,
            "price_locked": self.price_locked,
            "default_measure_formula": self.default_measure_formula,
            "measure_header_comment": self.measure_header_comment,
            "measure_header_units": self.measure_header_units,
            "measure_header_length": self.measure_header_length,
            "measure_header_width": self.measure_header_width,
            "measure_header_height": self.measure_header_height,
        }
        clone = self.create(vals)
        copied[key] = clone
        if copy_prices:
            for price in self.price_line_ids:
                self.env["bc3.concept.price.line"].create({
                    "concept_id": clone.id,
                    "sequence": price.sequence,
                    "name": price.name,
                    "partner_id": price.partner_id.id if price.partner_id else False,
                    "zone": price.zone,
                    "currency_id": price.currency_id.id if price.currency_id else False,
                    "price_unit": price.price_unit,
                    "date": price.date,
                    "active": price.active,
                    "note": price.note,
                })
        if copy_decomposition:
            Decomp = self.env["bc3.decomposition.line"]
            rels = Decomp.search([("file_id", "=", self.file_id.id)]).filtered(
                lambda rel: rel.parent_concept_id.id == self.id or self._normalize_code(rel.parent_code) == self._normalize_code(self.code)
            )
            for rel in rels.sorted(key=lambda item: (item.sequence, item.id)):
                child = rel.child_concept_id
                if not child:
                    child = self.search([
                        ("file_id", "=", self.file_id.id),
                        ("normalized_code", "=", self._normalize_code(rel.child_code)),
                    ], limit=1)
                child_clone = child._bc3_copy_to_file(target_file, copy_decomposition=True, copy_prices=copy_prices, copied=copied) if child else False
                Decomp.create({
                    "file_id": target_file.id,
                    "parent_code": clone.code,
                    "child_code": child_clone.code if child_clone else rel.child_code,
                    "parent_concept_id": clone.id,
                    "child_concept_id": child_clone.id if child_clone else False,
                    "sequence": rel.sequence,
                    "factor": rel.factor,
                    "performance": rel.performance,
                    "percent_codes": rel.percent_codes,
                })
        return clone


class Bc3BudgetReferenceTools(models.Model):
    _inherit = "bc3.budget"

    def action_open_insert_by_code(self):
        self.ensure_one()
        parent = self.line_ids.filtered(lambda line: line.line_type in ("root", "chapter"))[:1]
        if not parent:
            parent = self.line_ids.filtered(lambda line: not line.parent_id)[:1]
        return {
            "type": "ir.actions.act_window",
            "name": _("Insertar concepto por código"),
            "res_model": "bc3.budget.insert.code.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_budget_id": self.id, "default_parent_id": parent.id if parent else False},
        }

    def action_open_substitute_list(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Sustituir conceptos por lista"),
            "res_model": "bc3.budget.substitute.list.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_budget_id": self.id},
        }

    def action_open_price_operate(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Operar precios"),
            "res_model": "bc3.price.operate.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_budget_id": self.id},
        }

    def _catalog_source_files(self, catalog_file=False):
        self.ensure_one()
        if catalog_file:
            return catalog_file
        files = self.catalog_file_ids
        if not files:
            files = self.env["bc3.file"].search([("state", "=", "parsed"), ("info_type", "=", "1")])
        return files

    def _find_catalog_concept_by_code(self, code, catalog_file=False):
        self.ensure_one()
        normalized = self.env["bc3.concept"]._normalize_code(code)
        files = self._catalog_source_files(catalog_file)
        if not files:
            return self.env["bc3.concept"]
        return self.env["bc3.concept"].search([
            ("file_id", "in", files.ids),
            ("normalized_code", "=", normalized),
        ], limit=1)

    def _copy_budget_line_recursive(self, source_line, parent_line, new_code=False):
        self.ensure_one()
        vals = {
            "budget_id": self.id,
            "parent_id": parent_line.id if parent_line else False,
            "sequence": self._next_child_sequence(parent_line),
            "level": (parent_line.level + 1) if parent_line else 0,
            "position_path": "",
            "concept_id": source_line.concept_id.id if source_line.concept_id else False,
            "code": new_code or source_line.code,
            "name": source_line.name,
            "line_type": source_line.line_type,
            "unit_name": source_line.unit_name,
            "uom_id": source_line.uom_id.id if source_line.uom_id else False,
            "factor": source_line.factor,
            "performance": source_line.performance,
            "quantity": source_line.quantity,
            "price_unit": source_line.price_unit,
            "text": source_line.text,
            "measurement_label": source_line.measurement_label,
            "measurement_formula": source_line.measurement_formula,
            "measure_header_comment": source_line.measure_header_comment,
            "measure_header_units": source_line.measure_header_units,
            "measure_header_length": source_line.measure_header_length,
            "measure_header_width": source_line.measure_header_width,
            "measure_header_height": source_line.measure_header_height,
            "price_locked": source_line.price_locked,
            "is_inactive": source_line.is_inactive,
        }
        pos = "%s/%s" % (parent_line.position_path, vals["sequence"]) if parent_line and parent_line.position_path else str(vals["sequence"])
        vals["position_path"] = pos
        clone = self.env["bc3.budget.line"].with_context(bc3_skip_recompute=True).create(vals)
        for mline in source_line.budget_measurement_line_ids:
            self.env["bc3.budget.measurement.line"].with_context(bc3_skip_recompute=True).create({
                "budget_line_id": clone.id,
                "sequence": mline.sequence,
                "line_type": mline.line_type,
                "comment": mline.comment,
                "bim_id": mline.bim_id,
                "units": mline.units,
                "length": mline.length,
                "width": mline.width,
                "height": mline.height,
                "formula": mline.formula,
                "label": mline.label,
            })
        for child in source_line.child_ids.sorted(key=lambda item: (item.sequence, item.id)):
            self._copy_budget_line_recursive(child, clone)
        clone._recompute_after_change()
        return clone


class Bc3BudgetLineReferenceTools(models.Model):
    _inherit = "bc3.budget.line"

    measurement_formula = fields.Char(string="Fórmula de medición")
    measure_header_comment = fields.Char(string="Cabecera comentario", default="Comentario")
    measure_header_units = fields.Char(string="Cabecera N", default="N")
    measure_header_length = fields.Char(string="Cabecera longitud", default="Longitud")
    measure_header_width = fields.Char(string="Cabecera anchura", default="Anchura")
    measure_header_height = fields.Char(string="Cabecera altura", default="Altura")
    is_locked = fields.Boolean(string="Bloqueada")
    is_inactive = fields.Boolean(string="Anulada")
    price_locked = fields.Boolean(string="Precio manual bloqueado")

    @api.onchange("concept_id")
    def _onchange_concept_reference_defaults(self):
        for line in self:
            concept = line.concept_id
            if concept:
                line.measurement_formula = concept.default_measure_formula
                line.measure_header_comment = concept.measure_header_comment or "Comentario"
                line.measure_header_units = concept.measure_header_units or "N"
                line.measure_header_length = concept.measure_header_length or "Longitud"
                line.measure_header_width = concept.measure_header_width or "Anchura"
                line.measure_header_height = concept.measure_header_height or "Altura"

    def _leaf_amount_from_running_base(self, running_base=0.0):
        self.ensure_one()
        if self.is_inactive:
            return 0.0
        return super()._leaf_amount_from_running_base(running_base)

    def _recompute_from_existing_children(self):
        for line in self:
            if line.is_inactive:
                if line._float_diff(line.amount_total, 0.0):
                    line._write_recalculated_values({"amount_total": 0.0})
                continue
            children = line.child_ids.sorted(key=lambda item: (item.sequence, item.id))
            if not children:
                amount = line._leaf_amount_from_running_base(0.0)
                if line._float_diff(line.amount_total, amount):
                    line._write_recalculated_values({"amount_total": amount})
                continue
            children_total = sum(children.mapped("amount_total"))
            vals = {}
            if line.line_type == "work_unit":
                unit_price = line.price_unit if line.price_locked else children_total
                if not line.price_locked and line._float_diff(line.price_unit, children_total):
                    vals["price_unit"] = children_total
                amount = (line.quantity or 0.0) * (unit_price or 0.0)
                if line._float_diff(line.amount_total, amount):
                    vals["amount_total"] = amount
            else:
                if line._float_diff(line.amount_total, children_total):
                    vals["amount_total"] = children_total
            if vals:
                line._write_recalculated_values(vals)

    def write(self, vals):
        protected = {"code", "line_type", "factor", "performance", "quantity", "price_unit", "parent_id", "sequence"}
        if not self.env.context.get("bc3_skip_recompute"):
            locked = self.filtered(lambda line: line.is_locked or line.budget_id.state == "locked")
            if locked and protected.intersection(vals):
                raise UserError(_("La línea o el presupuesto están bloqueados. Desbloquee antes de modificar datos económicos."))
        vals = dict(vals)
        if "price_unit" in vals and not self.env.context.get("bc3_skip_recompute"):
            if any(line.child_ids for line in self):
                vals.setdefault("price_locked", True)
        return super().write(vals)

    def action_open_insert_by_code(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Insertar concepto por código"),
            "res_model": "bc3.budget.insert.code.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_budget_id": self.budget_id.id, "default_parent_id": self.id},
        }

    def action_duplicate_line(self):
        self.ensure_one()
        parent = self.parent_id
        if not parent:
            raise UserError(_("Solo se pueden duplicar líneas con superior."))
        clone = self.budget_id._copy_budget_line_recursive(self, parent)
        return {
            "type": "ir.actions.act_window",
            "name": _("Línea duplicada"),
            "res_model": "bc3.budget.line",
            "view_mode": "form",
            "res_id": clone.id,
        }

    def action_open_update_from_bank(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Actualizar desde banco"),
            "res_model": "bc3.budget.update.from.bank.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_budget_id": self.budget_id.id, "default_line_id": self.id, "default_code": self.code},
        }

    def action_unlock_price(self):
        self.write({"price_locked": False})
        self._recompute_after_change()
        return True

    def _apply_catalog_update_options(self, concept, update_summary=True, update_unit=True, update_text=True, update_price=True,
                                      update_decomposition=False, update_nature=True, update_formula=True, keep_measurements=True,
                                      price_line=False):
        self.ensure_one()
        vals = {"concept_id": concept.id, "code": concept.code}
        if update_summary:
            vals["name"] = concept.name
        if update_unit:
            vals.update({"unit_name": concept.unit_name, "uom_id": concept.uom_id.id if concept.uom_id else False})
        if update_text:
            vals["text"] = concept.text
        if update_price:
            vals["price_unit"] = price_line.price_unit if price_line else concept.price_unit
            if self.child_ids:
                vals["price_locked"] = bool(price_line)
        if update_nature:
            vals["line_type"] = self.budget_id._catalog_line_type(concept)
        if update_formula:
            vals.update({
                "measurement_formula": concept.default_measure_formula,
                "measure_header_comment": concept.measure_header_comment or "Comentario",
                "measure_header_units": concept.measure_header_units or "N",
                "measure_header_length": concept.measure_header_length or "Longitud",
                "measure_header_width": concept.measure_header_width or "Anchura",
                "measure_header_height": concept.measure_header_height or "Altura",
            })
        if update_decomposition:
            self.child_ids.with_context(bc3_skip_recompute=True).unlink()
        self.with_context(bc3_skip_recompute=True).write(vals)
        if not keep_measurements:
            self.budget_measurement_line_ids.with_context(bc3_skip_recompute=True).unlink()
        if update_decomposition:
            for rel in self.budget_id._catalog_decomposition_lines(concept):
                child = rel.child_concept_id
                if child:
                    self.budget_id._create_catalog_line_recursive(
                        child,
                        parent_line=self,
                        sequence=rel.sequence or self.budget_id._next_child_sequence(self),
                        level=self.level + 1,
                        position_path="%s/%s" % (self.position_path, rel.sequence or self.budget_id._next_child_sequence(self)),
                        factor=rel.factor or 1.0,
                        performance=rel.performance or 1.0,
                        quantity=(rel.factor or 1.0) * (rel.performance or 1.0),
                        copy_measurements=False,
                        visited=set(),
                    )
        self._recompute_after_change()
        return self


class Bc3BudgetMeasurementLineReferenceTools(models.Model):
    _inherit = "bc3.budget.measurement.line"

    formula = fields.Char(string="Fórmula")

    @api.depends("line_type", "units", "length", "width", "height", "formula")
    def _compute_subtotal(self):
        for line in self:
            if line.line_type in ("1", "2"):
                line.subtotal = 0.0
                continue
            if line.formula:
                line.subtotal = line._eval_measure_formula()
                continue
            values = [value for value in (line.units, line.length, line.width, line.height) if value not in (0.0, None)]
            if not values:
                line.subtotal = 0.0
                continue
            subtotal = 1.0
            for value in values:
                subtotal *= value
            line.subtotal = subtotal

    def _eval_measure_formula(self):
        self.ensure_one()
        expr = (self.formula or "").strip()
        if not expr:
            return 0.0
        expr = expr.replace("^", "**")
        values = {
            "A": self.units or 0.0,
            "B": self.length or 0.0,
            "C": self.width or 0.0,
            "D": self.height or 0.0,
            "P": math.pi,
            "PI": math.pi,
            "ABS": abs,
            "SQRT": math.sqrt,
            "SIN": lambda x: math.sin(math.radians(x)),
            "COS": lambda x: math.cos(math.radians(x)),
            "TAN": lambda x: math.tan(math.radians(x)),
            "REBAR": lambda diameter: (diameter ** 2 / 162.0),
        }
        try:
            result = safe_eval(expr, values, mode="eval", nocopy=True)
        except Exception as exc:
            raise UserError(_("Fórmula de medición no válida: %s") % exc)
        # Las fórmulas BC3 multiplican por las dimensiones no referenciadas explícitamente.
        used = set(re.findall(r"\b([ABCD])\b", expr.upper()))
        for letter, value in (("A", self.units), ("B", self.length), ("C", self.width), ("D", self.height)):
            if letter not in used and value not in (0.0, None):
                result *= value
        return result or 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("formula") and vals.get("budget_line_id"):
                line = self.env["bc3.budget.line"].browse(vals["budget_line_id"])
                vals["formula"] = line.measurement_formula or (line.concept_id.default_measure_formula if line.concept_id else False)
        return super().create(vals_list)

class Bc3FileReferencePriceTools(models.Model):
    _inherit = "bc3.file"

    def action_open_bank_price_operate(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Operar precios del banco"),
            "res_model": "bc3.price.operate.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_file_id": self.id},
        }
