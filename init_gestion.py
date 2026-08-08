#!/usr/bin/env python3
"""
Script de inicialización de gestion.db — ejecutar en la consola de PythonAnywhere:
  python init_gestion.py
Recrea las tablas y carga datos de ejemplo si la BD está vacía.
"""

import sys
import os

# Agregar el directorio del proyecto al path si es necesario
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gestion import init_db, DB_PATH

if __name__ == '__main__':
    print(f"Inicializando gestion.db en: {DB_PATH}")
    init_db()
    print("✓ Base de datos inicializada correctamente.")
    print("✓ Si estaba vacía, se cargaron datos de ejemplo automáticamente.")
    print("\nAccedé a https://tu-usuario.pythonanywhere.com/gestion para verificar.")
