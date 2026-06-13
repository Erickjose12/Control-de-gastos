# Finanzas Local

Sistema web local para controlar ingresos, gastos e importaciones bancarias en Quetzales.

La app corre en tu computadora y guarda los datos en SQLite dentro de `data/finanzas.db`.

## Funciones

- Dashboard mensual de ingresos, gastos, balance y ahorro.
- Cuentas preconfiguradas para GYT, BAM, efectivo y otros.
- Importacion de CSV.
- Importacion de PDF para estados de cuenta GYT con formato similar al machote probado.
- Bandeja de revision antes de registrar movimientos.
- Clasificacion inicial por reglas simples.
- Flujo para evitar duplicar pagos de tarjeta marcandolos como transferencia/ignorar.

## Requisitos

- Windows, macOS o Linux.
- Python 3.10 o superior.

## Uso Rapido En Windows

1. Descarga o clona este proyecto.
2. Abre la carpeta del proyecto.
3. Ejecuta:

```bat
scripts\start_windows.bat
```

El script crea un entorno virtual, instala dependencias y abre:

```text
http://127.0.0.1:8765
```

## Uso Manual

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python server.py
```

En macOS/Linux:

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python server.py
```

## Datos

Los datos locales viven en:

```text
data/finanzas.db
```

Ese archivo no se debe subir a GitHub porque puede contener informacion financiera personal.

## Importacion

Para CSV:

- Usa el boton de importar.
- Selecciona banco, producto y cuenta.
- Revisa tipo, categoria y accion.
- Marca `Pasar a Ingresos`, `Pasar a Gastos` o `Ignorar / transferencia`.
- Presiona `Registrar seleccionados`.

Para PDF:

- Actualmente se soporta el formato de estado de cuenta GYT probado.
- Otros PDFs pueden requerir un parser adicional.

## Siguientes Mejoras

- Importador especifico para tarjeta de credito GYT.
- Importador para BAM.
- Deteccion de duplicados.
- Reglas editables desde interfaz.
- Exportacion a Excel.
- Empaquetado como instalador de escritorio.
