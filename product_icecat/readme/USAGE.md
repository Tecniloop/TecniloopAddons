### Import a single product by part number

1. Go to *Website > Configuration > eCommerce > Products > Import from
   Icecat*.
2. Pick a Brand (it must have an Icecat manufacturer configured on its
   Icecat tab) and enter a Part Number, then *Search*.
3. Review the fetched name, EAN, category and short description, adjust
   the import switches if needed, then *Import Product*.

### Import all products of a brand

1. Open the Product Brand and go to its *Icecat* tab.
2. Select the catalog index. *On-Market Products* is the recommended
   default because it is smaller than the global catalog and contains
   products known to be distributed in a market.
3. Select the allowed *Icecat Categories*. With *Include Child
   Categories* enabled, choosing a parent category imports its complete
   descendant branch. Leaving the field empty allows all categories.
4. Optionally set *Modified Since* and/or *Added Since*. The first accepts
   old products edited recently; the second only accepts products first
   added to Icecat from that date.
5. Choose the data quality and availability requirements: standardized
   Icecat data only or supplier data too, on-market status, main image,
   and exclusion of restricted products. Set a maximum number of products
   for a controlled first test.
6. Click *Import All Products from Icecat*.
7. This runs entirely in the background: Icecat's compressed catalog index is
   scanned for matching part numbers, which are then imported a batch at
   a time by a scheduled action (*Icecat: process bulk product imports*,
   every 5 minutes by default). Progress (pending/done/error/skipped
   counts) is shown on the brand's Icecat tab; the queued lines themselves
   are available from there too, to inspect or retry failures.
8. Re-running *Import All Products from Icecat* later only queues new
   part numbers found since the last scan — it will not duplicate
   products already imported.

### Refresh an already-imported product

Open the product: if it was imported from Icecat, a *Refresh from Icecat*
button appears on it. This updates the eCommerce description and main
image only, so it never overwrites categories or gallery images that may
have been curated by hand since the import.
