import urllib.request
import io
import csv

SHEET_ID = "1GJxwpxXfLosqKxgIa6zyZhwjDK-89ZDavLi6nouWTsw"
GID = "1041328323"

url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID}"

try:
    with urllib.request.urlopen(url) as response:
        contenido = response.read().decode('utf-8')
        print("STATUS:", response.status)
        print("PRIMERAS LÍNEAS:")
        print(contenido[:500])
except Exception as e:
    print("ERROR:", e)