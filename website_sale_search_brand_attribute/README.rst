================================
Website Sale Search Enhancement
================================

This module extends Odoo 18 website/eCommerce product search beyond the default
product fields.

It can search, per website, across:

* Brand name and brand description, when a compatible brand field is installed
* Template attribute values
* Template attribute names
* Variant-level attribute values
* Product website tags
* Website categories
* Parent website categories, including descendants of a matched parent category

Configuration
=============

Go to Website settings and configure the ``Product Search`` options. Each website
can enable or disable individual search sources.

The module also includes an option to restrict attribute matching to attributes
that are visible on the website when the installed Odoo version exposes an
attribute visibility field.

Search behavior
===============

The addon updates both:

* The shop domain used by the ``/shop`` controller
* The generic website product search definition through ``search_extra``

Extra fields are intentionally added through domains/search hooks instead of
``search_fields``. This keeps the module compatible with Odoo's fuzzy search and
avoids pg_trgm crashes on arbitrary relational Many2one dot paths such as brand
fields.

Multi-word searches are improved in generic website search by requiring every
word to match at least one enabled extra field. The shop search continues to work
with Odoo's tokenized search hook.

Ranking
=======

When enabled, products matching brand, attributes, tags or categories are moved
higher in the current shop result page. The base Odoo result count, access rules
and shop domain are left untouched.

Brand compatibility
===================

The module checks installed model fields before generating domains. It supports
common brand field names such as ``product_brand_id``, ``brand_id``,
``product_brand_ids`` and ``brand_ids`` when those fields exist, and searches
available name/description fields on the related brand model.

Credits
=======

* APEN Solutions
* OCA guidelines
