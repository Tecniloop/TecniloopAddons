Search the [Icecat](https://icecat.biz) open product catalog by
manufacturer part number, or bulk-scan a whole brand, and import the
result straight into Odoo:

- Product name, EAN/barcode and Icecat category classification.
- Main image and additional gallery images, imported as eCommerce media
  (`product.image` records, from the *Website Sale* module).
- A rich eCommerce description built from Icecat's long description plus
  a technical specifications table, stored on the *Description for
  e-Commerce* field provided by the OCA `website_sale_product_description`
  module.
- Icecat category, optionally created/linked as a Product Category and/or
  an eCommerce Category.

Only the Icecat real-time single-product lookup (`XML_s3` interface) is
used for one-off imports. Bulk "import all products of a brand" streams
Icecat's catalog index file to find matches, then imports each one the
same way, in the background.
