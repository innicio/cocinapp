import database
import json

# Forzamos la creación de tablas por si acaso
database.crear_tablas()

receta_prueba = {
  "nombre": "Noodles de Setas y Verduras (Test)",
  "tipo": "Almuerzo",
  "ingredientes": [
    {"nombre": "Noodles", "cantidad": 250, "unidad": "g", "categoria": "Despensa"},
    {"nombre": "Setas Shiitake", "cantidad": 6, "unidad": "uds", "categoria": "Fruta/Verdura"}
  ]
}

print("Intentando guardar receta...")
exito = database.importar_receta_json(receta_prueba)

if exito:
    print("✅ ¡Éxito! La base de datos funciona perfectamente.")
    recetas = database.obtener_recetas()
    print("Recetas actuales en BD:", recetas)
else:
    print("❌ Falló la importación. Revisa el error que debe haber salido arriba.")
