/** @odoo-module */
import { register_payment_method } from "@point_of_sale/app/services/pos_store";
import { FinancialSurcharge } from "@pos_financial_surcharge/app/financial_surcharge";

register_payment_method("financial_surcharge", FinancialSurcharge);
