# odoo-pos-addons

Addons de Trixocom para el Punto de Venta de Odoo. Repo paraguas: en cada
subcarpeta vive un módulo independiente.

## Módulos

| Módulo | Versión | Resumen |
|---|---|---|
| `pos_financial_surcharge` | 19.0.1.0.0 | Recargo / descuento financiero por forma de pago en POS. Basado en `card_installment` de ADHOC. |

## Dependencias externas (submódulo)

El repo trae `ingadhoc/account-payment` como submódulo en `vendor/account-payment`,
del cual se usa el módulo `card_installment`. Para clonar con el submódulo:

```bash
git clone --recurse-submodules git@github.com:Trixocom/odoo-pos-addons.git
```

O si ya está clonado:

```bash
git submodule update --init --recursive
```

## addons_path en Odoo

Cuando deployás (vía `odoofly`), agregar al `addons_path`:

```
/.../odoo-pos-addons
/.../odoo-pos-addons/vendor/account-payment
```

De `vendor/account-payment` sólo se instala `card_installment` como
dependencia. Los demás módulos del repo de ADHOC (`account_payment_pro`,
`l10n_ar_payment_bundle`, etc.) NO se instalan a menos que se quieran usar
también.

## Convenciones

- Autor: Trixocom
- Licencia: LGPL-3
- Versionado: Odoo `M.0.X.Y.Z` (incrementar `X.Y.Z` con cada commit que cambie
  comportamiento).
