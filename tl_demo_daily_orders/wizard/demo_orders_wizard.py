# -*- coding: utf-8 -*-
import logging
import random
from datetime import datetime, time, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class TlDemoOrdersWizard(models.TransientModel):
    _name = "tl.demo.orders.wizard"
    _description = "Generar pedidos de compra y venta demo por fechas"

    date_from = fields.Date(required=True, default=lambda s: fields.Date.today() - timedelta(days=14))
    date_to = fields.Date(required=True, default=fields.Date.today)
    min_per_day = fields.Integer(default=3, required=True)
    max_per_day = fields.Integer(default=7, required=True)
    lines_min = fields.Integer(default=1)
    lines_max = fields.Integer(default=4)
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)
    warehouse_id = fields.Many2one("stock.warehouse")
    confirm_pickings = fields.Boolean(default=True, string="Validar albaranes")
    backdate_pickings = fields.Boolean(
        default=True,
        string="Fecha efectiva pasada (Odoo 19)",
        help="Desbloquea el albarán, escribe date_done / scheduled_date y vuelve a bloquear.",
    )
    last_summary = fields.Text(readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        wh = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        if wh and "warehouse_id" in fields_list:
            res["warehouse_id"] = wh.id
        return res

    def action_generate(self):
        self.ensure_one()
        if self.date_to < self.date_from:
            raise UserError("La fecha hasta no puede ser anterior a la fecha desde.")
        if self.min_per_day < 1 or self.max_per_day < self.min_per_day:
            raise UserError("Revisa el intervalo de pedidos por día (mínimo 3–7 recomendado).")

        customers = self._customers()
        vendors = self._vendors()
        products = self._products()
        if not customers:
            raise UserError("No hay contactos con rango de cliente (customer_rank > 0).")
        if not vendors:
            raise UserError("No hay contactos con rango de proveedor (supplier_rank > 0).")
        if not products:
            raise UserError("No hay productos almacenables o consumibles activos con precio.")

        sale_ids, purchase_ids = [], []
        day = self.date_from
        while day <= self.date_to:
            count = random.randint(self.min_per_day, self.max_per_day)
            when = self._dt_on(day)
            # Compras primero para que haya stock el mismo día
            for _ in range(count):
                po = self._create_purchase(random.choice(vendors), products, when)
                purchase_ids.append(po.id)
            for _ in range(count):
                so = self._create_sale(random.choice(customers), products, when)
                sale_ids.append(so.id)
            day += timedelta(days=1)

        summary = (
            f"Generados {len(sale_ids)} pedidos de venta y {len(purchase_ids)} pedidos de compra "
            f"entre {self.date_from} y {self.date_to}."
        )
        self.last_summary = summary
        _logger.info(summary)
        return {
            "type": "ir.actions.act_window",
            "name": "Pedidos de venta generados",
            "res_model": "sale.order",
            "view_mode": "list,form",
            "domain": [("id", "in", sale_ids)],
            "target": "current",
        }

    def _customers(self):
        return self.env["res.partner"].search(
            [
                ("customer_rank", ">", 0),
                ("active", "=", True),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", self.company_id.id),
            ]
        )

    def _vendors(self):
        partners = self.env["res.partner"].search(
            [
                ("supplier_rank", ">", 0),
                ("active", "=", True),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", self.company_id.id),
            ]
        )
        if partners:
            return partners
        # Si no hay proveedores, reutiliza clientes como fallback documentado
        return self._customers()

    def _products(self):
        Product = self.env["product.product"]
        domain = [
            ("sale_ok", "=", True),
            ("purchase_ok", "=", True),
            ("active", "=", True),
            ("type", "in", ("product", "consu")),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", self.company_id.id),
        ]
        products = Product.search(domain, limit=400)
        priced = products.filtered(lambda p: p.list_price > 0 or p.standard_price > 0)
        return priced or products

    def _dt_on(self, day):
        hour = random.randint(8, 17)
        minute = random.choice((0, 15, 30, 45))
        naive = datetime.combine(day, time(hour, minute))
        return fields.Datetime.to_datetime(naive)

    def _line_count(self):
        lo = max(1, self.lines_min)
        hi = max(lo, self.lines_max)
        return random.randint(lo, hi)

    def _create_purchase(self, vendor, products, when):
        lines = []
        used = set()
        for _ in range(self._line_count()):
            product = random.choice(products)
            if product.id in used and len(products) > 1:
                continue
            used.add(product.id)
            qty = random.randint(2, 12)
            price = product.standard_price or max(product.list_price * 0.7, 0.5)
            lines.append(
                (
                    0,
                    0,
                    {
                        "product_id": product.id,
                        "name": product.display_name,
                        "product_qty": qty,
                        "product_uom": product.uom_po_id.id or product.uom_id.id,
                        "price_unit": price,
                        "date_planned": when,
                    },
                )
            )
        po = self.env["purchase.order"].create(
            {
                "partner_id": vendor.id,
                "company_id": self.company_id.id,
                "date_order": when,
                "origin": "DEMO-%s" % when.date(),
                "order_line": lines,
            }
        )
        po.button_confirm()
        if self.confirm_pickings:
            for picking in po.picking_ids.filtered(lambda p: p.state != "cancel"):
                self._validate_and_backdate(picking, when)
        return po

    def _create_sale(self, customer, products, when):
        lines = []
        used = set()
        for _ in range(self._line_count()):
            product = random.choice(products)
            if product.id in used and len(products) > 1:
                continue
            used.add(product.id)
            qty = random.randint(1, 5)
            lines.append(
                (
                    0,
                    0,
                    {
                        "product_id": product.id,
                        "name": product.display_name,
                        "product_uom_qty": qty,
                        "product_uom": product.uom_id.id,
                        "price_unit": product.list_price or product.standard_price or 1.0,
                    },
                )
            )
        vals = {
            "partner_id": customer.id,
            "company_id": self.company_id.id,
            "date_order": when,
            "origin": "DEMO-%s" % when.date(),
            "order_line": lines,
        }
        if self.warehouse_id:
            vals["warehouse_id"] = self.warehouse_id.id
        if "commitment_date" in self.env["sale.order"]._fields:
            vals["commitment_date"] = when
        so = self.env["sale.order"].create(vals)
        so.action_confirm()
        if self.confirm_pickings:
            pickings = so.picking_ids.filtered(lambda p: p.state != "cancel")
            # Entregas: asignar y validar
            for picking in pickings:
                self._validate_and_backdate(picking, when)
        return so

    def _validate_and_backdate(self, picking, when):
        picking = picking.with_context(
            mail_notrack=True,
            tracking_disable=True,
            skip_sms=True,
            skip_immediate=True,
            skip_backorder=True,
            cancel_backorder=True,
        )
        if picking.state == "draft":
            picking.action_confirm()
        if picking.state in ("confirmed", "waiting", "assigned", "partially_available"):
            try:
                picking.action_assign()
            except Exception as exc:
                _logger.warning("No se pudo reservar %s: %s", picking.name, exc)
            self._set_done_qty(picking)
            try:
                picking.button_validate()
            except Exception as exc:
                _logger.warning("Validación inmediata de %s falló (%s), se intenta wizard.", picking.name, exc)
                self._validate_via_wizard(picking)
        if picking.state not in ("done",) and picking.state != "cancel":
            self._set_done_qty(picking)
            try:
                picking._action_done()
            except Exception as exc:
                _logger.warning("No se validó %s: %s", picking.name, exc)
                return
        if self.backdate_pickings:
            self._apply_effective_date(picking, when)

    def _set_done_qty(self, picking):
        for move in picking.move_ids.filtered(lambda m: m.state != "cancel"):
            qty = move.product_uom_qty
            if "quantity" in move._fields:
                move.quantity = qty
            elif "quantity_done" in move._fields:
                move.quantity_done = qty
            for line in move.move_line_ids:
                if "quantity" in line._fields:
                    line.quantity = line.quantity or qty
                elif "qty_done" in line._fields:
                    line.qty_done = line.qty_done or qty

    def _validate_via_wizard(self, picking):
        action = picking.button_validate()
        if not isinstance(action, dict):
            return
        model = action.get("res_model")
        ctx = dict(action.get("context") or {}, skip_backorder=True, cancel_backorder=True)
        if model == "stock.immediate.transfer":
            wiz = self.env[model].with_context(ctx).create(
                {"pick_ids": [(6, 0, picking.ids)]} if "pick_ids" in self.env[model]._fields else {}
            )
            if hasattr(wiz, "process"):
                wiz.process()
        elif model == "stock.backorder.confirmation":
            wiz = self.env[model].with_context(ctx).create({})
            if hasattr(wiz, "process_cancel_backorder"):
                wiz.process_cancel_backorder()
            elif hasattr(wiz, "process"):
                wiz.process()
        elif model == "stock.immediate.transfer" or model:
            try:
                wiz = self.env[model].with_context(ctx).browse(action.get("res_id"))
                if not wiz:
                    wiz = self.env[model].with_context(ctx).create({})
                for method in ("process", "button_validate", "action_confirm"):
                    if hasattr(wiz, method):
                        getattr(wiz, method)()
                        break
            except Exception as exc:
                _logger.warning("Wizard %s no procesado: %s", model, exc)

    def _apply_effective_date(self, picking, when):
        """Odoo 19: desbloquear, fecha efectiva, bloquear."""
        picking = picking.sudo()
        if picking.state != "done":
            return
        if "is_locked" in picking._fields and picking.is_locked and hasattr(picking, "action_toggle_is_locked"):
            picking.action_toggle_is_locked()
        vals = {}
        if "date_done" in picking._fields:
            vals["date_done"] = when
        if "scheduled_date" in picking._fields:
            vals["scheduled_date"] = when
        if vals:
            picking.write(vals)
        move_vals = {"date": when}
        if "date_deadline" in picking.move_ids._fields:
            move_vals["date_deadline"] = when
        picking.move_ids.write(move_vals)
        lines = picking.move_line_ids
        if lines and "date" in lines._fields:
            lines.write({"date": when})
        # asientos de valoración si existen
        accounts = self.env["account.move"]
        if "account_move_id" in picking.move_ids._fields:
            accounts |= picking.move_ids.mapped("account_move_id")
        if "stock_valuation_layer_ids" in picking.move_ids._fields:
            layers = picking.move_ids.mapped("stock_valuation_layer_ids")
            if "account_move_id" in layers._fields:
                accounts |= layers.mapped("account_move_id")
            if "create_date" not in layers._fields:
                pass
        for move in accounts.filtered(lambda m: m.state != "cancel"):
            try:
                if move.state == "posted" and hasattr(move, "button_draft"):
                    move.button_draft()
                move.write({"date": when.date() if hasattr(when, "date") else when})
                if move.state == "draft" and hasattr(move, "action_post"):
                    move.action_post()
            except Exception as exc:
                _logger.warning("No se retrodató asiento %s: %s", move.name, exc)
        if "is_locked" in picking._fields and not picking.is_locked and hasattr(picking, "action_toggle_is_locked"):
            picking.action_toggle_is_locked()
