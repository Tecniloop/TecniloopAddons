# Configuración Parseur — tl_vendor_parseur_intake

## 1. Webhook

En Parseur: mailbox → Export / Webhook → POST.

- URL: `https://<odoo>/parseur/vendor/intake`
- Método: POST
- Cuerpo: JSON del documento parseado (no form-urlencoded)
- Cabecera: `X-Webhook-Token: <token>`  
  Alternativas: `X-Parseur-Token`, query `?token=`, campo JSON `token`

El token se define en Odoo: **Compras → Ajustes → Parseur webhook token**  
(`ir.config_parameter`: `vendor_parseur_intake.webhook_token`).

Si el token está vacío, Odoo acepta cualquier POST (solo para pruebas).

Respuesta 200:

```json
{"ok": true, "intake_id": 12, "intake_name": "VDI/2026/00012", "state": "identified"}
```

401 = token incorrecto. 500 = excepción no controlada (ver log).  
Un reenvío con el mismo `DocumentID` devuelve el **mismo** `intake_id`.

Incluid en el JSON el `DocumentID` nativo de Parseur (id del documento).

## 2. Dos mailboxes (recomendado)

| Mailbox Parseur | `document_type` fijo o campo | Uso |
|---|---|---|
| Albaranes proveedores | `albaran` | Recepción / crear PO si no hay pedido |
| Facturas proveedores | `factura` | Factura sobre PO ya recibido |
| (opcional) Devoluciones | `devolucion` | Salida + to_refund |
| (opcional) Abonos | `abono` | Factura rectificativa |

Si no enviáis tipo: si hay `invoice_number` se trata como factura; si no, como albarán.

Valores reconocidos (minúsculas):

- Albarán: `delivery_note`, `albaran`, `albarán`, `dn`, `packing_slip`, `goods_receipt`
- Factura: `vendor_bill`, `invoice`, `factura`, `bill`, `in_invoice`
- Devolución: `return`, `devolucion`, `devolución`, `vendor_return`, `abono_albaran`
- Abono: `credit_note`, `abono`, `refund`, `in_refund`

Cantidades **todas negativas** en un albarán/factura también se reinterpretan como return/refund.

## 3. Plantilla — cabecera

Mapead **nombres de campo JSON** a uno de los alias. Mayúsculas/minúsculas indistintas.

### Obligatorio en la práctica

| Campo JSON recomendado | Alias aceptados | Para qué |
|---|---|---|
| `DocumentID` | `document_id`, `id` | Idempotencia |
| `document_type` | `DocumentType`, `type` | Flujo albarán/factura/return |
| `supplier_vat` | `SupplierVAT`, `tax_id`, `TaxID` | Identificar proveedor |
| `nif_destinatario` | `company_vat`, `customer_vat`, `buyer_vat`, `our_vat`, `dest_vat`, `cif_empresa` | Compañía Odoo (multi-company) |
| `document_number` | `DocumentNumber`, `number`, `albaran` | Duplicados + referencia |
| `items` | `Items`, `lines`, `Lines` | Tabla de líneas |

**No uses un único campo `VAT` / `vat`.** Ese alias está en `supplier_vat`. Si Parseur solo extrae “el NIF”, será el vuestro y el matching de proveedor fallará. Dos zonas en el PDF: NIF emisor y NIF destinatario.

### Recomendado

| Campo | Alias | Notas |
|---|---|---|
| `supplier_name` | `SupplierName`, `vendor_name`, `supplier` | Fallback si el NIF no está en Odoo |
| `supplier_code` | `vendor_code` | Match con `res.partner.ref` |
| `po_number` | `PONumber`, `purchase_order`, `pedido`, `order_number` | Primer intento de pedido |
| `document_date` | `DocumentDate`, `DeliveryDate`, `InvoiceDate`, `date` | `YYYY-MM-DD`, `DD/MM/YYYY`, `DD-MM-YYYY` |
| `delivery_note_number` | `albaran_number` | Relación 3-way |
| `invoice_number` | `InvoiceNumber` | `ref` de la factura Odoo |
| `currency` | `Currency` | ISO (`EUR`). Si falta, moneda de la compañía resuelta |
| `subtotal` / `tax` / `total` | `untaxed`, `TaxAmount`, `grand_total` | Auto-post de factura (tolerancia de total) |
| `company_name` | `customer_name`, `destinatario` | Solo si no hay NIF destino y hay varias compañías |

Números: se aceptan `1.234,56` y `1,234.56`.

## 4. Plantilla — líneas (`items[]`)

Tabla repetible en Parseur → array JSON.

| Campo recomendado | Alias | Uso |
|---|---|---|
| `sku` | `SKU`, `default_code`, `internal_ref` | Referencia interna Odoo |
| `supplier_code` | `vendor_sku`, `product_code` | Código del proveedor (`product.supplierinfo`) |
| `barcode` | `ean` | EAN / código de barras |
| `description` | `name`, `product`, `item` | Nombre; entra el corrector OCR |
| `qty` | `quantity`, `qty_received` | Ud. del documento (negativa = devolución) |
| `uom` | `UoM`, `unit` | Informativo |
| `unit_price` | `price`, `price_unit` | Precio factura vs PO |
| `line_total` | `LineTotal`, `amount` | Informativo |
| `lot` | `batch`, `serial` | Varios: `LOT1, LOT2` o `SN1;SN2` |
| `expiry` | `caducidad`, `best_before`, `use_by` | Fecha o GS1 `YYMMDD` |

Prioridad de producto: barcode → sku exacto → supplier_code → nombre exacto único → fuzzy.

## 5. Ejemplos de payload

Albarán:

```json
{
  "DocumentID": "parseur-abc",
  "document_type": "albaran",
  "supplier_vat": "ESB12345674",
  "nif_destinatario": "ESA00000000",
  "supplier_name": "Maderas Norte",
  "po_number": "P00045",
  "document_number": "ALB-8891",
  "document_date": "31/08/2026",
  "items": [
    {"sku": "WOOD-01", "qty": 12, "unit_price": 8.5, "lot": "L-2401", "expiry": "2027-03-01"}
  ]
}
```

Factura:

```json
{
  "DocumentID": "parseur-def",
  "document_type": "factura",
  "supplier_vat": "ESB12345674",
  "nif_destinatario": "ESA00000000",
  "invoice_number": "F-2026-100",
  "po_number": "P00045",
  "delivery_note_number": "ALB-8891",
  "currency": "EUR",
  "total": "102.00",
  "items": [
    {"sku": "WOOD-01", "qty": 12, "unit_price": 8.5}
  ]
}
```

## 6. Ajustes Odoo que afectan a Parseur

**Compras → Ajustes**

- Token webhook  
- Auto-apply (identify + apply si no hay excepción)  
- Auto-post factura + tolerancia de total  
- Tolerancias precio/cantidad (default compañía; override en el contacto)  
- Política de exceso de qty  
- Create lots / spellcheck / validar NIF / VIES  
- Prefijo de pistola y longitud mínima  

**Contacto proveedor**

- Auto-validate receipts  
- Tolerancias y vida mínima de lote  

**Compañía**

- VAT = NIF destinatario de las facturas  

## 7. Orden de trabajo Parseur

1. Crear dos mailboxes (albarán / factura) con plantillas distintas.  
2. En cada plantilla, cajas: NIF emisor, NIF destinatario, número, fecha, pedido, tabla líneas.  
3. Export JSON con los nombres de la tabla de arriba (no hace falta que coincidan todos los alias).  
4. Webhook de prueba a un Odoo de ensayo con token.  
5. Comprobar `vendor.document.intake`: partner, compañía, líneas, estado.  
6. Activar auto-apply solo cuando el matching sea estable.

## 8. Errores frecuentes de plantilla

| Síntoma en Odoo | Causa típica en Parseur |
|---|---|
| Vendor could not be identified | NIF emisor mal recortado, o `VAT` = NIF vuestro |
| Company VAT does not match | Falta `nif_destinatario` o no coincide con `res.company.vat` |
| Unidentified products | SKU de proveedor en `sku` en vez de `supplier_code` |
| Duplicate ignored | Mismo `DocumentID` o mismo número+tipo+compañía |
| Bill total not posted | `total` no extraído o fuera de tolerancia |
| Two intakes | No se envía `DocumentID` ni `document_number` |
| Currency EUR en sociedad USD | Falta `currency` y, antes del fix 1.4, compañía mal resuelta |
