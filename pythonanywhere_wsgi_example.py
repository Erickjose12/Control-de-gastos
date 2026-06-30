import os
import sys


# Cambia TU_USUARIO por tu usuario real de PythonAnywhere.
PROJECT_DIR = "/home/ejestrada26/Control-de-gastos"
DATA_DIR = "/home/ejestrada26/finanzas_data"

if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

os.environ["FINANZAS_DATA_DIR"] = DATA_DIR
os.environ["FINANZAS_AUTH"] = "1"
os.environ["FINANZAS_USER"] = "erick"
os.environ["FINANZAS_PASSWORD"] = "CAMBIA_ESTA_CLAVE"
os.environ["FINANZAS_SESSION_SECRET"] = "CAMBIA_ESTE_TEXTO_LARGO_ALEATORIO"

from wsgi import application  # noqa: E402
