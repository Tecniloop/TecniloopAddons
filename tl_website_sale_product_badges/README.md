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


## Ajuste por sitio web y corrección de imagen (19.0.2.0.0)

### Activable por sitio web

En la ficha de producto los distintivos se muestran siempre. Para el
**catálogo** (`/shop`, lista de deseos, snippets), dos interruptores nuevos en
**Website → Configuración → Sitios web → (tu sitio) → pestaña «Product
Badges»** — mismo patrón y mismo formulario que la pestaña nativa "Product Page
Extra Fields" de `website_sale`:

- `tl_show_badges_catalog` (desactivado por defecto)
- `tl_show_availability_catalog` (activado por defecto)

Cada sitio web decide de forma independiente si los muestra en el listado.

### Imagen recortada en el catálogo

No era un bug de este módulo: **el core ya usa `object-fit: contain` por
defecto**. El recorte viene de la variable CSS
`--o-wsale-card-thumb-fill-mode`, que `website_sale.scss` fija a `cover` cuando
la tarjeta usa el diseño **"Portrait"** (clase `oe_product_custom_portrait`,
activable desde el editor de Website → Personalizar → tarjeta de producto).

Se neutraliza en `badges.scss` con más especificidad y `!important` en la
propiedad real (no solo en la variable, porque el editor de Website puede
inyectar estilos inline). El efecto es el mismo en toda la tienda, esté
activado o no el toggle de distintivos: si el recorte era un problema, lo era
independientemente de esta funcionalidad.


## Campos adicionales estándar en el catálogo (19.0.3.0.0)

`website_sale` trae de serie **«Product Page Extra Fields»**
(`website.sale.extra.field`, pestaña propia en el formulario de sitio web):
permite mostrar campos char o binary de `product.template` (p.ej. Referencia
interna) en la ficha, pero **solo ahí** — la plantilla `ecom_show_extra_fields`
del core está anclada dentro de `website_sale.product`, no en la tarjeta del
listado.

No se recrea el modelo ni la configuración: se reutiliza
`website.shop_extra_field_ids` tal cual y se replica su misma lógica de
renderizado (texto para char, icono de descarga para binary) también en la
tarjeta, tras el interruptor `tl_show_extra_fields_catalog`.

Anclaje: `<t t-if="product_extra_information">`, un punto de extensión que el
propio core deja en `products_item` para insertar contenido adicional por
producto — más estable que colgarse de una clase CSS, y pensado justo para
esto.

No hace falta configurar nada nuevo: los campos que ya tengas en «Product Page
Extra Fields» son los que se muestran en el catálogo al activar el interruptor.
