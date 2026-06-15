{
    "name": "POS Promociones (descuento casa + reintegro banco)",
    "version": "19.0.1.0.2",
    "category": "Sales/Point of Sale",
    "sequence": 7,
    "summary": "Promociones en POS: descuento de la casa + reintegro del banco "
    "con nota de crédito fiscal automática",
    "description": """
Sistema de promociones para el Punto de Venta de Odoo 19 Community.

El cajero elige una **promoción** desde un botón del POS. Cada promoción define:

* **% de descuento de la casa**: se aplica sobre la orden como un descuento
  general (una única línea negativa etiquetada con el nombre de la promo).
  Es lo que el cliente paga de menos, de verdad.

* **% que devuelve el banco** (reintegro): NO se descuenta del total. Solo se
  **informa en el ticket**. La venta se cobra normalmente y se factura como
  comprobante fiscal (FA-A/B/C con CAE, vía `l10n_ar_pos_edi`).

* Inmediatamente después de la factura, y **dentro de la misma transacción**,
  se emite una **nota de crédito fiscal** (NC-A/B/C con CAE) por el importe de
  la devolución bancaria. Esto permite **no pagar el IVA** de esa devolución.
  **No se devuelve nada**: ni mercadería ni dinero. La NC es solo el contra-
  comprobante fiscal, asociado a la factura original (CbtesAsoc).

Reutiliza el motor de CAE de `l10n_ar_edi` (el `_post()` del move dispara la
solicitud de CAE) y la receta de NC vía el wizard `account.move.reversal`.

La base del reintegro (sobre total con IVA o sobre neto) y si la NC discrimina
IVA son **configurables por promoción**.
""",
    "author": "Trixocom",
    "website": "https://www.trixocom.com",
    "license": "LGPL-3",
    "depends": [
        "point_of_sale",
        "l10n_ar_pos_edi",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/pos_promotion_views.xml",
        "wizards/res_config_settings_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_promotions/static/src/**/*",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
