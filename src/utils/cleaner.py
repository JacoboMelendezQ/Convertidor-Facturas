"""
Limpieza y normalización de valores numéricos.
Maneja formato COP (1.234,56) y USA (1,234.56).
"""
import re
import unicodedata


def normalize_text(s: str) -> str:
    """Elimina tildes y convierte a minúsculas para comparaciones."""
    return unicodedata.normalize('NFKD', s.lower()).encode('ascii', 'ignore').decode()


def parse_number(val) -> float:
    """Convierte un valor numérico en string a float.
    Detecta automáticamente formato COP (punto miles, coma decimal)
    o USA (coma miles, punto decimal).
    """
    if val is None:
        return 0.0
    s = str(val).strip()
    # Quitar etiqueta de unidad al final: "5.00 BOX" → "5.00", "60.00 UND" → "60.00"
    s = re.sub(r'\s+[A-Za-z]+$', '', s)
    # Quitar símbolos monetarios y espacios
    s = re.sub(r'[$\s]', '', s)
    s = s.rstrip('%')
    if not s or s in ('-', '—', 'N/A', 'n/a'):
        return 0.0

    has_comma = ',' in s
    has_dot = '.' in s

    if has_comma and has_dot:
        last_comma = s.rfind(',')
        last_dot = s.rfind('.')
        if last_comma > last_dot:
            # COP: 1.234,56 → punto=miles, coma=decimal
            s = s.replace('.', '').replace(',', '.')
        else:
            # USA: 1,234.56 → coma=miles, punto=decimal
            s = s.replace(',', '')
    elif has_comma:
        # Solo coma: miles USA (1,234 o 2,121,280) o decimal COP (1234,56)
        if re.match(r'^\d{1,3}(,\d{3})+$', s):
            # Formato USA con uno o más grupos de miles: 1,234 o 2,121,280
            s = s.replace(',', '')
        else:
            # Decimal COP: 1234,56
            s = s.replace(',', '.')
    elif has_dot:
        if s.count('.') > 1:
            # Múltiples puntos: separadores de miles (ej. 1.562.000, 2.286.000)
            parts = s.split('.')
            if all(len(p) == 3 and p.isdigit() for p in parts[1:]):
                s = s.replace('.', '')
        else:
            dot_pos = s.rfind('.')
            after = s[dot_pos + 1:]
            if len(after) == 3 and after.isdigit():
                # Miles COP: 1.234
                s = s.replace('.', '')
            # else: decimal USA — dejar como está

    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_percentage(val) -> float:
    """Extrae el valor numérico de un porcentaje. '30%' → 30.0, '30.00% 0.00%' → 30.0"""
    if val is None:
        return 0.0
    s = str(val).strip()
    # Si hay múltiples porcentajes (ej. "30.00% 0.00%"), tomar el primero
    if '%' in s:
        s = s.split('%')[0].strip()
    return parse_number(s)


def classify_column(name: str) -> str:
    """Retorna 'price', 'qty', 'pct', o 'text' según el nombre de columna."""
    n = normalize_text(str(name))
    if any(kw in n for kw in ['precio', 'valor', 'total', 'importe', 'subtotal',
                               'vr.', ' vr', 'monto', 'vlr', 'unitari']):
        return 'price'
    if any(kw in n for kw in ['cant', 'cantidad', 'unidades', 'cajas', 'und']):
        return 'qty'
    if any(kw in n for kw in ['%', 'iva', 'dcto', 'descuento',
                               'recarg', 'impuest', 'imptos', 'impto']):
        return 'pct'
    return 'text'


def find_value_column(headers: list) -> str | None:
    """Identifica la columna de valor final para poner la fórmula TOTAL."""
    priority = [
        'valor total', 'vr. total', 'vr total', 'total', 'importe',
        'subtotal', 'valor_total', 'valor unit final', 'vr.total'
    ]
    normalized_headers = [(h, normalize_text(h)) for h in headers]
    for keyword in priority:
        for h, nh in reversed(normalized_headers):  # último que coincida
            if keyword in nh:
                return h
    # Fallback: última columna que sea 'price'
    for h in reversed(headers):
        if classify_column(h) == 'price':
            return h
    return None
