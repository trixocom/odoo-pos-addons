# odoo-pos-addons

Addons de Trixocom para el Punto de Venta de Odoo. Repo paraguas: en cada
subcarpeta vive un módulo independiente.

## Módulos

| Módulo | Versión | Resumen |
|---|---|---|
| `pos_financial_surcharge` | 19.0.1.1.0 | Recargo / descuento financiero por forma de pago en POS. Basado en `card_installment` de ADHOC. |

## Dependencia externa

`pos_financial_surcharge` depende de `card_installment`, que vive en
[`ingadhoc/account-payment`](https://github.com/ingadhoc/account-payment).
En el flow de odoofly el repo se agrega aparte al proyecto vía
`of repo add https://github.com/ingadhoc/account-payment.git --branch 19.0`,
no hace falta clonar submódulo desde acá.

## addons_path en Odoo

Cuando deployás (vía `odoofly`), agregar al `addons_path`:

```
/.../odoo-pos-addons
/.../account-payment
```

De `account-payment` sólo se instala `card_installment` como
dependencia. Los demás módulos del repo de ADHOC (`account_payment_pro`,
`l10n_ar_payment_bundle`, etc.) NO se instalan a menos que se quieran usar
también.

## Convenciones

- Autor: Trixocom
- Licencia: LGPL-3
- Versionado: Odoo `M.0.X.Y.Z` (incrementar `X.Y.Z` con cada commit que cambie
  comportamiento).

## Notas técnicas — pos_financial_surcharge

### Cálculo del recargo con impuestos

En Odoo 19 la función `compute_price_force_price_include` de Odoo 18 ya no
existe. El módulo usa `accountTaxHelpers` de `@account/helpers/account_tax`
y un loop iterativo (`_priceUnitFromInclTotal`) para encontrar el
`price_unit` que mejor aproxime el `priceIncluded` deseado dentro de la
grilla del `currency.rounding`.

### Redondeo en descuentos — decisión de diseño

Cuando el delta del descuento dividido por `(1 + rate)` no cae en la grilla
del `currency.rounding`, **es matemáticamente imposible** que el
`priceIncluded` de la línea matchee exactamente el monto "ideal" del plan.

**Ejemplo**: base $1.000 + IVA 21% = $1.210, descuento 10% sobre $1.000
→ delta deseado = −$100, pero ningún `price_unit` con 2 decimales produce
`priceIncluded = −$100,00` (los más cercanos son −$82,64 → −$99,99 y
−$82,65 → −$100,01).

**Decisión**: aceptar la diferencia de 1 centavo. El `payment_line.amount`
se ajusta a la **realidad de la línea** (`rawAmount + priceIncl real`), no
al monto ideal del plan. Por lo tanto la orden siempre cuadra
contablemente — el cliente paga el monto real, que puede diferir en
$0,01 del cálculo teórico del plan.

Si se necesita evitar este centavo, las alternativas son:
- Configurar `cash_rounding` en el POS para forzar redondeo de pagos.
- Usar bases imponibles donde el delta cierre exacto en la grilla
  (lo más común en pesos argentinos: $1.210, $2.420, etc.).
