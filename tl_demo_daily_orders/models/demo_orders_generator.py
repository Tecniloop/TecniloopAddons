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
        schedule_only = opts.get("schedule_only", False)
        count = int(opts.get("count") or 3)
        lines_min = int(opts.get("lines_min") or 1)
        lines_max = int(opts.get("lines_max") or 4)

        customers = self._customers(company.id)
        vendors = self._vendors(company.id) or customers
        products = self._products(company.id)
        if not customers or not products:
            raise UserError("Faltan clientes o productos para el job del %s." % day_str)

        when = self._dt_on(day)
        user_ids = opts.get("user_ids") or [2, 5]
        do_confirmed = opts.get("generate_confirmed", True)
        do_quotes = opts.get("generate_sale_quotes", False)
        do_rfqs = opts.get("generate_purchase_rfqs", False)
        po_ids, so_ids, quote_ids, rfq_ids = [], [], [], []
        sales_per_purchase = max(1, int(opts.get("sales_per_purchase") or 2))
        purchase_price_ratio = float(opts.get("purchase_price_ratio") or 0.65)
        sale_count = count * sales_per_purchase
        if do_confirmed:
            demand, sale_plans = self._plan_sales_demand(products, sale_count, lines_min, lines_max)
            for chunk in self._chunk_demand(demand, max(1, count)):
                po = self._create_purchase_planned(
                    random.choice(vendors),
                    chunk,
                    when,
                    confirm,
                    backdate,
                    user_ids,
                    schedule_only,
                    purchase_price_ratio,
                    opts.get("purchase_journal_id"),
                )
                po_ids.append(po.id)
            for lines in sale_plans:
                so = self._create_sale_planned(
                    random.choice(customers),
                    lines,
                    when,
                    warehouse,
                    confirm,
                    backdate,
                    user_ids,
                    schedule_only,
                    opts.get("sale_journal_id"),
                )
                so_ids.append(so.id)
        if do_quotes:
            for _ in range(count):
                quote_ids.append(
                    self._create_sale_quote(
                        random.choice(customers), products, when, warehouse, lines_min, lines_max, user_ids
                    ).id
                )
        if do_rfqs:
            for _ in range(count):
                rfq_ids.append(
                    self._create_purchase_rfq(
                        random.choice(vendors), products, when, lines_min, lines_max, user_ids
                    ).id
                )
        _logger.info(
            "Demo %s: %s compras, %s ventas, %s presupuestos, %s RFQ",
            day_str,
            len(po_ids),
            len(so_ids),
            len(quote_ids),
            len(rfq_ids),
        )
        return {
            "day": day_str,
            "purchase_ids": po_ids,
            "sale_ids": so_ids,
            "quote_ids": quote_ids,
            "rfq_ids": rfq_ids,
        }

    def _generate_leads_day(self, day_str, opts):
        day = fields.Date.from_string(day_str)
        company = self.env["res.company"].browse(opts["company_id"])
        self = self.with_company(company)
        when = self._dt_on(day)
        count = int(opts.get("count") or 3)
        user_ids = opts.get("user_ids") or []
        tag_ids = list(opts.get("tag_ids") or [])
        country_ids = list(opts.get("country_ids") or [])
        stage_ids = list(opts.get("stage_ids") or [])
        tags_min = max(0, int(opts.get("tags_min") or 0))
        tags_max = max(tags_min, int(opts.get("tags_max") or tags_min))
        partners = self._customers(company.id)
        names = (
            "Reforma caldera",
            "Consulta ánodos",
            "Presupuesto termos",
            "Cambio resistencias",
            "Mantenimiento industrial",
            "Petición web Araolit",
            "Llamada ferretería",
            "Lead feria",
            "WhatsApp recambios",
            "Email catálogo",
        )
        created = self.env["crm.lead"]
        for _ in range(count):
            partner = random.choice(partners) if partners else False
            chosen_tags = []
            if tag_ids:
                n = min(len(tag_ids), random.randint(tags_min, max(tags_min, tags_max)))
                chosen_tags = random.sample(tag_ids, n) if n else []
            vals = {
                "name": "%s — %s" % (random.choice(names), day),
                "type": "lead",
                "company_id": company.id,
                "user_id": self._pick_user(user_ids),
                "date_open": when,
                "create_date": when,
            }
            if partner:
                vals["partner_id"] = partner.id
                vals["email_from"] = partner.email
                vals["phone"] = partner.phone
            if chosen_tags:
                vals["tag_ids"] = [(6, 0, chosen_tags)]
            if country_ids:
                vals["country_id"] = random.choice(country_ids)
            if stage_ids:
                vals["stage_id"] = random.choice(stage_ids)
            rev_min = float(opts.get("expected_revenue_min") or 0)
            rev_max = float(opts.get("expected_revenue_max") or rev_min)
            if rev_max < rev_min:
                rev_max = rev_min
            if rev_max > 0:
                vals["expected_revenue"] = round(random.uniform(rev_min, rev_max), 2)
            pmin = float(opts.get("probability_min") or 0)
            pmax = float(opts.get("probability_max") or pmin)
            pmin = max(0.0, min(100.0, pmin))
            pmax = max(pmin, min(100.0, pmax))
            probability = round(random.uniform(pmin, pmax), 2)
            lead = self.env["crm.lead"].create(vals)
            self.env.cr.execute(
                "UPDATE crm_lead SET create_date = %s, date_open = %s, probability = %s, expected_revenue = %s WHERE id = %s",
                (when, when, probability, vals.get("expected_revenue") or 0.0, lead.id),
            )
            created |= lead
        _logger.info("Leads demo %s: %s", day_str, len(created))
        return {"day": day_str, "lead_ids": created.ids}

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
        for col in (
            "date_order",
            "date_approve",
            "confirmation_date",
            "date_planned",
            "commitment_date",
            "expected_date",
        ) + tuple(extra_columns):
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
            "confirmation_date",
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

    def _plan_sales_demand(self, products, sale_count, lines_min, lines_max):
        demand = {}
        sale_plans = []
        pool = list(products)
        if not pool:
            return demand, sale_plans
        for _ in range(sale_count):
            lines = []
            used = set()
            for _n in range(self._line_count(lines_min, lines_max)):
                product = random.choice(pool)
                if product.id in used and len(pool) > 1:
                    continue
                used.add(product.id)
                qty = random.randint(3, 8)
                lines.append((product, qty))
                demand[product] = demand.get(product, 0) + qty
            if lines:
                sale_plans.append(lines)
        return demand, sale_plans

    def _chunk_demand(self, demand, po_count):
        items = [(p, qty + max(1, int(qty * 0.15))) for p, qty in demand.items()]
        if not items:
            return []
        chunks = [[] for _ in range(po_count)]
        for i, item in enumerate(items):
            chunks[i % po_count].append(item)
        return [c for c in chunks if c]

    def _create_purchase_planned(
        self,
        vendor,
        items,
        when,
        confirm,
        backdate,
        user_ids,
        schedule_only,
        purchase_price_ratio,
        journal_id,
    ):
        lines = []
        for product, qty in items:
            sale_price = product.list_price or product.standard_price or 1.0
            line_vals = {
                "product_id": product.id,
                "name": product.display_name,
                "product_qty": qty,
                "price_unit": max(sale_price * (purchase_price_ratio or 0.65), 0.5),
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
                "user_id": self._pick_user(user_ids),
                "origin": "DEMO-%s" % when.date(),
                "order_line": lines,
            }
        )
        self._set_order_journal(po, journal_id)
        po.button_confirm()
        self._force_document_date(po, when)
        if confirm:
            for picking in po.picking_ids.filtered(lambda p: p.state != "cancel"):
                self._validate_and_backdate(picking, when, backdate)
        elif schedule_only or not confirm:
            self._schedule_picking_dates(po.picking_ids, when)
        self._assign_picking_users(po.picking_ids, user_ids)
        self._force_document_date(po, when)
        return po

    def _create_sale_planned(
        self,
        customer,
        items,
        when,
        warehouse,
        confirm,
        backdate,
        user_ids,
        schedule_only,
        journal_id,
    ):
        lines = []
        for product, qty in items:
            line_vals = {
                "product_id": product.id,
                "name": product.display_name,
                "product_uom_qty": qty,
                "price_unit": product.list_price or product.standard_price or 1.0,
            }
            if "purchase_price" in self.env["sale.order.line"]._fields:
                line_vals["purchase_price"] = max((product.list_price or 1.0) * 0.65, 0.5)
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
            "user_id": self._pick_user(user_ids),
            "origin": "DEMO-%s" % when.date(),
            "order_line": lines,
        }
        if warehouse:
            vals["warehouse_id"] = warehouse.id
        if "commitment_date" in self.env["sale.order"]._fields:
            vals["commitment_date"] = when
        so = self.env["sale.order"].create(vals)
        self._set_order_journal(so, journal_id)
        so.action_confirm()
        self._force_document_date(so, when)
        if confirm:
            for picking in so.picking_ids.filtered(lambda p: p.state != "cancel"):
                self._validate_and_backdate(picking, when, backdate)
        elif schedule_only or not confirm:
            self._schedule_picking_dates(so.picking_ids, when)
        self._assign_picking_users(so.picking_ids, user_ids)
        self._force_document_date(so, when)
        return so

    def _set_order_journal(self, order, journal_id):
        if not journal_id:
            return
        for fname in ("journal_id", "invoice_journal_id"):
            if fname in order._fields:
                order.with_context(tracking_disable=True).write({fname: journal_id})
                return

    def _pick_user(self, user_ids):
        ids = [int(x) for x in (user_ids or [2, 5]) if x]
        return random.choice(ids) if ids else self.env.uid

    def _schedule_picking_dates(self, pickings, when):
        """Albaranes pendientes con fecha prevista = fecha del pedido."""
        for picking in pickings.filtered(lambda p: p.state != "cancel"):
            if picking.state == "draft":
                picking.action_confirm()
            try:
                picking.action_assign()
            except Exception:
                pass
            vals = {}
            if "scheduled_date" in picking._fields:
                vals["scheduled_date"] = when
            if vals:
                picking.write(vals)
            move_vals = {}
            if "date" in picking.move_ids._fields:
                move_vals["date"] = when
            if "date_deadline" in picking.move_ids._fields:
                move_vals["date_deadline"] = when
            if move_vals and picking.move_ids:
                picking.move_ids.write(move_vals)

    def _assign_picking_users(self, pickings, user_ids):
        for picking in pickings.filtered(lambda p: p.state != "cancel"):
            uid = self._pick_user(user_ids)
            vals = {}
            if "user_id" in picking._fields:
                vals["user_id"] = uid
            if vals:
                picking.with_context(tracking_disable=True).write(vals)

    def _create_sale_quote(self, customer, products, when, warehouse, lines_min, lines_max, user_ids=None):
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
                "product_uom_qty": random.randint(3, 8),
                "price_unit": product.list_price or product.standard_price or 1.0,
            }
            if "purchase_price" in self.env["sale.order.line"]._fields:
                line_vals["purchase_price"] = max((product.list_price or 1.0) * 0.65, 0.5)
            fname, uom = self._uom_field("sale.order.line", product)
            if fname:
                line_vals[fname] = uom
            lines.append((0, 0, line_vals))
        vals = {
            "partner_id": customer.id,
            "company_id": self.env.company.id,
            "date_order": when,
            "user_id": self._pick_user(user_ids),
            "origin": "DEMO-%s" % when.date(),
            "order_line": lines,
            "state": "sent" if random.random() < 0.5 else "draft",
        }
        if warehouse:
            vals["warehouse_id"] = warehouse.id
        so = self.env["sale.order"].create(vals)
        if so.state not in ("draft", "sent"):
            so.write({"state": vals["state"]})
        self._force_document_date(so, when)
        return so

    def _create_purchase_rfq(self, vendor, products, when, lines_min, lines_max, user_ids=None):
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
                "product_qty": random.randint(2, 12),
                "price_unit": product.standard_price or max(product.list_price * 0.7, 0.5),
                "date_planned": when,
            }
            fname, uom = self._uom_field("purchase.order.line", product)
            if fname:
                line_vals[fname] = uom
            lines.append((0, 0, line_vals))
        state = "sent" if random.random() < 0.5 else "draft"
        po = self.env["purchase.order"].create(
            {
                "partner_id": vendor.id,
                "company_id": vendor.company_id.id or self.env.company.id,
                "date_order": when,
                "user_id": self._pick_user(user_ids),
                "origin": "DEMO-%s" % when.date(),
                "order_line": lines,
                "state": state,
            }
        )
        if po.state not in ("draft", "sent"):
            po.write({"state": state})
        self._force_document_date(po, when)
        return po

    def _create_purchase(
        self,
        vendor,
        products,
        when,
        confirm,
        backdate,
        lines_min,
        lines_max,
        user_ids=None,
        schedule_only=False,
        purchase_price_ratio=0.65,
        journal_id=False,
    ):
        lines = []
        used = set()
        fname, uom = None, None
        for _ in range(self._line_count(lines_min, lines_max)):
            product = random.choice(products)
            if product.id in used and len(products) > 1:
                continue
            used.add(product.id)
            sale_price = product.list_price or product.standard_price or 1.0
            line_vals = {
                "product_id": product.id,
                "name": product.display_name,
                "product_qty": random.randint(1, 3),
                "price_unit": max(sale_price * (purchase_price_ratio or 0.65), 0.5),
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
                "user_id": self._pick_user(user_ids),
                "origin": "DEMO-%s" % when.date(),
                "order_line": lines,
            }
        )
        self._set_order_journal(po, journal_id)
        po.button_confirm()
        self._force_document_date(po, when)
        if confirm:
            for picking in po.picking_ids.filtered(lambda p: p.state != "cancel"):
                self._validate_and_backdate(picking, when, backdate)
        elif schedule_only or not confirm:
            self._schedule_picking_dates(po.picking_ids, when)
        self._assign_picking_users(po.picking_ids, user_ids)
        self._force_document_date(po, when)
        return po

    def _create_sale(
        self,
        customer,
        products,
        when,
        warehouse,
        confirm,
        backdate,
        lines_min,
        lines_max,
        user_ids=None,
        schedule_only=False,
        journal_id=False,
    ):
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
                "product_uom_qty": random.randint(3, 8),
                "price_unit": product.list_price or product.standard_price or 1.0,
            }
            if "purchase_price" in self.env["sale.order.line"]._fields:
                line_vals["purchase_price"] = max((product.list_price or 1.0) * 0.65, 0.5)
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
            "user_id": self._pick_user(user_ids),
            "origin": "DEMO-%s" % when.date(),
            "order_line": lines,
        }
        if warehouse:
            vals["warehouse_id"] = warehouse.id
        if "commitment_date" in self.env["sale.order"]._fields:
            vals["commitment_date"] = when
        so = self.env["sale.order"].create(vals)
        self._set_order_journal(so, journal_id)
        so.action_confirm()
        self._force_document_date(so, when)
        if confirm:
            for picking in so.picking_ids.filtered(lambda p: p.state != "cancel"):
                self._validate_and_backdate(picking, when, backdate)
        elif schedule_only or not confirm:
            self._schedule_picking_dates(so.picking_ids, when)
        self._assign_picking_users(so.picking_ids, user_ids)
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
        self._sql_align_move_to_planned(picking, when)

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

    def _sql_align_move_to_planned(self, picking, when):
        """On-time rate: stock.move.date::date <= purchase.order.line.date_planned::date."""
        if not picking:
            return
        self.env.cr.execute(
            """
            UPDATE stock_move sm
            SET date = COALESCE(pol.date_planned, %s)
            FROM purchase_order_line pol
            WHERE sm.picking_id = %s
              AND sm.purchase_line_id = pol.id
            """,
            (when, picking.id),
        )
        self.env.cr.execute(
            """
            UPDATE stock_move sm
            SET date = %s
            WHERE sm.picking_id = %s
              AND sm.purchase_line_id IS NULL
            """,
            (when, picking.id),
        )
        self.env.cr.execute(
            """
            UPDATE stock_move_line sml
            SET date = sm.date
            FROM stock_move sm
            WHERE sml.move_id = sm.id
              AND sm.picking_id = %s
            """,
            (picking.id,),
        )
        picking.invalidate_recordset()
        if picking.move_ids:
            picking.move_ids.invalidate_recordset()

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
        sale_journal_id = opts.get("sale_journal_id") or False
        purchase_journal_id = opts.get("purchase_journal_id") or False
        if opts.get("invoice_sales", True):
            for so in sales:
                sale_moves |= self._invoice_sale(so, day, sale_journal_id)
        if opts.get("invoice_purchases", True):
            for po in purchases:
                purchase_moves |= self._invoice_purchase(po, day, purchase_journal_id)
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

    def _invoice_sale(self, order, day, journal_id=False):
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
            self._finalize_invoice(move, day, vendor_ref=False, journal_id=journal_id)
        return moves

    def _invoice_purchase(self, order, day, journal_id=False):
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
            self._finalize_invoice(move, day, vendor_ref=ref, journal_id=journal_id)
        return moves

    def _finalize_invoice(self, move, day, vendor_ref=False, journal_id=False):
        vals = {}
        if journal_id and "journal_id" in move._fields and move.state == "draft":
            vals["journal_id"] = journal_id
        if "invoice_date" in move._fields:
            vals["invoice_date"] = day
        if "invoice_date_due" in move._fields:
            vals["invoice_date_due"] = day
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
            extra_columns=("invoice_date", "date", "invoice_date_due"),
        )
        self.env.cr.execute(
            "UPDATE account_move SET invoice_date = %s, invoice_date_due = %s, date = %s "
            "WHERE id = %s",
            (day, day, day, move.id),
        )
        self.env.cr.execute(
            "UPDATE account_move_line SET date_maturity = %s, date = %s "
            "WHERE move_id = %s",
            (day, day, move.id),
        )
        if vendor_ref:
            self.env.cr.execute(
                "UPDATE account_move SET ref = %s WHERE id = %s",
                (vendor_ref, move.id),
            )
        move.invalidate_recordset()
        if move.line_ids:
            move.line_ids.invalidate_recordset()

    def _pay_day(self, day_str, opts):
        day = fields.Date.from_string(day_str)
        company = self.env["res.company"].browse(opts["company_id"])
        self = self.with_company(company)
        journal = self.env["account.journal"].browse(opts["journal_id"])
        origin = "DEMO-%s" % day
        paid = self.env["account.payment"]
        if opts.get("pay_customer", True):
            invoices = self._demo_open_moves(origin, company.id, ("out_invoice", "out_refund"))
            paid |= self._register_payments(invoices, journal, day, "inbound")
        if opts.get("pay_vendor", True):
            bills = self._demo_open_moves(origin, company.id, ("in_invoice", "in_refund"))
            paid |= self._register_payments(bills, journal, day, "outbound")
        _logger.info("Pagos demo %s: %s", day_str, len(paid))
        return {"day": day_str, "payment_ids": paid.ids}

    def _demo_open_moves(self, origin, company_id, types):
        Move = self.env["account.move"]
        domain = [
            ("company_id", "=", company_id),
            ("state", "=", "posted"),
            ("move_type", "in", list(types)),
            ("payment_state", "in", ("not_paid", "partial", "in_payment")),
        ]
        moves = Move.search(domain + [("invoice_origin", "=", origin)])
        so = self.env["sale.order"].search([("origin", "=", origin), ("company_id", "=", company_id)])
        if so:
            moves |= so.invoice_ids.filtered(
                lambda m: m.state == "posted" and m.payment_state in ("not_paid", "partial", "in_payment")
            )
        po = self.env["purchase.order"].search([("origin", "=", origin), ("company_id", "=", company_id)])
        if po:
            moves |= po.invoice_ids.filtered(
                lambda m: m.state == "posted" and m.payment_state in ("not_paid", "partial", "in_payment")
            )
        return moves.filtered(lambda m: m.move_type in types and abs(m.amount_residual) > 0.009)

    def _register_payments(self, moves, journal, day, payment_type):
        payments = self.env["account.payment"]
        if not moves:
            return payments
        Register = self.env["account.payment.register"]
        for move in moves:
            try:
                ctx = {
                    "active_model": "account.move",
                    "active_ids": move.ids,
                    "dont_redirect_to_payments": True,
                }
                vals = {
                    "journal_id": journal.id,
                    "payment_date": day,
                }
                if "amount" in Register._fields:
                    vals["amount"] = abs(move.amount_residual)
                wizard = Register.with_context(**ctx).create(vals)
                action = wizard.action_create_payments()
                new_pays = self.env["account.payment"]
                if isinstance(action, dict) and action.get("res_id"):
                    new_pays = self.env["account.payment"].browse(action["res_id"])
                elif isinstance(action, dict) and action.get("domain"):
                    new_pays = self.env["account.payment"].search(action["domain"])
                else:
                    new_pays = move._get_reconciled_payments() if hasattr(move, "_get_reconciled_payments") else self.env["account.payment"]
                for pay in new_pays:
                    self._backdate_payment(pay, day)
                payments |= new_pays
            except Exception as exc:
                _logger.warning("Pago demo %s: %s", move.name, exc)
        return payments

    def _backdate_payment(self, payment, day):
        if "date" in payment._fields:
            try:
                payment.with_context(tracking_disable=True, skip_account_move_synchronization=True).write({"date": day})
            except Exception:
                pass
        self.env.cr.execute("UPDATE account_payment SET date = %s WHERE id = %s", (day, payment.id))
        if payment.move_id:
            self.env.cr.execute(
                "UPDATE account_move SET date = %s WHERE id = %s",
                (day, payment.move_id.id),
            )
            self.env.cr.execute(
                "UPDATE account_move_line SET date = %s, date_maturity = %s WHERE move_id = %s",
                (day, day, payment.move_id.id),
            )
            payment.move_id.invalidate_recordset()
        payment.invalidate_recordset()
