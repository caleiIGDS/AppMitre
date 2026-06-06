import urllib.request
import io
import csv
from config import SHEET_ID, GIDS_CURSOS

# Usamos el GID del 1er año para la prueba
GID = GIDS_CURSOS[1]

url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID}"

try:
    with urllib.request.urlopen(url) as response:
        contenido = response.read().decode('utf-8')
        print("STATUS:", response.status)
        print("PRIMERAS LÍNEAS:")
        print(contenido[:500])
except Exception as e:
    print("ERROR:", e)