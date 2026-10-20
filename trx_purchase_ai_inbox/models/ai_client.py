# Part of trx_purchase_ai_inbox. Author: Trixocom. License: LGPL-3.
"""Cliente mínimo de la API de Anthropic (Messages) para leer facturas de proveedor.

La salida se fuerza con una herramienta (tool use) con esquema JSON: cabecera fija, líneas con
campos abiertos (EAN13 si está impreso, código del proveedor, descuentos de línea), descuentos
globales al pie, otros cargos y percepciones. Sin API key o sin red, levanta UserError.
"""
import base64
import io
import json
import re
import logging
import zipfile

import requests

from lxml import etree

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5-5"

TOOL_NAME = "registrar_factura"
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "proveedor": {
            "type": "object",
            "properties": {
                "razon_social": {"type": "string"},
                "cuit": {"type": "string", "description": "Sólo dígitos, 11, tal como está impreso (sin guiones)."},
                "condicion_iva": {"type": "string"},
            },
        },
        "receptor": {
            "type": "object",
            "properties": {"razon_social": {"type": "string"}, "cuit": {"type": "string"}},
        },
        "comprobante": {
            "type": "object",
            "properties": {
                "tipo": {"type": "string", "description": "FACTURA, NOTA DE CREDITO, NOTA DE DEBITO, REMITO, PRESUPUESTO u otro."},
                "letra": {"type": "string", "description": "A, B, C, M, E o vacío."},
                "punto_venta": {"type": "string", "description": "Dígitos del punto de venta, p. ej. 00006."},
                "numero": {"type": "string", "description": "Dígitos del número, p. ej. 00038359."},
                "fecha": {"type": "string", "description": "YYYY-MM-DD."},
                "vencimiento": {"type": "string", "description": "YYYY-MM-DD o vacío."},
                "cae": {"type": "string"},
                "cae_vencimiento": {"type": "string", "description": "YYYY-MM-DD o vacío."},
                "moneda": {"type": "string", "description": "ARS, USD… (ARS si no dice)."},
                "condicion_venta": {"type": "string"},
                "orden_compra": {"type": "string"},
            },
        },
        "lineas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "codigo_proveedor": {"type": "string", "description": "Código del artículo según el proveedor, tal cual impreso."},
                    "ean": {"type": "string", "description": "Código de barras EAN-13/EAN-8/UPC impreso en la línea (sólo dígitos). Vacío si no hay."},
                    "descripcion": {"type": "string"},
                    "cantidad": {"type": "number"},
                    "unidad": {"type": "string"},
                    "precio_unitario": {"type": "number", "description": "Precio unitario impreso, sin IVA si la factura es A; con IVA si es B/C."},
                    "descuento_linea_pct": {"type": "number", "description": "Descuento de la línea en %, 0 si no hay."},
                    "importe_linea": {"type": "number", "description": "Importe de la línea impreso (después del descuento de línea), sin IVA si es A."},
                    "alicuota_iva": {"type": "number", "description": "Alícuota de IVA de la línea en % (21, 10.5, 27, 0). Si la factura es B o C y no discrimina, 21 salvo que diga otra cosa."},
                    "extra": {"type": "string", "description": "Otros datos impresos en la línea (marca, bulto, origen, etc.)."},
                    "texto_original": {"type": "string", "description": "La línea tal como está impresa."},
                },
                "required": ["descripcion", "cantidad", "precio_unitario"],
            },
        },
        "descuentos_globales": {
            "type": "array",
            "description": "Descuentos o bonificaciones aplicados al pie sobre el total o el subtotal (no los de línea).",
            "items": {
                "type": "object",
                "properties": {
                    "descripcion": {"type": "string"},
                    "porcentaje": {"type": "number", "description": "% si está expresado en %, si no 0."},
                    "importe": {"type": "number", "description": "Importe en pesos (positivo) si está impreso, si no 0."},
                },
            },
        },
        "otros_cargos": {
            "type": "array",
            "description": "Flete, embalaje, intereses u otros cargos al pie que no son artículos.",
            "items": {"type": "object", "properties": {"descripcion": {"type": "string"}, "importe": {"type": "number"}}},
        },
        "percepciones": {
            "type": "array",
            "description": "Percepciones o retenciones impresas (IVA, Ganancias, IIBB por provincia, municipales). Una por renglón impreso.",
            "items": {
                "type": "object",
                "properties": {
                    "descripcion": {"type": "string", "description": "Texto impreso tal cual (p. ej. 'Perc. IIBB Bs. As. 3%')."},
                    "tipo": {"type": "string", "enum": ["iva", "ganancias", "iibb", "municipal", "otro"]},
                    "jurisdiccion": {"type": "string", "description": "Provincia o CABA si es IIBB; vacío si no corresponde."},
                    "alicuota": {"type": "number", "description": "Alícuota en % si está impresa, si no 0."},
                    "base": {"type": "number", "description": "Base imponible impresa, si está, si no 0."},
                    "importe": {"type": "number"},
                },
                "required": ["descripcion", "importe"],
            },
        },
        "totales": {
            "type": "object",
            "properties": {
                "neto_gravado": {"type": "number"},
                "neto_no_gravado": {"type": "number"},
                "exento": {"type": "number"},
                "iva": {"type": "number"},
                "percepciones": {"type": "number"},
                "total": {"type": "number"},
            },
        },
        "observaciones": {"type": "string", "description": "Dudas de lectura, datos ilegibles, inconsistencias."},
    },
    "required": ["proveedor", "comprobante", "lineas", "totales"],
}

SYSTEM_PROMPT = """Sos un asistente de Compras de una cadena de jugueterías en Argentina. Leés facturas de proveedores \
(PDF o foto) y devolvés los datos SIEMPRE llamando a la herramienta registrar_factura (nunca como texto), con estas reglas:
- En comprobante.tipo poné lo que dice el documento: FACTURA, NOTA DE CRÉDITO, NOTA DE DÉBITO, REMITO, PRESUPUESTO, \
SOLICITUD DE PEDIDO, PROFORMA, etc. Si es un Word o texto plano, leelo igual que una factura impresa.
- Transcribí sólo lo que está impreso. Lo que no está, queda vacío o en 0. No inventes códigos, EAN ni importes.
- Los números van como número (12345.67), sin separador de miles; el punto es el decimal.
- CUIT: sólo dígitos. Fechas: YYYY-MM-DD.
- Una línea por artículo facturado. Si la línea tiene un código de barras (8, 12 o 13 dígitos) ponelo en ean; \
el código interno del proveedor va en codigo_proveedor. No confundas uno con otro.
- Si la factura aplica una bonificación o descuento al pie (por ejemplo "Bonificación 10%" sobre el subtotal), \
cargalo en descuentos_globales y NO lo apliques a las líneas: las líneas van con su precio impreso.
- Si una línea trae su propio descuento, ponelo en descuento_linea_pct.
- En facturas A los precios son sin IVA; en B o C son finales. Decilo en alicuota_iva como corresponda.
- Flete, embalaje, intereses u otros cargos van en otros_cargos.
- Las percepciones o retenciones (IVA, Ganancias, IIBB de una provincia o CABA, municipales) van en percepciones, \
una por renglón, con su tipo y jurisdicción; nunca como línea de artículo. Su importe se suma al total pero no al neto ni al IVA.
- En observaciones anotá cualquier cosa ilegible o inconsistente (p. ej. la suma de líneas no coincide con el subtotal)."""


class TrxPurchaseAiClient(models.AbstractModel):
    _name = "trx.purchase.ai.client"
    _description = "Cliente IA para facturas de proveedor"

    def _config(self):
        icp = self.env["ir.config_parameter"].sudo()
        key = icp.get_param("trx_purchase_ai_inbox.api_key")
        model = icp.get_param("trx_purchase_ai_inbox.model") or DEFAULT_MODEL
        if not key:
            raise UserError(_("Falta la API key de Anthropic (Compras → Configuración → Ajustes → Facturas escaneadas)."))
        return key, model

    IMAGE_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}
    WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    def _docx_to_text(self, data):
        """Texto de un .docx (párrafos y tablas, sin dependencias): las tablas van como filas con ' | '."""
        w = "{%s}" % self.WORD_NS
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            root = etree.fromstring(z.read("word/document.xml"))
            images = []
            for name in z.namelist():
                ext = name.lower().rsplit(".", 1)[-1]
                if name.startswith("word/media/") and ext in self.IMAGE_TYPES and len(images) < 10:
                    raw = z.read(name)
                    if 0 < len(raw) <= 5 * 1024 * 1024:
                        images.append({"type": "image", "source": {"type": "base64", "media_type": self.IMAGE_TYPES[ext], "data": base64.b64encode(raw).decode()}})

        def para_text(p):
            parts = []
            for node in p.iter():
                if node.tag == w + "t":
                    parts.append(node.text or "")
                elif node.tag == w + "tab":
                    parts.append("\t")
                elif node.tag in (w + "br", w + "cr"):
                    parts.append("\n")
            return "".join(parts)

        lines = []
        body = root.find(w + "body")
        for el in (body if body is not None else root):
            if el.tag == w + "p":
                lines.append(para_text(el))
            elif el.tag == w + "tbl":
                for tr in el.iter(w + "tr"):
                    cells = []
                    for tc in tr.findall(w + "tc"):
                        cells.append(" ".join(para_text(p) for p in tc.findall(w + "p")).strip())
                    lines.append(" | ".join(cells))
                lines.append("")
        text = "\n".join(lines).strip()
        return text, images

    @staticmethod
    def _doc_to_text(data):
        """Texto de un Word 97-2003 (.doc) sin dependencias. El texto está en el archivo como UTF-16LE o cp1252;
        se toman las corridas legibles de las dos codificaciones y se queda la que más letras/dígitos ASCII aporta.
        Los fines de celda de tabla de Word (0x07) se convierten en ' | ' para conservar las columnas."""
        chars = rb"\x20-\x7E\xA0-\xFE\t\r\n\x07\x0b\x0c"
        runs16 = [m.group(0).decode("utf-16-le", "ignore") for m in re.finditer(rb"(?:[" + chars + rb"]\x00){4,}", data)]
        runs8 = [m.group(0).decode("cp1252", "ignore") for m in re.finditer(rb"[" + chars + rb"]{4,}", data)]

        def score(txt):
            return sum(1 for c in txt if c.isascii() and c.isalnum())

        def clean(runs):
            out = []
            for r in runs:
                r = r.replace("\x07", " | ").replace("\r", "\n").replace("\x0b", "\n").replace("\x0c", "\n").strip()
                dense = len("".join(r.split()))  # sin espacios: las columnas alineadas con espacios no penalizan
                if len(r) >= 4 and score(r) >= max(3, dense * 0.5):
                    out.append(r)
            return out

        a, b = clean(runs8), clean(runs16)
        best = b if sum(map(score, b)) >= sum(map(score, a)) else a
        return "\n".join(best)

    def _document_blocks(self, data_b64, mimetype, filename):
        """Bloques de contenido para la API según el tipo de archivo: PDF, imagen o Word (.docx)."""
        mimetype = (mimetype or "").lower()
        ext = (filename or "").lower().rsplit(".", 1)[-1]
        if mimetype == "application/pdf" or ext == "pdf":
            return [{"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data_b64}}]
        if mimetype in self.IMAGE_TYPES.values() or ext in self.IMAGE_TYPES:
            mt = mimetype if mimetype.startswith("image/") else self.IMAGE_TYPES[ext]
            return [{"type": "image", "source": {"type": "base64", "media_type": mt, "data": data_b64}}]
        if ext == "docx" or mimetype == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            try:
                text, images = self._docx_to_text(base64.b64decode(data_b64))
            except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError) as e:
                raise UserError(_("No se pudo leer el Word %s: %s", filename, e)) from e
            if not text and not images:
                raise UserError(_("El Word %s no tiene texto ni imágenes.", filename))
            blocks = []
            if text:
                blocks.append({"type": "text", "text": _("Contenido del documento Word '%s' (texto extraído; las tablas van fila por fila con ' | ' entre columnas):\n\n%s", filename, text[:200000])})
            blocks.extend(images)
            return blocks
        if ext == "doc" or mimetype == "application/msword":
            text = self._doc_to_text(base64.b64decode(data_b64))
            if len(text) < 20:
                raise UserError(_("No se pudo extraer texto del Word %s: guardalo como .docx o PDF y volvé a subirlo.", filename))
            return [{"type": "text", "text": _("Contenido del documento Word 97-2003 '%s' (texto extraído; el formato se pierde, las celdas de tabla van separadas por ' | '):\n\n%s", filename, text[:200000])}]
        raise UserError(_("Formato no soportado: %s. Subí un PDF, una foto (JPG/PNG) o un Word (.docx).", filename))

    def extract_invoice(self, data_b64, mimetype, filename, extra_hint=""):
        """Devuelve (dict con el esquema registrar_factura, info de uso)."""
        key, model = self._config()
        content = self._document_blocks(data_b64, mimetype, filename) + [{
            "type": "text",
            "text": "Leé esta factura de proveedor y registrala con la herramienta registrar_factura." + (" " + extra_hint if extra_hint else ""),
        }]
        payload = {
            "model": model,
            "max_tokens": 16000,
            "system": SYSTEM_PROMPT,
            "tools": [{"name": TOOL_NAME, "description": "Registra los datos leídos de la factura.", "input_schema": TOOL_SCHEMA}],
            # los modelos actuales no aceptan tool_choice forzado ("tool"/"any"): se pide por instrucción
            "tool_choice": {"type": "auto"},
            "messages": [{"role": "user", "content": content}],
        }
        headers = {"x-api-key": key, "anthropic-version": API_VERSION, "content-type": "application/json"}
        try:
            resp = requests.post(API_URL, headers=headers, data=json.dumps(payload), timeout=240)
        except requests.RequestException as e:
            raise UserError(_("No se pudo conectar con la API de Anthropic: %s", e)) from e
        if resp.status_code != 200:
            _logger.error("Anthropic API %s: %s", resp.status_code, resp.text[:2000])
            raise UserError(_("La API de Anthropic respondió %s: %s", resp.status_code, resp.text[:500]))
        body = resp.json()
        info = {"model": body.get("model"), "usage": body.get("usage"), "stop_reason": body.get("stop_reason")}
        for block in body.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == TOOL_NAME:
                return block.get("input") or {}, info
        # sin tool_use: si respondió el JSON como texto, lo tomamos igual
        for block in body.get("content", []):
            if block.get("type") == "text":
                m = re.search(r"\{.*\}", block.get("text") or "", re.S)
                if m:
                    try:
                        return json.loads(m.group(0)), info
                    except ValueError:
                        pass
        raise UserError(_("La IA no devolvió datos estructurados de la factura. Respuesta: %s", json.dumps(body)[:500]))
