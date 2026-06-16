# Convertidor de Facturas — Agente Facturas V3

Aplicación de escritorio para Windows que convierte automáticamente facturas PDF de proveedores de repuestos a archivos Excel listos para calcular precios de venta. No requiere Python instalado.

## ¿Qué hace?

- Detecta el proveedor automáticamente según el formato del PDF
- Extrae código, descripción, cantidad, precio unitario y valor total por producto
- Genera un Excel limpio con fila de totales y formato listo para usar
- Interfaz gráfica con arrastrar y soltar — sin línea de comandos

## Descarga

Ir a [Releases](https://github.com/JacoboMelendezQ/Convertidor-Facturas/releases) y descargar `Agente_Facturas_V3.exe`.

## Uso

1. Abrir `Agente_Facturas_V3.exe`
2. Arrastrar la factura PDF a la ventana, o usar el botón **"Buscar archivos PDF"**
3. El Excel se genera automáticamente en la carpeta `RESULTADOS/`

## Proveedores soportados (12 formatos)

| Proveedor | Estrategia de extracción |
|---|---|
| AKT MOTOS | Tablas PDF |
| CHOHO | Posición de palabras |
| DISTRI JYG / ENER | Posición de palabras |
| FEV | Posición de palabras |
| FR / REPREFIL (formato 1) | Tablas PDF |
| FR / REPREFIL (formato 2) | Tablas PDF |
| HA / HABICICLETS | Tablas PDF |
| JAPAN RACER | Posición de palabras |
| OMNIPARTS | Posición de palabras |
| OSAKA (formato 1) | Posición de palabras |
| OSAKA (formato 2) | Posición de palabras |
| SAI RAM | Posición de palabras |

## Para desarrolladores

### Estructura del proyecto

```
src/
├── parsers/auto_detector.py   ← detección y extracción por proveedor
├── utils/cleaner.py           ← normalización de números (formato COP/USA)
├── core/processor.py          ← orquestador del pipeline
└── gui/app.py                 ← interfaz Tkinter

scripts/
└── verify.py                  ← suite de pruebas automáticas (12/12 PASSED)

data/
└── ground_truth.json          ← conteos esperados por proveedor
```

### Agregar un proveedor nuevo

1. Copiar el PDF a `data/ejemplos_pdf/`
2. Procesar manualmente y verificar el Excel generado
3. Agregar la entrada en `data/ground_truth.json`
4. Implementar el parser en `auto_detector.py` si es necesario
5. Correr `python scripts/verify.py` → debe mostrar 13/13 PASSED
6. Recompilar: `pyinstaller agente_facturas.spec`

### Compilar el ejecutable

```bash
pyinstaller agente_facturas.spec
# Output: dist/Agente_Facturas_V3.exe
```

### Dependencias

```bash
pip install pdfplumber openpyxl watchdog tkinterdnd2
```

## Tecnologías

Python · pdfplumber · openpyxl · Tkinter · PyInstaller · Claude Code
