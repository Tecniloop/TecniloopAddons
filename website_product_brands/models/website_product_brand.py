# -*- coding: utf-8 -*-
#################################################################################
#
#	Copyright (c) 2017-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#   See LICENSE URL <https://store.webkul.com/license.html/> for full copyright and licensing details.
#################################################################################

import logging

from odoo import api, fields , models
from odoo.http import request

_logger = logging.getLogger(__name__)

class website(models.Model):
	_inherit = 'website'

	def get_wk_brands(self,brand_set):
		return self.env['wk.product.brand'].sudo().browse(list(set(brand_set)))

	def _get_brand_domain(self):
		brand_set = set()

		# 1) Parámetro 'attrib_brand' del request: soporta "", "42" y "12-42"
		vals = []
		try:
			vals = request.httprequest.args.getlist('attrib_brand')
		except Exception:
			vals = []

		# 2) Parámetro 'brand' (por compatibilidad con tu lógica previa)
		try:
			brand_param = request.httprequest.args.getlist('brand')
		except Exception:
			brand_param = []

		for v in vals:
			s = (str(v).strip()) if v is not None else ""
			if not s:
				# "Todas" => cadena vacía: no filtrar
				continue

			# intento directo (select simple "42")
			added = False
			try:
				val_int = int(s)
				# si hay brand en la URL y no coincide, se incluye (lógica previa)
				if brand_param and str(brand_param[0]) != str(val_int):
					brand_set.add(val_int)
				else:
					# si no hay brand en URL o coincide, igual lo contamos
					brand_set.add(val_int)
				added = True
			except ValueError:
				pass

			if not added and "-" in s:
				# Formato "12-42" -> tomamos la última parte no vacía (robusto)
				part = ""
				for piece in s.split("-")[::-1]:
					if piece.strip():
						part = piece.strip()
						break
				if part:
					try:
						val_int = int(part)
						if brand_param and str(brand_param[0]) != str(val_int):
							brand_set.add(val_int)
						else:
							brand_set.add(val_int)
					except ValueError:
						pass

		# 3) Preselección vía /shop/brand/<wk_brand>
		if request and getattr(request, "session", None):
			wk_brand = request.session.get('wk_brand')
			try:
				if wk_brand:
					brand_set.add(int(wk_brand))
			except (TypeError, ValueError):
				pass

		# 4) Sin selección → sin filtro
		if not brand_set:
			return []

		return [('product_brand_id.id', 'in', list(brand_set))]


	def sale_product_domain(self):
		return super().sale_product_domain()+self._get_brand_domain()
	

class product_template(models.Model):
	_inherit = 'product.template'

	product_brand_id = fields.Many2one(
		string='Brand',
		comodel_name="wk.product.brand"
	)

class Wk_ProductBrand(models.Model):
	_name = "wk.product.brand"
	_inherit = ['website.published.mixin']
	_description = "Website Product Brand"
	_order = "sequence asc"

	@api.depends('products')
	def _get_product_count(self):
		for rec in self:
			rec.total_products = len(rec.products.ids)

	name = fields.Char(
		string="Brand Name",required=True,
		translate=True
	)
	image = fields.Binary(
		string='product  image',
		help = " This Image will be visible to user in there shop  by brand onwebsite view !"
	)
	description = fields.Text(
		string ="Brand Description",
		translate=True
	)
	sequence = fields.Integer(
		string = "Sequence" ,
		help = "Gives the sequence order when displaying a list of brand onwebsite view.!"
	)
	products = fields.One2many(
		'product.template',
		'product_brand_id',
	)
	total_products = fields.Integer(
		string="Total no. of Products",
		compute=_get_product_count,
	)

	website_ribbon_id = fields.Many2one('product.ribbon', string='Ribbon')
	brand_banner = fields.Binary(string="Brand Banner")
	website_id = fields.Many2one('website', string="Website", ondelete='restrict')
	website_size_x = fields.Integer('Size X', default=1)
	website_size_y = fields.Integer('Size Y', default=1)
	country_of_origin = fields.Char(string="Country of Origin")

	@api.model
	def wk_activate_website_view(self):
		products_description = self.env.ref('website_sale.products_description')
		products_attributes = self.env.ref('website_sale.products_attributes')
		products_description.write(dict(active=1))
		products_attributes.write(dict(active=1))
		return True

	def _get_website_ribbon(self):
		return self.website_ribbon_id
