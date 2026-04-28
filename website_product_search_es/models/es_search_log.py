from odoo import fields, models


class EsSearchLog(models.Model):
    _name = "es.search.log"
    _description = "Elasticsearch Search Log"
    _order = "create_date desc"

    query = fields.Char(required=True)
    results_count = fields.Integer(default=0)
