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
    
    # Tabla planificador optimizada para permitir combinaciones ("+") sin importar adultos/niños
    cursor.execute('''CREATE TABLE IF NOT EXISTS planificador (
        id INTEGER PRIMARY KEY AUTOINCREMENT, dia_semana INTEGER, momento TEXT, id_receta INTEGER,
        FOREIGN KEY(id_receta) REFERENCES recetas(id) ON DELETE CASCADE)''')
    
    try: cursor.execute("ALTER TABLE recetas ADD COLUMN etiquetas TEXT DEFAULT ''")
    except: pass

    conn.commit()
    conn.close()

def actualizar_receta(id_receta, nombre, etiquetas):
    conn = conectar()
    cursor = conn.cursor()
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
        cursor.execute("DELETE FROM receta_detalle WHERE id_receta = ?", (receta_id,))
        for ing in d.get('ingredientes', []):
            cursor.execute("INSERT OR IGNORE INTO ingredientes (nombre, unidad, categoria) VALUES (?, ?, ?)",
                           (ing.get('nombre', '?'), ing.get('unidad', 'uds'), ing.get('categoria', 'Varios')))
            cursor.execute("SELECT id FROM ingredientes WHERE nombre = ?", (ing.get('nombre', '?'),))
            ing_id = cursor.fetchone()[0]
            cursor.execute("INSERT INTO receta_detalle (id_receta, id_ingrediente, cantidad_base) VALUES (?, ?, ?)",
                           (receta_id, ing_id, ing.get('cantidad', 1)))
        conn.commit()
        return True
    except: return False
    finally: conn.close()

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
    cursor.execute("UPDATE ingredientes SET nombre=?, unidad=?, categoria=? WHERE id=?", (nombre, unidad, categoria, id_ing))
    conn.commit()
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