from odoo import _, api, fields, models
from odoo.exceptions import UserError


def order_line_uom_field(env):
    """Return the sale order line UoM field name for the current Odoo version.

    Odoo 19 uses product_uom_id, while older versions used product_uom.
    Keeping the fallback avoids hard failures during upgrades.
    """
    fields_map = env["sale.order.line"]._fields
    if "product_uom_id" in fields_map:
        return "product_uom_id"
    if "product_uom" in fields_map:
        return "product_uom"
    return False


class SaleOrder(models.Model):
    _inherit = "sale.order"

    bc3_budget_id = fields.Many2one("bc3.budget", string="BC3 Budget", copy=False, index=True)
    bc3_file_id = fields.Many2one(related="bc3_budget_id.file_id", string="BC3 File", store=True)
    bc3_generated_from_budget = fields.Boolean(copy=False)

    def action_fill_from_bc3_budget(self):
        for order in self:
            if not order.bc3_budget_id:
                raise UserError(_("Select a BC3 budget first."))
            if order.state not in ("draft", "sent"):
                raise UserError(_("Only draft quotations can be filled from a BC3 budget."))
            order.order_line.unlink()
            values = []
            product = self.env.ref("tl_bc3_sale.product_bc3_work_unit", raise_if_not_found=False)
            for line in order.bc3_budget_id.line_ids.sorted(key=lambda item: (item.sequence, item.id)):
                if not order._bc3_should_create_sale_line(line):
                    continue
                values.append((0, 0, order._prepare_sale_line_from_bc3_line(line, product)))
            order.write({"order_line": values, "bc3_generated_from_budget": True})
        return True

    def _bc3_should_create_sale_line(self, budget_line):
        if budget_line.line_type in ("root", "chapter"):
            return True
        # Resources, percentages and lower decompositions remain in the BC3 technical budget.
        # The commercial quotation is generated from the work units directly under chapters.
        if budget_line.line_type != "work_unit":
            return False
        return bool(budget_line.parent_id and budget_line.parent_id.line_type == "chapter")

    def _prepare_sale_line_from_bc3_line(self, budget_line, product):
        if budget_line.line_type in ("root", "chapter"):
            return {
                "display_type": self._bc3_section_display_type(budget_line),
                "name": self._bc3_section_name(budget_line),
                "sequence": budget_line.sequence,
                "bc3_budget_line_id": budget_line.id,
                "bc3_code": budget_line.code,
                "bc3_position_path": budget_line.position_path,
                "bc3_line_type": budget_line.line_type,
            }
        name = "[%s] %s" % (budget_line.code, budget_line.name)
        if budget_line.text:
            name = "%s\n%s" % (name, budget_line.text)
        vals = {
            "name": name,
            "product_uom_qty": budget_line.quantity,
            "price_unit": budget_line.price_unit,
            "sequence": budget_line.sequence,
            "bc3_budget_line_id": budget_line.id,
            "bc3_code": budget_line.code,
            "bc3_position_path": budget_line.position_path,
            "bc3_line_type": budget_line.line_type,
            "bc3_measurement_total": budget_line.quantity,
            "bc3_original_price_unit": budget_line.price_unit,
            "bc3_original_subtotal": budget_line.amount_total,
        }
        if product:
            vals["product_id"] = product.id
        if budget_line.uom_id:
            uom_field = order_line_uom_field(self.env)
            if uom_field:
                vals[uom_field] = budget_line.uom_id.id
        return vals

    def _bc3_section_display_type(self, budget_line):
        selection = self.env["sale.order.line"]._fields["display_type"].selection
        values = [item[0] for item in selection] if isinstance(selection, list) else []
        if budget_line.level > 1 and "line_subsection" in values:
            return "line_subsection"
        return "line_section"

    def _bc3_section_name(self, budget_line):
        return "%s - %s" % (budget_line.code, budget_line.name)


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    bc3_budget_line_id = fields.Many2one("bc3.budget.line", string="BC3 Budget Line", copy=False, index=True)
    bc3_code = fields.Char(copy=False, index=True)
    bc3_position_path = fields.Char(copy=False, index=True)
    bc3_line_type = fields.Selection(
        [("root", "Root"), ("chapter", "Chapter"), ("work_unit", "Work Unit"), ("resource", "Resource"), ("percentage", "Percentage")],
        copy=False,
    )
    bc3_measurement_total = fields.Float(copy=False, digits="Product Unit of Measure")
    bc3_original_price_unit = fields.Float(copy=False, digits="Product Price")
    bc3_original_subtotal = fields.Monetary(copy=False, currency_field="currency_id")
    bc3_sync_state = fields.Selection(
        [("ok", "OK"), ("modified", "Modified"), ("obsolete", "Obsolete")],
        default="ok",
        copy=False,
    )
    bc3_certified_qty = fields.Float(string="BC3 Certified Qty", copy=False, digits="Product Unit of Measure")
    bc3_certified_amount = fields.Monetary(string="BC3 Certified Amount", copy=False, currency_field="currency_id")

    @api.onchange("product_uom_qty", "price_unit")
    def _onchange_bc3_sync_state(self):
        for line in self:
            if line.bc3_budget_line_id and not line.display_type:
                if line.product_uom_qty != line.bc3_measurement_total or line.price_unit != line.bc3_original_price_unit:
                    line.bc3_sync_state = "modified"
                else:
                    line.bc3_sync_state = "ok"

    def _get_bc3_sale_uom(self):
        self.ensure_one()
        if "product_uom_id" in self._fields:
            return self.product_uom_id
        if "product_uom" in self._fields:
            return self.product_uom
        return self.env["uom.uom"]
