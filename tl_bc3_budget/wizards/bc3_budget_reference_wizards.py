import fnmatch
import re

from odoo import _, fields, models
from odoo.exceptions import UserError


class Bc3BudgetInsertCodeWizard(models.TransientModel):
    _name = "bc3.budget.insert.code.wizard"
    _description = "Insertar concepto BC3 por código"

    budget_id = fields.Many2one("bc3.budget", required=True, readonly=True)
    parent_id = fields.Many2one("bc3.budget.line", string="Línea superior", required=True)
    catalog_file_id = fields.Many2one("bc3.file", string="Banco de precios", domain=[("state", "=", "parsed"), ("info_type", "=", "1")])
    code = fields.Char(string="Código", required=True)
    name = fields.Char(string="Resumen")
    line_type = fields.Selection(
        [("chapter", "Capítulo"), ("work_unit", "Partida"), ("resource", "Recurso"), ("percentage", "Porcentaje")],
        string="Tipo si no existe",
        default="work_unit",
        required=True,
    )
    quantity = fields.Float(string="Cantidad", default=1.0)
    price_unit = fields.Float(string="Precio", digits="Product Price")
    create_if_missing = fields.Boolean(string="Crear si no existe", default=True)
    copy_measurements = fields.Boolean(string="Copiar mediciones del banco")

    def action_insert(self):
        self.ensure_one()
        budget = self.budget_id
        code = (self.code or "").strip()
        if not code:
            raise UserError(_("Debe indicar un código."))
        concept = budget._find_catalog_concept_by_code(code, self.catalog_file_id)
        if concept:
            line = budget._insert_catalog_concept(concept, self.parent_id, quantity=self.quantity, copy_measurements=self.copy_measurements)
        else:
            existing_line = budget.line_ids.filtered(lambda line: line.code == code)[:1]
            if existing_line:
                line = budget._copy_budget_line_recursive(existing_line, self.parent_id)
            else:
                if not self.create_if_missing:
                    raise UserError(_("No se ha encontrado el código en los bancos asociados."))
                concept = self.env["bc3.concept"].search([
                    ("file_id", "=", budget.file_id.id),
                    ("normalized_code", "=", self.env["bc3.concept"]._normalize_code(code)),
                ], limit=1)
                if not concept:
                    concept = self.env["bc3.concept"].create({
                        "file_id": budget.file_id.id,
                        "code": code,
                        "normalized_code": self.env["bc3.concept"]._normalize_code(code),
                        "name": self.name or code,
                        "category": self.line_type,
                        "unit_name": "" if self.line_type in ("chapter", "percentage") else "ud",
                        "price_unit": self.price_unit,
                    })
                line = budget._insert_catalog_concept(concept, self.parent_id, quantity=self.quantity, copy_measurements=False)
                if self.price_unit:
                    line.write({"price_unit": self.price_unit})
        return {
            "type": "ir.actions.act_window",
            "name": _("Línea insertada"),
            "res_model": "bc3.budget.line",
            "view_mode": "form",
            "res_id": line.id,
        }


class Bc3BudgetUpdateFromBankWizard(models.TransientModel):
    _name = "bc3.budget.update.from.bank.wizard"
    _description = "Actualizar concepto BC3 desde banco"

    budget_id = fields.Many2one("bc3.budget", required=True, readonly=True)
    line_id = fields.Many2one("bc3.budget.line", string="Línea", required=True)
    catalog_file_id = fields.Many2one("bc3.file", string="Banco", domain=[("state", "=", "parsed"), ("info_type", "=", "1")])
    code = fields.Char(required=True)
    concept_id = fields.Many2one("bc3.concept", string="Concepto del banco")
    price_line_id = fields.Many2one("bc3.concept.price.line", string="Precio alternativo")
    update_summary = fields.Boolean(string="Resumen", default=True)
    update_unit = fields.Boolean(string="Unidad", default=True)
    update_text = fields.Boolean(string="Texto largo", default=True)
    update_price = fields.Boolean(string="Precio", default=True)
    update_decomposition = fields.Boolean(string="Descomposición/APU", default=True)
    update_nature = fields.Boolean(string="Naturaleza", default=True)
    update_formula = fields.Boolean(string="Fórmula de medición", default=True)
    keep_measurements = fields.Boolean(string="Conservar mediciones", default=True)

    def _get_concept(self):
        self.ensure_one()
        concept = self.concept_id
        if not concept:
            concept = self.budget_id._find_catalog_concept_by_code(self.code, self.catalog_file_id)
        if not concept:
            raise UserError(_("No se ha encontrado el concepto en los bancos asociados."))
        return concept

    def action_update(self):
        self.ensure_one()
        concept = self._get_concept()
        price_line = self.price_line_id if self.price_line_id and self.price_line_id.concept_id == concept else False
        self.line_id._apply_catalog_update_options(
            concept,
            update_summary=self.update_summary,
            update_unit=self.update_unit,
            update_text=self.update_text,
            update_price=self.update_price,
            update_decomposition=self.update_decomposition,
            update_nature=self.update_nature,
            update_formula=self.update_formula,
            keep_measurements=self.keep_measurements,
            price_line=price_line,
        )
        return True


class Bc3BudgetSubstituteListWizard(models.TransientModel):
    _name = "bc3.budget.substitute.list.wizard"
    _description = "Sustituir conceptos BC3 por lista"

    budget_id = fields.Many2one("bc3.budget", required=True, readonly=True)
    catalog_file_id = fields.Many2one("bc3.file", string="Banco", domain=[("state", "=", "parsed"), ("info_type", "=", "1")])
    mapping_text = fields.Text(
        string="Lista",
        required=True,
        help="Una sustitución por línea: código antiguo<TAB>código nuevo. Se admiten máscaras con *. Si deja el nuevo código vacío, elimina la línea.",
    )
    update_decomposition = fields.Boolean(string="Actualizar APU", default=True)
    keep_measurements = fields.Boolean(string="Conservar mediciones", default=True)

    def _parse_mapping(self):
        pairs = []
        for raw in (self.mapping_text or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = re.split(r"\t|;|,|\s+", line, maxsplit=1)
            old = parts[0].strip()
            new = parts[1].strip() if len(parts) > 1 else ""
            if old:
                pairs.append((old, new))
        return pairs

    def action_apply(self):
        self.ensure_one()
        count = 0
        for old, new in self._parse_mapping():
            candidates = self.budget_id.line_ids.filtered(lambda line: line.line_type != "root" and fnmatch.fnmatchcase(line.code or "", old))
            for line in candidates:
                if not new:
                    line.unlink()
                    count += 1
                    continue
                new_code = new
                if "*" in old and "*" in new:
                    # Basic mask replacement: keep the part matched by the first *.
                    prefix, suffix = old.split("*", 1)
                    middle = (line.code or "")[len(prefix):]
                    if suffix and middle.endswith(suffix):
                        middle = middle[:-len(suffix)]
                    new_code = new.replace("*", middle, 1)
                concept = self.budget_id._find_catalog_concept_by_code(new_code, self.catalog_file_id)
                if not concept:
                    raise UserError(_("No se ha encontrado el concepto %s en el banco.") % new_code)
                line._apply_catalog_update_options(
                    concept,
                    update_summary=True,
                    update_unit=True,
                    update_text=True,
                    update_price=True,
                    update_decomposition=self.update_decomposition,
                    update_nature=True,
                    update_formula=True,
                    keep_measurements=self.keep_measurements,
                )
                count += 1
        self.budget_id._recompute_all_lines()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("Sustitución BC3"), "message": _("Líneas afectadas: %s") % count, "type": "success"},
        }


class Bc3PriceOperateWizard(models.TransientModel):
    _name = "bc3.price.operate.wizard"
    _description = "Operar precios BC3"

    budget_id = fields.Many2one("bc3.budget", string="Presupuesto")
    file_id = fields.Many2one("bc3.file", string="Banco de precios", domain=[("state", "=", "parsed")])
    only_unlocked = fields.Boolean(string="Solo no bloqueados", default=True)
    percent_work_unit = fields.Float(string="% partidas")
    percent_labor = fields.Float(string="% mano de obra")
    percent_material = fields.Float(string="% materiales")
    percent_machinery = fields.Float(string="% maquinaria")
    percent_other = fields.Float(string="% otros")

    def _percent_for_concept(self, concept, line_type=False):
        ctype = concept.concept_type or ""
        category = concept.category or line_type or ""
        if category == "work_unit":
            return self.percent_work_unit
        if ctype == "1":
            return self.percent_labor
        if ctype == "2":
            return self.percent_machinery
        if ctype == "3":
            return self.percent_material
        return self.percent_other

    def action_apply(self):
        self.ensure_one()
        changed = 0
        if self.budget_id:
            lines = self.budget_id.line_ids.filtered(lambda line: line.line_type in ("work_unit", "resource"))
            if self.only_unlocked:
                lines = lines.filtered(lambda line: not line.price_locked and not line.is_locked)
            for line in lines:
                pct = self._percent_for_concept(line.concept_id, line.line_type)
                if pct:
                    line.with_context(bc3_skip_recompute=True).write({"price_unit": (line.price_unit or 0.0) * (1.0 + pct / 100.0)})
                    changed += 1
            self.budget_id._recompute_all_lines()
        elif self.file_id:
            concepts = self.file_id.concept_ids
            if self.only_unlocked:
                concepts = concepts.filtered(lambda concept: not concept.price_locked and not concept.is_locked)
            for concept in concepts:
                pct = self._percent_for_concept(concept)
                if pct:
                    concept.write({"price_unit": (concept.price_unit or 0.0) * (1.0 + pct / 100.0)})
                    changed += 1
        else:
            raise UserError(_("Debe seleccionar un presupuesto o un banco."))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("Operar precios"), "message": _("Precios modificados: %s") % changed, "type": "success"},
        }


class Bc3ConceptDuplicateWizard(models.TransientModel):
    _name = "bc3.concept.duplicate.wizard"
    _description = "Duplicar concepto BC3"

    concept_id = fields.Many2one("bc3.concept", required=True, readonly=True)
    target_file_id = fields.Many2one("bc3.file", string="Banco destino", required=True)
    new_code = fields.Char(string="Nuevo código", required=True)
    copy_decomposition = fields.Boolean(string="Copiar descomposición", default=True)
    copy_prices = fields.Boolean(string="Copiar precios alternativos", default=True)

    def action_duplicate(self):
        self.ensure_one()
        clone = self.concept_id._bc3_copy_to_file(
            self.target_file_id,
            new_code=self.new_code,
            copy_decomposition=self.copy_decomposition,
            copy_prices=self.copy_prices,
            copied={},
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Concepto duplicado"),
            "res_model": "bc3.concept",
            "view_mode": "form",
            "res_id": clone.id,
        }


class Bc3ConceptRenameWizard(models.TransientModel):
    _name = "bc3.concept.rename.wizard"
    _description = "Renombrar concepto BC3"

    concept_id = fields.Many2one("bc3.concept", required=True, readonly=True)
    new_code = fields.Char(string="Nuevo código", required=True)
    update_relations = fields.Boolean(string="Actualizar relaciones y líneas", default=True)

    def action_rename(self):
        self.ensure_one()
        concept = self.concept_id
        old_code = concept.code
        new_code = (self.new_code or "").strip()
        if not new_code:
            raise UserError(_("Debe indicar un código."))
        normalized = self.env["bc3.concept"]._normalize_code(new_code)
        duplicate = self.env["bc3.concept"].search([
            ("file_id", "=", concept.file_id.id),
            ("normalized_code", "=", normalized),
            ("id", "!=", concept.id),
        ], limit=1)
        if duplicate:
            raise UserError(_("Ya existe un concepto con ese código en el banco."))
        concept.write({"code": new_code, "normalized_code": normalized})
        if self.update_relations:
            decomp = self.env["bc3.decomposition.line"].search([("file_id", "=", concept.file_id.id)])
            decomp.filtered(lambda rel: rel.parent_code == old_code).write({"parent_code": new_code})
            decomp.filtered(lambda rel: rel.child_code == old_code).write({"child_code": new_code})
            self.env["bc3.budget.line"].search([("concept_id", "=", concept.id)]).write({"code": new_code})
        return True
