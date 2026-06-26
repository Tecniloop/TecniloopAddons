# POS Triple Discount

Modulo para Odoo 19 que añade soporte de triple descuento en TPV y en la integracion POS/Ventas.

## Alcance

- Añade `discount2`, `discount3` y `discounting_type` en `pos.order.line`.
- Calcula el descuento final en POS de forma multiplicativa o aditiva.
- Copia descuentos adicionales desde `sale.order.line` cuando existen campos `discount1`, `discount2`, `discount3` y `discounting_type`.
- Ajusta la base fiscal del POS para que impuestos, totales y factura usen el descuento final.
- Si existe `account_invoice_triple_discount`, traspasa los descuentos separados a la factura en modo multiplicativo.
- Si no existe `account_invoice_triple_discount`, traspasa a factura el descuento final agregado en el campo estandar `discount`.

## Integracion con tarifas triple descuento

Si esta instalado `sale_pricelist_triple_discount`, el TPV carga `discount2` y `discount3` de `product.pricelist.item` y tambien carga `discount_policy` de `product.pricelist`.

Cuando la tarifa tiene politica `Show public price & discount to the customer` (`discount_policy = without_discount`), el TPV replica el comportamiento de Ventas:

- conserva el precio base/publico en `price_unit`;
- guarda `discount`, `discount2` y `discount3` separados en la linea POS;
- calcula impuestos y total con el descuento final multiplicativo;
- muestra el desglose de descuentos en la linea del TPV y en el ticket.

Cuando la tarifa tiene politica `Discount included in the price` (`discount_policy = with_discount`), el TPV mantiene el comportamiento estandar: precio neto ya descontado sin desglose de descuentos de tarifa, igual que hace el modulo OCA en pedidos de venta.

## Visualizacion

En pantalla y en el ticket se muestra una linea adicional por producto cuando hay desglose:

```text
Desc.: 10% x 20% x 30% = 49.6%
```

La visualizacion aplica tanto a descuentos procedentes de tarifa como a descuentos introducidos manualmente con el boton `Triple desc.`.

## Nota importante

El modo aditivo se conserva en POS, pero al facturar contra `account_invoice_triple_discount` se envia el descuento final como `discount1` para evitar diferencias de total, ya que ese modulo de factura normalmente agrega los descuentos de forma multiplicativa.

En Odoo 19 `sale_triple_discount` convierte `sale.order.line.discount` en descuento total calculado; por eso al traer un pedido de venta al TPV se usa `discount1` como primer descuento de la linea POS y no el total agregado, evitando aplicar doblemente `discount2` y `discount3`.
