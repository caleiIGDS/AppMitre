#!/usr/bin/env python3
"""Test the complete api_guardar flow"""

import json
import sys
import os
sys.path.insert(0, '.')
os.environ.setdefault('FLASK_ENV', 'development')

from app import app
from crud import conectar, init_db as init_crud_db
import salidas
from config import ahora
from datetime import timedelta

# Inicializar bases de datos
print("Inicializando DBs...")
init_crud_db()
salidas.init_db()
print("✓ DBs inicializadas")

# Datos de prueba
test_payload = {
    "formato": "appmitre.salidas.v1",
    "resolucion": "RESOC-2024-3871-GDEBA-DGCYE",
    "generado": "2026-08-15T10:00:00Z",
    "datos_comunes": {
        "institucion_educativa": "EMILIO MITRE",
        "numero_institucion": "1",
        "distrito": "La Matanza",
        "denominacion_proyecto": "Test Salida",
        "lugar_a_visitar": "MALBA",
        "fecha_salida": "2026-08-20",
        "fecha_regreso": "2026-08-20"
    },
    "personas": [
        {
            "apellido_nombre": "Juan Pérez",
            "documento": "12345678",
            "rol": "estudiante",
            "cargo": "",
            "fecha_nacimiento": "2010-05-15",
            "menor16": True
        },
        {
            "apellido_nombre": "María García",
            "documento": "87654321",
            "rol": "docente_titular",
            "cargo": "Profesora de Historia",
            "fecha_nacimiento": "",
            "menor16": False
        }
    ],
    "totales": {"estudiantes": 1, "docentes": 1, "no_docentes": 0, "total": 2, "menores16": 1, "desde16": 0},
    "anexos": {
        "V": {
            "institucion_educativa": "EMILIO MITRE",
            "numero_institucion": "1",
            "distrito": "La Matanza",
            "lugar_a_visitar": "MALBA",
            "fecha": "2026-08-20",
            "listado_personas": [
                {"numero": 1, "apellido_nombre": "Juan Pérez", "documento": "12345678",
                 "estudiante": True, "docente": False, "no_docente": False, "asistencia": ""},
                {"numero": 2, "apellido_nombre": "María García", "documento": "87654321",
                 "estudiante": False, "docente": True, "no_docente": False, "asistencia": ""}
            ],
            "observaciones": ""
        },
        "IV": {
            "numero_institucion": "1",
            "distrito": "La Matanza",
            "docentes_responsables_titulares": [
                {"apellido_nombre": "María García", "cargo": "Profesora de Historia"}
            ],
            "docentes_reemplazantes": []
        },
        "IX": {
            "tipo_gestion": "estatal"
        }
    }
}

try:
    print("\nValidando JSON...")
    if not isinstance(test_payload, dict):
        raise ValueError("JSON no es un dict")
    print("✓ JSON es válido")

    print("\nExtrayendo comunes...")
    comunes = test_payload.get('datos_comunes') or {}
    anexos = test_payload.get('anexos') or {}
    print(f"  - Comunes: {len(comunes)} campos")
    print(f"  - Anexos: {len(anexos)} anexos")
    print("✓ Extracción OK")

    print("\nSimulando INSERT en DB...")
    con = conectar()
    cur = con.cursor()

    creado = ahora()
    vigencia = creado + timedelta(days=365)

    cur.execute(
        "INSERT INTO salidas (nombre_proyecto, fecha_salida, fecha_creacion, vigencia_hasta, datos_json) "
        "VALUES (?,?,?,?,?)",
        (comunes.get('denominacion_proyecto', '') or '',
         comunes.get('fecha_salida', '') or '',
         creado.isoformat(),
         vigencia.isoformat(),
         json.dumps(test_payload)))
    id_salida = cur.lastrowid
    con.commit()
    print(f"✓ Fila insertada con ID {id_salida}")

    print(f"\nGenerando PDFs (ID={id_salida})...")
    salidas._generar_pdfs(id_salida, anexos)
    print("✓ PDFs generados OK")

    con.close()
    print("\n✅ FLUJO COMPLETO OK — simulación de api_guardar exitosa")

except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
