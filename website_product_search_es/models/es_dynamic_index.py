import json
import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.osv import expression
from odoo.tools.safe_eval import safe_eval


class EsIndexConfig(models.Model):
    _name = "es.index.config"
    _description = "Elasticsearch Dynamic Index Config"
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    # Keep nullable for upgrade safety when legacy rows contain null model_id.
    model_id = fields.Many2one("ir.model", string="Model", required=False, ondelete="cascade")
    model_name = fields.Char(string="Model Technical Name", related="model_id.model", store=True)
    index_name = fields.Char(required=True, default="odoo_products")
    domain = fields.Char(default="[]", help="Example: [('website_published', '=', True)]")
    auto_sync = fields.Boolean(
        default=False,
        help=(
            "When enabled, index updates run automatically on create/write/unlink for this model. "
            "When disabled, index updates run only via 'Index Now' or scheduled cron jobs."
        ),
    )
    use_for_website_search = fields.Boolean(
        string="Use for Website Product Search",
        default=False,
        help="If enabled on product.template config, website search endpoints use this config/index.",
    )
    enable_badges = fields.Boolean(
        string="Enable Badges",
        default=True,
        help="Applicable to product.template configs. Enables dynamic badge computation.",
    )
    badge_bestseller_top_n = fields.Integer(string="Bestseller Top N", default=30)
    badge_bestseller_days = fields.Integer(string="Bestseller Days", default=90)
    badge_trending_top_n = fields.Integer(string="Trending Top N", default=30)
    badge_trending_days = fields.Integer(string="Trending Days", default=30)
    badge_trending_click_weight = fields.Float(string="Trending Click Weight", default=0.6)
    badge_trending_sales_weight = fields.Float(string="Trending Sales Weight", default=0.4)
    badge_new_arrival_days = fields.Integer(string="New Arrival Days", default=30)
    batch_size = fields.Integer(default=200)
    line_ids = fields.One2many("es.index.config.line", "config_id", string="Fields")
    last_indexed_on = fields.Datetime(readonly=True, copy=False)
    last_indexed_count = fields.Integer(readonly=True, copy=False)
    last_error = fields.Text(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._ensure_single_website_search_config()
        return records

    def write(self, vals):
        res = super().write(vals)
        self._ensure_single_website_search_config()
        return res

    def _ensure_single_website_search_config(self):
        for rec in self.filtered(lambda r: r.model_name == "product.template" and r.use_for_website_search):
            others = self.search(
                [
                    ("id", "!=", rec.id),
                    ("model_name", "=", "product.template"),
                    ("use_for_website_search", "=", True),
                ]
            )
            if others:
                others.write({"use_for_website_search": False})

    @api.model
    def create_default_product_search_config(self):
        """Create (or reuse) default product.template config for website search."""
        cfg = self.search(
            [
                ("model_name", "=", "product.template"),
                ("use_for_website_search", "=", True),
            ],
            limit=1,
        )
        if cfg:
            self._ensure_default_product_search_lines(cfg)
            return cfg

        existing = self.search([("model_name", "=", "product.template")], order="active desc, id asc", limit=1)
        if existing:
            existing.write({"use_for_website_search": True})
            self._ensure_default_product_search_lines(existing)
            return existing

        model = self.env["ir.model"].sudo().search([("model", "=", "product.template")], limit=1)
        if not model:
            return self.browse()

        idx = self.env["ir.config_parameter"].sudo().get_param("website_product_search_es.index", "odoo_products")
        cfg = self.create(
            {
                "name": "Default Product Search",
                "model_id": model.id,
                "index_name": idx or "odoo_products",
                "domain": "[('website_published', '=', True)]",
                "active": True,
                "auto_sync": False,
                "use_for_website_search": True,
                "enable_badges": True,
                "badge_bestseller_top_n": 30,
                "badge_bestseller_days": 90,
                "badge_trending_top_n": 30,
                "badge_trending_days": 30,
                "badge_trending_click_weight": 0.6,
                "badge_trending_sales_weight": 0.4,
                "badge_new_arrival_days": 30,
            }
        )
        self._ensure_default_product_search_lines(cfg)
        return cfg

    def _ensure_default_product_search_lines(self, config):
        """Ensure product search config has practical default mappings + boosts."""
        config.ensure_one()
        if config.model_name != "product.template":
            return

        fields_model = self.env["ir.model.fields"].sudo()
        defaults = [
            ("name", "name", True, 5.0),
            ("default_code", "default_code", True, 3.0),
            ("public_categ_ids", "public_categ_names", True, 2.0),
            ("product_brand_id", "brand_name", True, 2.0),
            ("attribute_line_ids", "attribute_values", True, 1.5),
            ("description_sale", "description_sale", True, 1.0),
            ("list_price", "list_price", False, 1.0),
            ("qty_available", "qty_available", False, 1.0),
            ("website_published", "website_published", False, 1.0),
        ]

        for field_name, es_field, is_searchable, search_boost in defaults:
            fld = fields_model.search(
                [("model", "=", "product.template"), ("name", "=", field_name)],
                limit=1,
            )
            if not fld:
                continue
            existing_line = config.line_ids.filtered(lambda l: l.field_id.id == fld.id)[:1]
            values = {
                "es_field_name": es_field,
                "is_searchable": is_searchable,
                "search_boost": search_boost,
            }
            if existing_line:
                existing_line.write(values)
            else:
                config.write({"line_ids": [(0, 0, dict(values, field_id=fld.id))]})

    @api.constrains("model_id", "use_for_website_search")
    def _check_single_website_search_config(self):
        for rec in self:
            if not rec.use_for_website_search or rec.model_name != "product.template":
                continue
            clash_count = self.search_count(
                [
                    ("id", "!=", rec.id),
                    ("model_name", "=", "product.template"),
                    ("use_for_website_search", "=", True),
                ]
            )
            if clash_count:
                raise ValidationError(
                    _("Only one product.template config can be marked 'Use for Website Product Search'.")
                )

    def _es_url_base(self):
        url = self.env["ir.config_parameter"].sudo().get_param(
            "website_product_search_es.url", "http://localhost:9200"
        )
        return (url or "").rstrip("/")

    def _parsed_domain(self):
        self.ensure_one()
        text = (self.domain or "[]").strip()
        try:
            parsed = safe_eval(text, {"uid": self.env.uid, "context": self.env.context})
        except Exception as exc:
            raise UserError(_("Invalid domain: %s") % exc)
        if not isinstance(parsed, (list, tuple)):
            raise UserError(_("Domain must be a list/tuple."))
        return list(parsed)

    def _selected_field_names(self):
        self.ensure_one()
        fields_names = [l.field_id.name for l in self.line_ids if l.field_id]
        if not fields_names:
            raise UserError(_("Please select at least one field to index."))
        return fields_names

    def _value_for_es(self, value):
        if isinstance(value, models.BaseModel):
            if len(value) == 1:
                return value.display_name
            return value.mapped("display_name")
        return value

    def _build_payload(self, rec):
        self.ensure_one()
        if self.model_name == "product.template" and self.use_for_website_search and hasattr(rec, "_es_payload"):
            base_payload = rec._es_payload()
            if not self.line_ids:
                return base_payload

            payload = {"id": rec.id}
            for line in self.line_ids:
                if not line.field_id:
                    continue
                key = (line.es_field_name or line.field_id.name or "").strip()
                if not key:
                    continue
                if key in base_payload:
                    payload[key] = base_payload.get(key)
                else:
                    payload[key] = self._value_for_es(rec[line.field_id.name])

            for key in (
                "website_published",
                "qty_available",
                "list_price",
                "badges",
                "is_bestseller",
                "is_trending",
                "is_new_arrival",
                "public_categ_names",
            ):
                if key not in payload and key in base_payload:
                    payload[key] = base_payload.get(key)
            return payload
        payload = {"id": rec.id}
        for line in self.line_ids:
            if not line.field_id:
                continue
            key = line.es_field_name or line.field_id.name
            payload[key] = self._value_for_es(rec[line.field_id.name])
        return payload

    def action_test_domain(self):
        self.ensure_one()
        model = self.env[self.model_name].sudo()
        count = model.search_count(self._parsed_domain())
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Domain Test"),
                "message": _("Matched records: %s") % count,
                "type": "success",
                "sticky": False,
            },
        }

    def action_preview_payload(self):
        self.ensure_one()
        model = self.env[self.model_name].sudo()
        rec = model.search(self._parsed_domain(), limit=1)
        if not rec:
            raise UserError(_("No record found for selected domain."))
        payload = self._build_payload(rec)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Sample Payload"),
                "message": json.dumps(payload, ensure_ascii=True)[:900],
                "type": "info",
                "sticky": True,
            },
        }

    def action_index_now(self):
        for cfg in self:
            cfg._run_index()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Elasticsearch"),
                "message": _("Indexing completed."),
                "type": "success",
                "sticky": False,
            },
        }

    def _run_index(self):
        self.ensure_one()
        if not self.active:
            return
        if self.model_name == "product.template":
            self.env["product.template"].sudo()._update_auto_badges(config=self)
        model = self.env[self.model_name].sudo()
        domain = self._parsed_domain()
        self._selected_field_names()
        base = self._es_url_base()
        if not base:
            raise UserError(_("Elasticsearch URL is missing in settings."))
        idx = self.index_name.strip()
        if not idx:
            raise UserError(_("Index name is required."))

        count = 0
        offset = 0
        batch = max(1, self.batch_size or 200)
        try:
            while True:
                recs = model.search(domain, offset=offset, limit=batch)
                if not recs:
                    break
                for rec in recs:
                    payload = self._build_payload(rec)
                    url = f"{base}/{idx}/_doc/{rec.id}"
                    resp = requests.put(url, json=payload, timeout=12)
                    status = "success" if resp.ok else "failed"
                    self.env["es.index.log"].sudo().create(
                        {
                            "model": self.model_name,
                            "res_id": rec.id,
                            "payload": json.dumps(payload),
                            "status": status,
                            "response": resp.text[:2000],
                        }
                    )
                    if resp.ok:
                        count += 1
                offset += batch
            self.write(
                {
                    "last_indexed_on": fields.Datetime.now(),
                    "last_indexed_count": count,
                    "last_error": False,
                }
            )
        except Exception as exc:
            self.write({"last_error": str(exc)})
            raise UserError(_("Indexing failed: %s") % exc)

    def _doc_url(self, rec_id):
        self.ensure_one()
        base = self._es_url_base()
        idx = (self.index_name or "").strip()
        return f"{base}/{idx}/_doc/{rec_id}"

    def _matches_config_domain(self, rec):
        self.ensure_one()
        domain = expression.AND([[("id", "=", rec.id)], self._parsed_domain()])
        return bool(rec.sudo().search_count(domain))

    def _sync_records(self, records, force=False):
        """Realtime sync for create/write hooks. Never raises to business flow."""
        for cfg in self:
            if not cfg.active or (not force and not cfg.auto_sync):
                continue
            touched = False
            for rec in records.sudo():
                try:
                    if cfg._matches_config_domain(rec):
                        payload = cfg._build_payload(rec)
                        resp = requests.put(cfg._doc_url(rec.id), json=payload, timeout=10)
                        status = "success" if resp.ok else "failed"
                        cfg.env["es.index.log"].sudo().create(
                            {
                                "model": cfg.model_name,
                                "res_id": rec.id,
                                "payload": json.dumps(payload),
                                "status": status,
                                "response": resp.text[:2000],
                            }
                        )
                        touched = True
                    else:
                        requests.delete(cfg._doc_url(rec.id), timeout=10)
                        touched = True
                except Exception as exc:
                    cfg.env["es.index.log"].sudo().create(
                        {
                            "model": cfg.model_name,
                            "res_id": rec.id,
                            "payload": "",
                            "status": "failed",
                            "response": str(exc)[:2000],
                        }
                    )
            if touched:
                cfg.write({"last_indexed_on": fields.Datetime.now()})

    def _delete_record_ids(self, record_ids, force=False):
        """Realtime cleanup for unlink hooks."""
        for cfg in self:
            if not cfg.active or (not force and not cfg.auto_sync):
                continue
            touched = False
            for rec_id in record_ids:
                try:
                    requests.delete(cfg._doc_url(rec_id), timeout=10)
                    touched = True
                except Exception as exc:
                    cfg.env["es.index.log"].sudo().create(
                        {
                            "model": cfg.model_name,
                            "res_id": rec_id,
                            "payload": "",
                            "status": "failed",
                            "response": str(exc)[:2000],
                        }
                    )
            if touched:
                cfg.write({"last_indexed_on": fields.Datetime.now()})


class EsIndexConfigLine(models.Model):
    _name = "es.index.config.line"
    _description = "Elasticsearch Dynamic Index Field Mapping"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    config_id = fields.Many2one("es.index.config", required=True, ondelete="cascade")
    model_id = fields.Many2one(related="config_id.model_id", store=True)
    field_id = fields.Many2one(
        "ir.model.fields",
        required=True,
        domain="[('model_id', '=', model_id), ('store', '=', True)]",
        ondelete="cascade",
    )
    es_field_name = fields.Char(help="Optional custom key in Elasticsearch document.")
    is_searchable = fields.Boolean(
        string="Searchable",
        default=True,
        help="Flag for query builder to include this field in search matching.",
    )
    search_boost = fields.Float(
        string="Search Boost",
        default=1.0,
        help="Boost used in Elasticsearch query (for example: name^5).",
    )

    _sql_constraints = [
        ("es_index_line_unique_field", "unique(config_id, field_id)", "Field already mapped in this config.")
    ]

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._trigger_auto_reindex_on_mapping_change()
        return records

    def write(self, vals):
        res = super().write(vals)
        self._trigger_auto_reindex_on_mapping_change()
        return res

    def unlink(self):
        configs = self.mapped("config_id")
        res = super().unlink()
        self._trigger_auto_reindex_for_configs(configs)
        return res

    def _trigger_auto_reindex_on_mapping_change(self):
        if self.env.context.get("skip_es_mapping_reindex"):
            return
        configs = self.mapped("config_id")
        self._trigger_auto_reindex_for_configs(configs)

    def _trigger_auto_reindex_for_configs(self, configs):
        if self.env.context.get("skip_es_mapping_reindex"):
            return
        configs = configs.filtered(lambda c: c.active and c.auto_sync)
        for cfg in configs:
            cfg.with_context(skip_es_mapping_reindex=True)._run_index()
