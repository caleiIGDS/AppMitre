import csv
from datetime import datetime

# Orden correcto de días
orden_dias = {
    "Lunes": 0,
    "Martes": 1,
    "Miércoles": 2,
    "Jueves": 3,
    "Viernes": 4
}

def parse_hora(hora):
    hora = hora.strip()[:5]  # se queda solo con HH:MM
    return datetime.strptime(hora, "%H:%M")

# Leer CSV
with open("datos.csv", newline='', encoding="utf-8") as f:
    reader = csv.DictReader(f)
    filas = list(reader)
    headers = reader.fieldnames

# Ordenar
filas.sort(key=lambda x: (
    int(x["curso"]) if x["curso"] else 0,
    x["division"] or "",
    orden_dias.get(x["dia"], 99),
    parse_hora(x["hora_inicio"]) if x["hora_inicio"] else datetime.min
))

# Guardar CSV ordenado
with open("ordenado.csv", "w", newline='', encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=headers)
    writer.writeheader()
    writer.writerows(filas)