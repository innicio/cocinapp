import sqlite3
import os
import json

if not os.path.exists('data'):
    os.makedirs('data')

def conectar():
    return sqlite3.connect('data/recetas.db')

def crear_tablas():
    conn = conectar()
    cursor = conn.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS ingredientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE, unidad TEXT, categoria TEXT DEFAULT 'Varios')''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS recetas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE, tipo TEXT, porciones_base INTEGER DEFAULT 4,
        imagen TEXT, etiquetas TEXT DEFAULT '')''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS receta_detalle (
        id INTEGER PRIMARY KEY AUTOINCREMENT, id_receta INTEGER, id_ingrediente INTEGER, cantidad_base REAL,
        FOREIGN KEY(id_receta) REFERENCES recetas(id) ON DELETE CASCADE,
        FOREIGN KEY(id_ingrediente) REFERENCES ingredientes(id) ON DELETE CASCADE)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS planificador (
        id INTEGER PRIMARY KEY AUTOINCREMENT, dia_semana INTEGER, momento TEXT, id_receta INTEGER,
        FOREIGN KEY(id_receta) REFERENCES recetas(id) ON DELETE CASCADE)''')
    
    try: cursor.execute("ALTER TABLE recetas ADD COLUMN etiquetas TEXT DEFAULT ''")
    except: pass

    conn.commit()
    conn.close()

# ==========================================
# NUEVO: FILTRO ANTIDUPLICADOS ESPAÑOL
# ==========================================
def normalizar_nombre_ingrediente(nombre):
    if not nombre: return "Desconocido"
    
    # 1. Limpieza básica
    n = nombre.strip().lower()
    
    # 2. Excepciones de ingredientes que no se deben singularizar o que son singulares per se
    excepciones = ['sal', 'miel', 'perejil', 'laurel', 'arroz', 'maíz', 'anís', 'queso', 'aceite', 'vinagre', 'azúcar', 'leche']
    if n in excepciones:
        return n.capitalize()
        
    # 3. Reglas gramaticales básicas de singular en español
    if n.endswith('ces'):
        n = n[:-3] + 'z'  # Ej. Nueces -> Nuez
    elif n.endswith('es') and len(n) > 3 and n[-3] in 'lrndj':
        n = n[:-2]        # Ej. Limones -> Limon, Frijoles -> Frijol
    elif n.endswith('s') and len(n) > 2 and n[-2] in 'aeiouáéíóú':
        n = n[:-1]        # Ej. Tomates -> Tomate, Zanahorias -> Zanahoria
        
    # 4. Primera letra en mayúscula (Ej. Aceite de oliva)
    return n.capitalize()

# ==========================================
# LÓGICA DE DATOS
# ==========================================
def actualizar_receta(id_receta, nombre, etiquetas, imagen=None):
    conn = conectar()
    cursor = conn.cursor()
    if imagen:
        cursor.execute("UPDATE recetas SET nombre=?, etiquetas=?, imagen=? WHERE id=?", (nombre, etiquetas, imagen, id_receta))
    else:
        cursor.execute("UPDATE recetas SET nombre=?, etiquetas=? WHERE id=?", (nombre, etiquetas, id_receta))
    conn.commit()
    conn.close()

def agregar_plan_multi(dia, momento, id_receta):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO planificador (dia_semana, momento, id_receta) VALUES (?, ?, ?)", (dia, momento, id_receta))
    conn.commit()
    conn.close()

def limpiar_plan_turno(dia, momento):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM planificador WHERE dia_semana = ? AND momento = ?", (dia, momento))
    conn.commit()
    conn.close()

def importar_receta_json(data):
    if isinstance(data, str):
        try: d = json.loads(data)
        except: return False
    else: d = data
    
    conn = conectar()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO recetas (nombre, tipo, porciones_base, imagen, etiquetas) VALUES (?, ?, ?, ?, ?)",
                       (d.get('nombre', 'Nueva Receta'), d.get('tipo', 'Almuerzo'), 2, "", ""))
        cursor.execute("SELECT id FROM recetas WHERE nombre = ?", (d.get('nombre', 'Nueva Receta'),))
        receta_id = cursor.fetchone()[0]
        
        for ing in d.get('ingredientes', []):
            # APLICAMOS EL FILTRO AQUÍ (Evita que la IA cree duplicados)
            nombre_limpio = normalizar_nombre_ingrediente(ing.get('nombre', '?'))
            
            cursor.execute("INSERT OR IGNORE INTO ingredientes (nombre, unidad, categoria) VALUES (?, ?, ?)",
                           (nombre_limpio, ing.get('unidad', 'uds'), ing.get('categoria', 'Varios')))
            cursor.execute("SELECT id FROM ingredientes WHERE nombre = ?", (nombre_limpio,))
            ing_id = cursor.fetchone()[0]
            
            cursor.execute("INSERT INTO receta_detalle (id_receta, id_ingrediente, cantidad_base) VALUES (?, ?, ?)",
                           (receta_id, ing_id, ing.get('cantidad', 1)))
        conn.commit()
        return True
    except Exception as e: 
        print(f"\n[ERROR FATAL EN BASE DE DATOS]: {e}\n")
        return False
    finally: 
        conn.close()

def eliminar_ingrediente_a_receta(id_receta, nombre_ingrediente):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM receta_detalle WHERE id_receta = ? AND id_ingrediente = (SELECT id FROM ingredientes WHERE nombre = ?)", (id_receta, nombre_ingrediente))
    conn.commit()
    conn.close()

def obtener_ingredientes():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nombre, unidad, categoria FROM ingredientes ORDER BY categoria, nombre ASC")
    filas = cursor.fetchall()
    conn.close()
    return filas

def actualizar_ingrediente(id_ing, nombre, unidad, categoria):
    conn = conectar()
    cursor = conn.cursor()
    # APLICAMOS EL FILTRO AQUÍ TAMBIÉN (Para cuando edites a mano)
    nombre_limpio = normalizar_nombre_ingrediente(nombre)
    try:
        cursor.execute("UPDATE ingredientes SET nombre=?, unidad=?, categoria=? WHERE id=?", (nombre_limpio, unidad, categoria, id_ing))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # Si al limpiar el nombre, choca con uno que ya existe, cancelamos para no romper la BD.
        return False 
    finally:
        conn.close()

def eliminar_ingrediente(id_ing):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ingredientes WHERE id = ?", (id_ing,))
    conn.commit()
    conn.close()

def obtener_recetas():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nombre, tipo, porciones_base, imagen, etiquetas FROM recetas ORDER BY nombre ASC")
    filas = cursor.fetchall()
    conn.close()
    return filas

def eliminar_receta(id_receta):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM recetas WHERE id = ?", (id_receta,))
    conn.commit()
    conn.close()

def agregar_ingrediente_a_receta(id_receta, id_ingrediente, cantidad):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO receta_detalle (id_receta, id_ingrediente, cantidad_base) VALUES (?, ?, ?)", (id_receta, id_ingrediente, cantidad))
    conn.commit()
    conn.close()

def obtener_detalles_receta(id_receta):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT i.nombre, rd.cantidad_base, i.unidad, i.categoria FROM receta_detalle rd JOIN ingredientes i ON rd.id_ingrediente = i.id WHERE rd.id_receta = ?", (id_receta,))
    filas = cursor.fetchall()
    conn.close()
    return filas

def obtener_plan_semanal():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT p.dia_semana, p.momento, r.nombre, r.id FROM planificador p JOIN recetas r ON p.id_receta = r.id")
    filas = cursor.fetchall()
    conn.close()
    return filas

def generar_lista_compra():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT i.nombre, SUM(rd.cantidad_base), i.unidad, i.categoria
        FROM planificador p
        JOIN receta_detalle rd ON p.id_receta = rd.id_receta
        JOIN ingredientes i ON rd.id_ingrediente = i.id
        JOIN recetas r ON p.id_receta = r.id
        GROUP BY i.nombre, i.unidad, i.categoria
        ORDER BY i.categoria ASC
    ''')
    filas = cursor.fetchall()
    conn.close()
    return filas
