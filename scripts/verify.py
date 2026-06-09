#!/usr/bin/env python3
"""
Auto-verification script for auto_detector.py and cleaner.py changes.

OBLIGATORIO: ejecutar después de CUALQUIER cambio en esos archivos.
Debe mostrar 8/8 PASSED antes de reportar éxito al usuario.

Uso:
    python scripts/verify.py
"""
import sys
import json
import pathlib
import re
import unicodedata

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.parsers.auto_detector import extract_from_pdf
from src.utils.cleaner import classify_column, parse_number

# ── Configuración ──────────────────────────────────────────────
GROUND_TRUTH_PATH = ROOT / 'data' / 'ground_truth.json'
PDF_DIR           = ROOT / 'data' / 'ejemplos_pdf'

JUNK_KEYWORDS = [
    'CCLL',
    'FECHA EXPEDICION',
    'JAPAN Y RACING',
    'PASEO BOLI',
    'grupojapaniracer',
    'BODEGA',
    'NIT:',
    'Pagina',
    'SOCIEDAD IMPORTADORA',
]

_CODE_PREFIXES = ('cod', 'item', 'ref', 'plu', 'sku')


# ── Utilidades ──────────────────────────────────────────────────
def _norm(s: str) -> str:
    return unicodedata.normalize('NFKD', s.lower()).encode('ascii', 'ignore').decode()


def _find_code_col(headers: list):
    return next(
        (h for h in headers
         if any(_norm(h).startswith(p) for p in _CODE_PREFIXES)
         and 'descripcion' not in _norm(h)),
        None,
    )


def _find_desc_col(headers: list):
    return next((h for h in headers if 'descripci' in _norm(h)), None)


def _match_gt(pdf_name: str, gt: dict):
    name_up = pdf_name.upper()
    for key, val in gt.items():
        if key.upper() in name_up:
            return key, val
    return None, None


# ── Verificación de un PDF ──────────────────────────────────────
def verify_one(pdf_path: pathlib.Path, expected: dict) -> tuple[int, list[str]]:
    errors = []

    try:
        headers, rows = extract_from_pdf(str(pdf_path))
    except Exception as exc:
        return 0, [f"extract_from_pdf lanzó excepción: {exc}"]

    # 1. Conteo de filas
    if 'filas' in expected and len(rows) != expected['filas']:
        errors.append(
            f"filas: obtuvo {len(rows)}, esperaba {expected['filas']}"
        )

    code_col = _find_code_col(headers)
    desc_col = _find_desc_col(headers)
    qty_cols  = [h for h in headers if classify_column(h) == 'qty']

    for i, row in enumerate(rows):
        row_num   = i + 1
        row_text  = ' '.join(str(v) for v in row.values())

        # 2. Texto basura
        for kw in JUNK_KEYWORDS:
            if kw.upper() in row_text.upper():
                errors.append(f"fila {row_num}: texto basura '{kw}'")
                break  # un error de basura por fila es suficiente

        # 3. Descripción vacía
        if desc_col:
            if not row.get(desc_col, '').strip():
                errors.append(f"fila {row_num}: descripcion vacia")

        # 4. Código vacío (solo cuando hay columna de código separada)
        if code_col and code_col != desc_col:
            if not row.get(code_col, '').strip():
                errors.append(f"fila {row_num}: codigo vacio en '{code_col}'")

        # 5. Cantidad = 0 cuando hay dígitos (parse fallido o valor real 0)
        for qc in qty_cols:
            val = row.get(qc, '').strip()
            if val and re.search(r'\d', val) and parse_number(val) == 0.0:
                errors.append(
                    f"fila {row_num}: cantidad=0 en '{qc}' "
                    f"(valor crudo={repr(val)}) — posible bug en parse_number"
                )

    return len(rows), errors


# ── Main ────────────────────────────────────────────────────────
def main() -> int:
    if not GROUND_TRUTH_PATH.exists():
        print(f"ERROR: {GROUND_TRUTH_PATH} no encontrado")
        return 1

    gt   = json.loads(GROUND_TRUTH_PATH.read_text(encoding='utf-8'))
    pdfs = sorted(PDF_DIR.glob('*.pdf'))

    if not pdfs:
        print(f"ERROR: no hay PDFs en {PDF_DIR}")
        return 1

    passed  = 0
    failed  = 0
    skipped = 0

    print(f"Verificando {len(pdfs)} PDFs contra ground truth...\n")

    for pdf in pdfs:
        gt_key, expected = _match_gt(pdf.name, gt)
        if expected is None:
            print(f"  [SKIP]  {pdf.name[:58]}")
            skipped += 1
            continue

        n_rows, errors = verify_one(pdf, expected)

        if not errors:
            print(f"  [PASS]  {pdf.name[:55]}  ({n_rows} filas)")
            passed += 1
        else:
            print(f"  [FAIL]  {pdf.name[:55]}  ({n_rows} filas)")
            shown = errors[:6]
            for e in shown:
                print(f"          - {e}")
            if len(errors) > 6:
                print(f"          ... y {len(errors) - 6} errores más")
            failed += 1

    total = passed + failed
    sep   = '=' * 58
    print(f"\n{sep}")
    print(f"Resultado: {passed}/{total} PASSED  ({skipped} sin ground truth)")

    if failed == 0 and total > 0:
        print("TODOS LOS TESTS EN VERDE — seguro reportar exito al usuario")
        return 0
    else:
        print("HAY FALLOS — NO reportar exito hasta corregir y re-ejecutar")
        return 1


if __name__ == '__main__':
    sys.exit(main())
