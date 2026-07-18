==========================
Icecat Catalog Integration
==========================

..
   !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
   !! This file is assembled by hand from the         !!
   !! readme/*.md fragments, following the OCA        !!
   !! oca-gen-addon-readme convention. Edit the        !!
   !! fragments, not this file directly.               !!
   !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

Search the `Icecat <https://icecat.biz>`_ open product catalog by
manufacturer part number, or bulk-scan a whole brand, and import the
result straight into Odoo:

* Product name, EAN/barcode and Icecat category classification.
* Main image and additional gallery images, imported as eCommerce media
  (``product.image`` records, from the *Website Sale* module).
* A rich eCommerce description built from Icecat's long description plus
  a technical specifications table, stored on the *Description for
  e-Commerce* field provided by the OCA ``website_sale_product_description``
  module.
* Icecat category, optionally created/linked as a Product Category and/or
  an eCommerce Category.

Only the Icecat real-time single-product lookup (``XML_s3`` interface) is
used for one-off imports. Bulk "import all products of a brand" streams
Icecat's compressed On-Market index by default, filters it by the linked
Icecat Supplier ID and optionally by the ``Updated`` date, then imports each
matching product in the background. The Full and Daily indexes remain
available for exceptional cases.

**Table of contents**

.. contents::
   :local:

Configuration
=============

#. Go to *Settings > General Settings > Icecat* and enter your Icecat
   account credentials (username, password, data language). Use
   *Test Connection* to confirm they work.
#. Go to *Website > Configuration > eCommerce > Products > Icecat
   Manufacturers* and create the manufacturers you work with, using the
   exact name Icecat knows them by. For bulk import, also fill in their
   *Icecat Supplier ID*.
#. For each manufacturer, choose what should be imported by default: main
   image, additional gallery images, Product Category creation, eCommerce
   Category creation.
#. On each Product Brand, open the *Icecat* tab and link it to the
   matching Icecat manufacturer.
#. For bulk imports, keep *Catalog Index* set to *On-Market Products*
   unless you explicitly need the complete global catalog. Set *Modified
   Since* when you only want products updated from a particular date.

Usage
=====

Import a single product by part number
---------------------------------------

#. Go to *Website > Configuration > eCommerce > Products > Import from
   Icecat*.
#. Pick a Brand (it must have an Icecat manufacturer configured on its
   Icecat tab) and enter a Part Number, then *Search*.
#. Review the fetched name, EAN, category and short description, adjust
   the import switches if needed, then *Import Product*.

Import all products of a brand
-------------------------------

#. Open the Product Brand and go to its *Icecat* tab.
#. Select the catalog index. *On-Market Products* is the recommended
   default because it is smaller than the global catalog and contains
   products known to be distributed in the configured language market.
#. Optionally set *Modified Since* to exclude products whose Icecat
   ``Updated`` timestamp is older than that date, and set a maximum number
   of products for a controlled first test.
#. Click *Import All Products from Icecat*.
#. This runs entirely in the background: Icecat's compressed catalog index
   is scanned for matching part numbers, which are then imported a batch at
   a time by a scheduled action (*Icecat: process bulk product imports*,
   every 5 minutes by default). Progress (pending/done/error/skipped
   counts) is shown on the brand's Icecat tab; the queued lines themselves
   are available from there too, to inspect or retry failures.
#. Re-running *Import All Products from Icecat* later only queues new
   part numbers found since the last scan — it will not duplicate
   products already imported.

Refresh an already-imported product
-------------------------------------

Open the product: if it was imported from Icecat, a *Refresh from Icecat*
button appears on it. This updates the eCommerce description and main
image only, so it never overwrites categories or gallery images that may
have been curated by hand since the import.

Known issues / Roadmap
=======================

* Category names synced via *Sync Categories from Icecat* are always in
  English (Icecat's own fixed language ID for its reference taxonomy
  file), independent of the configured product data language.
* Icecat's downloadable PDFs/manuals (``ProductMultimediaObject``) are
  parsed but not imported anywhere yet. Wiring them into
  ``website_sale_product_attachment`` would be a natural follow-up.
* The bulk import queue is a simple built-in cron-driven table, not an
  OCA ``queue_job`` integration. It has no per-line retry backoff or
  priority channels; failures just sit in ``error`` state for manual or
  bulk retry.
* Bulk-scanning Icecat's full catalog index can still take a while for a
  brand with many products. Prefer the compressed On-Market index and a
  *Modified Since* date whenever the business does not need historical
  or no-longer-distributed products.

Credits
=======

Contributors
------------

* Custom Development

Maintainers
-----------

This is a private module, not part of an OCA repository. It follows OCA
development conventions (manifest, readme fragments, folder layout,
``pylint-odoo`` style) for consistency and maintainability alongside the
OCA modules it depends on.
