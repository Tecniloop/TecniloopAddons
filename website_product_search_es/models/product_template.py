import json
import requests

from datetime import timedelta

from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    es_is_bestseller = fields.Boolean(string="ES Bestseller", default=False, index=True, copy=False)
    es_is_trending = fields.Boolean(string="ES Trending", default=False, index=True, copy=False)
    es_is_new_arrival = fields.Boolean(string="ES New Arrival", default=False, index=True, copy=False)
    es_badge_updated_on = fields.Datetime(string="ES Badge Updated On", copy=False)
    es_badges_enabled = fields.Boolean(string="ES Badges Enabled", compute="_compute_es_badges_enabled")

    @api.model
    def _website_product_search_config(self):
        return (
            self.env["es.index.config"]
            .sudo()
            .search(
                [
                    ("active", "=", True),
                    ("model_name", "=", "product.template"),
                    ("use_for_website_search", "=", True),
                ],
                limit=1,
            )
        )

    def _es_badges_list(self):
        self.ensure_one()
        if not self._es_badges_enabled():
            return []
        badges = []
        if self.es_is_bestseller:
            badges.append("Bestseller")
        if self.es_is_trending:
            badges.append("Trending")
        if self.es_is_new_arrival:
            badges.append("New Arrival")
        return badges

    @api.model
    def _es_badges_enabled(self):
        cfg = self._website_product_search_config()
        if cfg:
            return bool(cfg.enable_badges)
        return True

    def _compute_es_badges_enabled(self):
        enabled = self._es_badges_enabled()
        for rec in self:
            rec.es_badges_enabled = enabled

    def _es_payload(self):
        self.ensure_one()
        qty_available = 0.0
        if "qty_available" in self._fields:
            qty_available = self.qty_available
        elif "free_qty" in self._fields:
            qty_available = self.free_qty
        elif "product_variant_ids" in self._fields and self.product_variant_ids:
            variants = self.product_variant_ids
            if "qty_available" in variants._fields:
                qty_available = sum(variants.mapped("qty_available"))
            elif "free_qty" in variants._fields:
                qty_available = sum(variants.mapped("free_qty"))

        attribute_values = []
        for line in self.attribute_line_ids:
            attribute_values.extend(line.value_ids.mapped("name"))
        category_names = self.public_categ_ids.mapped("name")
        brand_name = ""
        if "product_brand_id" in self._fields and self.product_brand_id:
            brand_name = self.product_brand_id.name
        return {
            "id": self.id,
            "name": self.name,
            "default_code": self.default_code or "",
            "description_sale": self.description_sale or "",
            "list_price": self.list_price,
            "qty_available": qty_available,
            "website_published": self.website_published,
            "public_categ_ids": [c.id for c in self.public_categ_ids],
            "public_categ_names": category_names,
            "attribute_values": attribute_values,
            "brand_name": brand_name,
            "badges": self._es_badges_list(),
            "is_bestseller": bool(self.es_is_bestseller),
            "is_trending": bool(self.es_is_trending),
            "is_new_arrival": bool(self.es_is_new_arrival),
        }

    def _es_config(self):
        config = self.env["ir.config_parameter"].sudo()
        return {
            "enabled": config.get_param("website_product_search_es.enabled", default="False") == "True",
            "url": config.get_param("website_product_search_es.url", default="http://localhost:9200"),
            "index": config.get_param("website_product_search_es.index", default="odoo_products"),
        }

    @api.model
    def _website_dynamic_search_config(self):
        return (
            self.env["es.index.config"]
            .sudo()
            .search(
                [
                    ("active", "=", True),
                    ("model_name", "=", "product.template"),
                    ("use_for_website_search", "=", True),
                ],
                limit=1,
            )
        )

    def _es_index_one(self):
        cfg = self._es_config()
        if not cfg["enabled"]:
            return
        dynamic_cfg = (
            self.env["es.index.config"]
            .sudo()
            .search(
                [
                    ("active", "=", True),
                    ("model_name", "=", "product.template"),
                    ("use_for_website_search", "=", True),
                ],
                limit=1,
            )
        )
        if dynamic_cfg:
            dynamic_cfg._sync_records(self, force=True)
            return
        url = f"{cfg['url'].rstrip('/')}/{cfg['index']}/_doc/{self.id}"
        payload = self._es_payload()
        try:
            response = requests.put(url, json=payload, timeout=10)
            status = "success" if response.ok else "failed"
        except Exception as exc:
            status = "failed"
            response = type("obj", (object,), {"text": str(exc)})()
        self.env["es.index.log"].sudo().create(
            {
                "model": "product.template",
                "res_id": self.id,
                "payload": json.dumps(payload),
                "status": status,
                "response": response.text,
            }
        )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        dynamic_cfg = records._website_dynamic_search_config()
        if dynamic_cfg:
            return records
        for rec in records:
            rec._es_index_one()
        return records

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get("skip_es_index"):
            return res
        dynamic_cfg = self._website_dynamic_search_config()
        if dynamic_cfg:
            return res
        for rec in self:
            rec._es_index_one()
        return res

    def unlink(self):
        dynamic_cfg = self._website_dynamic_search_config()
        if dynamic_cfg:
            return super().unlink()
        cfg = self._es_config()
        if cfg["enabled"]:
            dynamic_cfg = (
                self.env["es.index.config"]
                .sudo()
                .search(
                    [
                        ("active", "=", True),
                        ("model_name", "=", "product.template"),
                        ("use_for_website_search", "=", True),
                    ],
                    limit=1,
                )
            )
            if dynamic_cfg:
                dynamic_cfg._delete_record_ids(self.ids, force=True)
                return super().unlink()
            for rec in self:
                url = f"{cfg['url'].rstrip('/')}/{cfg['index']}/_doc/{rec.id}"
                try:
                    requests.delete(url, timeout=10)
                except Exception:
                    pass
        return super().unlink()

    @api.model
    def _get_bestseller_ids(self, limit=30, days=90):
        SaleReport = self.env["sale.report"].sudo()
        qty_field = next((f for f in ("product_uom_qty", "qty_delivered", "product_qty") if f in SaleReport._fields), None)
        if not qty_field:
            return []
        domain = []
        if "state" in SaleReport._fields:
            domain.append(("state", "in", ["sale", "done"]))
        if "date" in SaleReport._fields:
            domain.append(("date", ">=", fields.Datetime.to_string(fields.Datetime.now() - timedelta(days=days))))
        groups = SaleReport.read_group(
            domain,
            ["product_tmpl_id", f"{qty_field}:sum"],
            ["product_tmpl_id"],
            limit=max(limit * 3, 60),
            orderby="product_tmpl_id asc",
        )
        sum_key = f"{qty_field}_sum"
        groups = [g for g in groups if g.get("product_tmpl_id")]
        groups.sort(key=lambda g: g.get(sum_key, 0.0), reverse=True)
        return [g["product_tmpl_id"][0] for g in groups[:limit]]

    @api.model
    def _normalize_trending_weights(self, click_weight=0.6, sales_weight=0.4):
        try:
            cw = float(click_weight)
        except Exception:
            cw = 0.6
        try:
            sw = float(sales_weight)
        except Exception:
            sw = 0.4
        cw = max(0.0, cw)
        sw = max(0.0, sw)
        total = cw + sw
        if total <= 0.0:
            return 0.6, 0.4
        return cw / total, sw / total

    @api.model
    def _get_trending_ids(self, limit=30, days=30):
        return self._get_trending_ids_hybrid(limit=limit, days=days, click_weight=0.6, sales_weight=0.4)

    @api.model
    def _get_trending_ids_hybrid(self, limit=30, days=30, click_weight=0.6, sales_weight=0.4):
        Click = self.env["es.search.click"].sudo()
        SaleReport = self.env["sale.report"].sudo()
        from_date = fields.Datetime.to_string(fields.Datetime.now() - timedelta(days=days))
        cw, sw = self._normalize_trending_weights(click_weight, sales_weight)

        click_groups = Click.read_group(
            [("create_date", ">=", from_date)],
            ["product_tmpl_id", "id:count"],
            ["product_tmpl_id"],
            limit=max(limit * 6, 120),
            orderby="product_tmpl_id asc",
        )
        click_scores = {
            g["product_tmpl_id"][0]: float(g.get("product_tmpl_id_count", 0))
            for g in click_groups
            if g.get("product_tmpl_id")
        }

        qty_field = next((f for f in ("product_uom_qty", "qty_delivered", "product_qty") if f in SaleReport._fields), None)
        sales_scores = {}
        if qty_field:
            sales_domain = []
            if "state" in SaleReport._fields:
                sales_domain.append(("state", "in", ["sale", "done"]))
            if "date" in SaleReport._fields:
                sales_domain.append(("date", ">=", from_date))
            sales_groups = SaleReport.read_group(
                sales_domain,
                ["product_tmpl_id", f"{qty_field}:sum"],
                ["product_tmpl_id"],
                limit=max(limit * 6, 120),
                orderby="product_tmpl_id asc",
            )
            sum_key = f"{qty_field}_sum"
            sales_scores = {
                g["product_tmpl_id"][0]: float(g.get(sum_key, 0.0))
                for g in sales_groups
                if g.get("product_tmpl_id")
            }

        candidate_ids = set(click_scores.keys()) | set(sales_scores.keys())
        if not candidate_ids:
            return []

        max_click = max(click_scores.values()) if click_scores else 0.0
        max_sales = max(sales_scores.values()) if sales_scores else 0.0
        scored = []
        for pid in candidate_ids:
            c_norm = (click_scores.get(pid, 0.0) / max_click) if max_click > 0 else 0.0
            s_norm = (sales_scores.get(pid, 0.0) / max_sales) if max_sales > 0 else 0.0
            scored.append(((cw * c_norm) + (sw * s_norm), pid))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [pid for _, pid in scored[:limit]]

    @api.model
    def _get_new_arrival_ids(self, days=30, limit=100):
        recs = self.search(
            [
                ("website_published", "=", True),
                ("create_date", ">=", fields.Datetime.to_string(fields.Datetime.now() - timedelta(days=days))),
            ],
            limit=limit,
            order="create_date desc",
        )
        return recs.ids

    @api.model
    def _update_auto_badges(self, config=None):
        cfg = config or self._website_product_search_config()
        enabled = bool(cfg.enable_badges) if cfg else True
        if not enabled:
            return self.browse()
        products = self.search([("website_published", "=", True)])
        if not products:
            return self.browse()

        bestseller_top_n = max(1, int((cfg.badge_bestseller_top_n if cfg else 30) or 30))
        bestseller_days = max(1, int((cfg.badge_bestseller_days if cfg else 90) or 90))
        trending_top_n = max(1, int((cfg.badge_trending_top_n if cfg else 30) or 30))
        trending_days = max(1, int((cfg.badge_trending_days if cfg else 30) or 30))
        trending_click_weight = float((cfg.badge_trending_click_weight if cfg else 0.6) or 0.6)
        trending_sales_weight = float((cfg.badge_trending_sales_weight if cfg else 0.4) or 0.4)
        new_days = max(1, int((cfg.badge_new_arrival_days if cfg else 30) or 30))

        bestseller_ids = set(self._get_bestseller_ids(limit=bestseller_top_n, days=bestseller_days))
        trending_ids = set(
            self._get_trending_ids_hybrid(
                limit=trending_top_n,
                days=trending_days,
                click_weight=trending_click_weight,
                sales_weight=trending_sales_weight,
            )
        )
        new_ids = set(self._get_new_arrival_ids(days=new_days, limit=max(100, bestseller_top_n + trending_top_n)))

        changed = self.browse()
        now = fields.Datetime.now()
        for p in products:
            vals = {
                "es_is_bestseller": p.id in bestseller_ids,
                "es_is_trending": p.id in trending_ids,
                "es_is_new_arrival": p.id in new_ids,
            }
            if (
                p.es_is_bestseller != vals["es_is_bestseller"]
                or p.es_is_trending != vals["es_is_trending"]
                or p.es_is_new_arrival != vals["es_is_new_arrival"]
            ):
                vals["es_badge_updated_on"] = now
                p.with_context(skip_es_index=True).write(vals)
                changed |= p
        return changed

    @api.model
    def cron_reindex_products(self):
        cfg = self._es_config()
        if not cfg["enabled"]:
            return
        self._update_auto_badges()
        products = self.search([("website_published", "=", True)])
        for rec in products:
            rec._es_index_one()
