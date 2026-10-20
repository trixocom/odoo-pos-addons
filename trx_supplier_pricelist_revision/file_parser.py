# Part of trx_supplier_pricelist_revision. Author: Trixocom. License: LGPL-3.
"""Lector de listas de precios de proveedor en el formato original (xlsx / xls / csv).

No exige un formato: busca en las primeras filas de cada hoja una fila de encabezados con
columnas reconocibles (código, detalle, precio de lista, bonificación, código de barras,
PVP sugerido) y toma las filas de datos que siguen. Las columnas sin encabezado se
deducen del contenido (código de barras: dígitos de 8 a 14; precio: la columna numérica
más alta; descripción: la columna de texto más larga). Devuelve una lista de dicts:
``{"code", "name", "barcode", "list_price", "discount", "suggested", "row"}``.

Probado con las listas reales de Derajim (Excel de Compras y .xls del portal), Tapimovil,
Sisfriends, Maldón y Caffaro (octubre 2026).
"""
import csv
import io
import re
import statistics
import unicodedata

HEADER_SCAN_ROWS = 40
SNIFF_ROWS = 300

# Sinónimos por campo (ya normalizados: minúsculas, sin acentos ni puntuación).
SYNONYMS = {
    "code": [
        "codigo pro", "codigo de producto", "codigo producto", "codigo prov", "cod prov", "codigo proveedor",
        "cod proveedor", "codigo", "cod", "codigo product", "codigo art", "cod art", "codigo articulo", "cod articulo",
        "cod alfa", "codigo alfa", "alfa", "articulo", "art", "sku", "item", "referencia", "ref", "code", "nro articulo",
        "n articulo", "codigo interno", "cod int", "sku maldon",
    ],
    "name": [
        "detalle", "descripcion", "descrip", "desc", "producto", "nombre", "description", "denominacion",
        "articulo descripcion", "titulo", "nombre del producto", "detalle del producto",
    ],
    "list_price": [
        "precio de lista", "precio lista", "precio", "lista", "p lista", "precio unitario", "precio unit", "pu", "p unit",
        "precio bruto", "precio neto", "precio mayorista", "precio venta mayorista", "pvm", "mayorista", "precio por mayor",
        "costo", "neto", "list price", "price", "precio sin iva", "precio s iva",
    ],
    "discount": [
        "bon1", "bon 1", "bonif", "bonificacion", "bonif 1", "descuento", "descuento 1", "desc 1", "desc1", "dto",
        "dto 1", "desc", "discount", "bonificacion 1", "bonif %", "descuento %",
    ],
    "barcode": [
        "cod alfaba", "alfaba", "codigo de barra", "codigo de barras", "codigo barra", "codigo barras", "cod barra",
        "cod barras", "barcode", "ean", "ean13", "ean 13", "ean code", "codigo ean", "upc", "gtin",
    ],
    "suggested": [
        "sugerido", "pvp sugerido", "precio sugerido", "precio publico", "precio publico sugerido", "pvp",
        "precio venta sugerido", "precio de venta sugerido", "sug", "pvp sug", "precio sug", "venta sugerido",
        "precio de venta", "precio venta", "p venta",
    ],
}

NO_BARCODE_TOKENS = {"sc", "s/c", "s c", "sin codigo", "n/a", "na", "-", "--", "0", "x", "nuevo"}
BARCODE_RE = re.compile(r"\d{8,14}")
SKIP_CODES = {"codigo", "cod", "cod alfa", "art", "articulo", "total", "subtotal", "sku"}


def normalize(text):
    if text is None:
        return ""
    text = str(text).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[*:()\[\]\"'.,;%$#]+", " ", text)
    text = re.sub(r"[\s_/]+", " ", text)
    return text.strip()


def _header_map(row):
    """Devuelve {campo: índice de columna} si la fila parece un encabezado (al menos código + otra), si no {}."""
    found = {}
    used = set()
    cells = [normalize(c) for c in row]
    if sum(1 for c in cells if c) < 2:
        return {}
    for field, names in SYNONYMS.items():  # pasada exacta
        for name in names:
            for idx, cell in enumerate(cells):
                if idx not in used and cell == name:
                    found[field] = idx
                    used.add(idx)
                    break
            if field in found:
                break
    for field, names in SYNONYMS.items():  # pasada por prefijo
        if field in found:
            continue
        for name in names:
            if len(name) < 4:
                continue
            for idx, cell in enumerate(cells):
                if idx in used or not cell or not cell.startswith(name):
                    continue
                if field == "list_price" and ("sug" in cell or "public" in cell or "venta" in cell or "pvp" in cell):
                    continue
                if field == "code" and ("barra" in cell or "alfaba" in cell or "ean" in cell):
                    continue
                found[field] = idx
                used.add(idx)
                break
            if field in found:
                break
    if "code" in found and len(found) >= 2:
        return found
    return {}


def _to_float(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("$", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    text = re.sub(r"[^0-9.\-]", "", text)
    if not re.fullmatch(r"-?\d+(\.\d+)?", text):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_code(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _to_barcode(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if normalize(text) in NO_BARCODE_TOKENS:
        return ""
    text = re.sub(r"\s+", "", text)
    if text.endswith(".0"):
        text = text[:-2]
    if not re.fullmatch(r"\d{8,14}", text):
        return ""
    return text


def _col(row, idx):
    return row[idx] if idx is not None and idx < len(row) else None


def _sniff_columns(rows, header_map, header_row_idx):
    """Deduce por contenido las columnas sin encabezado: código de barras, precio y descripción."""
    data = [list(r) for r in rows[header_row_idx + 1: header_row_idx + 1 + SNIFF_ROWS]]
    if not data:
        return header_map
    ncols = max(len(r) for r in data)
    used = set(header_map.values())
    stats = []
    for idx in range(ncols):
        if idx in used:
            continue
        values = [_col(r, idx) for r in data]
        values = [v for v in values if v is not None and str(v).strip() != ""]
        if len(values) < max(3, len(data) * 0.3):
            continue
        n = len(values)
        barcodes = sum(1 for v in values if _to_barcode(v))
        nums = [_to_float(v) for v in values]
        nums = [x for x in nums if x is not None]
        texts = [str(v) for v in values if _to_float(v) is None and len(str(v).strip()) >= 3]
        stats.append({
            "idx": idx, "n": n, "barcode_ratio": barcodes / n, "num_ratio": len(nums) / n,
            "median": statistics.median(nums) if nums else 0.0, "text_ratio": len(texts) / n,
            "text_len": statistics.mean(len(t) for t in texts) if texts else 0.0,
        })
    if "barcode" not in header_map:
        cands = [s for s in stats if s["barcode_ratio"] >= 0.5 and s["median"] >= 10 ** 7]
        if cands:
            best = max(cands, key=lambda s: s["barcode_ratio"])
            header_map["barcode"] = best["idx"]
            used.add(best["idx"])
            stats = [s for s in stats if s["idx"] != best["idx"]]
    if "list_price" not in header_map:
        cands = [s for s in stats if s["num_ratio"] >= 0.6 and s["median"] > 0 and s["barcode_ratio"] < 0.5]
        if cands:
            best = max(cands, key=lambda s: s["median"])
            header_map["list_price"] = best["idx"]
            used.add(best["idx"])
            stats = [s for s in stats if s["idx"] != best["idx"]]
    if "name" not in header_map:
        cands = [s for s in stats if s["text_ratio"] >= 0.6 and s["text_len"] >= 6]
        if cands:
            best = max(cands, key=lambda s: s["text_len"])
            header_map["name"] = best["idx"]
    return header_map


def _rows_from_sheet(rows, header_map, header_row_idx):
    if "list_price" not in header_map:
        return []
    out = []
    for n, row in enumerate(rows[header_row_idx + 1:], start=header_row_idx + 2):
        row = list(row)
        code = _to_code(_col(row, header_map["code"]))
        price = _to_float(_col(row, header_map["list_price"]))
        if not code or price is None or normalize(code) in SKIP_CODES:
            continue
        name_val = _col(row, header_map.get("name"))
        item = {
            "row": n,
            "code": code,
            "name": str(name_val).strip() if name_val is not None else "",
            "list_price": price,
            "discount": _to_float(_col(row, header_map["discount"])) if "discount" in header_map else None,
            "barcode": _to_barcode(_col(row, header_map["barcode"])) if "barcode" in header_map else "",
            "suggested": _to_float(_col(row, header_map["suggested"])) if "suggested" in header_map else None,
        }
        if item["discount"] is not None and 0 < item["discount"] < 1:
            item["discount"] *= 100.0  # 0,20 → 20 %
        out.append(item)
    return out


def _best_sheet(sheets):
    """sheets: lista de (nombre, filas). Elige la hoja con más columnas reconocidas y más filas."""
    best = None
    for name, rows in sheets:
        for idx, row in enumerate(rows[:HEADER_SCAN_ROWS]):
            header_map = _header_map(row)
            if not header_map:
                continue
            header_map = _sniff_columns(rows, dict(header_map), idx)
            data = _rows_from_sheet(rows, header_map, idx)
            score = (len(header_map), len(data))
            if data and (best is None or score > best[0]):
                best = (score, name, header_map, data)
            break  # primera fila de encabezado válida por hoja
    return best


def parse_xlsx(content):
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    sheets = []
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        sheets.append((ws.title, rows))
    return _best_sheet(sheets)


def parse_xls(content):
    import xlrd

    book = xlrd.open_workbook(file_contents=content)
    sheets = []
    for sh in book.sheets():
        rows = [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
        sheets.append((sh.name, rows))
    return _best_sheet(sheets)


def parse_csv(content):
    text = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return None
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t|")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"
    rows = list(csv.reader(io.StringIO(text), dialect))
    return _best_sheet([("csv", rows)])


def parse(content, filename=""):
    """Devuelve (nombre_hoja, header_map, filas) o None si no se reconoce nada."""
    ext = (filename or "").lower().rsplit(".", 1)[-1] if "." in (filename or "") else ""
    if ext in ("xlsx", "xlsm") or content[:2] == b"PK":
        res = parse_xlsx(content)
    elif ext == "xls" or content[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        res = parse_xls(content)
    else:
        res = parse_csv(content)
    if not res:
        return None
    _score, sheet_name, header_map, data = res
    return sheet_name, header_map, data
