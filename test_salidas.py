#!/usr/bin/env python3
"""Test script para verificar que salidas.py funciona con los nuevos campos."""

import json
import sys
sys.path.insert(0, '.')

try:
    from salidas import _generar_pdf_anexo
    from config import ahora

    print("✓ Importes OK")

    # Datos de prueba con los nuevos campos (cargo, fecha_nacimiento)
    test_data = {
        "formato": "appmitre.salidas.v1",
        "datos_comunes": {
            "institucion_educativa": "EMILIO MITRE",
            "numero_institucion": "1",
            "distrito": "La Matanza",
            "lugar_a_visitar": "MALBA",
            "fecha_salida": "2026-08-20",
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
        "anexos": {
            "V": {
                "listado_personas": [
                    {"numero": 1, "apellido_nombre": "Juan Pérez", "documento": "12345678",
                     "estudiante": True, "docente": False, "no_docente": False, "asistencia": ""},
                    {"numero": 2, "apellido_nombre": "María García", "documento": "87654321",
                     "estudiante": False, "docente": True, "no_docente": False, "asistencia": ""}
                ]
            },
            "IV": {
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

    # Prueba: generar PDF del Anexo V
    print("Intentando generar PDF del Anexo V...")
    _generar_pdf_anexo("V", test_data["anexos"]["V"], "/tmp/test_anexo_v.pdf")
    print("✓ Anexo V generado OK")

    # Prueba: generar PDF del Anexo IV
    print("Intentando generar PDF del Anexo IV...")
    _generar_pdf_anexo("IV", test_data["anexos"]["IV"], "/tmp/test_anexo_iv.pdf")
    print("✓ Anexo IV generado OK")

    print("\n✅ TODAS LAS PRUEBAS OK — no hay errores de generación de PDF")

except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
