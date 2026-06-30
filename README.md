# Finanzas Local

Sistema web local para controlar ingresos, gastos e importaciones bancarias en Quetzales.

La app corre en tu computadora y guarda los datos en SQLite dentro de `data/finanzas.db`.

## Funciones

- Dashboard mensual de ingresos, gastos, balance y ahorro.
- Cuentas preconfiguradas para GYT, BAC, Banrural, efectivo y otros.
- Importacion de CSV.
- Importacion de PDF para estados de cuenta GYT con formato similar al machote probado.
- Bandeja de revision antes de registrar movimientos.
- Clasificacion inicial por reglas simples.
- Registro manual de ahorro a Banrural y venta de dolares.
- Flujo para evitar duplicar pagos de tarjeta marcandolos como transferencia/ignorar.

## Modelo De Uso

La app esta pensada para este flujo mensual:

- `GYT - Cuenta ahorro sueldo`: recibe el primer sueldo y desde ahi se paga tarjeta, debito/efectivo y ahorro.
- `GYT - Tarjeta credito`: registra consumos reales de tarjeta.
- `GYT - Tarjeta debito`: registra retiros o pagos que salen de la cuenta GYT.
- `BAC - Cuenta ahorro USD`: recibe el segundo sueldo en dolares.
- `Banrural - Cuenta ahorro`: recibe el ahorro y el dinero de venta de dolares.

El dashboard separa:

- `Ingreso`: sueldos y entradas reales.
- `Gasto`: consumos reales del mes.
- `Ahorro`: dinero enviado a Banrural.
- `Venta USD`: venta manual de dolares convertida a Quetzales.
- `Transferencia`: movimientos entre tus propias cuentas o pago de tarjeta que no deben contar como gasto.

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

## Modo Demo Para Compartir

Si queres que otra persona pruebe el sistema sin usar tus datos reales, ejecuta:

```bat
scripts\start_demo_windows.bat
```

Ese modo usa una base separada:

```text
data_demo/finanzas.db
```

Cada vez que se inicia el modo demo desde ese script, se reinicia la base demo y se cargan datos ficticios. Tu base real sigue en:

```text
data/finanzas.db
```

### Compartir temporalmente por internet

Para una prueba corta, podes compartir tu app local con un tunel. Tu computadora debe quedar encendida y el servidor demo abierto.

Con Cloudflare Tunnel:

```bat
cloudflared tunnel --url http://localhost:8765
```

Cloudflare genera una URL temporal de `trycloudflare.com` para compartir. Esta opcion es para pruebas y desarrollo.

Con ngrok:

```bat
ngrok http 8765
```

ngrok muestra una URL HTTPS publica que apunta a tu app local.

Importante: aunque la app ya tiene login, para compartir datos reales conviene usar una clave fuerte, una URL HTTPS y un almacenamiento persistente.

## Login Y Seguridad

La app protege las rutas de datos con usuario, contrasena y sesion por cookie.

Credenciales locales por defecto:

```text
Usuario: erick
Contrasena: cambiar-esta-clave
```

Antes de compartirla o subirla a internet, cambia esos valores con variables de entorno:

```bat
set FINANZAS_AUTH=1
set FINANZAS_USER=erick
set FINANZAS_PASSWORD=una-clave-larga-y-privada
set FINANZAS_SESSION_SECRET=un-texto-largo-aleatorio
set FINANZAS_HOST=0.0.0.0
```

Tambien podes usar hash SHA-256 en lugar de guardar la clave directa:

```bat
python -c "import hashlib; print(hashlib.sha256('tu-clave'.encode()).hexdigest())"
set FINANZAS_PASSWORD_HASH=hash-generado
```

Para hosting, configura tambien:

```text
FINANZAS_DATA_DIR=/ruta/persistente/data
PORT=8765
```

La carpeta `FINANZAS_DATA_DIR` debe ser persistente porque ahi vive SQLite y los documentos/fotos adjuntos.

## Subir A PythonAnywhere

La app incluye `wsgi.py` para poder correr en PythonAnywhere.

### 1. Subir el codigo

En PythonAnywhere, abre una consola Bash y clona el repositorio:

```bash
git clone https://github.com/Erickjose12/Control-de-gastos.git
```

Entra a la carpeta:

```bash
cd Control-de-gastos
```

Instala dependencias:

```bash
pip3 install --user -r requirements.txt
```

### 2. Crear carpeta persistente

La base de datos SQLite y los documentos adjuntos deben vivir fuera del repo:

```bash
mkdir -p /home/ejestrada26/finanzas_data
```

### 3. Crear la Web App

En PythonAnywhere:

- Entra a `Web`.
- Presiona `Add a new web app`.
- Elige tu dominio gratis `ejestrada26.pythonanywhere.com`.
- Elige `Manual configuration`.
- Elige la version de Python disponible.

### 4. Configurar el archivo WSGI

En la seccion `Code`, abre el archivo WSGI que te crea PythonAnywhere y pega este contenido, cambiando las claves:

```python
import os
import sys

PROJECT_DIR = "/home/ejestrada26/Control-de-gastos"
DATA_DIR = "/home/ejestrada26/finanzas_data"

if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

os.environ["FINANZAS_DATA_DIR"] = DATA_DIR
os.environ["FINANZAS_AUTH"] = "1"
os.environ["FINANZAS_USER"] = "erick"
os.environ["FINANZAS_PASSWORD"] = "pon-aqui-una-clave-fuerte"
os.environ["FINANZAS_SESSION_SECRET"] = "pon-aqui-un-texto-largo-aleatorio"

from wsgi import application
```

Tambien podes usar el archivo `pythonanywhere_wsgi_example.py` como referencia.

### 5. Recargar

Vuelve a la pestana `Web` y presiona `Reload`.

La app deberia quedar disponible en:

```text
https://ejestrada26.pythonanywhere.com
```

Importante: no subas `data/finanzas.db` ni PDFs reales a GitHub. Para pruebas publicas usa datos demo o datos falsos.

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

## Registro Manual

Usa el panel `Registro manual` para capturar:

- Cuanto ahorro ingresaste a Banrural.
- Cuantos dolares vendiste y cuanto recibiste en Quetzales.
- Ajustes puntuales que no vengan en un estado de cuenta.

## Siguientes Mejoras

- Importador especifico para tarjeta de credito GYT.
- Importador para BAM.
- Deteccion de duplicados.
- Reglas editables desde interfaz.
- Exportacion a Excel.
- Empaquetado como instalador de escritorio.
