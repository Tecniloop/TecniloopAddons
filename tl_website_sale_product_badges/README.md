# tl_website_sale_product_badges

Distintivos de características e indicador de disponibilidad en la tienda de
Odoo 19, replicando el patrón de piko-shop.de: iconos sobre la imagen y punto
de color de disponibilidad, tanto en la ficha como en el listado.

Autor: Tecniloop · Licencia: LGPL-3 · Versión: 19.0.1.1.0 · Depende de `website_sale`

## Qué añade

- `product.attribute.tl_is_badge` — marca un atributo como distintivo.
- `product.attribute.tl_badge_sequence` — orden de los distintivos.
- `product.attribute.value.tl_badge_text` — texto corto alternativo.
  El icono usa el campo `image` **que ya existe en el core** (pensado para
  `display_type='image'`), en vez de crear uno nuevo.
- `product.template.tl_availability` + `tl_availability_note` — estado y detalle.
- `product.template.tl_badge_value_ids` — calculado: los valores de atributo
  marcados como distintivo, ordenados.

Sin imagen se pinta el texto del valor: «III», «DB», «DC»… que es exactamente
lo que hace la tienda de PIKO con la época y la administración.

## Anclajes de plantilla (verificados contra el fuente 19.0)

| Dónde | Anclaje | Por qué ese |
| --- | --- | --- |
| Ficha | `//t[@t-call='website_sale.shop_product_images']` | el `div.o_wsale_product_images` que lo envuelve usa `t-attf-class`, y `hasclass()` no lo encuentra al heredar |
| Tarjeta (iconos) | `//span[hasclass('oe_product_image_img_wrapper_primary')]` | tiene `class` literal y está dentro del `<a>` `position-relative`, así que la superposición absoluta funciona |
| Tarjeta (disponibilidad) | `//div[hasclass('o_wsale_product_information_text')]` | `class` literal, justo encima del nombre |

Misma cautela en el formulario de producto: se ancla en
`//page[@name='sales']//group[@name='extra_info']`, porque el grupo `shop` que
usaban módulos de versiones anteriores ya no existe en 19.

## Uso

1. Ajustes → Atributos: marca *Mostrar como distintivo* en los que quieras
   (época, administración, corriente, sonido…) y ordénalos.
2. Opcional: sube un icono al campo *Imagen* de cada valor.
3. En el producto, pestaña Ventas → *Distintivos y disponibilidad*, elige el
   estado. `tl_piko_product_import` lo rellena solo a partir del texto de
   disponibilidad de la ficha de origen.


## Nota sobre los xpath

Todos los anclajes usan `//*[...]` en vez de fijar la etiqueta (`//div[...]`,
`//span[...]`). Atar el xpath al nombre del elemento hace que la vista falle con
"no puede ser localizado" en cuanto el core cambia un `div` por un `section`,
aunque el `id` o la clase sigan ahí. El identificador ya es único por sí solo.
