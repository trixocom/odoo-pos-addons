{
    "name": "Listas de proveedor - Revisión de precios programada",
    "version": "19.0.1.0.2",
    "category": "Inventory/Purchase",
    "summary": "Carga la lista de precios de un proveedor (Excel/CSV tal como llega), muestra costo actual / "
    "nuevo / variación y PVP actual / propuesto, y la aplica en la fecha y hora programadas.",
    "description": """
Listas de proveedor / Revisión de precios
=========================================

Documento persistente por cada lista que manda un proveedor (Compras → Listas de proveedor):

* **Carga**: se sube el archivo original del proveedor (Excel, CSV); el sistema detecta
  las columnas (código, detalle, precio de lista, bonificación, código de barras, PVP
  sugerido) y arma las líneas. Se cargan todas las líneas de la lista.
* **Reconocimiento del artículo** por este orden: código de barras → código del
  proveedor (lista de proveedor del artículo) → código alfa → nombre (sólo sugerido).
  Lo que no se reconoce queda como **Nuevo**: catálogo del proveedor; se crea el artículo
  sólo con **Incorporar** (código alfa automático: prefijo del proveedor + correlativo).
* **Grilla de revisión**: por línea costo actual / costo nuevo / % variación, PVP actual /
  PVP propuesto / % / PVP anterior; filtros subieron / bajaron / iguales / nuevos /
  sin PVP; edición masiva de la decisión.
* **Regla de PVP por proveedor** (factor sobre precio de lista o sobre costo neto, PVP
  sugerido del proveedor, margen del artículo, mantener) con redondeo; las bajas de
  costo **no bajan el PVP** salvo que se decida (política por documento).
* **Aplicación programada**: fecha y hora por documento (sugerido: mañana 00:00). Al
  aplicar: actualiza el precio de lista del proveedor (con su regla de descuento →
  costo de reposición), el PVP de la red, y registra todo en el historial de precios
  con origen "Revisión de lista". Botón "Aplicar ahora" para urgencias.
* Las listas quedan guardadas (estado Aplicada) y sirven como catálogo del proveedor.

Autor: Trixocom.
""",
    "author": "Trixocom",
    "website": "https://www.trixocom.com",
    "license": "LGPL-3",
    "depends": [
        "purchase",
        "mail",
        "product_replenishment_cost",
        "product_planned_price",
        "trx_product_price_history",
    ],
    "external_dependencies": {"python": ["openpyxl"]},
    "data": [
        "security/ir.model.access.csv",
        "data/data.xml",
        "views/revision_views.xml",
        "views/revision_line_views.xml",
        "views/res_partner_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
}
