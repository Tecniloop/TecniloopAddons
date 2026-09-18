# -*- coding: utf-8 -*-
import logging
import random
from datetime import datetime, time, timedelta

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class TlDemoOrdersGenerator(models.AbstractModel):
    _name = "tl.demo.orders.generator"
    _description = "Motor de pedidos demo (un job por día)"

    def _generate_day(self, day_str, opts):
        """Ejecutado por queue_job: un día = N compras + N ventas."""
        day = fields.Date.from_string(day_str)
        company = self.env["res.company"].browse(opts["company_id"])
        self = self.with_company(company)
        warehouse = self.env["stock.warehouse"].browse(opts.get("warehouse_id") or 0)
        confirm = opts.get("confirm_pickings", True)
        backdate = opts.get("backdate_pickings", True)
        count = int(opts.get("count") or 3)
        lines_min = int(opts.get("lines_min") or 1)
        lines_max = int(opts.get("lines_max") or 4)

        customers = self._customers(company.id)
        vendors = self._vendors(company.id) or customers
        products = self._products(company.id)
        if not customers or not products:
            raise UserError("Faltan clientes o productos para el job del %s." % day_str)

        when = self._dt_on(day)
        po_ids, so_ids = [], []
        for _ in range(count):
            po = self._create_purchase(random.choice(vendors), products, when, confirm, backdate, lines_min, lines_max)
            po_ids.append(po.id)
        for _ in range(count):
            so = self._create_sale(
                random.choice(customers), products, when, warehouse, confirm, backdate, lines_min, lines_max
            )
            so_ids.append(so.id)
        _logger.info("Demo %s: %s compras, %s ventas", day_str, len(po_ids), len(so_ids))
        return {"day": day_str, "purchase_ids": po_ids, "sale_ids": so_ids}

    def _customers(self, company_id):
        return self.env["res.partner"].search(
            [
                ("customer_rank", ">", 0),
                ("active", "=", True),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", company_id),
            ]
        )

    def _vendors(self, company_id):
        return self.env["res.partner"].search(
            [
                ("supplier_rank", ">", 0),
                ("active", "=", True),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", company_id),
            ]
        )

    def _products(self, company_id):
        products = self.env["product.product"].search(
            [
                ("sale_ok", "=", True),
                ("purchase_ok", "=", True),
                ("active", "=", True),
                ("type", "in", ("product", "consu")),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", company_id),
            ],
            limit=400,
        )
        priced = products.filtered(lambda p: p.list_price > 0 or p.standard_price > 0)
        return priced or products

    def _dt_on(self, day):
        naive = datetime.combine(day, time(random.randint(8, 17), random.choice((0, 15, 30, 45))))
        return fields.Datetime.to_datetime(naive)

    def _line_count(self, lines_min, lines_max):
        lo = max(1, lines_min)
        hi = max(lo, lines_max)
        return random.randint(lo, hi)

    def _uom_field(self, model_name, product):
        Line = self.env[model_name]
        uom_id = product.uom_id.id
        if "product_uom_id" in Line._fields:
            return "product_uom_id", uom_id
        if "product_uom" in Line._fields:
            return "product_uom", uom_id
        return None, None

    def _sql_set_dates(self, table, ids, when, extra_columns=()):
        if not ids:
            return
        cr = self.env.cr
        cr.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s",
            (table,),
        )
        existing = {row[0] for row in cr.fetchall()}
        assigns = []
        params = []
        for col in ("date_order", "date_approve", "date_planned", "commitment_date", "expected_date") + tuple(extra_columns):
            if col in existing:
                assigns.append("%s = %%s" % col)
                params.append(when)
        if "create_date" in existing:
            assigns.append("create_date = %s")
            params.append(when)
        if "write_date" in existing:
            assigns.append("write_date = %s")
            params.append(when)
        if not assigns:
            return
        params.append(tuple(ids))
        cr.execute(
            "UPDATE %s SET %s WHERE id IN %%s" % (table, ", ".join(assigns)),
            params,
        )

    def _force_document_date(self, record, when):
        """Tras confirmar, Odoo 19 deja date_order en 'ahora' y a veces readonly.
        Se fuerza por ORM y por SQL en cabecera y líneas.
        """
        vals = {}
        for fname in (
            "date_order",
            "date_approve",
            "effective_date",
            "commitment_date",
            "expected_date",
            "date_planned",
        ):
            field = record._fields.get(fname)
            if not field:
                continue
            if field.compute and not field.store:
                continue
            vals[fname] = when
        ctx = dict(tracking_disable=True, mail_notrack=True, skip_readonly_check=True)
        if vals:
            try:
                record.with_context(**ctx).sudo().write(vals)
            except Exception:
                pass
        lines = record.order_line if "order_line" in record._fields else record.browse()
        line_vals = {}
        if "customer_lead" in lines._fields:
            line_vals["customer_lead"] = 0
        if "date_planned" in lines._fields:
            line_vals["date_planned"] = when
        if "date_order" in lines._fields:
            line_vals["date_order"] = when
        if line_vals and lines:
            try:
                lines.with_context(**ctx).sudo().write(line_vals)
            except Exception:
                pass
        table = record._table
        self._sql_set_dates(table, record.ids, when)
        if lines:
            self._sql_set_dates(lines._table, lines.ids, when)
        record.invalidate_recordset()
        if lines:
            lines.invalidate_recordset()

    def _create_purchase(self, vendor, products, when, confirm, backdate, lines_min, lines_max):
        lines = []
        used = set()
        fname, uom = None, None
        for _ in range(self._line_count(lines_min, lines_max)):
            product = random.choice(products)
            if product.id in used and len(products) > 1:
                continue
            used.add(product.id)
            line_vals = {
                "product_id": product.id,
                "name": product.display_name,
                "product_qty": random.randint(2, 12),
                "price_unit": product.standard_price or max(product.list_price * 0.7, 0.5),
                "date_planned": when,
            }
            fname, uom = self._uom_field("purchase.order.line", product)
            if fname:
                line_vals[fname] = uom
            lines.append((0, 0, line_vals))
        po = self.env["purchase.order"].create(
            {
                "partner_id": vendor.id,
                "company_id": vendor.company_id.id or self.env.company.id,
                "date_order": when,
                "origin": "DEMO-%s" % when.date(),
                "order_line": lines,
            }
        )
        po.button_confirm()
        self._force_document_date(po, when)
        if confirm:
            for picking in po.picking_ids.filtered(lambda p: p.state != "cancel"):
                self._validate_and_backdate(picking, when, backdate)
        self._force_document_date(po, when)
        return po

    def _create_sale(self, customer, products, when, warehouse, confirm, backdate, lines_min, lines_max):
        lines = []
        used = set()
        for _ in range(self._line_count(lines_min, lines_max)):
            product = random.choice(products)
            if product.id in used and len(products) > 1:
                continue
            used.add(product.id)
            line_vals = {
                "product_id": product.id,
                "name": product.display_name,
                "product_uom_qty": random.randint(1, 5),
                "price_unit": product.list_price or product.standard_price or 1.0,
            }
            if "customer_lead" in self.env["sale.order.line"]._fields:
                line_vals["customer_lead"] = 0
            fname, uom = self._uom_field("sale.order.line", product)
            if fname:
                line_vals[fname] = uom
            lines.append((0, 0, line_vals))
        vals = {
            "partner_id": customer.id,
            "company_id": self.env.company.id,
            "date_order": when,
            "origin": "DEMO-%s" % when.date(),
            "order_line": lines,
        }
        if warehouse:
            vals["warehouse_id"] = warehouse.id
        if "commitment_date" in self.env["sale.order"]._fields:
            vals["commitment_date"] = when
        so = self.env["sale.order"].create(vals)
        so.action_confirm()
        self._force_document_date(so, when)
        if confirm:
            for picking in so.picking_ids.filtered(lambda p: p.state != "cancel"):
                self._validate_and_backdate(picking, when, backdate)
        self._force_document_date(so, when)
        return so

    def _validate_and_backdate(self, picking, when, backdate):
        picking = picking.with_context(
            mail_notrack=True,
            tracking_disable=True,
            skip_sms=True,
            skip_immediate=True,
            skip_backorder=True,
            cancel_backorder=True,
        )
        if "scheduled_date" in picking._fields:
            picking.scheduled_date = when
        if picking.move_ids and "date_deadline" in picking.move_ids._fields:
            picking.move_ids.write({"date": when, "date_deadline": when})
        if picking.state == "draft":
            picking.action_confirm()
        if picking.state in ("confirmed", "waiting", "assigned", "partially_available"):
            try:
                picking.action_assign()
            except Exception as exc:
                _logger.warning("Reserva %s: %s", picking.name, exc)
            self._set_done_qty(picking)
            try:
                picking.button_validate()
            except Exception as exc:
                _logger.warning("Validate %s: %s", picking.name, exc)
                try:
                    picking._action_done()
                except Exception as exc2:
                    _logger.warning("Done %s: %s", picking.name, exc2)
                    return
        if backdate:
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

    def _apply_effective_date(self, picking, when):
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
        if picking.move_line_ids and "date" in picking.move_line_ids._fields:
            picking.move_line_ids.write({"date": when})
        if "is_locked" in picking._fields and not picking.is_locked and hasattr(picking, "action_toggle_is_locked"):
            picking.action_toggle_is_locked()

    def _invoice_day(self, day_str, opts):
        """Factura ventas y compras DEMO de un día, con fecha de factura = ese día."""
        day = fields.Date.from_string(day_str)
        company = self.env["res.company"].browse(opts["company_id"])
        self = self.with_company(company)
        origin = "DEMO-%s" % day
        sales = self.env["sale.order"].search(
            [
                ("origin", "=", origin),
                ("company_id", "=", company.id),
                ("state", "in", ("sale", "done")),
                ("invoice_status", "in", ("to invoice", "no")),
            ]
        )
        # incluir parcialmente facturados
        sales |= self.env["sale.order"].search(
            [
                ("origin", "=", origin),
                ("company_id", "=", company.id),
                ("state", "in", ("sale", "done")),
                ("invoice_status", "=", "to invoice"),
            ]
        )
        purchases = self.env["purchase.order"].search(
            [
                ("origin", "=", origin),
                ("company_id", "=", company.id),
                ("state", "in", ("purchase", "done")),
                ("invoice_status", "in", ("to invoice", "no")),
            ]
        )
        purchases |= self.env["purchase.order"].search(
            [
                ("origin", "=", origin),
                ("company_id", "=", company.id),
                ("invoice_status", "=", "to invoice"),
            ]
        )
        sale_moves, purchase_moves = self.env["account.move"], self.env["account.move"]
        if opts.get("invoice_sales", True):
            for so in sales:
                sale_moves |= self._invoice_sale(so, day)
        if opts.get("invoice_purchases", True):
            for po in purchases:
                purchase_moves |= self._invoice_purchase(po, day)
        _logger.info(
            "Facturas demo %s: %s ventas, %s compras",
            day_str,
            len(sale_moves),
            len(purchase_moves),
        )
        return {
            "day": day_str,
            "sale_move_ids": sale_moves.ids,
            "purchase_move_ids": purchase_moves.ids,
        }

    def _random_vendor_ref(self, day):
        year = day.year if hasattr(day, "year") else fields.Date.from_string(str(day)).year
        styles = (
            "F-%s/%05d" % (year, random.randint(1, 99999)),
            "FRA-%s-%04d" % (year, random.randint(100, 9999)),
            "A-%s" % random.randint(100000, 999999),
            "%s/%02d/%04d" % (year, random.randint(1, 12), random.randint(1, 9999)),
            "ALB-%s" % random.randint(10000, 99999),
        )
        return random.choice(styles)

    def _invoice_sale(self, order, day):
        if order.invoice_status not in ("to invoice",):
            # intentar igual si hay qty por facturar
            if all(line.qty_to_invoice <= 0 for line in order.order_line if line.product_id):
                return self.env["account.move"]
        moves = self.env["account.move"]
        try:
            created = order._create_invoices()
            moves = created if created else self.env["account.move"]
        except Exception as exc:
            _logger.warning("No se facturó venta %s: %s", order.name, exc)
            return self.env["account.move"]
        for move in moves:
            self._finalize_invoice(move, day, vendor_ref=False)
        return moves

    def _invoice_purchase(self, order, day):
        if hasattr(order, "invoice_status") and order.invoice_status not in ("to invoice",):
            if all(
                (getattr(line, "qty_to_invoice", 0) or 0) <= 0
                for line in order.order_line
                if line.product_id
            ):
                return self.env["account.move"]
        moves = self.env["account.move"]
        try:
            action = order.with_context(create_bill=True).action_create_invoice()
            if isinstance(action, dict) and action.get("res_id"):
                moves = self.env["account.move"].browse(action["res_id"])
            elif isinstance(action, dict) and action.get("res_ids"):
                moves = self.env["account.move"].browse(action["res_ids"])
            else:
                moves = order.invoice_ids.filtered(lambda m: m.state == "draft")
        except Exception as exc:
            _logger.warning("No se facturó compra %s: %s", order.name, exc)
            return self.env["account.move"]
        ref = self._random_vendor_ref(day)
        for move in moves:
            self._finalize_invoice(move, day, vendor_ref=ref)
        return moves

    def _finalize_invoice(self, move, day, vendor_ref=False):
        vals = {}
        if "invoice_date" in move._fields:
            vals["invoice_date"] = day
        if "date" in move._fields:
            vals["date"] = day
        if vendor_ref:
            if "ref" in move._fields:
                vals["ref"] = vendor_ref
            if "payment_reference" in move._fields:
                vals["payment_reference"] = vendor_ref
        if vals:
            move.with_context(tracking_disable=True, check_move_validity=False).write(vals)
        if move.state == "draft":
            try:
                move.action_post()
            except Exception as exc:
                _logger.warning("No se publicó %s: %s", move.name, exc)
        # Forzar fecha contable / factura por si action_post la pisa
        when_dt = datetime.combine(day, time(12, 0))
        self._sql_set_dates(
            move._table,
            move.ids,
            fields.Datetime.to_datetime(when_dt),
            extra_columns=("invoice_date", "date"),
        )
        if vendor_ref:
            self.env.cr.execute(
                "UPDATE account_move SET ref = %s WHERE id = %s",
                (vendor_ref, move.id),
            )
        move.invalidate_recordset()
