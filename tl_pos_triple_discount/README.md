# POS Triple Discount

Modulo para Odoo 19 que añade soporte de triple descuento en TPV y en la integracion POS/Ventas.

## Alcance

- Añade `discount2`, `discount3` y `discounting_type` en `pos.order.line`.
- Calcula el descuento final en POS de forma multiplicativa o aditiva.
- Copia descuentos adicionales desde `sale.order.line` cuando existen campos `discount1`, `discount2`, `discount3` y `discounting_type`.
- Ajusta la base fiscal del POS para que impuestos, totales y factura usen el descuento final.
- Si existe `account_invoice_triple_discount`, traspasa los descuentos separados a la factura en modo multiplicativo.

## Nota importante

El modo aditivo se conserva en POS, pero al facturar contra `account_invoice_triple_discount` se envia el descuento final como `discount1` para evitar diferencias de total, ya que ese modulo de factura normalmente agrega los descuentos de forma multiplicativa.

## Integración con tarifas triple descuento

Si está instalado `sale_pricelist_triple_discount`, el TPV carga `discount2` y `discount3` de `product.pricelist.item` y aplica el mismo cálculo multiplicativo que el módulo de ventas: `percent_price` o `price_discount` se agregan con `discount2` y `discount3` antes de calcular el precio de tarifa en POS.

En Odoo 19 `sale_triple_discount` convierte `sale.order.line.discount` en descuento total calculado; por eso al traer un pedido de venta al TPV se usa `discount1` como primer descuento de la línea POS y no el total agregado, evitando aplicar doblemente `discount2` y `discount3`.
