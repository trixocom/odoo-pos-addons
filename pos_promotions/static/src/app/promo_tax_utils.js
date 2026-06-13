/** @odoo-module */
import { accountTaxHelpers } from "@account/helpers/account_tax";

/**
 * Calcula el priceIncluded (total con impuestos) de una baseLine con un
 * price_unit dado y el set de impuestos del producto.
 */
function _computeInclWithPriceUnit(pos, priceUnit, taxes, company) {
    const baseLine = accountTaxHelpers.prepare_base_line_for_taxes_computation(
        {},
        {
            tax_ids: taxes,
            quantity: 1,
            price_unit: priceUnit,
            currency_id: pos.currency,
        }
    );
    accountTaxHelpers.add_tax_details_in_base_line(baseLine, company);
    accountTaxHelpers.round_base_lines_tax_details([baseLine], company);
    return baseLine.tax_details.total_included_currency;
}

/**
 * Devuelve el price_unit (sin impuesto) tal que el total INCLUIDO de una
 * orderline de qty=1 sea lo más cercano posible a `targetIncl` (que puede ser
 * negativo, p.ej. un descuento). En Odoo 19 `compute_price_force_price_include`
 * ya no existe: usamos `accountTaxHelpers` + refinamiento fino en la grilla del
 * `currency.rounding` para minimizar el error de centavos.
 *
 * Misma lógica probada en pos_financial_surcharge (_priceUnitFromInclTotal).
 */
export function priceUnitFromInclTotal(pos, targetIncl, product) {
    const company = pos.company;
    const taxes = (product.taxes_id || []).filter(
        (t) => !t.company_id || t.company_id.id === company.id
    );
    if (!taxes.length) {
        return targetIncl;
    }
    const taxesAddingUp = taxes.filter((t) => !t.price_include);
    if (!taxesAddingUp.length) {
        return targetIncl;
    }
    const inclWithTarget = _computeInclWithPriceUnit(pos, targetIncl, taxes, company);
    if (!inclWithTarget) {
        return targetIncl;
    }
    let bestPu = (targetIncl * targetIncl) / inclWithTarget;

    const rounding = pos.currency?.rounding || 0.01;
    const roundedPu = Math.round(bestPu / rounding) * rounding;
    let bestDiff = Number.POSITIVE_INFINITY;
    let bestRefined = roundedPu;
    for (let step = -2; step <= 2; step += 1) {
        const testPu = roundedPu + step * rounding;
        const incl = _computeInclWithPriceUnit(pos, testPu, taxes, company);
        if (incl === undefined || incl === null) {
            continue;
        }
        const diff = Math.abs(incl - targetIncl);
        if (diff < bestDiff) {
            bestDiff = diff;
            bestRefined = testPu;
        }
    }
    return bestRefined;
}
