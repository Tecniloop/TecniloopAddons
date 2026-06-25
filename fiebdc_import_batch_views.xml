# FIEBDC BC3 Product Import for Odoo 19

Odoo 19 module to import product templates/articles from a ZIP file that contains one BC3 file plus related images and PDF/documents referenced by the BC3 records.

## Supported FIEBDC records

- `~V`: source metadata, charset and URL base.
- `~C`: product concept, code, unit, summary, prices, dates and type.
- `~T`: long description.
- `~X`: technical data stored as JSON text on the product.
- `~G`: product images/graphics.
- `~F`: product documents and PDFs.

The module does not execute DLL/EXE parametric files. Executable attachments found in the ZIP are blocked.

## Odoo 19 compatibility notes

- Manifest version is `19.0.1.0.14`.
- List views use the Odoo 19 `<list>` root element.
- Product type is mapped to Odoo 19 values: `consu` = Goods and `service` = Service.
- The wizard includes `Track Inventory for Goods`, which sets `is_storable` when the Inventory/Stock module is installed.
- Imported PDFs/images are stored as `ir.attachment` and, in Odoo 19, linked to `product.document` so they appear in the product Documents smart button.

## Installation

1. Copy `tl_fiebdc_product_import` to your Odoo 19 addons path.
2. Restart Odoo.
3. Update the Apps list.
4. Install `FIEBDC BC3 Product Import`.

## Usage

1. Open `FIEBDC > Import BC3 Products`.
2. Upload a ZIP file.
3. Leave `BC3 Filename` empty to import the first `.bc3` found, or set the path when the ZIP contains several BC3 files.
4. Click `Preview` to inspect the importable concepts.
5. Click `Import`.
6. Review `FIEBDC > Import History` for warnings and errors.

## Product mapping

- BC3 code -> `default_code` and `bc3_code`.
- BC3 summary -> product name.
- First BC3 price -> sales price.
- BC3 unit -> Odoo UoM best effort mapping.
- BC3 text -> sale description and BC3 description field.
- BC3 technical info -> JSON text field.
- BC3 type 1/2 -> Service.
- BC3 type 3 -> default wizard type, normally Goods.
- First image from `~G` or `~F` type 13 -> product image, depending on wizard options.
- All images/PDFs/documents -> `ir.attachment` linked to `product.template`; also wrapped as `product.document` in Odoo 19.

## Notes

- Root and chapter concepts ending in `#` or `##` are skipped.
- BC3 type 4 and 5 are skipped by default; they can be enabled in the wizard.
- The manual wizard imports ZIP files. Manufacturer maintenance records can download a BC3 directly from a saved HTTP/HTTPS URL.
- `~D` decompositions are not converted to BoM in this version.

## Compatibility

Prepared for Odoo 19 with standard `base`, `product`, `uom`, `stock` and `mail` modules.


## Upload fix for Odoo 19

Version 19.0.1.0.2 stores the wizard ZIP field directly on the transient model (`attachment=False`) and explicitly binds the import action to the binary-upload view.


## Odoo 19 upload note

The import wizard uses `zip_attachment_ids` with the `many2many_binary` widget for ZIP upload. This is more reliable in Odoo 19 dialogs than a plain binary field and still accepts exactly one `.zip` file.


## Abrir el importador

La version 19.0.1.0.7 incluye tres puntos de entrada para evitar problemas de menu/cache:

1. Menu principal: **BC3 / FIEBDC > Importar productos BC3**.
2. Productos: abrir un producto y pulsar el boton **Importar BC3**.
3. Productos: desde lista/formulario, menu **Accion > Importar productos BC3 / FIEBDC**.

Si no aparece ninguno, Odoo no esta cargando esta carpeta del modulo o no se ha ejecutado la actualizacion `-u tl_fiebdc_product_import` sobre la base correcta.

## 19.0.1.0.10

Safe install build: removes the product form header button and server action bindings. The wizard is opened only from the top menu `BC3 / FIEBDC -> Importar productos BC3` to avoid stale XML action references during installation.


## 19.0.1.0.11

Compatibility fix for Odoo 19: the importer no longer writes `uom_po_id` unless that field exists on `product.template`. Some Odoo 19 builds removed/renamed the Purchase UoM field, causing `Invalid field 'uom_po_id' in 'product.template'` during import.

## 19.0.1.0.12

- Reorganized the root menu so **BC3 / FIEBDC** behaves as the application entry point and the existing options are grouped below it.
- Added **BC3 / FIEBDC > Configuracion > Fabricantes**.
- Each manufacturer stores a persistent **URL del fichero BC3** and the same import options as the existing wizard.
- Manufacturer records provide **Vista previa** and **Importar** actions that download the BC3 from the configured URL.
- Import history now stores the manufacturer and source BC3 URL when the import is launched from a manufacturer.
- Remote related images/documents referenced by the BC3 are resolved from the BC3 URL directory, from the BC3 `~V` URL base, and from `~G`/`~F` URL extensions when available.


## Nota SSL

En el mantenimiento de fabricantes se ha anadido la opcion **Permitir SSL sin verificar** para servidores HTTPS de fabricantes que publican el fichero BC3 con una cadena de certificados incompleta. Mantengala desactivada por defecto y activela solo en URLs de fabricantes conocidos.


## 19.0.1.0.14

- Added configurable download limits on each manufacturer:
  - **Limite descarga BC3 (MB)**, default 500 MB for the main BC3 URL.
  - **Limite adjunto relacionado (MB)**, default 75 MB per related file.
- Improved the size-limit error message so it indicates the configured limit and tells the user where to increase it.
- Existing manufacturer records with empty/zero values fall back to the safe defaults above.
## Changes in 19.0.1.0.15

- Removed the direct menu entry to the legacy file import wizard from the BC3 / FIEBDC app menus.
- Reordered the top app menus so Operations appears before Configuration.

