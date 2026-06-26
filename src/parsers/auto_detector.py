"""
Detector universal de tablas en facturas PDF.
Estrategia:
  1. Tablas pdfplumber (CHOHO, AKT, JAPAN) — rechaza tablas con celdas fusionadas
  2. Posiciones de palabras (ROKO, FEV, HA) — detecta encabezado de mayor puntuación
"""
import re
import pdfplumber
from src.utils.cleaner import normalize_text, classify_column

HEADER_KEYWORDS = {
    'referencia', 'codigo', 'descripcion', 'cantidad', 'cant',
    'precio', 'valor', 'total', 'importe', 'u.m', 'um', 'unidad',
    'descuento', 'dcto', 'iva', 'plu', 'unidades', 'subtotal',
    'unitario', 'producto', 'articulo', 'vr', 'ean', 'cajas', 'recarg',
    'impto', 'impuest', 'vlr', 'serial',
}

_SKIP_RE = re.compile(
    r'^(TOTAL[_\s]|^TOTAL$|SUBTOTAL|VIENE\b|PASA\b|BASE IVA|RETEFUENTE|RETEIVA|'
    r'VALOR BRUTO|DESCUENTOS?\b|FLETE\b|RECARGOS?\b|IMP\. CONSUMO|'
    r'OBSERVACI|SOFTW|FAVOR CON|SEÑOR|RECUERDE|RESOLUCI|AUTORIZACI|'
    r'CORBEPUNTO|TOTAL\$|TOTAL \$|AVISO|'
    r'SIESA\b|ESTA FACTURA\b|CONMUTADOR\b|DECLARAM|'
    r'FACTURA GENERADA|^ENV|^HASTA\b|^N.MERO|RANGO AUTORIZADO|'
    r'^BANCO\b|^PAGAR\b|^RTE\b|^REFERENCIA\b|'
    r'^D.AS\b|^SUPERIOR|^REDUCI|^APLICA\b|^CR.DITO\b|^IVA\b|'
    r'Nit\s+o\s+C|'           # ROKO/SIESA: "Nit o C.C.:" línea de info del cliente
    r'\d{9}-\d)',
    re.IGNORECASE,
)
_FOOTER_RE = re.compile(
    r'(TOTAL_BRUTO|TOTAL BRUTO|DSCTO\s+X|SUB-TOTAL|DCTO\s+GLOBAL|'
    r'SUBTOTAL ANTES|DCTO COMERCIAL|DCTO ADICIONAL|DCTO PROMO|'
    r'I\.V\.A\.|RETEFUENTE|RETEIVA|VALOR IVA|BASE IVA|IMP\.\s*CONSUMO|'
    r'VALOR BRUTO|DESCUENTOS\b|'
    r'Nit\s*:|NIT\s*:|Tels?\s*:|PBX\s*:|'  # encabezados de empresa colombiana
    r'BODEGA\s*#\s*\d|PARQUE\s+INDUSTRIAL|'  # dirección bodega en pie/encabezado de página
    r'BANCOLOMBIA|CONVENIO\s+RECAUDO|CRUCE\s+RESTRICTIVO|CONSIGNAR\b|'
    r'TRANSFERENCIA\s+ELECTR|'             # instrucciones de pago
    r'JAPAN\s+Y\s+RACING|PASEO\s+BOLI|grupojapaniracer|\b901465474\b|'  # JAPAN encabezado de empresa
    r'FECHA\s+EXPEDI|'                                                   # JYG encabezado de página
    r'CUENTA\s+CORRIENTE|'                                              # OSAKA instrucciones de pago
    r'PESOS\s+\d+/100|Descuento\s+N\.|'                                # OSAKA2 pie de página
    r'EFECTOS\s+LEGALES|'                                              # SAIMRAM pie legal
    r'\bhabilita\b|'                                                    # SAIMRAM línea autorización
    r'\bCancele\b|'                                                     # SAIMRAM instrucción de pago
    r'Fecha\s+y\s+Hora\s+de\s+Generaci|'                              # SAIMRAM pie fecha generación
    r'Cr\s+\d+\s+\d+F\s+\d+)',                                        # SAIMRAM dirección pie de página
    re.IGNORECASE,
)


# ──────────────────────────────────────────────────────────────
# Utilidades
# ──────────────────────────────────────────────────────────────

def _score_header(cells) -> int:
    combined = normalize_text(' '.join(str(c or '') for c in cells))
    words = set(re.split(r'[\s/.,;:()\[\]|%#\-]+', combined))
    return len(words & HEADER_KEYWORDS)


# Patrón de código de producto: empieza con código alfanumérico típico
_PRODUCT_CODE_START = re.compile(r'^([A-Z]{1,5}\d|[A-Z]{2,4}\d|\d{5,}|\[)')

# Patrón para texto de continuación de descripción (overflow a columna CÓDIGO).
# Distingue partes de nombre de producto (códigos de cadena, modelos, variantes)
# de texto de pie de página (instrucciones de pago, nombres de banco, etc.).
_CONTINUATION_PATTERN = re.compile(
    r'[A-Z0-9][-/\(][A-Z0-9]'  # separador de código: 428H-132L, C100/BIZ, (12
    r'|\d{2,}[A-Z]'             # dígitos+letra: 428H, 125X
    r'|[A-Z]{3,}[\)\(]'         # palabra+paréntesis: NUCLEOS), (SET
    r'|\+\s*\d'                  # plus+dígito: + 428
    r'|[A-Z]{2,}\d{3,}'         # código de modelo: KW387, KW639, MX502
)

def _is_skip_line(text: str) -> bool:
    s = text.strip().lstrip('|').strip()
    if not s:
        return True
    # Sección "✂ cortar aquí" u otros símbolos no alfanuméricos al inicio
    if s and ord(s[0]) > 0x250 and not s[0].isalpha():
        return True
    if _SKIP_RE.match(s):
        return True
    if _FOOTER_RE.search(s):
        # Solo conservar si comienza con código de producto real
        if not _PRODUCT_CODE_START.match(s):
            return True
    # ROKO/SIESA: encabezado de página con caracteres dobles alfabéticos (CCLL, CCAALLII, TTeell::, NNIITT).
    # Solo aplica si el token tiene letras (evita falsos positivos con códigos numéricos tipo 220044).
    first_tok = s.split()[0] if s.split() else ''
    if (len(first_tok) >= 4 and len(first_tok) % 2 == 0
            and any(c.isalpha() for c in first_tok)
            and all(first_tok[i] == first_tok[i + 1] for i in range(0, len(first_tok) - 1, 2))):
        return True
    return False


def _looks_like_product(text: str) -> bool:
    """Heurística: ¿es una fila de producto? Requiere texto Y al menos 2 tokens numéricos."""
    if not re.search(r'[A-Za-záéíóúÁÉÍÓÚñÑ]{3,}', text):
        return False
    if _is_skip_line(text):
        return False
    # Texto con font disperso (cada carácter separado): >40% de tokens son 1 carácter
    tokens = text.split()
    if tokens and sum(1 for t in tokens if len(t) == 1) / len(tokens) > 0.4:
        return False
    num_tokens = re.findall(r'\b\d[\d.,]*\b', text)
    return len(num_tokens) >= 2


def _is_separator_line(words) -> bool:
    """Detecta líneas separadoras como +----...----+ o =========."""
    combined = ''.join(w['text'] if isinstance(w, dict) else str(w) for w in words)
    if len(combined) < 5:
        return False
    alpha = sum(1 for c in combined if c.isalnum())
    return alpha < len(combined) * 0.25


_CONNECTORS = frozenset({
    'de', 'y', 'e', 'a', 'el', 'la', 'los', 'las', 'del', 'con', 'en', 'por', 'al',
})

# Words that pdfplumber merges into one token but represent two separate columns.
# Maps normalized compound word → list of individual column names.
_COMPOUND_SPLITS = {
    'comercialadicional': ['COMERCIAL', 'ADICIONAL'],
}


def _is_numeric_column(h: str) -> bool:
    """True if column name represents a quantity, price, or total field."""
    nh = normalize_text(h)
    return bool(re.search(r'cant|precio|valor|subtotal|total|dcto|descuento|importe', nh))


def _drop_sparse_columns(headers: list, rows: list, threshold: float = 0.8) -> tuple:
    """
    Elimina columnas donde >threshold de las filas de producto están vacías.
    'Filas de producto' = filas donde la primera columna tiene valor numérico.
    Al eliminar una columna, si la columna siguiente tiene ≥2 palabras en su nombre,
    inserta el nombre eliminado entre la primera y segunda palabra (ej. UNT + VALOR FINAL
    → VALOR UNT FINAL).
    """
    if not rows or not headers:
        return headers, rows

    first_h = headers[0]
    prod_rows = [r for r in rows if re.match(r'^\d', r.get(first_h, '').strip())]
    if not prod_rows:
        prod_rows = rows

    n = len(prod_rows)
    to_drop = set()
    for h in headers:
        empty = sum(1 for r in prod_rows if not r.get(h, '').strip())
        if n > 0 and empty / n > threshold:
            to_drop.add(h)

    if not to_drop:
        return headers, rows

    new_headers = list(headers)
    rename_map = {}  # old name → new name
    for i, h in enumerate(headers):
        if h not in to_drop:
            continue
        # Si la columna siguiente (no vacía) tiene ≥2 palabras, insertar el nombre eliminado
        if i + 1 < len(headers):
            nxt = headers[i + 1]
            if nxt in to_drop:
                continue  # la siguiente también se elimina: no renombrar
            parts = nxt.split(' ', 1)
            if len(parts) == 2:
                rename_map[nxt] = parts[0] + ' ' + h + ' ' + parts[1]

    # Aplicar renombres
    for old, new in rename_map.items():
        idx = new_headers.index(old)
        new_headers[idx] = new

    kept = [h for h in new_headers if h not in to_drop]
    rows_out = [{(rename_map.get(h, h)): r.get(h, '') for h in headers
                 if h not in to_drop} for r in rows]
    return kept, rows_out


def _merge_continuation_rows(headers: list, rows: list) -> list:
    """
    Fusiona filas de continuación con la fila de producto anterior.
    Caso 1: CÓDIGO vacío + CANT vacío + algún texto en DESCRIPCIÓN.
    Caso 2: CÓDIGO contiene '/' (overflow de descripción) + CANT vacío + SUBTOTAL vacío.
    Caso 3: CÓDIGO tiene texto no-código que coincide con _CONTINUATION_PATTERN + sin
            CANT ni valores de precio/qty (2ª línea de descripción multi-línea del PDF).
    """
    code_col = next(
        (h for h in headers
         if normalize_text(h).startswith('cod') and 'descripcion' not in normalize_text(h)),
        None,
    )
    desc_col = next((h for h in headers if 'descripcion' in normalize_text(h)), None)
    cant_col = next((h for h in headers if normalize_text(h).startswith('cant')), None)
    sub_col = next((h for h in headers if 'subtotal' in normalize_text(h)), None)
    price_qty_cols = [h for h in headers if classify_column(h) in ('price', 'qty')]
    price_cols = [h for h in headers if classify_column(h) == 'price']

    if not desc_col:
        return rows

    # Sin columna de código (ej. FEV): solo aplicar caso1 — fila sin CANT ni precios
    # que tiene descripción se fusiona con el producto anterior.
    if not code_col:
        merged = []
        for row in rows:
            cant_v = row.get(cant_col, '').strip() if cant_col else ''
            desc_v = row.get(desc_col, '').strip()
            no_numeric = not any(row.get(h, '').strip() for h in price_qty_cols)
            if not cant_v and desc_v and no_numeric and merged:
                prev = dict(merged[-1])
                prev_desc = prev.get(desc_col, '').strip()
                prev[desc_col] = (prev_desc + ' ' + desc_v).strip() if prev_desc else desc_v
                merged[-1] = prev
            else:
                merged.append(row)
        return merged

    if not cant_col:
        return rows

    merged = []
    pending_prefix = ''  # text buffered from cross-page orphan lines
    for row in rows:
        code_v = row.get(code_col, '').strip()
        cant_v = row.get(cant_col, '').strip()
        desc_v = row.get(desc_col, '').strip()
        sub_v = row.get(sub_col, '').strip() if sub_col else ''

        # Caso 1: código vacío, cant vacía, hay descripción
        case1 = not code_v and not cant_v and desc_v
        # Caso 2: código tiene '/' (overflow), cant vacía, subtotal vacío
        case2 = '/' in code_v and not cant_v and not sub_v
        # Caso 3: texto en código que NO es un código de producto real + sin CANT ni precios.
        # Aplica a overflow de descripción como "YAMAHA", "MRX", "128L", "135/XCD125/...".
        case3 = (
            bool(code_v) and not cant_v
            and not _PRODUCT_CODE_START.match(code_v)
            and not any(row.get(h, '').strip() for h in price_qty_cols)
        )
        # Caso 4: código vacío + CANT tiene valor (número de modelo que cayó en columna
        # CANT por posición x) + sin columnas de precio → 2ª línea de descripción.
        case4 = (
            not code_v and bool(cant_v)
            and not any(row.get(h, '').strip() for h in price_cols)
        )

        is_continuation = case1 or case2 or case3 or case4

        # Case 3 sub-check: if code has letters but NO continuation pattern match,
        # treat as cross-page orphan — buffer it instead of appending to previous product.
        if case3 and not _CONTINUATION_PATTERN.search(code_v) and re.search(r'[A-Za-z]', code_v):
            parts = [row.get(h, '').strip() for h in headers
                     if h != cant_col and classify_column(h) not in ('price', 'pct')
                     and row.get(h, '').strip()]
            orphan_text = ' '.join(parts)
            pending_prefix = (pending_prefix + ' ' + orphan_text).strip() if pending_prefix else orphan_text
            continue

        if is_continuation and merged:
            prev = dict(merged[-1])
            prev_desc = prev.get(desc_col, '').strip()
            if case2:
                extra = (code_v + ' ' + desc_v).strip()
            elif case3:
                # Recoger texto de TODAS las columnas no-precio/no-cant
                parts = [row.get(h, '').strip() for h in headers
                         if h != cant_col and classify_column(h) not in ('price', 'pct')
                         and row.get(h, '').strip()]
                extra = ' '.join(parts)
                # Detectar sufijo de cadena (ej. "128L" tras "428H"): unir con guión
                prev_words = prev_desc.split()
                prev_last = prev_words[-1] if prev_words else ''
                first_token = extra.split()[0] if extra.split() else ''
                if (re.match(r'^\d+[A-Z]+$', first_token)
                        and re.search(r'[A-Z0-9]$', prev_last)):
                    prev[desc_col] = prev_desc + '-' + extra
                else:
                    prev[desc_col] = (prev_desc + ' ' + extra).strip() if prev_desc else extra
                merged[-1] = prev
                continue
            elif case4:
                extra = (cant_v + ' ' + desc_v).strip()
            else:
                extra = desc_v
            prev[desc_col] = (prev_desc + ' ' + extra).strip() if prev_desc else extra
            merged[-1] = prev
        else:
            # If there's a buffered cross-page prefix, prepend it to this row's description.
            if pending_prefix and _PRODUCT_CODE_START.match(code_v):
                row = dict(row)
                cur_desc = row.get(desc_col, '').strip()
                # Extract code suffix (e.g. '200' from '2100041141238 200') and place
                # it after pending_prefix so _split_code_description doesn't re-prepend it.
                code_tokens = code_v.split(None, 1)
                code_suffix = code_tokens[1].strip() if len(code_tokens) > 1 else ''
                parts = [pending_prefix]
                if code_suffix:
                    parts.append(code_suffix)
                if cur_desc:
                    parts.append(cur_desc)
                row[desc_col] = ' '.join(parts)
                row[code_col] = code_tokens[0]  # strip suffix so _split_code_description skips it
                pending_prefix = ''
            elif pending_prefix and not is_continuation:
                # Non-product garbage row between orphan and its target — skip flushing buffer
                pass
            merged.append(row)
    return merged


def _split_code_description(headers: list, rows: list) -> list:
    """
    Post-proceso: separa el prefijo de descripción que se coló en la columna CÓDIGO.
    Si CÓDIGO='2010001201132 CADENA' → CÓDIGO='2010001201132', prepend 'CADENA' a DESCRIPCIÓN.
    Solo aplica cuando el primer token contiene dígitos (es un código real).
    """
    _CODE_PREFIXES = ('cod', 'item', 'ref', 'plu', 'sku')
    code_col = next(
        (h for h in headers
         if any(normalize_text(h).startswith(p) for p in _CODE_PREFIXES)
         and 'descripcion' not in normalize_text(h)),
        None,
    )
    desc_col = next(
        (h for h in headers if 'descripcion' in normalize_text(h)),
        None,
    )
    if not code_col or not desc_col:
        return rows

    new_rows = []
    for row in rows:
        code_val = row.get(code_col, '').strip()
        parts = code_val.split(None, 1)
        if len(parts) == 2 and re.search(r'\d', parts[0]):
            row = dict(row)
            row[code_col] = parts[0]
            desc_val = row.get(desc_col, '').strip()
            prefix = parts[1].strip()
            row[desc_col] = (prefix + ' ' + desc_val).strip() if desc_val else prefix
        new_rows.append(row)
    return new_rows


def _clean_tainted_cant(headers: list, rows: list) -> list:
    """
    Limpia la columna CANT cuando contiene texto de overflow de columnas adyacentes.
    Ej: '428H-132L 20' → CANT='20', '115 1' → CANT='1', 'NEGRO 3' → CANT='3'.
    Regla: el último token puramente entero es el CANT real.
    Tokens no-enteros con letras (len>1) se prependen a DESCRIPCIÓN.
    Tokens enteros previos (overflow numérico) se descartan.
    """
    cant_col = next((h for h in headers if normalize_text(h).startswith('cant')), None)
    desc_col = next((h for h in headers if 'descripcion' in normalize_text(h)), None)

    if not cant_col:
        return rows

    new_rows = []
    for row in rows:
        cant_val = row.get(cant_col, '').strip()
        tokens = cant_val.split()
        if len(tokens) <= 1:
            new_rows.append(row)
            continue

        # Ignorar el token "Unidades"/"Unidad" que FEV escribe junto a la cantidad.
        tokens = [t for t in tokens if not re.match(r'^[Uu]nidades?$', t)]
        if len(tokens) <= 1:
            if tokens:
                row = dict(row)
                raw = tokens[0]
                # Limpiar decimal tipo "3,00" → "3" (FEV usa decimales de relleno)
                cleaned = re.sub(r'[,\.]0+$', '', raw)
                row[cant_col] = cleaned if re.match(r'^\d+$', cleaned) else raw
            new_rows.append(row)
            continue

        last_int_idx = None
        for k in range(len(tokens) - 1, -1, -1):
            if re.match(r'^\d+([,\.]\d+)?$', tokens[k]):
                last_int_idx = k
                break

        if last_int_idx is None:
            new_rows.append(row)
            continue

        # Si el token es decimal (e.g. "3,00"), convertir a entero limpio
        raw_cant = tokens[last_int_idx]
        real_cant = re.sub(r'[,\.]0+$', '', raw_cant)  # "3,00" → "3", "3,50" → "3,50"
        if not re.match(r'^\d+$', real_cant):
            real_cant = raw_cant  # era decimal real (e.g. "3,50"), conservar
        # Todos los tokens previos al CANT real van a descripción.
        # Incluye letras ('NEGRO', 'SET-2') y números cortos ('125', '115' = modelos).
        # Excluir tokens vacíos (no debería haber ninguno tras split).
        overflow = [t for t in tokens[:last_int_idx] if t]

        row = dict(row)
        row[cant_col] = real_cant
        if overflow and desc_col:
            suffix = ' '.join(overflow)
            desc_val = row.get(desc_col, '').strip()
            row[desc_col] = (desc_val + ' ' + suffix).strip() if desc_val else suffix
        new_rows.append(row)
    return new_rows


def _filter_product_rows(headers: list, rows: list) -> list:
    """
    Conserva solo filas donde al menos una columna de precio o cantidad
    contiene un número positivo (> 0). Elimina filas de encabezado/pie
    que pasaron los filtros anteriores (e.g. '0' solo no es suficiente).
    """
    from src.utils.cleaner import parse_number as _pn
    numeric_cols = [h for h in headers if classify_column(h) in ('price', 'qty')]
    if not numeric_cols:
        return rows

    result = []
    for row in rows:
        for h in numeric_cols:
            val = row.get(h, '').strip()
            if val and re.match(r'^[\d\s.,]+$', val) and re.search(r'\d', val):
                if _pn(val) > 0:
                    result.append(row)
                    break
    return result


def _drop_zero_pct_columns(headers: list, rows: list) -> tuple:
    """Drop percentage columns where every row parses to 0 (e.g. Impto always 0.00)."""
    from src.utils.cleaner import parse_percentage as _pp
    pct_cols = [h for h in headers if classify_column(h) == 'pct']
    if not pct_cols or not rows:
        return headers, rows
    to_drop = {h for h in pct_cols if all(_pp(r.get(h, '')) == 0.0 for r in rows)}
    if not to_drop:
        return headers, rows
    new_headers = [h for h in headers if h not in to_drop]
    new_rows = [{h: r.get(h, '') for h in new_headers} for r in rows]
    return new_headers, new_rows


_VALID_UNITS = frozenset({
    'und', 'un', 'unid', 'unidad', 'unidades',
    'kit', 'par', 'set', 'pz', 'pza', 'pzs',
    'gln', 'gal', 'galon', 'lt', 'ltr', 'litro', 'litros',
    'ml', 'cc', 'kg', 'kgs', 'gr', 'grs', 'ton',
    'mt', 'mts', 'm', 'cm', 'mm', 'm2', 'm3', 'km',
    'box', 'caja', 'caj', 'paq', 'paquete', 'pac', 'paca',
    'bls', 'bolsa', 'jar', 'jarra', 'caneca',
    'rollo', 'metro', 'hora', 'dia', 'mes', 'srv',
})


def _fix_unit_overflow(headers: list, rows: list) -> list:
    """
    HA/HABICICLETAS: la columna 'Unidad' está vacía en el PDF pero pdfplumber
    asigna la primera parte de la descripción a ella por proximidad de coordenadas x.
    Si el valor de Unidad no es una unidad de medida válida, se fusiona con Descripción.
    """
    unit_col = next(
        (h for h in headers
         if normalize_text(h).rstrip('.') in ('unidad', 'u.m', 'u m', 'um', 'u/m')),
        None,
    )
    desc_col = next((h for h in headers if 'descripcion' in normalize_text(h)), None)
    if not unit_col or not desc_col:
        return rows
    new_rows = []
    for row in rows:
        unit_val = row.get(unit_col, '').strip()
        if not unit_val or normalize_text(unit_val) in _VALID_UNITS:
            new_rows.append(row)
            continue
        row = dict(row)
        desc_val = row.get(desc_col, '').strip()
        row[desc_col] = (unit_val + ' ' + desc_val).strip() if desc_val else unit_val
        row[unit_col] = ''
        new_rows.append(row)
    return new_rows


_TRAILING_UNIT_RE = re.compile(r'\s+\bUnd\.?\s*$', re.IGNORECASE)


def _clean_und_artifacts(headers: list, rows: list) -> list:
    """
    Limpia caracteres de 'Und.' interleados dentro de tokens de descripción por
    el renderizado de doble capa del PDF. Ej: 'ABUAnJOd'→'ABAJO', 'VEUNnTdA.'→'VENTA'.
    Solo actúa sobre secuencias puramente alfabéticas en mayúsculas; los tokens con
    dígitos o los valores como '$UND' no se modifican.
    """
    desc_col = next((h for h in headers if 'descripcion' in normalize_text(h)), None)
    if not desc_col:
        return rows
    # Detecta palabras con marcadores de artefacto n/d entre mayúsculas
    _contam = re.compile(r'[A-Z][nd][A-Z]')
    new_rows = []
    for row in rows:
        desc = row.get(desc_col, '').strip()
        if not desc:
            new_rows.append(row)
            continue
        # Paso 0: en palabras con marcadores de artefacto (n/d entre mayúsculas),
        # eliminar también la U mayúscula atrapada entre dos mayúsculas.
        # Aplicar ANTES de que las reglas siguientes eliminen los marcadores n/d.
        # Ej: '10MM/AUBAnJdO.' → '10MM/ABAnJdO.' (el AnJ confirma artefacto; AU→A)
        desc = ' '.join(
            re.sub(r'(?<=[A-Z])U(?=[A-Z])', '', w) if _contam.search(w) else w
            for w in desc.split()
        )
        # Eliminar U al final de secuencia ≥2 mayúsculas antes de separador
        # Ej: 'C100BIZU/' → 'C100BIZ/' (sin \b, funciona aunque preceda dígito)
        desc = re.sub(r'([A-Z]{2,})U(?=[/\-\(\s]|$)', r'\1', desc)
        # Eliminar U solitaria antes de '$' o '(' (ej. U$SET → $SET, U(SAI) → (SAI))
        desc = re.sub(r'\bU(?=[$\(])', '', desc)
        # U seguida de mayúscula + 'n' minúscula → artefacto específico de 'Und.'
        desc = re.sub(r'(?<=[A-Z])[Uu](?=[A-Z][nN])', '', desc)
        # n minúscula después de mayúscula antes de mayúscula, / - o espacio → artefacto
        desc = re.sub(r'(?<=[A-Z])n(?=[A-Z/\-\s]|$)', '', desc)
        # d minúscula + punto opcional después de mayúscula → artefacto 'd.' de 'Und.'
        desc = re.sub(r'(?<=[A-Z])d\.?(?=[A-Z\s]|$)', '', desc)
        # Punto embebido después de UNA SOLA mayúscula antes de mayúscula o dígito → artefacto
        # Ej: 'C.90' → 'C90', 'S.T' → 'ST'
        # Excluir si hay ≥2 mayúsculas antes del punto (ej. 'TELES.CR5' es nombre real).
        desc = re.sub(r'(?<![A-Z][A-Z])(?<=[A-Z])\.(?=[A-Z\d])', '', desc)
        # Punto espurio al inicio de token numérico (espacio + punto + dígito)
        # Ej: ' .10MM' → ' 10MM'
        desc = re.sub(r'(?<=\s)\.(?=\d)', '', desc)
        # d minúscula después de separador (/ - ( espacio) antes de mayúscula → artefacto
        # Ej: '/dC' → '/C', '(dSAI' → '(SAI'
        desc = re.sub(r'(?<=[/\-\(\s])d(?=[A-Z])', '', desc)
        # Punto después de '$' o '(' antes de mayúscula → artefacto (ej. $.SET → $SET)
        desc = re.sub(r'(?<=[$\(])\.(?=[A-Z])', '', desc)
        # U mayúscula al final de una palabra en mayúsculas → artefacto 'U' de 'Und.'
        desc = re.sub(r'\b([A-Z]+)[Uu]\b', r'\1', desc)
        # n/d interleados dentro de secuencias de dígitos (ej. '1n0d'→'10')
        desc = re.sub(r'(?<=\d)[nd](?=[\d\s]|$)', '', desc)
        # Punto residual al final de palabra (después de mayúscula o ')') antes de espacio/fin
        # Ej: '(SAI).' → '(SAI)', '$SET.' → '$SET'
        desc = re.sub(r'(?<=[A-Z\)])\.(?=\s|$)', '', desc)
        # Período residual al final de palabras largas en mayúsculas (≥4 letras)
        desc = re.sub(r'([A-Z]{4,})\.(?=\s|$)', r'\1', desc)
        # 'n' inicial antes de secuencia en mayúsculas → remanente de limpieza de 'nEdN.'
        desc = re.sub(r'\bn([A-Z]{2,})\.?(?=\s|$)', r'\1', desc)
        # Eliminar tokens 'Und.' sueltos que no van precedidos de '$'
        desc = re.sub(r'(?<!\$)\s*\bUnd\.?\b\s*', ' ', desc, flags=re.IGNORECASE)
        desc = re.sub(r'\s+', ' ', desc).strip()
        if desc != row.get(desc_col, '').strip():
            row = dict(row)
            row[desc_col] = desc
        new_rows.append(row)
    return new_rows


def _strip_trailing_units(headers: list, rows: list) -> list:
    """
    Elimina el token "Und." que algunos PDFs imprimen como unidad de medida al
    final del texto de descripción por solapamiento de columnas en el layout.
    """
    desc_col = next((h for h in headers if 'descripcion' in normalize_text(h)), None)
    if not desc_col:
        return rows
    new_rows = []
    for row in rows:
        desc = row.get(desc_col, '').strip()
        cleaned = _TRAILING_UNIT_RE.sub('', desc).strip()
        if cleaned != desc:
            row = dict(row)
            row[desc_col] = cleaned
        new_rows.append(row)
    return new_rows


def _merge_description_label_rows(headers: list, rows: list) -> tuple:
    """
    OSAKA S.A.S.: la descripción aparece en una fila separada precedida por la
    etiqueta 'Descripción' (ej. "Descripción Pastilla Semimetálica Ak110/...").
    Esa fila no tiene columna desc propia — el texto queda repartido entre las
    columnas de código, cantidad, precio, etc.

    Detecta cualquier fila donde ALGÚN valor empiece con 'Descripci', extrae
    todo el texto de esa fila (quitando el prefijo), lo añade como descripción
    del producto anterior y elimina la fila basura.

    Si no existe columna Descripción en los headers, la crea.
    """
    _DESC_LABEL_RE = re.compile(r'^[Dd]escripci[oó]n\s*', re.IGNORECASE)

    def _is_label_row(row):
        return any(_DESC_LABEL_RE.match(str(v)) for v in row.values() if v)

    if not any(_is_label_row(r) for r in rows):
        return headers, rows

    desc_col = next((h for h in headers if 'descripcion' in normalize_text(h)), None)
    if not desc_col:
        desc_col = 'Descripción'
        headers = list(headers)
        # Insertar la columna nueva en posición 1 (después del código/item)
        headers.insert(1, desc_col)
        rows = [{**r, desc_col: ''} for r in rows]

    new_rows = []
    for row in rows:
        if not _is_label_row(row):
            new_rows.append(row)
            continue
        # Concatenar todos los valores de la fila, quitando el prefijo "Descripción"
        parts = []
        for v in row.values():
            s = str(v).strip() if v else ''
            if not s:
                continue
            s = _DESC_LABEL_RE.sub('', s).strip()
            if s:
                parts.append(s)
        desc_text = ' '.join(parts).strip()
        if desc_text and new_rows:
            prev = dict(new_rows[-1])
            prev_desc = prev.get(desc_col, '').strip()
            prev[desc_col] = (prev_desc + ' ' + desc_text).strip() if prev_desc else desc_text
            new_rows[-1] = prev

    return headers, new_rows


def _handle_mo_column(headers: list, rows: list) -> tuple:
    """
    ROKO/SIESA: elimina la columna 'Mo' (código interno de modelo).
    El valor de Mo puede tener un prefijo de variante (ej. '2V 01', '2018+ 01')
    que pertenece a la descripción del producto. El código numérico al final
    (ej. '01') es un código interno de ROKO que se descarta.
    """
    mo_col = next((h for h in headers if normalize_text(h).strip() == 'mo'), None)
    if not mo_col:
        return headers, rows

    desc_col = next((h for h in headers if 'descripcion' in normalize_text(h)), None)

    new_rows = []
    for row in rows:
        mo_val = row.get(mo_col, '').strip()
        row = dict(row)
        if mo_val and desc_col:
            # Quitar código interno al final (1-2 dígitos, ej. "01")
            prefix = re.sub(r'\s*\d{1,2}$', '', mo_val).strip()
            if prefix:
                desc_val = row.get(desc_col, '').strip()
                row[desc_col] = (desc_val + ' ' + prefix).strip() if desc_val else prefix
        new_rows.append({k: v for k, v in row.items() if k != mo_col})

    new_headers = [h for h in headers if h != mo_col]
    return new_headers, new_rows


def _merge_fragmented_headers(headers: list, rows: list) -> tuple:
    """
    Merges compound column names that were split across multiple cells.
    Two cases:
      1. Connector word (DE, Y, A…): merge it AND the noun that follows.
         "DESCRIPCIÓN | DE | PRODUCTO" → "DESCRIPCIÓN DE PRODUCTO"
      2. Direct connector: already handles "PRECIO DE LISTA", "VALOR A PAGAR", etc.
    """
    if len(headers) <= 1:
        return headers, rows

    merge_into_prev = set()
    for i, h in enumerate(headers[1:], start=1):
        norm = normalize_text(h).strip()
        norm_parts = norm.split()
        if norm in _CONNECTORS:
            merge_into_prev.add(i)
            # Also pull in the noun that completes the prepositional phrase
            if i + 1 < len(headers):
                merge_into_prev.add(i + 1)
        elif len(norm_parts) > 1 and norm_parts[0] in _CONNECTORS:
            # "DE PRODUCTO" as single cell → merge into previous column
            merge_into_prev.add(i)

    if not merge_into_prev:
        return headers, rows

    new_headers = []
    merge_map = {}
    for i, h in enumerate(headers):
        if i in merge_into_prev and new_headers:
            new_headers[-1] = new_headers[-1] + ' ' + h
            merge_map[i] = len(new_headers) - 1
        else:
            merge_map[i] = len(new_headers)
            new_headers.append(h)

    new_rows = []
    for row in rows:
        new_row = {h: '' for h in new_headers}
        for i, old_h in enumerate(headers):
            new_h = new_headers[merge_map[i]]
            val = row.get(old_h, '').strip()
            if not val:
                continue
            new_row[new_h] = (new_row[new_h] + ' ' + val).strip() if new_row[new_h] else val
        new_rows.append(new_row)

    return new_headers, new_rows


# ──────────────────────────────────────────────────────────────
# Estrategia 1: Tablas pdfplumber
# ──────────────────────────────────────────────────────────────

def _clean_cell(val) -> str:
    if val is None:
        return ''
    return str(val).strip().replace('\n', ' ')


def _find_best_table(tables: list):
    best_score = 0
    best = None
    for table in tables:
        for i, row in enumerate(table):
            score = _score_header(row)
            if score > best_score and score >= 3:
                best_score = score
                best = (i, table)
    return best


def _extract_from_table(header_idx: int, table: list):
    raw_header = [_clean_cell(c) for c in table[header_idx]]

    # Encabezado en 2 filas (ej. AKT)
    data_start = header_idx + 1
    if data_start < len(table):
        next_row = [_clean_cell(c) for c in table[data_start]]
        if _score_header(next_row) >= 2:
            for j, cell in enumerate(next_row):
                if cell and j < len(raw_header):
                    raw_header[j] = (raw_header[j] + ' ' + cell).strip() if raw_header[j] else cell
            data_start += 1

    # VALIDAR: rechazar tabla con celdas fusionadas.
    # Señal 1: múltiples celdas con \n≥2 en la misma fila (filas fusionadas, ej. HA)
    # Señal 2: celda individual > 100 chars (múltiples códigos fusionados, ej. CHOHO)
    for row in table[data_start:data_start + 3]:
        cleaned = [_clean_cell(c) for c in row]
        if any(len(v) > 100 for v in cleaned):
            return [], []  # Celda muy larga = filas fusionadas
        multi_nl = sum(1 for val in row if val and str(val).count('\n') >= 2)
        if multi_nl >= 2:
            return [], []  # Múltiples celdas con saltos = filas fusionadas

    # Normalizar encabezados
    headers = []
    seen = {}
    for h in raw_header:
        h = h.strip()
        if not h:
            h = f'Col{len(headers)+1}'
        base = h
        if h in seen:
            seen[h] += 1
            h = f'{h}_{seen[h]}'
        else:
            seen[base] = 0
        headers.append(h)

    rows = []
    for row in table[data_start:]:
        vals = [_clean_cell(c) for c in row]
        if not any(v for v in vals):
            continue
        row_text = ' '.join(vals)
        if _is_skip_line(row_text):
            continue
        if _FOOTER_RE.search(row_text):
            if not re.match(r'^[A-Z0-9]{3,}', vals[0] if vals else ''):
                continue
        # Saltar filas dispersas (sub-encabezados como '%' 'VLR')
        filled = sum(1 for v in vals if v.strip())
        if filled < max(2, len(vals) * 0.25):
            continue
        row_dict = {h: (vals[i] if i < len(vals) else '') for i, h in enumerate(headers)}
        rows.append(row_dict)

    # Eliminar columnas vacías
    non_empty = [h for h in headers if any(r.get(h, '') for r in rows)]
    rows = [{h: r.get(h, '') for h in non_empty} for r in rows]

    # Fusionar encabezados fragmentados (ej. 'DESCRIPCIÓN' | 'DE' | 'PRODUCTO')
    non_empty, rows = _merge_fragmented_headers(non_empty, rows)
    return non_empty, rows


# ──────────────────────────────────────────────────────────────
# Estrategia 2: Posiciones de palabras
# ──────────────────────────────────────────────────────────────

def _group_by_line(words: list, y_tol: int = 4) -> list:
    buckets = {}
    for w in words:
        y = w['top']
        key = None
        for k in buckets:
            if abs(k - y) <= y_tol:
                key = k
                break
        if key is None:
            key = y
            buckets[key] = []
        buckets[key].append(w)
    return [sorted(buckets[y], key=lambda w: w['x0']) for y in sorted(buckets)]


def _build_columns(header_words: list, page_width: float) -> list:
    """
    Construye columnas desde palabras del encabezado.
    - Fusiona caracteres individuales consecutivos (texto esparcido).
    - Fusiona palabras adyacentes con gap < 3pts (ej. 'UNT FINAL').
    - Expande compuestos de _COMPOUND_SPLITS (ej. 'COMERCIALADICIONAL').
    """
    filtered = [w for w in header_words
                if w['text'].strip() and w['text'].strip() not in ('|', '-', '—', '*')]
    if not filtered:
        return []

    cols = []
    i = 0
    while i < len(filtered):
        w = filtered[i]
        name = w['text']
        x_start = w['x0']
        x_end = w['x1']

        # Fusionar SOLO si son caracteres individuales consecutivos (texto esparcido)
        while i + 1 < len(filtered):
            nw = filtered[i + 1]
            gap = nw['x0'] - x_end
            if len(w['text'].strip()) <= 2 and len(nw['text'].strip()) <= 2 and gap < 8:
                name = name + nw['text']   # sin espacio (colapsar texto esparcido)
                x_end = nw['x1']
                w = nw
                i += 1
            elif name.strip().endswith('.') and len(name.strip()) <= 3 and gap < 6:
                # "V." + "TOTAL" → "V. TOTAL": prefijo abreviado con gap mínimo
                name = name + ' ' + nw['text']
                x_end = nw['x1']
                w = nw
                i += 1
            elif len(name.strip()) <= 2 and gap < 6:
                # "Vr" + "Unitario", "%" + "Dcto": prefijo corto pegado a la siguiente palabra
                name = name.strip() + ' ' + nw['text'].strip()
                x_end = nw['x1']
                w = nw
                i += 1
            else:
                break

        clean_name = name.strip('|').strip()
        if clean_name:
            compound_key = normalize_text(clean_name).replace(' ', '')
            if compound_key in _COMPOUND_SPLITS:
                # Expandir compuesto en columnas individuales con ancho equitativo
                parts = _COMPOUND_SPLITS[compound_key]
                part_w = (x_end - x_start) / len(parts)
                for k, part_name in enumerate(parts):
                    cols.append({
                        'name': part_name,
                        'x_start': x_start + k * part_w,
                        'x_end': x_start + (k + 1) * part_w,
                    })
            else:
                cols.append({'name': clean_name, 'x_start': x_start, 'x_end': x_end})
        i += 1

    # Ajustar límites con punto medio. Excepción específica: columna de código seguida
    # de descripción con gap >80 pts → usar margen estrecho (5 pts) para que palabras
    # de descripción no caigan en la columna de código.
    # Caso SAIMRAM: "Código" x1=80, "Descripción" x0=205, gap=125 → límite en x=85.
    _CODE_COL_PREFIXES = ('cod', 'ref', 'plu', 'sku')
    for j in range(len(cols) - 1):
        left_x_end = cols[j]['x_end']
        right_x_start = cols[j + 1]['x_start']
        gap = right_x_start - left_x_end
        left_is_code = any(normalize_text(cols[j]['name']).startswith(p)
                           for p in _CODE_COL_PREFIXES)
        right_is_desc = normalize_text(cols[j + 1]['name']).startswith('descripci')
        if gap > 80 and left_is_code and right_is_desc:
            new_boundary = left_x_end + 5
        else:
            new_boundary = (left_x_end + right_x_start) / 2
        cols[j]['x_end'] = new_boundary
        cols[j + 1]['x_start'] = new_boundary
    if cols:
        cols[-1]['x_end'] = page_width

    # Deduplicar nombres: "Total", "Total" → "Total", "Total_1"
    seen_names: dict = {}
    for col in cols:
        name = col['name']
        if name in seen_names:
            seen_names[name] += 1
            col['name'] = f"{name}_{seen_names[name]}"
        else:
            seen_names[name] = 0

    return cols


def _merge_prev_header(cols: list, prev_words: list):
    """
    Combina palabras de la línea anterior (parte superior del encabezado de 2 filas)
    con los nombres de columna ya construidos.
    Ej: PRECIO(línea anterior) + UNITARIO(línea principal) → "PRECIO UNITARIO"
    """
    filtered = [w for w in prev_words
                if w['text'].strip() and w['text'].strip() not in ('|', '-', '—', '*')]
    for pw in filtered:
        cx = (pw['x0'] + pw['x1']) / 2
        # Encontrar columna más cercana
        best = min(cols, key=lambda c: abs((c['x_start'] + c['x_end']) / 2 - cx), default=None)
        if best is None:
            continue
        dist = abs((best['x_start'] + best['x_end']) / 2 - cx)
        if dist < 50:
            best['name'] = (pw['text'].strip('|') + ' ' + best['name']).strip()


def _extend_with_subheader(cols: list, sub_words: list):
    """
    Extiende nombres con sub-encabezado (fila debajo del encabezado principal).
    Ej: DESCRIPCIÓN(principal) + "DE PRODUCTO"(sub) → "DESCRIPCIÓN DE PRODUCTO"
    """
    filtered = [w for w in sub_words
                if w['text'].strip() and w['text'].strip() not in ('|', '-', '—', '*')]
    for sw in filtered:
        # Ignorar caracteres que son solo símbolos
        if not re.search(r'[A-Za-z0-9]', sw['text']):
            continue
        cx = (sw['x0'] + sw['x1']) / 2
        best = min(cols, key=lambda c: abs((c['x_start'] + c['x_end']) / 2 - cx), default=None)
        if best is None:
            continue
        dist = abs((best['x_start'] + best['x_end']) / 2 - cx)
        if dist < 55:
            best['name'] = (best['name'] + ' ' + sw['text'].strip('|')).strip()


def _assign_to_columns(line_words: list, columns: list) -> dict:
    _UNIT_COL_NORMS = frozenset({'unidad', 'u.m', 'u m', 'um', 'u/m'})
    unit_col_names = {col['name'] for col in columns
                      if normalize_text(col['name']).rstrip('.') in _UNIT_COL_NORMS}

    buckets = {col['name']: [] for col in columns}
    for w in line_words:
        text = w['text'].strip('|').strip()
        if not text or text in ('*', '—', '-'):
            continue
        nt = normalize_text(text).rstrip('.')
        # Tokens que empiezan en minúscula, contienen mayúsculas Y NO comienzan con
        # un signo de puntuación son artefactos del PDF de doble capa.
        # Excepción 1: tokens como "nEdN." se dejan pasar para que _clean_und_artifacts
        # recupere las letras reales (ej. "EN") que llevan interleadas.
        # Excepción 2: 'n' artefacto antes de '(' real (ej. 'n(AdR.RIBA' → '(ARRIBA'):
        # se descarta solo la 'n' inicial; el resto lo limpia _clean_und_artifacts.
        if len(text) >= 3 and text[0].islower() and any(c.isupper() for c in text):
            if re.match(r'^[nNeE][a-zA-Z]+[nNeEdD]\.?$', text):
                pass  # excepción 1: artefacto recuperable
            elif re.match(r'^n\(', text):
                text = text[1:]  # excepción 2: quitar 'n' artefacto, conservar '(…'
            else:
                continue
        cx = (w['x0'] + w['x1']) / 2
        best = None
        best_dist = float('inf')
        for col in columns:
            if col['x_start'] <= cx < col['x_end']:
                best = col
                break
            dist = min(abs(cx - col['x_start']), abs(cx - col['x_end']))
            if dist < best_dist:
                best_dist = dist
                best = col
        if best is None:
            continue
        # Filtrar tokens "Und." (y variantes) solo cuando NO van al campo de unidad de
        # medida — evita que aparezcan en descripción/código, pero los conserva en U.M.
        if nt in ('und', 'unid', 'unidad', 'unidades') and best['name'] not in unit_col_names:
            continue
        buckets[best['name']].append(text)
    return {k: ' '.join(v) for k, v in buckets.items()}


def _extract_by_words(page, existing_cols=None):
    """Extracción basada en posiciones de palabras."""
    try:
        words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False)
    except Exception:
        return None, [], None

    if not words:
        return None, [], None

    lines = _group_by_line(words)
    columns = existing_cols
    header_found_at = None

    if columns is None:
        # Encontrar la línea con MAYOR puntuación como encabezado
        best_score = 0
        for i, line in enumerate(lines):
            score = _score_header([' '.join(w['text'] for w in line)])
            if score > best_score and score >= 3:
                best_score = score
                header_found_at = i

        if header_found_at is None:
            return None, [], None

        header_ws = [w for w in lines[header_found_at]
                     if w['text'].strip() not in ('|', '-', '—', '*')]
        columns = _build_columns(header_ws, page.width)

        # ¿La línea ANTERIOR también es parte del encabezado (encabezado de 2 filas)?
        if header_found_at > 0:
            prev = lines[header_found_at - 1]
            prev_score = _score_header([' '.join(w['text'] for w in prev)])
            if prev_score >= 3 and not _is_separator_line(prev):
                _merge_prev_header(columns, prev)

        # ¿La línea SIGUIENTE es sub-encabezado?
        next_idx = header_found_at + 1
        if next_idx < len(lines):
            sub_line = lines[next_idx]
            sub_text = ' '.join(w['text'] for w in sub_line)
            if _is_separator_line(sub_line):
                # Línea separadora (----) — saltarla sin extender
                header_found_at = next_idx
            elif _score_header([sub_text]) < 3 and not _looks_like_product(sub_text):
                # Sub-encabezado real (no es fila de datos, no tiene keywords completos)
                _extend_with_subheader(columns, sub_line)
                header_found_at = next_idx  # Saltar también esta línea

    if not columns:
        return None, [], None

    headers = [col['name'] for col in columns]
    start = (header_found_at + 1) if header_found_at is not None else 0
    rows = []

    price_cols_set = {col['name'] for col in columns
                      if classify_column(col['name']) == 'price'}

    prev_was_product = False
    for line in lines[start:]:
        line_text = ' '.join(w['text'] for w in line)
        if _is_separator_line(line):
            prev_was_product = False
            continue
        if _is_skip_line(line_text):
            prev_was_product = False
            continue
        # OSAKA: fila de descripción explícita que empieza con la etiqueta "Descripción".
        # La etiqueta es señal inequívoca: siempre capturar, ignorar si hay texto en
        # columnas de precio (el texto de descripción puede caer en cualquier columna).
        if prev_was_product and re.match(r'[Dd]escripci[oó]n\b', line_text):
            row = _assign_to_columns(line, columns)
            if any(v.strip() for v in row.values()):
                rows.append(row)
            continue  # prev_was_product sigue True
        if _looks_like_product(line_text):
            row = _assign_to_columns(line, columns)
            # Parece producto pero sin código de producto ni precios: es continuación.
            # Ej: "YAMAHA RX 110/ RX115 SET-2" o "MRX 125 150(>2019)/ARIZONA BALINES"
            # que pasan _looks_like_product por tener múltiples tokens numéricos.
            if prev_was_product and not any(row.get(c, '').strip() for c in price_cols_set):
                first_name = columns[0]['name'] if columns else None
                fv = row.get(first_name, '').strip() if first_name else ''
                if fv and not _PRODUCT_CODE_START.match(fv):
                    rows.append(row)
                    continue  # prev_was_product sigue True
            if any(v.strip() for v in row.values()):
                rows.append(row)
                prev_was_product = True
            continue
        # Recoger líneas de continuación que no parecen producto (fallan _looks_like_product).
        # Requiere _CONTINUATION_PATTERN para no recoger "Unidades", notas, etc.
        # Solo bloquear si hay PRECIO (no qty): números de modelo caen en columna CANT.
        if (prev_was_product and _CONTINUATION_PATTERN.search(line_text)):
            row = _assign_to_columns(line, columns)
            has_price = any(row.get(c, '').strip() for c in price_cols_set)
            if not has_price and any(v.strip() for v in row.values()):
                rows.append(row)
                # prev_was_product sigue True: puede haber múltiples continuaciones
            else:
                prev_was_product = False
        else:
            prev_was_product = False

    return headers, rows, columns


# ──────────────────────────────────────────────────────────────
# Función principal
# ──────────────────────────────────────────────────────────────

def extract_from_pdf(pdf_path: str) -> tuple[list, list]:
    """
    Extrae datos de productos de cualquier factura PDF.
    Retorna (headers, rows). Nunca lanza excepciones.
    """
    all_headers = None
    all_rows = []
    word_columns = None

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_headers = None
                page_rows = []
                page_tables = []

                # ── Estrategia 1: tablas ──
                try:
                    page_tables = page.extract_tables() or []
                    if page_tables:
                        result = _find_best_table(page_tables)
                        if result:
                            h_idx, table = result
                            page_headers, page_rows = _extract_from_table(h_idx, table)
                except Exception:
                    pass

                # ── Continuación multi-página: tabla sin encabezado ──
                if not page_rows and all_headers and page_tables:
                    for table in page_tables:
                        if not table or len(table[0]) != len(all_headers):
                            continue
                        for row in table:
                            vals = [_clean_cell(c) for c in row]
                            row_text = ' '.join(vals)
                            if not _looks_like_product(row_text):
                                continue
                            if _FOOTER_RE.search(row_text):
                                continue
                            row_dict = {h: (vals[i] if i < len(vals) else '')
                                        for i, h in enumerate(all_headers)}
                            page_rows.append(row_dict)
                        if page_rows:
                            page_headers = all_headers
                            break

                # ── Estrategia 2: posiciones de palabras ──
                if not page_rows:
                    try:
                        ph, pr, wc = _extract_by_words(
                            page, word_columns if all_headers else None
                        )
                        if ph:
                            page_headers, page_rows = ph, pr
                            if wc:
                                word_columns = wc
                    except Exception:
                        pass

                # Acumular
                if page_headers and not all_headers:
                    all_headers = page_headers
                if page_rows:
                    if all_headers and page_headers and set(page_headers) != set(all_headers):
                        for row in page_rows:
                            all_rows.append({h: row.get(h, '') for h in all_headers})
                    else:
                        all_rows.extend(page_rows)

    except Exception:
        pass

    if not all_headers:
        all_headers = []

    valid = [h for h in all_headers if h and h.strip() and not re.match(r'^Col\d+$', h)]
    if not valid:
        valid = all_headers

    clean_rows = []
    for row in all_rows:
        r = {h: row.get(h, '') for h in valid}
        if any(v.strip() for v in r.values()):
            clean_rows.append(r)

    valid, clean_rows = _merge_fragmented_headers(valid, clean_rows)
    valid, clean_rows = _handle_mo_column(valid, clean_rows)
    valid, clean_rows = _merge_description_label_rows(valid, clean_rows)
    valid, clean_rows = _drop_sparse_columns(valid, clean_rows)
    valid, clean_rows = _drop_zero_pct_columns(valid, clean_rows)
    clean_rows = _fix_unit_overflow(valid, clean_rows)
    clean_rows = _clean_tainted_cant(valid, clean_rows)
    clean_rows = _merge_continuation_rows(valid, clean_rows)
    clean_rows = _filter_product_rows(valid, clean_rows)
    clean_rows = _clean_und_artifacts(valid, clean_rows)
    clean_rows = _strip_trailing_units(valid, clean_rows)
    clean_rows = _split_code_description(valid, clean_rows)
    return valid, clean_rows
