"""
Interfaz gráfica principal.
Tkinter + tkinterdnd2 para drag & drop.
Diseñada para usuarios no técnicos: fuente grande, botones claros.
"""
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, scrolledtext
from pathlib import Path

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND_AVAILABLE = True
except ImportError:
    _DND_AVAILABLE = False

from src.core.processor import process_pdf
from src.core.watcher import start_watcher

# ── Colores y fuentes ──
BG_MAIN = '#F0F4FA'
BG_DROP = '#E8F0FE'
BG_DROP_HOVER = '#C5D8FC'
FG_TITLE = '#1A237E'
FG_BTN = '#FFFFFF'
BG_BTN_PRIMARY = '#1565C0'
BG_BTN_HOVER = '#0D47A1'
BG_BTN_SECONDARY = '#43A047'
BG_BTN_SEC_HOVER = '#2E7D32'
FONT_TITLE = ('Arial', 16, 'bold')
FONT_NORMAL = ('Arial', 12)
FONT_SMALL = ('Arial', 10)
FONT_LOG = ('Courier New', 10)


class App:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.watch_dir = os.path.join(base_dir, 'data', 'POR_PROCESAR')
        self.results_dir = os.path.join(base_dir, 'data', 'RESULTADOS')
        self.processed_dir = os.path.join(base_dir, 'data', 'PROCESADOS')

        for d in [self.watch_dir, self.results_dir, self.processed_dir]:
            os.makedirs(d, exist_ok=True)

        # Ventana principal
        if _DND_AVAILABLE:
            self.root = TkinterDnD.Tk()
        else:
            self.root = tk.Tk()

        self.root.title('Agente Facturas V3 — Conversor de PDF a Excel')
        self.root.geometry('680x580')
        self.root.configure(bg=BG_MAIN)
        self.root.resizable(True, True)
        self.root.minsize(500, 450)

        self._build_ui()
        self._start_watcher()

    def _build_ui(self):
        root = self.root

        # ── Título ──
        tk.Label(root, text='📄 Conversor de Facturas PDF a Excel',
                 font=FONT_TITLE, bg=BG_MAIN, fg=FG_TITLE,
                 pady=12).pack(fill='x', padx=20)

        # ── Zona de drop ──
        self.drop_frame = tk.Frame(root, bg=BG_DROP, relief='groove',
                                   bd=2, cursor='hand2')
        self.drop_frame.pack(fill='x', padx=20, pady=(0, 10), ipady=18)

        self.drop_label = tk.Label(
            self.drop_frame,
            text='⬇   Arrastra aquí los archivos PDF   ⬇\n\no usa el botón de abajo',
            font=FONT_NORMAL, bg=BG_DROP, fg='#3949AB', justify='center'
        )
        self.drop_label.pack(expand=True)

        if _DND_AVAILABLE:
            self.drop_frame.drop_target_register(DND_FILES)
            self.drop_frame.dnd_bind('<<Drop>>', self._on_drop)
            self.drop_frame.dnd_bind('<<DragEnter>>', self._on_drag_enter)
            self.drop_frame.dnd_bind('<<DragLeave>>', self._on_drag_leave)
        else:
            self.drop_label.config(
                text='⬇   Selecciona archivos PDF con el botón   ⬇',
            )

        # ── Botones ──
        btn_frame = tk.Frame(root, bg=BG_MAIN)
        btn_frame.pack(fill='x', padx=20, pady=4)

        self.btn_open = _make_button(
            btn_frame, '📂  Buscar archivos PDF', BG_BTN_PRIMARY, BG_BTN_HOVER,
            self._browse_files
        )
        self.btn_open.pack(side='left', expand=True, fill='x', padx=(0, 6))

        self.btn_results = _make_button(
            btn_frame, '📁  Ver resultados', BG_BTN_SECONDARY, BG_BTN_SEC_HOVER,
            self._open_results
        )
        self.btn_results.pack(side='left', expand=True, fill='x')

        # ── Separador ──
        tk.Frame(root, bg='#BBDEFB', height=1).pack(fill='x', padx=20, pady=8)

        # ── Log ──
        tk.Label(root, text='Registro de actividad:',
                 font=FONT_SMALL, bg=BG_MAIN, fg='#546E7A',
                 anchor='w').pack(fill='x', padx=20)

        self.log_box = scrolledtext.ScrolledText(
            root, font=FONT_LOG, bg='#FAFAFA', fg='#212121',
            relief='flat', bd=1, wrap='word', state='disabled',
            height=14
        )
        self.log_box.pack(fill='both', expand=True, padx=20, pady=(4, 8))

        # Colorear tags en el log
        self.log_box.tag_config('ok', foreground='#2E7D32')
        self.log_box.tag_config('err', foreground='#C62828')
        self.log_box.tag_config('info', foreground='#1565C0')

        # ── Barra de estado ──
        self.status_var = tk.StringVar(value='Listo. Esperando archivos PDF...')
        tk.Label(root, textvariable=self.status_var,
                 font=FONT_SMALL, bg='#E3F2FD', fg='#0D47A1',
                 anchor='w', padx=10, pady=4).pack(fill='x')

    # ── Eventos drag & drop ──

    def _on_drag_enter(self, event):
        self.drop_frame.config(bg=BG_DROP_HOVER)
        self.drop_label.config(bg=BG_DROP_HOVER)

    def _on_drag_leave(self, event):
        self.drop_frame.config(bg=BG_DROP)
        self.drop_label.config(bg=BG_DROP)

    def _on_drop(self, event):
        self.drop_frame.config(bg=BG_DROP)
        self.drop_label.config(bg=BG_DROP)
        # Los paths vienen como string con {} para rutas con espacios
        raw = event.data
        paths = self.root.tk.splitlist(raw)
        pdfs = [p for p in paths if p.lower().endswith('.pdf')]
        if pdfs:
            self._process_files(pdfs)

    # ── Botones ──

    def _browse_files(self):
        paths = filedialog.askopenfilenames(
            title='Seleccionar facturas PDF',
            filetypes=[('Archivos PDF', '*.pdf'), ('Todos', '*.*')]
        )
        if paths:
            self._process_files(list(paths))

    def _open_results(self):
        try:
            os.startfile(self.results_dir)
        except Exception:
            pass

    # ── Procesamiento ──

    def _process_files(self, paths: list):
        def worker():
            total = len(paths)
            for i, path in enumerate(paths, 1):
                self._set_status(f'Procesando {i}/{total}: {Path(path).name}')
                process_pdf(
                    path,
                    self.results_dir,
                    self.processed_dir,
                    self._log
                )
            self._set_status(f'Listo. {total} archivo(s) procesado(s).')

        threading.Thread(target=worker, daemon=True).start()

    def _start_watcher(self):
        def callback(msg):
            self._log(msg)

        try:
            self._observer = start_watcher(
                self.watch_dir, self.results_dir, self.processed_dir, callback
            )
            self._log(f'ℹ Vigilando carpeta: {self.watch_dir}', tag='info')
        except Exception as e:
            self._log(f'Aviso: vigilancia de carpeta no disponible ({e})', tag='err')

    # ── Utilidades UI ──

    def _log(self, msg: str, tag: str = None):
        """Agrega una línea al log. Thread-safe."""
        def _insert():
            self.log_box.config(state='normal')
            if tag is None:
                if '✅' in msg or 'productos' in msg.lower():
                    t = 'ok'
                elif '❌' in msg or 'Error' in msg:
                    t = 'err'
                else:
                    t = 'info'
            else:
                t = tag
            self.log_box.insert('end', msg + '\n', t)
            self.log_box.see('end')
            self.log_box.config(state='disabled')

        try:
            self.root.after(0, _insert)
        except Exception:
            pass

    def _set_status(self, msg: str):
        try:
            self.root.after(0, lambda: self.status_var.set(msg))
        except Exception:
            pass

    def run(self):
        self.root.mainloop()
        if hasattr(self, '_observer'):
            self._observer.stop()
            self._observer.join()


# ── Helper para botones ──

def _make_button(parent, text, bg, hover_bg, command):
    btn = tk.Button(
        parent, text=text, font=FONT_NORMAL,
        bg=bg, fg=FG_BTN, activebackground=hover_bg, activeforeground=FG_BTN,
        relief='flat', bd=0, padx=10, pady=8, cursor='hand2',
        command=command
    )
    btn.bind('<Enter>', lambda e: btn.config(bg=hover_bg))
    btn.bind('<Leave>', lambda e: btn.config(bg=bg))
    return btn
