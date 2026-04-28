from odoo import fields, models


class EsSearchClick(models.Model):
    _name = "es.search.click"
    _description = "Elasticsearch Suggestion Click Log"
    _order = "create_date desc"

    query = fields.Char(required=True)
    query_norm = fields.Char(index=True, required=True)
    product_tmpl_id = fields.Many2one("product.template", required=True, ondelete="cascade", index=True)
    source = fields.Selection(
        [
            ("suggestion", "Suggestion"),
            ("trending_product", "Trending Product"),
        ],
        default="suggestion",
        required=True,
    )
    website_id = fields.Many2one("website", index=True)
