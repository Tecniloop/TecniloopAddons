# Descripción de compra por variante (Odoo 19)

Odoo gestiona la "Descripción para el proveedor" (`description_purchase`)
solo a nivel de **plantilla** de producto: todas las variantes comparten el
mismo texto. Este módulo añade un campo de texto adicional a nivel de
**variante** (`product.product`), pensado para notas que solo aplican a un
color/talla/combinación concreta.

## Instalación

Copia la carpeta `tl_purchase_variant_description` en tu carpeta de addons,
actualiza la lista de aplicaciones e instálalo. Sin dependencias externas
ni de otros módulos aparte de `purchase` (ya incluye `product`).

## Uso

1. Ve a **Inventario** (o Compras) **> Productos > Variantes de producto**,
   abre la variante que quieras y rellena "Descripción de compra adicional
   (variante)".
2. Al añadir esa variante en una línea de pedido de compra o de solicitud
   de presupuesto, la descripción de la línea se rellena con: descripción
   de la plantilla (como ya hace Odoo) + tu texto adicional de la
   variante, en una línea nueva.
3. A partir de ahí la línea es editable a mano como cualquier otra; si
   cambias el producto de la línea, se vuelve a recalcular igual que ya
   hace Odoo con la descripción de plantilla.

Como el texto forma parte de la propia descripción de la línea, aparece
automáticamente en el PDF y el correo de la solicitud de presupuesto/
pedido, sin tocar ningún informe. Es traducible: si el proveedor tiene otro
idioma configurado, se usa esa traducción si existe.

## Cómo funciona por dentro

El único punto de extensión usado es
`purchase.order.line._get_product_purchase_description()`, el mismo método
que ya usa el núcleo de Odoo (`addons/purchase`) para construir la
descripción a partir de la plantilla. Este módulo simplemente llama a
`super()` y añade el texto de la variante al final:

```python
def _get_product_purchase_description(self, product_lang):
    description = super()._get_product_purchase_description(product_lang)
    if product_lang.purchase_variant_description:
        description += '\n' + product_lang.purchase_variant_description
    return description
```

Al reutilizar el mismo mecanismo que ya usa Odoo (en vez de un `onchange`
propio o una vista de compra distinta), el campo se comporta de forma
coherente con el resto: se recalcula exactamente cuándo y cómo ya lo hace
la descripción de plantilla, sin lógica duplicada.

## Limitaciones

- Solo afecta a documentos de **compra** (pedidos y solicitudes de
  presupuesto). No toca ventas ni fabricación.
- El campo vive en `product.product`, así que aparece en la ficha de
  **variante**, no en la ficha de plantilla — es la ubicación correcta
  para un dato por variante, pero si buscas el campo desde el menú
  general de "Productos" (que muestra plantillas) no lo verás ahí; hay que
  entrar en "Variantes de producto" o abrir una variante concreta desde el
  botón de variantes de la plantilla.
