# eCommerce Same Category Product Carousel

Odoo 19 addon that adds a new, independent website snippet named **Products from the Same Category**.

## Behaviour

- Intended for the shared product-page editable area.
- Retrieves published products sharing at least one directly assigned eCommerce category (`public_categ_ids`).
- Excludes every variant of the current product template.
- Uses Odoo's standard dynamic product card, prices, pricelist, website and company filtering.
- Displays one card per product template by default; variants can be enabled from the snippet design options.
- Hides itself outside product pages, when the current product has no eCommerce category, or when no related products are found.
- Does not replace or patch the existing **Products** dynamic snippet.

## Installation

1. Copy the module to an addons path.
2. Update the Apps list.
3. Install **eCommerce Same Category Product Carousel**.
4. Edit a product page and drop **Products from the Same Category** from the **Catalog** snippets.

The block should normally be added to the shared product page area so the same placement is used by all products.
