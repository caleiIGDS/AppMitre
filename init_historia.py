#!/usr/bin/env python3
"""
Script de inicialización de historia.db — ejecutar en la consola de PythonAnywhere:
  python init_historia.py
Crea las tablas si no existen. No carga datos de ejemplo: la línea del tiempo arranca vacía.
"""

import sys
import os

# Agregar el directorio del proyecto al path si es necesario
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from historia import init_db, DB_PATH

if __name__ == '__main__':
    print(f"Inicializando historia.db en: {DB_PATH}")
    init_db()
    print("✓ Base de datos inicializada correctamente.")
    print("\nAccedé a https://tu-usuario.pythonanywhere.com/historia para verificar.")
