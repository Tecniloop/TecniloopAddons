import requests

from odoo import _, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    es_search_url = fields.Char(
        string="Elasticsearch URL",
        config_parameter="website_product_search_es.url",
        default="http://localhost:9200",
    )
    es_search_index = fields.Char(
        string="Elasticsearch Index",
        config_parameter="website_product_search_es.index",
        default="odoo_products",
    )
    es_search_enabled = fields.Boolean(
        string="Enable Elasticsearch Search",
        config_parameter="website_product_search_es.enabled",
        default=False,
    )
    es_hide_out_of_stock = fields.Boolean(
        string="Hide Out of Stock",
        config_parameter="website_product_search_es.hide_out_of_stock",
        default=False,
    )
    es_enable_autocomplete = fields.Boolean(
        string="Enable Autocomplete",
        config_parameter="website_product_search_es.autocomplete",
        default=True,
    )
    es_enable_trending = fields.Boolean(
        string="Enable Trending Searches",
        config_parameter="website_product_search_es.trending",
        default=True,
    )

    def get_values(self):
        res = super().get_values()
        params = self.env["ir.config_parameter"].sudo()
        res.update(
            es_search_enabled=str(params.get_param("website_product_search_es.enabled", "False")).lower() in ("1", "true", "yes", "on"),
            es_hide_out_of_stock=str(params.get_param("website_product_search_es.hide_out_of_stock", "False")).lower() in ("1", "true", "yes", "on"),
            es_enable_autocomplete=str(params.get_param("website_product_search_es.autocomplete", "True")).lower() in ("1", "true", "yes", "on"),
            es_enable_trending=str(params.get_param("website_product_search_es.trending", "True")).lower() in ("1", "true", "yes", "on"),
        )
        return res

    def set_values(self):
        super().set_values()
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("website_product_search_es.enabled", "True" if self.es_search_enabled else "False")
        params.set_param("website_product_search_es.hide_out_of_stock", "True" if self.es_hide_out_of_stock else "False")
        params.set_param("website_product_search_es.autocomplete", "True" if self.es_enable_autocomplete else "False")
        params.set_param("website_product_search_es.trending", "True" if self.es_enable_trending else "False")

    def action_test_es_connection(self):
        self.ensure_one()

        base_url = (self.es_search_url or "").strip().rstrip("/")
        index = (self.es_search_index or "").strip()
        if not base_url or not index:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Elasticsearch"),
                    "message": _("Please set both Elasticsearch URL and Index before testing."),
                    "type": "warning",
                    "sticky": False,
                },
            }

        try:
            root_resp = requests.get(base_url, timeout=5)
            root_resp.raise_for_status()
            root_json = root_resp.json() if root_resp.text else {}
            cluster_name = root_json.get("cluster_name", "N/A")

            count_url = f"{base_url}/{index}/_count"
            count_resp = requests.get(count_url, timeout=5)
            count_resp.raise_for_status()
            count_json = count_resp.json() if count_resp.text else {}
            doc_count = count_json.get("count", 0)

            msg = _("Connected to Elasticsearch (cluster: %s). Index '%s' is reachable. Documents: %s.") % (
                cluster_name,
                index,
                doc_count,
            )
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Connection Successful"),
                    "message": msg,
                    "type": "success",
                    "sticky": False,
                },
            }
        except Exception as exc:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Connection Failed"),
                    "message": _("Could not connect to Elasticsearch: %s") % (str(exc),),
                    "type": "danger",
                    "sticky": True,
                },
            }
