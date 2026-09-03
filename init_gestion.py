#!/usr/bin/env python3
"""
Script de inicialización de las bases de gestión — ejecutar en la consola de PythonAnywhere:
  python init_gestion.py
Crea/actualiza el registro de inventarios (gestion.db) y pone al día el archivo de cada
inventario (inventarios/<slug>.db). No siembra nada: un inventario nuevo arranca vacío y se
crea desde /gestion, que es donde se le pone el nombre y la clave.
"""

import sys
import os

# Agregar el directorio del proyecto al path si es necesario
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gestion import init_db, DB_PATH

if __name__ == '__main__':
    print(f"Inicializando el registro de inventarios en: {DB_PATH}")
    init_db()
    print("✓ Bases de datos inicializadas correctamente.")
    print("\nAccedé a https://tu-usuario.pythonanywhere.com/gestion para verificar.")
