# Odoo Smart Search using Elasticsearch (Odoo 18)

Odoo Smart Search using Elasticsearch is a high-performance website search module that improves customer experience with faster product discovery, smart suggestions, and relevance-focused ranking.

## Compatibility
- Odoo version: `18.0`
- Module version: `18.0.1.0.0`
- Supported app: `website_sale`

## What This Module Adds
- Replaces base shop autocomplete with custom Elasticsearch dropdown.
- Suggestion cards with `product image + product name + category + formatted price`.
- Real-time type-ahead and auto-complete suggestions.
- Auto-classified badges on shop cards and product page: `Bestseller`, `Trending`, `New Arrival`.
- Badge display policy: max 2 badges on cards and product page (priority: Bestseller > Trending > New Arrival).
- Backend visibility for `product.template`: list/form/kanban/search filters for badge-based merchandising.
- Configurable badge rules from Settings: top-N and day windows for Bestseller/Trending/New Arrival.
- Dynamic indexing foundation: configure any Odoo model + mapped fields + custom domain and index to Elasticsearch.
- Field-level relevance boosts (`name^5`, `sku^3`, etc.) from Dynamic ES Indexing.
- Dynamic auto-sync option: for configured models, index updates automatically on create/write/unlink.
- Trending products ranked using sales history.
- Trending search terms from click analytics (cleaned, noise-filtered).
- Click-through tracking and click-aware reranking for repeated queries.
- Advanced filters: category, brand, attributes, min/max price.
- Elasticsearch facets: category, brand, attribute, price buckets.
- Option to hide out-of-stock products.
- Auto indexing on product create/write/unlink when auto-sync is enabled in dynamic config.
- Scheduled reindex cron for periodic sync.
- Fallback to Odoo ORM search when Elasticsearch is unavailable.

## Why Elasticsearch
- Built for full-text search and analytics with inverted indexing.
- Much faster query response for large catalogs.
- Better relevance and user experience for ecommerce search bars.

## Odoo Settings
Go to `Settings -> Elasticsearch Search` and configure:
- `Enable Elasticsearch Search`
- `Elasticsearch URL` (example: `http://localhost:9200`)
- `Elasticsearch Index` (default: `odoo_products`)
- `Hide Out Of Stock`
- `Enable Autocomplete`
- `Enable Trending Searches`
- `Test Elasticsearch Connection`

## Dynamic ES Indexing
Go to `Website -> Configuration -> Dynamic ES Indexing`:
- Create indexing configs for any model with `index_name` and custom `domain`.
- Add field mappings with optional ES key names.
- Mark fields as searchable and set `search_boost`.
- Enable `Auto Sync` to keep ES docs updated on create/write/unlink.
- For product search, keep only one config enabled with `Use for Website Product Search`.

## How It Works
- Customer types in shop search bar.
- Module calls `/es/search_suggest` and renders custom dropdown.
- Suggestion clicks are logged using `/es/search_click`.
- Search results and filters are served by `/es/search`.
- Product index stays updated from model hooks and cron.

## Main Endpoints
- `GET /es/search_suggest?q=<term>`
- `GET /es/search?q=<term>&category_id=&brand=&min_price=&max_price=&attrs=`
- `POST /es/search_click`

## Elasticsearch Notes
- Expected index name: `odoo_products` (configurable).
- Ensure ES is reachable from Odoo server.
- Reindex after large catalog imports.

## Upgrade Note (Odoo 18)
- This module uses Odoo 18-compatible backend views and web assets.
- If upgrading from an older custom revision, restart Odoo and run module upgrade:
  - `-u website_product_search_es`

## Screenshots
### Search Dropdown
  ![Search Dropdown](static/description/screenshot_main.png)

  ### Settings
  ![Settings](static/description/Screenshot_config.png)

  ### Product Badges
  ![Product Badges](static/description/Screenshot_badges.png)

  ### Dynamic Indexing
  ![Dynamic Indexing](static/description/Screenshot_dynamic_indexing.png)
