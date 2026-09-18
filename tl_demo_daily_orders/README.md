# Pedidos demo diarios — Odoo 19

Genera entre 3 y 7 pedidos de **venta** y de **compra** por cada día de un
intervalo. Los albaranes se validan y se les pone fecha efectiva pasada
(desbloquear → `date_done` → bloquear), que es el flujo nativo de Odoo 19.

## Uso

1. Copia `tl_demo_daily_orders` a `extra-addons` y actualiza la lista de apps.
2. Instala **Pedidos demo diarios (compra y venta)**.
3. Ventas → Datos demo → Pedidos aleatorios por fechas.
4. Indica `date_from` / `date_to` y Generar.

## Requisitos de datos

- Contactos con `customer_rank > 0` (clientes).
- Contactos con `supplier_rank > 0` (proveedores). Si no hay, reutiliza clientes.
- Productos almacenables o consumibles, venta y compra activas.

Cada día: primero compras (entrada de stock) y después ventas (salida).

## Shell (alternativa)

```python
wiz = env['tl.demo.orders.wizard'].create({
    'date_from': '2026-09-01',
    'date_to': '2026-09-18',
    'min_per_day': 3,
    'max_per_day': 7,
})
wiz.action_generate()
env.cr.commit()
```
