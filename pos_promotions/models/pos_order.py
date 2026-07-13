import logging

from odoo import api, fields, models
from odoo.tools import float_round

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = "pos.order"

    promotion_id = fields.Many2one(
        "pos.promotion",
        string="Promoción aplicada",
        help="Promoción elegida en el POS para esta orden.",
    )
    promotion_pos_id = fields.Integer(
        string="Promo (id POS)",
        copy=False,
        help="ID de la promoción enviado desde el POS. Campo escalar (no "
        "relacional) para el round-trip frontend→backend; se mapea a "
        "promotion_id al crear la orden.",
    )
    promo_bank_pct = fields.Float(
        string="Devolución banco (%)",
        digits=(16, 4),
        help="Porcentaje de reintegro del banco vigente al momento de la venta.",
    )
    promo_bank_amount = fields.Monetary(
        string="Importe devolución banco",
        currency_field="currency_id",
        help="Importe de la devolución bancaria informado en el ticket. Es el "
        "importe por el que se emite la nota de crédito fiscal.",
    )
    promo_bank_nc_id = fields.Many2one(
        "account.move",
        string="NC devolución bancaria",
        readonly=True,
        copy=False,
        help="Nota de crédito fiscal emitida por el importe de la devolución "
        "bancaria de la promoción.",
    )

    # NO override de _load_pos_data_fields en pos.order: el default del mixin
    # devuelve [] y `read([])` carga TODOS los campos. `promotion_pos_id` es
    # stored, así que ya viaja al POS solo. Si lo overrideábamos devolviendo una
    # lista, el POS cargaba SOLO esos campos y se perdían `lines`/`partner_id`/...
    # → `this.lines` undefined → crash en `_computeAllPrices`.

    def _process_order(self, order, existing_order):
        order_id = super()._process_order(order, existing_order)
        rec = self.browse(order_id)
        if rec.promotion_pos_id and not rec.promotion_id:
            promo = self.env["pos.promotion"].browse(rec.promotion_pos_id).exists()
            if promo:
                rec.promotion_id = promo.id
        return order_id

    # ------------------------------------------------------------------
    # Generación de la factura + NC de devolución bancaria
    # ------------------------------------------------------------------
    def _generate_pos_order_invoice(self):
        """Tras emitir la factura fiscal (con CAE), si la orden tiene una promo
        con reintegro bancario, emite la NC fiscal por ese importe.

        Todo ocurre dentro de la misma transacción de ``sync_from_ui`` /
        invoicing: factura fiscal + nota de crédito fiscal asociada.
        """
        invoice = super()._generate_pos_order_invoice()
        # self es singleton en este método (igual que el core).
        try:
            self._promo_create_bank_credit_note(invoice)
        except Exception:  # noqa: BLE001
            # NUNCA propagar: la factura ya tiene CAE (legalmente emitida) y un
            # raise haría rollback de un comprobante ya autorizado por AFIP.
            # Se loguea para reintento manual; la venta queda correcta, solo
            # falta el contra-comprobante fiscal de la devolución.
            _logger.exception(
                "[pos_promotions] No se pudo emitir la NC de devolución bancaria "
                "para la orden %s (factura %s). Reintentar manualmente.",
                self.display_name,
                invoice.name,
            )
        return invoice

    def _promo_iva_rate(self, product):
        """Tasa de IVA (ej.: 0.21) de los impuestos NO incluidos en precio del
        producto de descuento de la compañía. 0.0 si no hay."""
        company = self.company_id or self.env.company
        taxes = product.taxes_id.filtered(
            lambda t: t.company_id == company
            and t.amount_type == "percent"
            and not t.price_include
        )
        return sum(taxes.mapped("amount")) / 100.0

    def _promo_create_bank_credit_note(self, invoice):
        """Crea y postea la NC fiscal por el importe de la devolución bancaria.

        - NO registra pago ni movimiento de stock (no se devuelve plata ni
          mercadería): la NC es solo el contra-comprobante fiscal.
        - Se asocia a la factura original (``reversed_entry_id``) para el
          ``CbtesAsoc`` que exige AFIP en NC.
        - El ``action_post()`` dispara la solicitud de CAE vía ``l10n_ar_edi``.
        """
        self.ensure_one()
        promo = self.promotion_id
        if not promo or promo.bank_discount_pct <= 0:
            return False
        if not invoice or invoice.move_type != "out_invoice":
            return False
        if invoice.company_id.country_id.code != "AR":
            return False
        # NO exigimos CAE en la factura origen. En modo electrónico (AFIP), el
        # `action_post()` de la NC pide el CAE solo y adjunta el CbtesAsoc a la
        # factura via `reversed_entry_id`. En modo no-AFIP (diario simple), la NC
        # se postea sin CAE. En ambos casos la NC DEBE emitirse: es el
        # contra-comprobante que evita pagar el IVA de lo que devuelve el banco.
        if not invoice.l10n_ar_afip_auth_code:
            _logger.info(
                "[pos_promotions] Factura %s sin CAE (modo no electrónico): se "
                "emite igual la NC de devolución bancaria, sin CAE.",
                invoice.name,
            )
        if self.promo_bank_nc_id:
            # Idempotencia: ya se emitió.
            return self.promo_bank_nc_id

        company = invoice.company_id
        product = company.pos_promo_discount_product_id
        if not product:
            _logger.warning(
                "[pos_promotions] La compañía %s no tiene 'Producto para "
                "descuento de promoción' configurado: no se emite NC.",
                company.display_name,
            )
            return False

        rounding = invoice.currency_id.rounding or 0.01
        rate = self._promo_iva_rate(product)
        pct = promo.bank_discount_pct / 100.0

        # Importe de la devolución bancaria (lo que el banco reintegra).
        if promo.bank_base == "untaxed":
            base = invoice.amount_untaxed
        else:
            base = invoice.amount_total
        reintegro = float_round(base * pct, precision_rounding=rounding)
        if reintegro <= 0:
            return False

        with_iva = promo.bank_nc_with_iva
        if with_iva and promo.bank_base == "total_incl" and rate:
            # reintegro es importe con IVA incluido -> neteamos para que el
            # total de la NC (neto + IVA) iguale el reintegro.
            net = float_round(reintegro / (1.0 + rate), precision_rounding=rounding)
            taxes = product.taxes_id
        elif with_iva:
            # base neta: el reintegro ya es neto, el IVA se suma encima.
            net = reintegro
            taxes = product.taxes_id
        else:
            # NC sin IVA.
            net = reintegro
            taxes = self.env["account.tax"]

        # --- Crear la NC vía el wizard (asigna doc_type NC-A/B/C + CbtesAsoc) ---
        # Llamar _reverse_moves directo deja l10n_latam_document_type como
        # 'invoice' y revienta. El wizard elige el NC correcto.
        company_ctx = self.env(context=dict(self.env.context, allowed_company_ids=[company.id]))
        wiz = (
            company_ctx["account.move.reversal"]
            .with_context(
                active_model="account.move",
                active_ids=invoice.ids,
                active_id=invoice.id,
            )
            .create(
                {
                    "journal_id": invoice.journal_id.id,
                    "reason": "Devolución bancaria - Promo %s (%s%%)"
                    % (promo.name, promo.bank_discount_pct),
                    "date": fields.Date.context_today(self),
                    "move_ids": [(6, 0, invoice.ids)],
                }
            )
        )
        res = wiz.refund_moves()
        nc_id = res.get("res_id") if isinstance(res, dict) else False
        if not nc_id and wiz.new_move_ids:
            nc_id = wiz.new_move_ids[:1].id
        nc = company_ctx["account.move"].browse(nc_id)

        # Reemplazar las líneas del reverso por una única línea de reintegro:
        # NO es una devolución de la mercadería, es solo el importe bancario.
        nc.write(
            {
                "invoice_line_ids": [(5, 0, 0)]
                + [
                    (
                        0,
                        0,
                        {
                            "product_id": product.id,
                            "name": "Reintegro bancario - Promo %s (%s%%)"
                            % (promo.name, promo.bank_discount_pct),
                            "quantity": 1.0,
                            "price_unit": net,
                            "tax_ids": [(6, 0, taxes.ids)],
                        },
                    )
                ],
            }
        )

        # Postear -> dispara CAE (WSFEv1) con CbtesAsoc a la factura original.
        nc.sudo().with_company(company).action_post()

        self.promo_bank_nc_id = nc.id
        self.promo_bank_pct = promo.bank_discount_pct
        self.promo_bank_amount = reintegro
        _logger.info(
            "[pos_promotions] NC de devolución bancaria %s emitida (CAE %s) por "
            "%s contra factura %s.",
            nc.name,
            nc.l10n_ar_afip_auth_code,
            nc.amount_total,
            invoice.name,
        )
        return nc

    def action_promo_retry_bank_credit_note(self):
        """Reintento manual de la NC de devolución bancaria (si falló en la
        venta, p.ej. AFIP caído)."""
        for order in self:
            invoice = order.account_move.filtered(
                lambda m: m.move_type == "out_invoice"
            )[:1]
            if invoice:
                order._promo_create_bank_credit_note(invoice)
        return True
