# trx_product_price_history

Historial de precios de artículos para Odoo 19 CE (Trixocom).

Registra cada cambio de **PVP**, **costo contable** (por razón social) y **precio de
proveedor** con valor anterior, nuevo, variación %, fecha/hora de vigencia, usuario,
origen y referencia.

## Cómo se alimenta

| Qué cambia | Dónde se captura | Origen por defecto |
|---|---|---|
| `product.template.list_price` | `write()` | `product` |
| `product.template.list_price` vía precio planificado (SQL de `product_planned_price`) | `_update_prices_from_planned()` | `planned` |
| `product.product.standard_price` (company dependent) | `write()` con `env.company` | `product` / `planned` (cron ADHOC) |
| `product.supplierinfo.price` | `create()` / `write()` | `supplierinfo` |

Otros módulos pueden identificar el origen pasando contexto:

```python
product.with_context(
    trx_price_history_origin="revision",
    trx_price_history_ref="LP/2026/00001",
    trx_price_history_reason="Lista Derajim 292",
    trx_price_history_date=apply_at,
).write({"list_price": 29545})
```

`trx_price_history_skip=True` evita registrar (migraciones, cargas iniciales).

## Vistas

* Artículo → botón "Cambios de precio" y pestaña **Historial de precios** (con `PVP anterior`).
* Compras → Informes → **Historial de precios**: lista, pivot (proveedor × mes) y gráfico.

Autor: Trixocom. Licencia: LGPL-3.
