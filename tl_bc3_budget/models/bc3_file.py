from odoo import _, api, fields, models
from odoo.exceptions import UserError


class Bc3File(models.Model):
    _inherit = "bc3.file"

    def action_create_budget(self):
        self.ensure_one()
        if self.state != "parsed":
            raise UserError(_("Procese el fichero BC3 antes de crear un presupuesto."))
        budget = self.env["bc3.budget"].create_from_file(self)
        return {
            "type": "ir.actions.act_window",
            "name": _("Presupuesto BC3"),
            "res_model": "bc3.budget",
            "view_mode": "form",
            "res_id": budget.id,
        }

class Bc3FileBudgetLinks(models.Model):
    _inherit = "bc3.file"

    budget_ids = fields.One2many("bc3.budget", "file_id", string="Presupuestos")
    budget_count = fields.Integer(string="Presupuestos", compute="_compute_budget_count")

    def _compute_budget_count(self):
        for rec in self:
            rec.budget_count = len(rec.budget_ids)

    def action_open_budgets(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Presupuestos BC3"),
            "res_model": "bc3.budget",
            "view_mode": "list,form",
            "domain": [("file_id", "=", self.id)],
            "context": {"default_file_id": self.id},
        }


class Bc3FileManualPriceBank(models.Model):
    _inherit = "bc3.file"

    is_manual_price_bank = fields.Boolean(string="Banco de precios manual", tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        manual_context = self.env.context.get("bc3_manual_price_bank") or self.env.context.get("default_info_type") == "1"
        for vals in vals_list:
            is_bank = manual_context or vals.get("info_type") == "1" or vals.get("is_manual_price_bank")
            if is_bank:
                vals.setdefault("info_type", "1")
                vals.setdefault("state", "parsed")
                vals.setdefault("source_type", "upload")
                vals.setdefault("is_manual_price_bank", True)
        return super().create(vals_list)

    def action_mark_as_price_bank(self):
        for rec in self:
            rec.write({
                "info_type": "1",
                "state": "parsed",
                "source_type": rec.source_type or "upload",
                "is_manual_price_bank": True,
            })
            rec.action_refresh_price_bank_stats()
        return True

    def action_refresh_price_bank_stats(self):
        for rec in self:
            raw_count = len(rec.raw_record_ids)
            concept_count = len(rec.concept_ids)
            decomposition_count = len(rec.decomposition_line_ids)
            measurement_count = len(rec.measurement_line_ids)
            by_category = {}
            for concept in rec.concept_ids:
                by_category[concept.category or "other"] = by_category.get(concept.category or "other", 0) + 1
            labels = {
                "root": "Raices",
                "chapter": "Capitulos",
                "work_unit": "Partidas",
                "resource": "Recursos",
                "percentage": "Porcentajes",
                "other": "Otros",
            }
            lines = [
                "Conceptos: %s" % concept_count,
                "Descomposiciones: %s" % decomposition_count,
                "Mediciones: %s" % measurement_count,
            ]
            for key in ("root", "chapter", "work_unit", "resource", "percentage", "other"):
                if by_category.get(key):
                    lines.append("%s: %s" % (labels[key], by_category[key]))
            rec.write({
                "record_count": raw_count,
                "concept_count": concept_count,
                "decomposition_count": decomposition_count,
                "measurement_count": measurement_count,
                "record_stats_text": "\n".join(lines),
            })
        return True


class Bc3ConceptManualPriceBank(models.Model):
    _inherit = "bc3.concept"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            code = vals.get("code")
            if code and not vals.get("normalized_code"):
                vals["normalized_code"] = self._normalize_code(code)
            if code and not vals.get("category"):
                vals["category"] = self._get_category_from_code(code, vals.get("concept_type"))
        records = super().create(vals_list)
        records.mapped("file_id").filtered(lambda f: f.info_type == "1").action_refresh_price_bank_stats()
        return records

    def write(self, vals):
        if vals.get("code") and not vals.get("normalized_code"):
            vals = dict(vals)
            vals["normalized_code"] = self._normalize_code(vals.get("code"))
        files = self.mapped("file_id")
        res = super().write(vals)
        (files | self.mapped("file_id")).filtered(lambda f: f.info_type == "1").action_refresh_price_bank_stats()
        return res

    def unlink(self):
        files = self.mapped("file_id")
        res = super().unlink()
        files.filtered(lambda f: f.info_type == "1").action_refresh_price_bank_stats()
        return res


class Bc3DecompositionLineManualPriceBank(models.Model):
    _inherit = "bc3.decomposition.line"

    @api.onchange("parent_concept_id")
    def _onchange_parent_concept_id_manual_bank(self):
        for line in self:
            if line.parent_concept_id:
                line.parent_code = line.parent_concept_id.code
                line.file_id = line.file_id or line.parent_concept_id.file_id

    @api.onchange("child_concept_id")
    def _onchange_child_concept_id_manual_bank(self):
        for line in self:
            if line.child_concept_id:
                line.child_code = line.child_concept_id.code
                line.file_id = line.file_id or line.child_concept_id.file_id

    @api.model
    def _manual_prepare_vals(self, vals):
        vals = dict(vals)
        file_id = vals.get("file_id")
        parent = self.env["bc3.concept"].browse(vals.get("parent_concept_id")) if vals.get("parent_concept_id") else self.env["bc3.concept"]
        child = self.env["bc3.concept"].browse(vals.get("child_concept_id")) if vals.get("child_concept_id") else self.env["bc3.concept"]
        if parent:
            vals["parent_code"] = parent.code
            file_id = file_id or parent.file_id.id
        if child:
            vals["child_code"] = child.code
            file_id = file_id or child.file_id.id
        if file_id:
            vals["file_id"] = file_id
            Concept = self.env["bc3.concept"]
            if not parent and vals.get("parent_code"):
                normalized = Concept._normalize_code(vals.get("parent_code"))
                parent = Concept.search([("file_id", "=", file_id), ("normalized_code", "=", normalized)], limit=1)
                if parent:
                    vals["parent_concept_id"] = parent.id
            if not child and vals.get("child_code"):
                normalized = Concept._normalize_code(vals.get("child_code"))
                child = Concept.search([("file_id", "=", file_id), ("normalized_code", "=", normalized)], limit=1)
                if child:
                    vals["child_concept_id"] = child.id
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._manual_prepare_vals(vals) for vals in vals_list]
        records = super().create(vals_list)
        records.mapped("file_id").filtered(lambda f: f.info_type == "1").action_refresh_price_bank_stats()
        return records

    def write(self, vals):
        files = self.mapped("file_id")
        vals = self._manual_prepare_vals(vals) if any(k in vals for k in ("file_id", "parent_concept_id", "child_concept_id", "parent_code", "child_code")) else vals
        res = super().write(vals)
        (files | self.mapped("file_id")).filtered(lambda f: f.info_type == "1").action_refresh_price_bank_stats()
        return res

    def unlink(self):
        files = self.mapped("file_id")
        res = super().unlink()
        files.filtered(lambda f: f.info_type == "1").action_refresh_price_bank_stats()
        return res
