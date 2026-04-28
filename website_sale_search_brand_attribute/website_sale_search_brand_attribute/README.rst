================================
Website Sale Search Enhancement
================================

This module extends the eCommerce (``/shop``) search in Odoo 18 to also match:

* Product brand name (Many2one field ``product_brand_id`` from ``website_product_brands``)
* Product attribute values (variant attributes) via ``attribute_line_ids.value_ids``

It updates:
* The shop domain used by the ``/shop`` controller (so the shop listing search finds the products)
* The website searchable definition for products (so generic website searches can find them too)

Usage
=====

Go to the website shop page and use the search box. Typing a brand name or an attribute value
will return matching products.

Credits
=======

* APEN Solutions
* OCA guidelines
