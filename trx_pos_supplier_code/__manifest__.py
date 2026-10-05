{
    "name": "POS - Búsqueda por código de proveedor",
    "version": "19.0.1.0.0",
    "category": "Sales/Point of Sale",
    "summary": "Busca productos en el POS (y en el backend) por los códigos de artículo de sus proveedores.",
    "description": """
Un mismo artículo (mismo código interno y mismo código de barras) puede tener un
código distinto en cada proveedor, y en el local muchas veces se vende tipeando
ese código.

* Campo ``trx_supplier_codes`` en el producto: todos los códigos de proveedor
  (pestaña Compras → proveedores → código del producto del proveedor), guardado
  e indexado.
* POS: la búsqueda de productos encuentra el artículo por cualquiera de esos
  códigos, tanto en los productos cargados como en la búsqueda en el servidor.
* Backend: los buscadores de productos (plantillas y variantes) aceptan el
  código de proveedor.

Autor: Trixocom.
""",
    "author": "Trixocom",
    "website": "https://www.trixocom.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": ["views/product_views.xml"],
    "assets": {
        "point_of_sale._assets_pos": ["trx_pos_supplier_code/static/src/app/**/*"],
    },
    "installable": True,
    "application": False,
}
