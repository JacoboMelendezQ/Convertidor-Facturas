"""
Orquestador: recibe una ruta de PDF, extrae datos y genera Excel.
"""
import os
import shutil
import time
from pathlib import Path

from src.parsers.auto_detector import extract_from_pdf
from src.utils.excel_writer import write_excel


def _unique_path(path: str) -> str:
    """Agrega timestamp al nombre si el archivo ya existe."""
    if not os.path.exists(path):
        return path
    stem = Path(path).stem
    suffix = Path(path).suffix
    parent = Path(path).parent
    ts = int(time.time())
    return str(parent / f'{stem}_{ts}{suffix}')


def process_pdf(pdf_path: str,
                results_dir: str,
                processed_dir: str,
                progress_callback=None,
                move_when_done: bool = False) -> tuple[bool, str, str]:
    """
    Procesa un PDF de factura.
    Retorna (éxito: bool, mensaje: str, ruta_excel: str).
    progress_callback(msg) se llama con actualizaciones de estado.
    """
    pdf_name = Path(pdf_path).stem
    excel_name = pdf_name + '.xlsx'
    excel_path = _unique_path(os.path.join(results_dir, excel_name))

    def log(msg):
        if progress_callback:
            progress_callback(msg)

    log(f'Procesando: {Path(pdf_path).name}')

    try:
        headers, rows = extract_from_pdf(pdf_path)

        if not rows:
            # Generar Excel vacío con nota
            headers = headers or ['Sin datos']
            rows = [{'Sin datos': 'No se detectaron productos en este PDF'}]
            write_excel(headers, rows, excel_path)
            log(f'⚠ Sin productos detectados — Excel vacío generado')
        else:
            write_excel(headers, rows, excel_path)
            log(f'✅ {len(rows)} productos → {Path(excel_path).name}')

        # Mover PDF a PROCESADOS solo si viene de POR_PROCESAR (watchdog)
        if move_when_done:
            try:
                dest = _unique_path(os.path.join(processed_dir, Path(pdf_path).name))
                shutil.move(pdf_path, dest)
            except Exception:
                pass

        return True, f'{len(rows)} productos extraídos', excel_path

    except Exception as e:
        msg = f'❌ Error procesando {Path(pdf_path).name}: {e}'
        log(msg)
        return False, str(e), ''
