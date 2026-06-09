"""
Vigilancia de carpeta POR_PROCESAR con watchdog.
"""
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from src.core.processor import process_pdf


class PdfHandler(FileSystemEventHandler):
    def __init__(self, results_dir: str, processed_dir: str, callback=None):
        self.results_dir = results_dir
        self.processed_dir = processed_dir
        self.callback = callback  # callback(msg) para log en GUI

    def _handle(self, path: str):
        if Path(path).suffix.lower() == '.pdf' and Path(path).exists():
            time.sleep(1)  # Esperar a que el archivo esté completamente escrito
            process_pdf(path, self.results_dir, self.processed_dir, self.callback,
                        move_when_done=True)

    def on_created(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._handle(event.dest_path)


def start_watcher(watch_dir: str, results_dir: str, processed_dir: str,
                  callback=None) -> Observer:
    """Inicia el Observer en background. Retorna el Observer (llamar .stop() para detener)."""
    handler = PdfHandler(results_dir, processed_dir, callback)
    observer = Observer()
    observer.schedule(handler, watch_dir, recursive=False)
    observer.start()
    return observer
