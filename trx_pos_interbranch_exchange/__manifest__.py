{
    "name": "POS - Cambio inter-sucursal (multi-compañía)",
    "version": "19.0.1.0.1",
    "category": "Sales/Point of Sale",
    "sequence": 8,
    "summary": "Cambio de productos en cualquier sucursal de la red aunque la venta "
    "original sea de otro CUIT: NC en la compañía que vendió, stock en la que "
    "recibe, y cuenta corriente entre compañías.",
    "description": """
Cambio inter-sucursal para redes de locales con varias razones sociales
(una compañía Odoo por CUIT) que comparten productos y clientes.

Flujo en el POS de la sucursal que toma el cambio (compañía B):

1. El cajero elige el medio de pago "Cambio inter-sucursal" y escanea o tipea
   el código del ticket de cambio (uuid o número de orden de la venta original).
2. El servidor busca la venta original (puede ser de OTRA compañía, A), valida
   la elegibilidad de cada línea (categoría del producto con el tilde "Acepta
   cambios inter-sucursal", override por producto, plazo en días, cantidad ya
   devuelta) y el cajero elige qué productos/cantidades toma.
3. El importe del cambio queda como pago de la venta nueva en B.
4. Al confirmar la venta en B, en la MISMA transacción:
   * Nota de crédito en A por los productos devueltos: fiscal (NC electrónica
     con CAE y comprobante asociado, vía account.move.reversal + l10n_ar_edi)
     si la venta original fue facturada; interna (diario de ventas sin
     documentos) si fue una venta NF.
   * Asiento de compensación en A que cancela el saldo a favor del cliente que
     deja la NC contra la cuenta corriente "Cambios inter-sucursal"
     (A le debe a B ese importe).
   * Ingreso del producto devuelto al depósito de B (devolución de cliente).
   * En B el pago se contabiliza al cierre de sesión en la misma cuenta
     corriente (B tiene a cobrar de A).
5. Todo lo que ocurre en A lo ejecuta el servidor con un usuario técnico: el
   cajero de B solo necesita el grupo "POS: cambio inter-sucursal", nunca
   acceso a la contabilidad de A. Cada cambio queda registrado (quién, cuándo,
   orden original, NC, picking, importes) para la compensación periódica
   entre compañías.

Autor: Trixocom.
""",
    "author": "Trixocom",
    "website": "https://www.trixocom.com",
    "license": "LGPL-3",
    "depends": [
        "point_of_sale",
        "stock",
        "account",
        "l10n_ar",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "data/ir_cron_data.xml",
        "views/trx_ibx_exchange_views.xml",
        "views/product_views.xml",
        "views/pos_payment_method_views.xml",
        "views/res_config_settings_views.xml",
        "views/pos_order_views.xml",
        "report/ticket_cambio_report.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "trx_pos_interbranch_exchange/static/src/app/**/*",
            "trx_pos_interbranch_exchange/static/src/overrides/**/*",
        ],
    },
    "installable": True,
    "application": False,
}
