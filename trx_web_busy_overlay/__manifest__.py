{
    "name": "Web - Indicador de proceso en pantalla (Trixocom)",
    "version": "19.0.1.0.0",
    "category": "Hidden/Tools",
    "summary": "Overlay visual (barra horizontal animada, título, detalle y tiempo transcurrido) mientras corre una acción "
    "larga: lectura con IA, importaciones, consultas a servicios externos. Se activa desde cualquier botón de vista "
    "con context={'trx_busy': 'Título'} o desde JS con el servicio trx_busy.",
    "description": """
Indicador de proceso en pantalla
================================

Cualquier botón de una vista puede mostrar el overlay mientras corre su acción::

    <button name="action_scan" type="object" string="Leer factura"
            context="{'trx_busy': 'Leyendo la factura con IA', 'trx_busy_sub': 'Puede tardar hasta un minuto.'}"/>

Desde JavaScript::

    const busy = useService("trx_busy");
    await busy.run(() => rpc(...), "Importando artículos", {subtitle: "No cierres la pestaña."});

Autor: Trixocom.
""",
    "author": "Trixocom",
    "website": "https://www.trixocom.com",
    "license": "LGPL-3",
    "depends": ["web"],
    "assets": {
        "web.assets_backend": [
            "trx_web_busy_overlay/static/src/busy_service.js",
            "trx_web_busy_overlay/static/src/busy_overlay.js",
            "trx_web_busy_overlay/static/src/busy_overlay.xml",
            "trx_web_busy_overlay/static/src/busy_overlay.scss",
        ],
    },
    "installable": True,
    "application": False,
}
