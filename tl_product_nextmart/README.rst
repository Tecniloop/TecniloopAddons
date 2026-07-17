===========================
Product Nextmart Enrichment
===========================

This Odoo 19 module completes a product from the GTIN/EAN using Nextmart
DataView::

    https://www.nexmart.com/api/dataview/?partnerkey=KEY&gtin=GTIN&lang=es

Features
========

* Partner key and import policy in General Settings.
* Manual "Complete with Nextmart" action on product templates and variants.
* Product name, sales description and Odoo 19 eCommerce description.
* Main image and de-duplicated extra product media.
* OCA ``product_brand`` mapping and automatic brand creation.
* OCA ``product_manufacturer`` fields for manufacturer, product name, code and URL.
* Generic technical specification table for manufacturer-dependent properties.
* Nextmart source metadata and synchronization timestamp.
* Does not change prices, costs, stock, taxes, accounts or routes.

Compatibility
=============

The partner key uses the legacy system parameter ``website.nexmart_apikey``
from the Odoo 12 ``website_sale_nexmart`` module, so an existing migrated value
continues to work.

Installation
============

Install these OCA dependencies first:

* ``product_brand``
* ``product_manufacturer``

The ``website_sale`` dependency provides the Odoo 19 eCommerce description and
extra product media model.

Website DataView and complete image import
------------------------------------------

After a successful enrichment the module can enable a live Nextmart DataView
iframe on the public eCommerce product page. The iframe uses the configured
Partner Key, product GTIN/EAN and language. Its height is configurable.

When ``Import All Nextmart Images`` is enabled, every unique image exposed in
the DataView slider is downloaded: product, packaging, dimensions, application,
detail, compatibility/material icons and GPSR labels. The first product image is
stored as the product main image and all remaining images as ``product.image``
records, with the original Nextmart URL retained to prevent duplicates.
