1. Go to *Settings > General Settings > Icecat* and enter your Icecat
   account credentials (username, password, data language). Use
   *Test Connection* to confirm they work.
2. Go to *Website > Configuration > eCommerce > Products* and run
   *Sync Manufacturers from Icecat* to import Icecat's full suppliers
   list (names and Supplier IDs) in one go. Alternatively, create a
   manufacturer by hand under *Icecat Manufacturers* using the exact
   name Icecat knows it by — its Supplier ID is looked up automatically
   from Icecat's suppliers list the first time it is needed (or via the
   *Fetch Supplier ID from Icecat* button on its form).
3. For each manufacturer, choose what should be imported by default: main
   image, additional gallery images, Product Category creation, eCommerce
   Category creation.
4. On each Product Brand, open the *Icecat* tab and link it to the
   matching Icecat manufacturer.
5. For bulk imports, keep *Catalog Index* set to *On-Market Products*
   unless you explicitly need the complete global catalog. Select one or
   more *Icecat Categories* on the brand to limit the scan; optionally
   include all child categories in those taxonomy branches.
6. Use *Modified Since* for recently edited data and *Added Since* when
   old products must be excluded even if Icecat edited them recently.
   Quality, market, image and access filters are evaluated directly from
   the index before any product sheet is downloaded.
