# Part of trx_pos_purchase_receipt. Author: Trixocom. License: LGPL-3.
import base64
import logging

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

PENDING_STATES = ("confirmed", "waiting", "assigned")


class StockPicking(models.Model):
    _inherit = "stock.picking"

    # ------------------------------------------------------------------
    # Helpers de seguridad: todo lo que pide el POS pasa por acá
    # ------------------------------------------------------------------
    @api.model
    def _trx_receipt_config(self, config_id):
        """Devuelve el pos.config (sudo) si el usuario actual puede recibir en él."""
        config = self.env["pos.config"].browse(int(config_id)).exists()
        if not config:
            raise UserError(_("El punto de venta no existe."))
        config.check_access("read")
        if not config.trx_receipt_enabled:
            raise UserError(_("La recepción de mercadería no está habilitada en %s.", config.name))
        if not self.env.user.has_group("trx_pos_purchase_receipt.group_pos_receipt"):
            raise AccessError(_("No tenés permiso para recibir mercadería en el POS."))
        if config.company_id not in self.env.user.company_ids:
            raise AccessError(_("No tenés acceso a la compañía de este punto de venta."))
        if not config.warehouse_id:
            raise UserError(_("El punto de venta %s no tiene depósito.", config.name))
        return config.sudo()

    @api.model
    def _trx_receipt_blind(self, config):
        return bool(
            config.trx_receipt_blind
            and not self.env.user.has_group("trx_pos_purchase_receipt.group_pos_receipt_see_expected")
        )

    @api.model
    def _trx_receipt_domain(self, config):
        return [
            ("picking_type_id.code", "=", "incoming"),
            ("picking_type_id.warehouse_id", "=", config.warehouse_id.id),
            ("company_id", "=", config.company_id.id),
            ("state", "in", PENDING_STATES),
            ("purchase_id", "!=", False),
        ]

    @api.model
    def _trx_receipt_picking(self, config, picking_id):
        picking = (
            self.sudo()
            .with_company(config.company_id)
            .search(self._trx_receipt_domain(config) + [("id", "=", int(picking_id))], limit=1)
        )
        if not picking:
            raise UserError(
                _("La recepción ya no está pendiente en este depósito (puede que la haya validado otra caja).")
            )
        return picking

    def _trx_receipt_moves(self):
        self.ensure_one()
        return self.move_ids.filtered(lambda m: m.state not in ("done", "cancel")).sorted(
            lambda m: (m.sequence, m.id)
        )

    def _trx_receipt_block_over(self):
        """stock_ux: 'Bloquear cantidades adicionales' en el tipo de operación."""
        self.ensure_one()
        ptype = self.picking_type_id
        return bool("block_additional_quantity" in ptype._fields and ptype.block_additional_quantity)

    def _trx_receipt_vendor(self):
        self.ensure_one()
        partner = self.purchase_id.partner_id or self.partner_id
        return partner | partner.commercial_partner_id

    # ------------------------------------------------------------------
    # API para el POS
    # ------------------------------------------------------------------
    @api.model
    def trx_pos_receipt_count(self, config_id):
        config = self._trx_receipt_config(config_id)
        return self.sudo().with_company(config.company_id).search_count(self._trx_receipt_domain(config))

    @api.model
    def trx_pos_receipt_pending(self, config_id):
        """Entradas pendientes de OC del depósito del punto de venta."""
        config = self._trx_receipt_config(config_id)
        blind = self._trx_receipt_blind(config)
        pickings = (
            self.sudo()
            .with_company(config.company_id)
            .search(self._trx_receipt_domain(config), order="scheduled_date asc, id asc")
        )
        result = []
        for picking in pickings:
            moves = picking._trx_receipt_moves()
            scanned = sum(moves.mapped("trx_pos_scanned_qty"))
            vals = {
                "id": picking.id,
                "name": picking.name,
                "purchase": picking.purchase_id.name or "",
                "partner": (picking.purchase_id.partner_id or picking.partner_id).display_name or "",
                "partner_ref": picking.purchase_id.partner_ref or "",
                "scheduled_date": fields.Datetime.to_string(picking.scheduled_date) if picking.scheduled_date else "",
                "is_backorder": bool(picking.backorder_id),
                "line_count": len(moves),
                "scanned": scanned,
                "in_progress": bool(scanned),
                "demand": False if blind else sum(moves.mapped("product_qty")),
            }
            result.append(vals)
        return result

    @api.model
    def trx_pos_receipt_load(self, config_id, picking_id):
        """Datos de una entrada para escanear. En modo ciego no se envía lo pedido."""
        config = self._trx_receipt_config(config_id)
        picking = self._trx_receipt_picking(config, picking_id)
        blind = self._trx_receipt_blind(config)
        vendors = picking._trx_receipt_vendor()
        lines = []
        for move in picking._trx_receipt_moves():
            product = move.product_id
            tmpl = product.product_tmpl_id
            sellers = tmpl.seller_ids.filtered(
                lambda s, p=product: (not s.product_id or s.product_id == p)
                and (not s.company_id or s.company_id == picking.company_id)
            )
            vendor_codes = [c for c in sellers.filtered(lambda s: s.partner_id in vendors).mapped("product_code") if c]
            other_codes = [
                c for c in sellers.filtered(lambda s: s.partner_id not in vendors).mapped("product_code") if c
            ]
            codes = [c for c in [product.barcode, product.default_code] + vendor_codes if c]
            lines.append(
                {
                    "move_id": move.id,
                    "product_id": product.id,
                    "name": product.name,
                    "default_code": product.default_code or "",
                    "barcode": product.barcode or "",
                    "vendor_code": vendor_codes[0] if vendor_codes else "",
                    "codes": list(dict.fromkeys(c.strip() for c in codes)),
                    "other_codes": list(dict.fromkeys(c.strip() for c in other_codes)),
                    "uom": product.uom_id.name,
                    "tracking": product.tracking != "none",
                    "demand": False if blind else move.product_qty,
                    "scanned": move.trx_pos_scanned_qty,
                }
            )
        return {
            "id": picking.id,
            "name": picking.name,
            # Lo decide el servidor: el POS puede tener la configuración vieja en caché
            "label_format": config.trx_receipt_label_format or "none",
            "purchase": picking.purchase_id.name or "",
            "partner": (picking.purchase_id.partner_id or picking.partner_id).display_name or "",
            "partner_ref": picking.purchase_id.partner_ref or "",
            "scheduled_date": fields.Datetime.to_string(picking.scheduled_date) if picking.scheduled_date else "",
            "blind": blind,
            "block_over": picking._trx_receipt_block_over(),
            "backorder_policy": picking.picking_type_id.create_backorder,
            "lines": lines,
        }

    def _trx_receipt_write_scanned(self, quantities):
        """quantities: {move_id: cantidad en la unidad del producto}"""
        self.ensure_one()
        moves = self._trx_receipt_moves()
        by_id = {m.id: m for m in moves}
        for move_id, qty in (quantities or {}).items():
            move = by_id.get(int(move_id))
            if not move:
                continue
            qty = max(float(qty or 0.0), 0.0)
            if move.product_id.uom_id.compare(qty, move.trx_pos_scanned_qty):
                move.trx_pos_scanned_qty = qty

    @api.model
    def trx_pos_receipt_save(self, config_id, picking_id, quantities):
        """Guarda el avance del escaneo (lo llama el POS mientras se escanea)."""
        config = self._trx_receipt_config(config_id)
        picking = self._trx_receipt_picking(config, picking_id)
        picking._trx_receipt_write_scanned(quantities)
        return True

    @api.model
    def trx_pos_receipt_identify(self, config_id, code):
        """Para avisar qué artículo es un código que no está en la recepción."""
        config = self._trx_receipt_config(config_id)
        code = (code or "").strip()
        if not code:
            return False
        Product = self.env["product.product"].sudo().with_company(config.company_id)
        product = Product.search(["|", ("barcode", "=", code), ("default_code", "=ilike", code)], limit=1)
        if not product:
            seller = (
                self.env["product.supplierinfo"]
                .sudo()
                .search([("product_code", "=ilike", code)], limit=1)
            )
            product = seller.product_id or seller.product_tmpl_id.product_variant_id
        return product.display_name if product else False

    @api.model
    def trx_pos_receipt_validate(self, config_id, picking_id, quantities, shortage=None, cashier=None):
        """Valida la entrada con lo escaneado.

        shortage: qué hacer si falta mercadería: 'backorder' (queda pendiente en una
        nueva entrada) o 'cancel' (no llega más). En recepción a ciegas siempre
        'backorder'.
        """
        config = self._trx_receipt_config(config_id)
        picking = self._trx_receipt_picking(config, picking_id)
        blind = self._trx_receipt_blind(config)
        picking._trx_receipt_write_scanned(quantities)
        moves = picking._trx_receipt_moves()

        tracked = moves.filtered(lambda m: m.product_id.tracking != "none" and m.trx_pos_scanned_qty)
        if tracked:
            raise UserError(
                _(
                    "Hay artículos con lote o número de serie (%s): esta recepción se valida desde el backend.",
                    ", ".join(tracked.product_id.mapped("display_name")),
                )
            )
        if all(m.product_id.uom_id.is_zero(m.trx_pos_scanned_qty) for m in moves):
            raise UserError(_("No hay nada escaneado en %s.", picking.name))

        diffs = []
        has_short = False
        for move in moves:
            cmp = move.product_id.uom_id.compare(move.trx_pos_scanned_qty, move.product_qty)
            if cmp:
                diffs.append((move, move.product_qty, move.trx_pos_scanned_qty))
                has_short = has_short or cmp < 0
        over = [(m, d, s) for m, d, s in diffs if s > d]
        if over and picking._trx_receipt_block_over():
            raise UserError(
                _(
                    "No se puede recibir más de lo pedido en %(picking)s: %(items)s. "
                    "Revisá lo escaneado o pedí al supervisor o gerente que corrija la orden de compra.",
                    picking=picking.name,
                    items=", ".join(m.product_id.display_name for m, _d, _s in over),
                )
            )
        if has_short:
            if blind:
                shortage = "backorder"
            elif shortage not in ("backorder", "cancel"):
                raise UserError(_("Faltan unidades: indicá si lo faltante queda pendiente o si no llega más."))

        for move in moves:
            qty = move.product_id.uom_id._compute_quantity(
                move.trx_pos_scanned_qty, move.product_uom, rounding_method="HALF-UP"
            )
            move.quantity = qty
            move.picked = True

        ctx = {"skip_backorder": True, "skip_sms": True, "skip_expired": True, "skip_immediate": True}
        if has_short and shortage == "cancel":
            ctx["picking_ids_not_to_backorder"] = picking.ids
        picking.with_context(**ctx).button_validate()

        if picking.state != "done":
            raise UserError(_("No se pudo validar %s.", picking.name))
        moves.write({"trx_pos_scanned_qty": 0.0})
        backorder = self.sudo().search([("backorder_id", "=", picking.id)], limit=1)
        self._trx_receipt_log(config, picking, diffs, shortage if has_short else None, backorder, cashier, blind)
        return {
            "id": picking.id,
            "name": picking.name,
            # Lo decide el servidor: el POS puede tener la configuración vieja en caché
            "label_format": config.trx_receipt_label_format or "none",
            "backorder": backorder.name or False,
            "short": has_short,
            "over": bool(over),
        }

    @api.model
    def trx_pos_receipt_labels(self, config_id, picking_id):
        """PDF (base64) con una etiqueta de precio por unidad recibida en la entrada."""
        config = self._trx_receipt_config(config_id)
        if config.trx_receipt_label_format in (False, "none"):
            raise UserError(_("Este punto de venta no imprime etiquetas al recibir."))
        domain = self._trx_receipt_domain(config)
        domain = [d for d in domain if d[0] not in ("state", "purchase_id")] + [
            ("state", "=", "done"),
            ("id", "=", int(picking_id)),
        ]
        picking = self.sudo().with_company(config.company_id).search(domain, limit=1)
        if not picking:
            raise UserError(_("No se encontró la recepción validada en este depósito."))
        moves = picking.move_ids.filtered(lambda m: m.state == "done" and m.quantity > 0)
        if not moves:
            raise UserError(_("%s no tiene unidades recibidas.", picking.name))
        Layout = self.env["product.label.layout"].sudo().with_company(config.company_id)
        wizard = Layout.create(
            {
                "print_format": config.trx_receipt_label_format,
                "product_ids": [(6, 0, moves.product_id.ids)],
                "move_ids": [(6, 0, moves.ids)],
                "move_quantity": "move",
                # Precio de la lista de la caja (p. ej. "Interior" = base + 10 %),
                # no el precio base del artículo. Sin lista: precio de venta.
                "pricelist_id": config.pricelist_id.id,
            }
        )
        xml_id, data = wizard._prepare_report_data()
        report = self.env.ref(xml_id).sudo()
        pdf, _type = (
            self.env["ir.actions.report"]
            .sudo()
            .with_company(config.company_id)
            ._render_qweb_pdf(report.report_name, moves.product_id.ids, data=data)
        )
        count = sum(int(q) for q in (data.get("quantity_by_product") or {}).values())
        return {
            "pdf": base64.b64encode(pdf).decode(),
            "filename": "Etiquetas %s.pdf" % picking.name.replace("/", "-"),
            "count": count,
        }

    @api.model
    def _trx_receipt_log(self, config, picking, diffs, shortage, backorder, cashier, blind):
        user = self.env.user
        who = user.name
        if cashier and cashier != user.name:
            who = _("%(cashier)s (usuario %(user)s)", cashier=cashier, user=user.name)
        body = Markup("<p>%s</p>") % _(
            "Recibido desde el POS %(pos)s por %(who)s%(blind)s.",
            pos=config.name,
            who=who,
            blind=_(" (recepción a ciegas)") if blind else "",
        )
        items = []
        for move, demand, scanned in diffs:
            uom = move.product_id.uom_id.name
            items.append(
                _(
                    "%(product)s: pedido %(demand)s, recibido %(scanned)s %(uom)s",
                    product=move.product_id.display_name,
                    demand=f"{demand:g}",
                    scanned=f"{scanned:g}",
                    uom=uom,
                )
            )
        if items:
            body += Markup("<p>%s</p><ul>%s</ul>") % (
                _("Diferencias con lo pedido:"),
                Markup("").join(Markup("<li>%s</li>") % i for i in items),
            )
        if shortage == "cancel":
            body += Markup("<p>%s</p>") % _("Lo faltante se informó como que no llega más (sin pendiente).")
        elif backorder:
            body += Markup("<p>%s</p>") % _("Lo faltante quedó pendiente en %s.", backorder.name)
        picking.message_post(body=body, subtype_xmlid="mail.mt_note")
        if picking.purchase_id:
            picking.purchase_id.message_post(
                body=Markup("<p><b>%s</b></p>") % picking.name + body,
                subtype_xmlid="mail.mt_note",
            )
