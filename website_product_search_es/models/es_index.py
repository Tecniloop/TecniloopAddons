import json
import requests

from odoo import api, fields, models


class EsIndexLog(models.Model):
    _name = "es.index.log"
    _description = "Elasticsearch Index Log"
    _order = "create_date desc"

    model = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    payload = fields.Text()
    status = fields.Selection(
        [("success", "Success"), ("failed", "Failed")], default="success"
    )
    response = fields.Text()


class EsSearchMixin(models.AbstractModel):
    _name = "es.search.mixin"
    _description = "Elasticsearch Helper"

    def _es_config(self):
        config = self.env["ir.config_parameter"].sudo()
        return {
            "enabled": config.get_param("website_product_search_es.enabled", default="False") == "True",
            "url": config.get_param("website_product_search_es.url", default="http://localhost:9200"),
            "index": config.get_param("website_product_search_es.index", default="odoo_products"),
            "hide_oos": config.get_param("website_product_search_es.hide_out_of_stock", default="False") == "True",
        }

    def _es_index_url(self):
        cfg = self._es_config()
        return f"{cfg['url'].rstrip('/')}/{cfg['index']}"

    def _es_request(self, method, path, payload=None):
        cfg = self._es_config()
        url = f"{cfg['url'].rstrip('/')}/{cfg['index']}{path}"
        headers = {"Content-Type": "application/json"}
        data = json.dumps(payload) if payload is not None else None
        return requests.request(method, url, headers=headers, data=data, timeout=10)

    def _es_log(self, model, res_id, payload, status, response_text):
        self.env["es.index.log"].sudo().create(
            {
                "model": model,
                "res_id": res_id,
                "payload": json.dumps(payload) if payload else "",
                "status": status,
                "response": response_text,
            }
        )
