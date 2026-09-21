/** @odoo-module */
import { register_payment_method } from "@point_of_sale/app/services/pos_store";
import { InterbranchExchange } from "@trx_pos_interbranch_exchange/app/ibx_payment";

register_payment_method("interbranch_exchange", InterbranchExchange);
