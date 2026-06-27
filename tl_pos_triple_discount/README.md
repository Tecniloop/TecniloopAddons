# POS Triple Discount

Modulo Tecniloop para Odoo 19 que adapta el TPV al comportamiento de
`sale_triple_discount` y `sale_pricelist_triple_discount`.

## Funcionalidad

- Anade `discount2` y `discount3` a las lineas de TPV.
- El tipo de calculo queda fijado a multiplicativo, igual que
  `sale_triple_discount` 19.0.
- El boton **Triple desc.** solo pregunta por los tres descuentos; ya no pregunta
  por tipo aditivo/multiplicativo.
- El descuento final se calcula de forma multiplicativa:

```text
D.final = 1 - ((1 - D1) x (1 - D2) x (1 - D3))
```

- El desglose se muestra en la linea del TPV:

```text
Desc.: 10% x 20% x 30% = 49.6%
```

- El mismo desglose se muestra en el ticket, al heredarse el componente
  `point_of_sale.Orderline` usado por pantalla y recibo.
- Si existe `account_invoice_triple_discount`, la factura generada desde TPV
  recibe `discount1`, `discount2` y `discount3`. Si no existe, la factura recibe
  el descuento final agregado en el campo estandar `discount`.

## Tarifas con triple descuento

Si esta instalado `sale_pricelist_triple_discount`, el TPV carga `discount2` y
`discount3` de `product.pricelist.item`.

En Odoo 19 no se depende de la politica visible de tarifa. Cuando la regla de
tarifa de tipo **Descuento** o **Formula** tiene descuentos, el TPV conserva el
precio base en la linea y aplica los descuentos separados:

```text
price_unit = precio base
D1 = percent_price / price_discount
D2 = discount2
D3 = discount3
```

Esto hace que el producto insertado directamente en TPV se comporte como una
linea de pedido de venta: precio base visible, descuentos desglosados, total
neto calculado correctamente.

## Casos cubiertos

1. Producto directo en TPV con regla de tarifa con dos o tres descuentos.
2. Descuento manual desde el boton **Triple desc.**.
3. Pedido de venta con `discount1`, `discount2` y `discount3` cargado en TPV por
   `pos_sale`.
4. Recalculo al cambiar cantidad o tarifa del cliente.
5. Factura desde TPV con campos separados si existe
   `account_invoice_triple_discount`.

## Instalacion

1. Copiar el modulo en el addons path.
2. Actualizar lista de aplicaciones.
3. Actualizar o instalar `POS Triple Discount`.
4. Reiniciar Odoo y recargar assets del TPV.
5. Cerrar y abrir de nuevo la sesion TPV, limpiando cache del navegador si se
   mantienen assets antiguos.
