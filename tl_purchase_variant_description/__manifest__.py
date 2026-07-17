{
    'name': 'Descripción de compra por variante',
    'version': '19.0.1.0.0',
    'category': 'Purchases',
    'summary': 'Añade una descripción de compra adicional a nivel de variante de producto',
    'description': """
Descripción de compra por variante
====================================

Odoo gestiona de serie la "Descripción para el proveedor"
(`description_purchase`) únicamente a nivel de PLANTILLA de producto
(`product.template`): todas las variantes de un mismo producto comparten
siempre el mismo texto. Este módulo añade un campo de texto adicional a
nivel de VARIANTE (`product.product`) para los casos en los que una
variante concreta necesita una nota propia (p. ej. "confirmar acabado con
el proveedor" solo para el color X, o una instrucción que solo aplica a
una talla concreta).

Funcionamiento
--------------
* Nuevo campo "Descripción de compra adicional (variante)" en la ficha de
  cada variante (menú Inventario/Compras > Productos > Variantes de
  producto).
* Al seleccionar esa variante en una línea de pedido de compra (o de
  solicitud de presupuesto), su descripción se completa automáticamente
  con: descripción de la plantilla (comportamiento de serie de Odoo) +
  descripción adicional de la variante (lo que añade este módulo) — no la
  sustituye, la complementa. Técnicamente se hace ampliando el mismo punto
  de extensión que usa el propio Odoo
  (`purchase.order.line._get_product_purchase_description`), así que se
  comporta exactamente igual que la descripción de plantilla: se rellena
  al elegir el producto y a partir de ahí es editable a mano en la línea.
* Al formar parte del mismo texto de la línea, aparece automáticamente en
  los PDF y correos de solicitud de presupuesto/pedido de compra, sin
  tocar ningún informe.
* Es traducible: si el proveedor tiene un idioma distinto configurado, se
  usa la traducción de ese idioma si existe, igual que la descripción de
  compra de la plantilla.

Limitaciones
------------
* Solo afecta a pedidos/líneas de COMPRA. No toca ventas ni fabricación.
* Si se cambia el producto de una línea ya creada, el texto se recalcula
  igual que ya hace Odoo con la descripción de plantilla (es decir: se
  vuelve a rellenar al cambiar de producto, pero no se fuerza si el
  usuario ya editó la línea a mano y no vuelve a tocar el campo producto).
""",
    'author': 'Tecniloop',
    'license': 'LGPL-3',
    'depends': ['purchase'],
    'data': [
        'views/product_product_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
