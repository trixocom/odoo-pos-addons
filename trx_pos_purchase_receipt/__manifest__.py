{
    "name": "POS - Recepción de mercadería (OC pendientes)",
    "version": "19.0.1.1.0",
    "category": "Sales/Point of Sale",
    "summary": "Recibir desde el POS las entradas (WH/IN) pendientes de las órdenes de compra, "
    "leyendo códigos de barras, al estilo de la app Barcode.",
    "description": """
Recepción de mercadería desde el Punto de Venta (Odoo 19 Community).

Las órdenes de compra se cargan en el backend. Al confirmarlas, Odoo deja la entrada
(WH/IN) pendiente en el depósito del local. Desde el POS:

* Botón **Recepciones** arriba a la izquierda (junto a Órdenes) con la cantidad de
  entradas pendientes del depósito del punto de venta.
* Lista de pendientes (proveedor, OC, referencia del proveedor, fecha, avance) con
  buscador.
* Pantalla de escaneo: cada lectura suma una unidad al artículo. Se busca por código
  de barras, código interno (alfa) o código del proveedor de la OC. También se puede
  tipear el código o tocar la línea para cargar la cantidad.
* El avance se guarda en el servidor mientras se escanea (se puede seguir después o
  desde otra caja).
* Al validar, si faltan unidades se pregunta: dejar el resto pendiente (nueva
  entrada) o "no llega más" (se cancela el saldo). Si sobran, se pide confirmación.
* Recepción a ciegas opcional por punto de venta: quien no tiene el permiso
  "Ver cantidades pedidas" no ve lo pedido (el servidor no lo envía); lo faltante
  queda siempre pendiente y las diferencias se registran en la entrada.
* Al validar ofrece imprimir las **etiquetas de precio** de lo recibido (una por
  unidad), en el formato elegido por punto de venta (térmica 50 x 25 mm u hoja A4).
* El cajero no necesita permisos de Inventario ni de Compras: el servidor valida el
  permiso "Recibir mercadería en el POS", el depósito del punto de venta y registra
  quién recibió (usuario y empleado del POS) en la entrada y en la OC.

Autor: Trixocom.
""",
    "author": "Trixocom",
    "website": "https://www.trixocom.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale", "purchase_stock", "trx_product_price_label"],
    "data": [
        "security/security.xml",
        "views/res_config_settings_views.xml",
        "views/stock_picking_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "trx_pos_purchase_receipt/static/src/app/**/*",
        ],
    },
    "installable": True,
    "application": False,
}
