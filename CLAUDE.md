# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Agente Facturas V3** is a Python Windows desktop application with a Tkinter GUI that processes PDF invoices from 15 suppliers, extracts product line-items using a universal table detector, and outputs formatted Excel files.

Main entry point: `main.py`

## REGLA OBLIGATORIA: Verificación Automática

> **NUNCA reportar éxito de un fix hasta ver 15/15 PASSED.**

Después de **CUALQUIER** cambio en `auto_detector.py` o `cleaner.py`:

```bash
python scripts/verify.py
```

Protocolo:
1. Ejecutar `python scripts/verify.py`
2. Si algún test falla → corregir el código y volver al paso 1
3. Solo cuando la salida muestre **15/15 PASSED** → reportar éxito al usuario

El script valida por cada PDF (actualmente 15 PDFs, 15/15 PASSED):
- Conteo de filas coincide con `data/ground_truth.json`
- Sin texto basura (CCLL, FECHA EXPEDICION, JAPAN Y RACING, etc.)
- Sin descripciones vacías
- Sin códigos vacíos
- Sin cantidades que parseen a 0 cuando tienen dígitos

Para agregar un nuevo proveedor: procesar el PDF, verificar manualmente el xlsx,
y añadir su entrada en `data/ground_truth.json`.

---

## Commands

**Run the application (Python):**
```bash
python main.py
```

**Build Windows executable (single .exe, no console):**
```bash
pyinstaller agente_facturas.spec
# Output: dist/Agente_Facturas_V3.exe
```

**Quick extraction test (no GUI):**
```bash
python -c "
from src.parsers.auto_detector import extract_from_pdf
h, rows = extract_from_pdf('data/ejemplos_pdf/SOMEFILE.pdf')
print(h); [print(r) for r in rows[:3]]
"
```

**Test manually:** Drop a PDF into `data/POR_PROCESAR/`. Results appear in `data/RESULTADOS/`. Processed PDFs move to `data/PROCESADOS/`.

## Dependencies

No `requirements.txt` — install manually:
- `pdfplumber` — PDF text extraction
- `openpyxl` — Excel file creation
- `watchdog` — Filesystem event monitoring
- `tkinterdnd2` — Drag & drop support (optional; app falls back gracefully)
- `pyinstaller` — Build tool (dev only)

## Architecture

The app follows a **GUI / folder-watch → parse → export** pipeline:

```
GUI (Tkinter)          drag & drop / file picker
  │                         │
  └──────────┬──────────────┘
             ▼
        process_pdf()          src/core/processor.py
             ├── extract_from_pdf()    src/parsers/auto_detector.py
             ├── write_excel()         src/utils/excel_writer.py
             └── shutil.move → data/PROCESADOS/
                           data/RESULTADOS/<invoice>.xlsx

Folder watcher (watchdog)    src/core/watcher.py
  Monitors data/POR_PROCESAR/ and calls process_pdf() on new PDFs
```

**Directory layout** (relative to `main.py` / .exe):
```
data/
  POR_PROCESAR/    # Watched input folder
  PROCESADOS/      # Archive of processed PDFs
  RESULTADOS/      # Output Excel files
  ejemplos_pdf/    # Reference PDFs for testing (15 suppliers)
src/
  parsers/
    auto_detector.py   # Universal table extractor
  core/
    processor.py       # Orchestrator
    watcher.py         # Watchdog handler
  utils/
    cleaner.py         # Number parsing (COP/USA formats)
    excel_writer.py    # openpyxl output with formatting
  gui/
    app.py             # Tkinter GUI
main.py                # Entry point; sets BASE_DIR
agente_facturas.spec   # PyInstaller build config
```

`BASE_DIR` is set in `main.py` as `sys.executable` directory (frozen) or `__file__` directory (script).

## Supported Invoice Formats

The **universal detector** (`auto_detector.py`) handles all formats without per-supplier regex. It uses two strategies in sequence:

| Strategy | How | Best for |
|----------|-----|----------|
| 1. pdfplumber tables | `page.extract_tables()` + header scoring | AKT, FR, HA |
| 2. Word positions | `page.extract_words()` + column alignment | FEV, JAPAN, CHOHO, ROKO |

Merged/fused cells detected and rejected (falls back to strategy 2).

| Supplier | Example file |
|----------|-------------|
| AKT MOTOS | `AKT MOTOS ad0890900943006260041C421 (1).pdf` |
| CHOHO | `CHOHO FEBRERO (1).pdf` |
| FEV | `FEV04706.pdf` |
| FR / REPREFIL (formato 1) | `FR1214 MELENDEZ.pdf` |
| FR / REPREFIL (formato 2) | `FR1225.pdf` |
| HA / HABICICLETS | `ha8888888888888888888.pdf` |
| JAPAN RACER (formato 1, Orden de Venta) | `JAPAN PENDIENTE DESCUENTO Orden_de_venta_S05177 (1).pdf` |
| JAPAN RACER (formato 2, Factura Electrónica) | `JAPAN FACTURA ELECTRONICA.pdf` |
| DISTRI JYG / ENER | `ENER MELENDEZ ALMACEN HJM #359 (1).pdf` |
| OSAKA (formato 1) | `osaka.pdf` |
| OSAKA (formato 2) | `osaka2.pdf` |
| OMNIPARTS | `omniparts.pdf` |
| SAI RAM | `SAIMRAM.pdf` |
| FANALCA / Fábrica Nacional de Autopartes | `FANALCA JUNIO 26..pdf` |
| CORBETA / AKT MOTOS (layout 2, NIT 890900943 compartido con AKT) | `CORBETA JUNIO 28.pdf` |

> **CORBETA columnas:** `PLU | CODIGO-EAN13 | DESCRIPCION | TOTAL UNIDADES | Vr | %DESC | SUBTOTAL | %IVA | Vr. TOTAL`
> Detectado por NIT `890900943` + líneas con prefijo `N|` (layout distinto al AKT original de 1 fila).

## Key Functions

- `extract_from_pdf(pdf_path)` — returns `(headers: list, rows: list[dict])`. Never raises; returns empty on failure.
- `_find_best_table(tables)` — scores each table's header row by keyword overlap; rejects fused cells.
- `_extract_by_words(page, existing_cols)` — builds column map from header word positions; handles 2-row headers.
- `write_excel(headers, rows, output_path)` — openpyxl workbook: blue header row, TOTAL row with SUM formula, auto column width, freeze pane at A2.
- `classify_column(name)` — returns `'price'`, `'qty'`, `'pct'`, or `'text'` from column name.
- `parse_number(val)` — disambiguates COP format (`1.234,56`) vs USA (`1,234.56`).
- `process_pdf(pdf_path, results_dir, processed_dir, callback)` — orchestrates extract → save → move; calls `callback(msg)` for GUI log updates.

## Known Issues (as of 2026-06-29)

- **Terminal display of accented chars** — `Ó`, `Á`, `É` appear as `?` in Windows bash/cmd terminal output. This is a terminal rendering artifact only; the Python strings and Excel cells contain correct Unicode (U+00D3, U+00C1, etc.). Open the xlsx in Excel to confirm correct accents.
- **CHOHO/FR/JAPAN: page-header rows in intermediate list** — running headers (company address, phone, customer info) pass `_looks_like_product()` and enter the row accumulator, but are correctly removed by `_filter_product_rows` before writing to Excel. Final output is clean.
- **ROKO format untested** — no example PDF available; word-position strategy should handle it but unverified.
