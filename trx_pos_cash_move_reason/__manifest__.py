{
    "name": "POS Cash In/Out Reasons",
    "version": "19.0.1.0.0",
    "category": "Sales/Point of Sale",
    "summary": "Motivos de ingreso/retiro de efectivo en POS con imputación directa a cuentas contables",
    "description": """
Motivos configurables para los ingresos y retiros de efectivo de la caja del
Punto de Venta. Cada motivo define la cuenta contable de contrapartida para el
ingreso y/o para el retiro, de modo que el movimiento se registra directamente
contra esa cuenta (gasto, depósito bancario, aporte, etc.) en lugar de quedar en
la cuenta transitoria del diario de efectivo pendiente de conciliar.

- Selector de motivo en el popup "Ingreso/Retiro de efectivo" del POS.
- Opción por punto de venta para exigir motivo.
- Motivos restringibles por compañía y por punto de venta.
- Ingreso/retiro desde la sesión en el backend (gestores).
- Reporte de movimientos de caja por motivo.
""",
    "author": "Trixocom",
    "website": "https://www.trixocom.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/pos_cash_move_reason_views.xml",
        "views/account_bank_statement_line_views.xml",
        "views/pos_session_views.xml",
        "views/res_config_settings_views.xml",
        "wizards/pos_cash_move_wizard_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "trx_pos_cash_move_reason/static/src/app/**/*",
        ],
        "web.assets_tests": [
            "trx_pos_cash_move_reason/static/tests/tours/**/*",
        ],
    },
    "installable": True,
}
