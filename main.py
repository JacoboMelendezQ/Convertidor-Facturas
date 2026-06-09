"""
Punto de entrada principal.
Detecta si corre como .exe (PyInstaller) o como script Python.
"""
import sys
import os

# Determinar directorio base
if getattr(sys, 'frozen', False):
    # Ejecutable compilado: buscar data/ junto al exe.
    # Si no existe (ej. exe en dist/ durante desarrollo), subir un nivel.
    _exe_dir = os.path.dirname(sys.executable)
    if os.path.isdir(os.path.join(_exe_dir, 'data')):
        BASE_DIR = _exe_dir
    else:
        BASE_DIR = os.path.dirname(_exe_dir)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Agregar src al path para imports
sys.path.insert(0, BASE_DIR)

from src.gui.app import App


def main():
    app = App(BASE_DIR)
    app.run()


if __name__ == '__main__':
    main()
