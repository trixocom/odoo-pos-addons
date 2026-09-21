{
    "name": "Reportes multi-compañía por razón social (CUIT)",
    "version": "19.0.1.0.0",
    "category": "Reporting",
    "sequence": 9,
    "summary": "Agrupar ventas, facturas y stock por razón social (compañía raíz / CUIT) "
    "en redes con muchas compañías y sucursales; vista 'Ventas por razón social y local'.",
    "description": """
Red de locales con varias razones sociales (una compañía Odoo raíz por CUIT) y
locales adicionales como sucursales (compañías con parent_id). La casa matriz
tiene acceso a todas las compañías y necesita ver la información agrupada por
CUIT además de por local.

Odoo no ofrece un campo agrupable "compañía raíz" en los reportes (root_id no
es almacenado). Este módulo agrega:

* Campo almacenado e indexado **Razón social (CUIT)** (`trx_root_company_id` =
  `company_id.root_id`) en pos.order, pos.order.line, pos.payment,
  account.move, account.move.line, account.payment, stock.picking, stock.move
  y stock.quant, con filtro "Mi razón social" y agrupación en las vistas de
  búsqueda correspondientes.
* La misma dimensión en los análisis estándar **Análisis de ventas POS**
  (report.pos.order) y **Análisis de facturas** (account.invoice.report).
* Vista SQL **Ventas por razón social y local** (`trx.mc.sales.report`):
  ventas POS confirmadas + facturas/NC de clientes que NO vienen del POS, por
  día, razón social (CUIT), local, punto de venta, producto y categoría, con
  cantidad, neto, total con impuestos y costo; pivot y gráfico bajo Punto de
  Venta → Informes. Base para el cruce de ventas por franquicia contra los
  informes de proveedores.

Autor: Trixocom.
""",
    "author": "Trixocom",
    "website": "https://www.trixocom.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale", "account", "stock"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/search_views.xml",
        "views/trx_mc_sales_report_views.xml",
    ],
    "installable": True,
    "application": False,
}
