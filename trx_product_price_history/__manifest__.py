{
    "name": "Historial de precios de artículos",
    "version": "19.0.1.0.0",
    "category": "Inventory/Purchase",
    "summary": "Registra cada cambio de PVP, costo contable y precio de proveedor de un artículo, "
    "con valor anterior, nuevo, variación, fecha/hora, usuario y origen.",
    "description": """
Historial de precios
====================

Cada vez que cambia un precio de un artículo queda una fila en el historial:

* **PVP** (precio de venta de la red): cambios desde la ficha, desde una revisión de
  lista de proveedor programada, desde el precio planificado (cron) o por importación.
* **Costo contable** (por razón social): cambios desde la ficha o desde la
  sincronización con el costo de reposición.
* **Precio de proveedor** (lista del proveedor en la pestaña Compras del artículo):
  alta, cambio desde la ficha o desde una revisión de lista.

Por cada fila: valor anterior, valor nuevo, variación %, fecha y hora de vigencia,
usuario, origen (artículo / lista de proveedor / revisión / planificado / importación)
y referencia (p. ej. el documento de revisión).

* Pestaña **Historial de precios** en el artículo (lista + gráfico).
* Menú Compras → Informes → **Historial de precios** (lista, pivot y gráfico): "cuánto
  aumentaron los proveedores este mes", "qué PVP tenía este artículo antes".
* Campos ``PVP anterior`` y ``Costo de proveedor anterior`` en el artículo, para la
  grilla de revisión de listas.

Autor: Trixocom.
""",
    "author": "Trixocom",
    "website": "https://www.trixocom.com",
    "license": "LGPL-3",
    "depends": ["product", "purchase", "product_planned_price"],
    "data": [
        "security/ir.model.access.csv",
        "views/price_history_views.xml",
        "views/product_views.xml",
    ],
    "installable": True,
    "application": False,
}
