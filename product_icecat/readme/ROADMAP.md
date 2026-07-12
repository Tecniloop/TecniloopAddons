- Category names synced via *Sync Categories from Icecat* are always in
  English (Icecat's own fixed language ID for its reference taxonomy
  file), independent of the configured product data language.
- Icecat's downloadable PDFs/manuals (`ProductMultimediaObject`) are
  parsed but not imported anywhere yet. Wiring them into
  `website_sale_product_attachment` would be a natural follow-up.
- The bulk import queue is a simple built-in cron-driven table, not an
  OCA `queue_job` integration. It has no per-line retry backoff or
  priority channels; failures just sit in `error` state for manual or
  bulk retry.
- Bulk-scanning Icecat's full catalog index can take a while for the
  first run on a brand with many products: the index itself can be a
  large, non-gzipped XML file covering every supplier, streamed and
  filtered locally since Icecat does not offer a per-supplier index
  endpoint.
