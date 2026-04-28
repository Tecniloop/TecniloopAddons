import re
import requests

from odoo import http
from odoo.http import request


class EsSearchController(http.Controller):
    def _param_bool(self, config, key, default=False):
        raw = config.get_param(key)
        if raw is None:
            return default
        return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')

    def _currency_info(self):
        website = request.website
        if hasattr(website, "_get_current_pricelist"):
            pricelist = website._get_current_pricelist()
        elif hasattr(website, "get_current_pricelist"):
            pricelist = website.get_current_pricelist()
        else:
            pricelist = False
        currency = pricelist.currency_id if pricelist and pricelist.currency_id else request.website.currency_id
        return {
            'symbol': currency.symbol or '',
            'position': currency.position or 'before',
        }

    def _badges_enabled(self):
        cfg = self._product_search_config()
        if cfg:
            return bool(cfg.enable_badges)
        return True

    def _product_search_config(self):
        return request.env["es.index.config"].sudo().search(
            [
                ("active", "=", True),
                ("model_name", "=", "product.template"),
                ("use_for_website_search", "=", True),
            ],
            limit=1,
        )

    def _product_search_fields(self):
        cfg = self._product_search_config()
        default_fields = [
            "name^5",
            "default_code^3",
            "public_categ_names^2",
            "brand_name^2",
            "attribute_values^1.5",
            "description_sale",
        ]
        if not cfg:
            return default_fields
        search_lines = cfg.line_ids.filtered(lambda l: l.is_searchable)
        if not search_lines:
            return default_fields
        fields = []
        for line in search_lines:
            key = (line.es_field_name or (line.field_id.name if line.field_id else "")).strip()
            if key:
                boost = line.search_boost or 1.0
                if abs(boost - 1.0) < 0.0001:
                    fields.append(key)
                else:
                    fields.append(f"{key}^{boost:g}")
        return fields or default_fields

    def _price_label(self, amount):
        if amount is None:
            return ''
        try:
            value = float(amount)
        except Exception:
            return ''
        info = self._currency_info()
        txt = f"{value:.2f}"
        return f"{info['symbol']}{txt}" if info['position'] == 'before' else f"{txt}{info['symbol']}"

    def _clean_trending_terms(self, groups, limit=5):
        cleaned = []
        seen = set()
        for row in groups:
            term = (row.get('query') or '').strip()
            if len(term) < 3:
                continue
            if re.fullmatch(r'[\d\W_]+', term):
                continue
            if not re.search(r'[a-zA-Z]', term):
                continue
            key = term.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(term)
            if len(cleaned) >= limit:
                break
        return cleaned

    def _normalize_query(self, query):
        return (query or "").strip().lower()

    def _get_trending_terms(self, limit=5):
        groups = request.env['es.search.click'].sudo().read_group(
            [('query_norm', '!=', False)],
            ['query_norm', 'id:count'],
            ['query_norm'],
            limit=50,
            orderby='query_norm asc'
        )
        groups = sorted(groups, key=lambda t: t.get('query_norm_count', 0), reverse=True)
        shaped = [{'query': row.get('query_norm')} for row in groups]
        return self._clean_trending_terms(shaped, limit=limit)

    def _apply_click_ranking(self, query, results):
        if not results:
            return results
        query_norm = self._normalize_query(query)
        if not query_norm:
            return results
        product_ids = [r.get('id') for r in results if r.get('id')]
        if not product_ids:
            return results
        groups = request.env['es.search.click'].sudo().read_group(
            [('query_norm', '=', query_norm), ('product_tmpl_id', 'in', product_ids)],
            ['product_tmpl_id', 'id:count'],
            ['product_tmpl_id'],
            limit=len(product_ids),
            orderby='product_tmpl_id asc'
        )
        click_count_by_product = {
            row['product_tmpl_id'][0]: row.get('product_tmpl_id_count', 0)
            for row in groups
            if row.get('product_tmpl_id')
        }
        indexed = list(enumerate(results))
        indexed.sort(key=lambda t: (-click_count_by_product.get(t[1].get('id'), 0), t[0]))
        return [row for _, row in indexed]

    def _get_trending_products(self, limit=5):
        Product = request.env['product.template'].sudo()
        cfg = self._product_search_config()
        badges_enabled = bool(cfg.enable_badges) if cfg else True

        if badges_enabled:
            products = Product.search(
                [('website_published', '=', True), ('es_is_trending', '=', True)],
                limit=limit,
                order='es_badge_updated_on desc, write_date desc',
            )
            if products:
                return [
                    {
                        'id': p.id,
                        'name': p.name,
                        'url': '/shop/product/%s' % p.id,
                        'price': p.list_price,
                        'price_label': self._price_label(p.list_price),
                        'detail': self._price_label(p.list_price),
                        'category': (p.public_categ_ids[:1].name if p.public_categ_ids else ''),
                        'image_url': '/web/image/product.template/%s/image_128' % p.id,
                        'badges': (p._es_badges_list() if self._badges_enabled() else []),
                    }
                    for p in products
                ]

        trending_days = max(1, int((cfg.badge_trending_days if cfg else 30) or 30))
        click_weight = float((cfg.badge_trending_click_weight if cfg else 0.6) or 0.6)
        sales_weight = float((cfg.badge_trending_sales_weight if cfg else 0.4) or 0.4)

        product_ids = Product._get_trending_ids_hybrid(
            limit=max(limit * 2, 10),
            days=trending_days,
            click_weight=click_weight,
            sales_weight=sales_weight,
        )
        products = Product.browse()
        if product_ids:
            ranked = Product.search([('id', 'in', product_ids), ('website_published', '=', True)])
            by_id = {p.id: p for p in ranked}
            products = Product.browse([pid for pid in product_ids if pid in by_id])[:limit]

        if not products:
            fallback_domain = [('website_published', '=', True)]
            products = Product.search(fallback_domain, limit=limit, order='write_date desc')

        return [
            {
                'id': p.id,
                'name': p.name,
                'url': '/shop/product/%s' % p.id,
                'price': p.list_price,
                'price_label': self._price_label(p.list_price),
                'detail': self._price_label(p.list_price),
                'category': (p.public_categ_ids[:1].name if p.public_categ_ids else ''),
                'image_url': '/web/image/product.template/%s/image_128' % p.id,
                'badges': (p._es_badges_list() if self._badges_enabled() else []),
            }
            for p in products
        ]

    @http.route('/es/search_suggest', type='http', auth='public', website=True)
    def search_suggest(self, q=None, **kwargs):
        config = request.env['ir.config_parameter'].sudo()
        if not self._param_bool(config, 'website_product_search_es.enabled', default=False):
            return request.make_json_response({'results': []})
        autocomplete_enabled = self._param_bool(config, 'website_product_search_es.autocomplete', default=True)
        trending_enabled = self._param_bool(config, 'website_product_search_es.trending', default=True)
        if not autocomplete_enabled:
            return request.make_json_response({
                'results': [],
                'trending': [],
                'trending_products': [],
                'autocomplete_enabled': False,
                'trending_enabled': trending_enabled,
            })

        query = (q or '').strip()

        if not query:
            trending_terms = self._get_trending_terms(limit=5) if trending_enabled else []
            return request.make_json_response({
                'results': [],
                'trending': trending_terms,
                'trending_products': self._get_trending_products(limit=6) if trending_enabled else [],
                'autocomplete_enabled': True,
                'trending_enabled': trending_enabled,
            })

        es_url = config.get_param('website_product_search_es.url', default='http://localhost:9200')
        search_cfg = self._product_search_config()
        index = (search_cfg.index_name if search_cfg else config.get_param('website_product_search_es.index', default='odoo_products'))
        hide_oos = self._param_bool(config, 'website_product_search_es.hide_out_of_stock', default=False)
        search_fields = self._product_search_fields()

        must_filters = [
            {"term": {"website_published": True}},
        ]
        if hide_oos:
            must_filters.append({"range": {"qty_available": {"gt": 0}}})

        payload = {
            "query": {
                "bool": {
                    "should": [
                        {
                            "match_phrase_prefix": {
                                "name": {
                                    "query": query,
                                    "boost": 8
                                }
                            }
                        },
                        {
                            "multi_match": {
                                "query": query,
                                "fields": search_fields,
                                "type": "phrase_prefix",
                                "boost": 4
                            }
                        },
                        {
                            "multi_match": {
                                "query": query,
                                "fields": search_fields,
                                "type": "best_fields",
                                "operator": "and",
                                "fuzziness": "AUTO:4,7",
                                "prefix_length": 1
                            }
                        }
                    ],
                    "minimum_should_match": 1,
                    "filter": must_filters,
                }
            },
            "size": 7
        }

        url = f"{es_url.rstrip('/')}/{index}/_search"
        try:
            resp = requests.get(url, json=payload, timeout=5)
            data = resp.json()
            hits = data.get('hits', {}).get('hits', [])
            results = []
            for h in hits:
                src = h.get('_source', {})
                prod_id = src.get('id')
                results.append({
                    'id': prod_id,
                    'name': src.get('name'),
                    'url': '/shop/product/%s' % prod_id,
                    'price': src.get('list_price'),
                    'price_label': self._price_label(src.get('list_price')),
                    'detail': self._price_label(src.get('list_price')),
                    'category': (src.get('public_categ_names') or [''])[0] if isinstance(src.get('public_categ_names'), list) else '',
                    'image_url': '/web/image/product.template/%s/image_128' % prod_id if prod_id else '',
                    'badges': (src.get('badges') or []) if self._badges_enabled() else [],
                })
            results = self._apply_click_ranking(query, results)

            if len(query) >= 3:
                request.env['es.search.log'].sudo().create({
                    'query': query,
                    'results_count': len(results),
                })

            trending_terms = []
            trending_products = []
            if trending_enabled and len(query) < 2:
                trending_terms = self._get_trending_terms(limit=5)
                trending_products = self._get_trending_products(limit=5)
            return request.make_json_response({
                'results': results,
                'trending': trending_terms,
                'trending_products': trending_products,
                'autocomplete_enabled': True,
                'trending_enabled': trending_enabled,
            })
        except Exception:
            with request.env.cr.savepoint():
                products = request.env['product.template'].sudo().search(
                    [('website_published', '=', True), ('name', 'ilike', query)], limit=7
                )
                results = [
                    {
                        'id': p.id,
                        'name': p.name,
                        'url': '/shop/product/%s' % p.id,
                        'price': p.list_price,
                        'price_label': self._price_label(p.list_price),
                        'detail': self._price_label(p.list_price),
                        'category': (p.public_categ_ids[:1].name if p.public_categ_ids else ''),
                        'image_url': '/web/image/product.template/%s/image_128' % p.id,
                        'badges': (p._es_badges_list() if self._badges_enabled() else []),
                    }
                    for p in products
                ]
                trending_products = self._get_trending_products(limit=5) if (trending_enabled and len(query) < 2) else []
                return request.make_json_response({
                    'results': results,
                    'trending': [],
                    'trending_products': trending_products,
                    'autocomplete_enabled': True,
                    'trending_enabled': trending_enabled,
                })

    @http.route('/es/search_click', type='json', auth='public', website=True, csrf=False)
    def search_click(self, query=None, product_id=None, source='suggestion', **kwargs):
        config = request.env['ir.config_parameter'].sudo()
        if not self._param_bool(config, 'website_product_search_es.enabled', default=False):
            return {'ok': False, 'reason': 'disabled'}
        query_text = (query or '').strip()
        query_norm = self._normalize_query(query_text)
        try:
            pid = int(product_id)
        except Exception:
            return {'ok': False, 'reason': 'invalid_product'}
        if not query_norm or not pid:
            return {'ok': False, 'reason': 'missing_data'}
        if source not in ('suggestion', 'trending_product'):
            source = 'suggestion'

        product = request.env['product.template'].sudo().search([('id', '=', pid), ('website_published', '=', True)], limit=1)
        if not product:
            return {'ok': False, 'reason': 'product_not_found'}

        request.env['es.search.click'].sudo().create({
            'query': query_text,
            'query_norm': query_norm,
            'product_tmpl_id': product.id,
            'source': source,
            'website_id': request.website.id if request.website else False,
        })
        return {'ok': True}

    @http.route('/es/search', type='http', auth='public', website=True)
    def search(self, q=None, category_id=None, brand=None, min_price=None, max_price=None, attrs=None, **kwargs):
        config = request.env['ir.config_parameter'].sudo()
        if not self._param_bool(config, 'website_product_search_es.enabled', default=False):
            return request.make_json_response({'results': [], 'facets': {}})

        es_url = config.get_param('website_product_search_es.url', default='http://localhost:9200')
        search_cfg = self._product_search_config()
        index = (search_cfg.index_name if search_cfg else config.get_param('website_product_search_es.index', default='odoo_products'))
        hide_oos = self._param_bool(config, 'website_product_search_es.hide_out_of_stock', default=False)
        search_fields = self._product_search_fields()

        must_filters = [{"term": {"website_published": True}}]
        if hide_oos:
            must_filters.append({"range": {"qty_available": {"gt": 0}}})
        if category_id:
            try:
                must_filters.append({"term": {"public_categ_ids": int(category_id)}})
            except ValueError:
                pass
        if brand:
            must_filters.append({"term": {"brand_name.keyword": brand}})
        price_range = {}
        if min_price:
            try:
                price_range["gte"] = float(min_price)
            except ValueError:
                pass
        if max_price:
            try:
                price_range["lte"] = float(max_price)
            except ValueError:
                pass
        if price_range:
            must_filters.append({"range": {"list_price": price_range}})

        if attrs:
            attr_values = [a.strip() for a in attrs.split(",") if a.strip()]
            if attr_values:
                must_filters.append({"terms": {"attribute_values": attr_values}})

        query_text = (q or "").strip()
        bool_query = {
            "filter": must_filters,
        }
        if query_text:
            bool_query["must"] = [
                {
                    "multi_match": {
                        "query": query_text,
                        "fields": search_fields,
                        "fuzziness": "AUTO"
                    }
                }
            ]
        else:
            bool_query["must"] = [{"match_all": {}}]

        payload = {
            "query": {
                "bool": bool_query
            },
            "size": 24,
            "aggs": {
                "categories": {"terms": {"field": "public_categ_names.keyword", "size": 10}},
                "brands": {"terms": {"field": "brand_name.keyword", "size": 10}},
                "attributes": {"terms": {"field": "attribute_values.keyword", "size": 10}},
                "price_ranges": {
                    "range": {
                        "field": "list_price",
                        "ranges": [
                            {"to": 50},
                            {"from": 50, "to": 100},
                            {"from": 100, "to": 250},
                            {"from": 250}
                        ]
                    }
                }
            }
        }

        url = f"{es_url.rstrip('/')}/{index}/_search"
        try:
            resp = requests.get(url, json=payload, timeout=8)
            data = resp.json()
            hits = data.get('hits', {}).get('hits', [])
            results = []
            for h in hits:
                src = h.get('_source', {})
                results.append({
                    'name': src.get('name'),
                    'url': '/shop/product/%s' % src.get('id'),
                    'price': src.get('list_price'),
                    'price_label': self._price_label(src.get('list_price')),
                    'badges': (src.get('badges') or []) if self._badges_enabled() else [],
                })
            aggs = data.get('aggregations', {})
            facets = {
                "categories": aggs.get("categories", {}).get("buckets", []),
                "brands": aggs.get("brands", {}).get("buckets", []),
                "attributes": aggs.get("attributes", {}).get("buckets", []),
                "price_ranges": aggs.get("price_ranges", {}).get("buckets", []),
            }
            return request.make_json_response({'results': results, 'facets': facets})
        except Exception:
            domain = [('website_published', '=', True)]
            if query_text:
                domain.append(('name', 'ilike', query_text))
            if category_id:
                try:
                    domain.append(('public_categ_ids', 'in', [int(category_id)]))
                except ValueError:
                    pass
            if min_price:
                try:
                    domain.append(('list_price', '>=', float(min_price)))
                except ValueError:
                    pass
            if max_price:
                try:
                    domain.append(('list_price', '<=', float(max_price)))
                except ValueError:
                    pass
            products = request.env['product.template'].sudo().search(domain, limit=24)
            results = [
                {
                    'name': p.name,
                    'url': '/shop/product/%s' % p.id,
                    'price': p.list_price,
                    'price_label': self._price_label(p.list_price),
                    'badges': (p._es_badges_list() if self._badges_enabled() else []),
                }
                for p in products
            ]
            return request.make_json_response({'results': results, 'facets': {}})
