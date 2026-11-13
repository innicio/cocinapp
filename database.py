import sqlite3
import os
import json

if not os.path.exists('data'):
    os.makedirs('data')

def conectar():
    conn = sqlite3.connect('data/recetas.db')
    conn.execute("PRAGMA foreign_keys = ON") # <-- AÑADIR ESTA LÍNEA
    return conn

def crear_tablas():
    conn = conectar()
    cursor = conn.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS ingredientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE, unidad TEXT, categoria TEXT DEFAULT 'Varios')''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS recetas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE, tipo TEXT, porciones_base INTEGER DEFAULT 1,
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
    try: cursor.execute("ALTER TABLE recetas ADD COLUMN instrucciones TEXT DEFAULT ''")
    except: pass
    try: cursor.execute("ALTER TABLE planificador ADD COLUMN personas INTEGER DEFAULT 1")
    except: pass

    conn.commit()
    conn.close()

    sanear_ingredientes_existentes()

# ==========================================
# NUEVO: FILTRO ANTIDUPLICADOS ESPAÑOL
# ==========================================
def normalizar_nombre_ingrediente(nombre):
    if not nombre: return "Desconocido"
    
    n = " ".join(nombre.strip().lower().split())
    
    excepciones = {
        'sal', 'miel', 'perejil', 'laurel', 'arroz', 'maíz', 'anís', 
        'queso', 'aceite', 'vinagre', 'azúcar', 'leche', 'harina', 
        'agua', 'pan', 'mantequilla', 'nata', 'canela', 'pimienta', 
        'orégano', 'comino', 'azafrán', 'cúrcuma', 'jengibre', 'pasta'
    }
    preposiciones = {'de', 'del', 'en', 'con', 'al', 'para', 'sin', 'a', 'la', 'el', 'los', 'las'}
    tildes_singular = {
        'limon': 'limón', 'jamon': 'jamón', 'melon': 'melón', 
        'salmon': 'salmón', 'camaron': 'camarón', 'mejillon': 'mejillón', 
        'champiñon': 'champiñón', 'piñon': 'piñón', 'requeson': 'requesón',
        'boqueron': 'boquerón', 'pimenton': 'pimentón', 'atun': 'atún', 'anis': 'anís'
    }

    def singularizar_palabra(p):
        if p in excepciones or p in preposiciones or len(p) <= 2:
            return p
        if p.endswith('ces'):
            p = p[:-3] + 'z'
        elif p.endswith('es') and len(p) > 3 and p[-3] in 'lrndj':
            p = p[:-2]
        elif p.endswith('s') and len(p) > 2 and p[-2] in 'aeiouáéíóú':
            p = p[:-1]
        return tildes_singular.get(p, p)

    palabras = n.split(' ')
    resultado = []
    for i, p in enumerate(palabras):
        # Si ya encontramos una preposición ("de", "en"...), no singularizamos el complemento (ej. "Dientes de ajo")
        if i > 0 and any(prev in preposiciones for prev in palabras[:i]):
            resultado.append(p)
        else:
            resultado.append(singularizar_palabra(p))
            
    return " ".join(resultado).capitalize()

# ==========================================
# LÓGICA DE DATOS
# ==========================================
def actualizar_receta(id_receta, nombre, etiquetas, imagen=None, instrucciones=""):
    conn = conectar()
    cursor = conn.cursor()
    if imagen:
        cursor.execute("UPDATE recetas SET nombre=?, etiquetas=?, imagen=?, instrucciones=? WHERE id=?", (nombre, etiquetas, imagen, instrucciones, id_receta))
    else:
        cursor.execute("UPDATE recetas SET nombre=?, etiquetas=?, instrucciones=? WHERE id=?", (nombre, etiquetas, instrucciones, id_receta))
    conn.commit()
    conn.close()

def agregar_plan_multi(dia, momento, id_receta, personas=1):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO planificador (dia_semana, momento, id_receta, personas) VALUES (?, ?, ?, ?)", (dia, momento, id_receta, int(personas)))
    conn.commit()
    conn.close()

def actualizar_personas_plan(id_plan, personas):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("UPDATE planificador SET personas = ? WHERE id = ?", (max(1, int(personas)), id_plan))
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
        cursor.execute("INSERT OR IGNORE INTO recetas (nombre, tipo, porciones_base, imagen, etiquetas, instrucciones) VALUES (?, ?, ?, ?, ?, ?)",
                       (d.get('nombre', 'Nueva Receta'), d.get('tipo', 'Almuerzo'), 1, d.get('imagen', ''), "", d.get('instrucciones', '')))
        cursor.execute("SELECT id FROM recetas WHERE nombre = ?", (d.get('nombre', 'Nueva Receta'),))
        receta_id = cursor.fetchone()[0]
        
        cursor.execute("DELETE FROM receta_detalle WHERE id_receta = ?", (receta_id,))
        
        for ing in d.get('ingredientes', []):
            nombre_limpio = normalizar_nombre_ingrediente(ing.get('nombre', '?'))
            
            cursor.execute("INSERT OR IGNORE INTO ingredientes (nombre, unidad, categoria) VALUES (?, ?, ?)",
                           (nombre_limpio, ing.get('unidad', 'uds'), ing.get('categoria', 'Varios')))
            cursor.execute("SELECT id FROM ingredientes WHERE nombre = ?", (nombre_limpio,))
            ing_id = cursor.fetchone()[0]
            
            cursor.execute("SELECT id, cantidad_base FROM receta_detalle WHERE id_receta = ? AND id_ingrediente = ?", (receta_id, ing_id))
            existente = cursor.fetchone()
            if existente:
                cursor.execute("UPDATE receta_detalle SET cantidad_base = ? WHERE id = ?", (existente[1] + float(ing.get('cantidad', 1)), existente[0]))
            else:
                cursor.execute("INSERT INTO receta_detalle (id_receta, id_ingrediente, cantidad_base) VALUES (?, ?, ?)",
                               (receta_id, ing_id, float(ing.get('cantidad', 1))))
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
    cursor.execute('''
        SELECT i.id, i.nombre, i.unidad, i.categoria, COALESCE(GROUP_CONCAT(r.nombre, ', '), '')
        FROM ingredientes i
        LEFT JOIN receta_detalle rd ON i.id = rd.id_ingrediente
        LEFT JOIN recetas r ON rd.id_receta = r.id
        GROUP BY i.id
        ORDER BY i.nombre ASC
    ''')
    filas = cursor.fetchall()
    conn.close()
    return filas

def actualizar_ingrediente(id_ing, nombre, unidad, categoria):
    if id_ing is None or not nombre: return False
    conn = conectar()
    cursor = conn.cursor()
    nombre_limpio = normalizar_nombre_ingrediente(nombre)
    try:
        # Comprobamos si ya existe otro ingrediente con ese mismo nombre limpio
        cursor.execute("SELECT id FROM ingredientes WHERE nombre = ? AND id != ?", (nombre_limpio, id_ing))
        duplicado = cursor.fetchone()
        
        if duplicado:
            id_destino = duplicado[0]
            cursor.execute("UPDATE ingredientes SET unidad=?, categoria=? WHERE id=?", (unidad, categoria, id_destino))
            # Reasignamos las recetas al ingrediente existente sumando cantidades si ya estaba en el plato
            cursor.execute("SELECT id_receta, cantidad_base FROM receta_detalle WHERE id_ingrediente = ?", (id_ing,))
            for id_rec, cant in cursor.fetchall():
                cursor.execute("SELECT id, cantidad_base FROM receta_detalle WHERE id_receta = ? AND id_ingrediente = ?", (id_rec, id_destino))
                ya_en_plato = cursor.fetchone()
                if ya_en_plato:
                    cursor.execute("UPDATE receta_detalle SET cantidad_base = ? WHERE id = ?", (ya_en_plato[1] + cant, ya_en_plato[0]))
                else:
                    cursor.execute("UPDATE receta_detalle SET id_ingrediente = ? WHERE id_receta = ? AND id_ingrediente = ?", (id_destino, id_rec, id_ing))
            cursor.execute("DELETE FROM receta_detalle WHERE id_ingrediente = ?", (id_ing,))
            cursor.execute("DELETE FROM ingredientes WHERE id = ?", (id_ing,))
        else:
            cursor.execute("UPDATE ingredientes SET nombre=?, unidad=?, categoria=? WHERE id=?", (nombre_limpio, unidad, categoria, id_ing))
        conn.commit()
        return True
    except Exception as e:
        print(f"[ERROR ACTUALIZAR ING]: {e}")
        return False
    finally:
        conn.close()

def eliminar_ingrediente(id_ing):
    conn = conectar()
    cursor = conn.cursor()
    # Borramos primero su presencia en recetas para evitar el fallo de FOREIGN KEY
    cursor.execute("DELETE FROM receta_detalle WHERE id_ingrediente = ?", (id_ing,))
    cursor.execute("DELETE FROM ingredientes WHERE id = ?", (id_ing,))
    conn.commit()
    conn.close()

def obtener_recetas():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nombre, tipo, porciones_base, imagen, etiquetas, instrucciones FROM recetas ORDER BY nombre ASC")
    filas = cursor.fetchall()
    conn.close()
    return filas

def eliminar_receta(id_receta):
    conn = conectar()
    cursor = conn.cursor()
    # Borramos primero sus hijos en planificador y detalles
    cursor.execute("DELETE FROM planificador WHERE id_receta = ?", (id_receta,))
    cursor.execute("DELETE FROM receta_detalle WHERE id_receta = ?", (id_receta,))
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
    cursor.execute("SELECT p.dia_semana, p.momento, r.nombre, r.id, p.id, COALESCE(p.personas, 1) FROM planificador p JOIN recetas r ON p.id_receta = r.id")
    filas = cursor.fetchall()
    conn.close()
    return filas

def eliminar_item_plan(id_plan):
  conn = conectar()
  cursor = conn.cursor()
  cursor.execute("DELETE FROM planificador WHERE id = ?", (id_plan,))
  conn.commit()
  conn.close()

def limpiar_todo_el_plan():
  conn = conectar()
  cursor = conn.cursor()
  cursor.execute("DELETE FROM planificador")
  conn.commit()
  conn.close()

def generar_lista_compra():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT i.nombre, COALESCE(SUM(rd.cantidad_base * COALESCE(p.personas, 1)), 0.0), i.unidad, i.categoria
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

def sanear_ingredientes_existentes():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nombre FROM ingredientes")
    for id_actual, nombre_actual in cursor.fetchall():
        nombre_limpio = normalizar_nombre_ingrediente(nombre_actual)
        if nombre_limpio != nombre_actual:
            cursor.execute("SELECT id FROM ingredientes WHERE nombre = ? AND id != ?", (nombre_limpio, id_actual))
            duplicado = cursor.fetchone()
            if duplicado:
                id_destino = duplicado[0]
                # Redirigimos las recetas al ingrediente ya normalizado y borramos el duplicado
                cursor.execute("UPDATE receta_detalle SET id_ingrediente = ? WHERE id_ingrediente = ?", (id_destino, id_actual))
                cursor.execute("DELETE FROM ingredientes WHERE id = ?", (id_actual,))
            else:
                cursor.execute("UPDATE ingredientes SET nombre = ? WHERE id = ?", (nombre_limpio, id_actual))
    conn.commit()
    conn.close()

def crear_receta_manual(nombre="Nueva Receta"):
    conn = conectar()
    cursor = conn.cursor()
    # Si ya existe "Nueva Receta", le añade un número para no chocar con UNIQUE
    base_nom = nombre
    contador = 1
    while True:
        cursor.execute("SELECT id FROM recetas WHERE nombre = ?", (nombre,))
        if not cursor.fetchone():
            break
        contador += 1
        nombre = f"{base_nom} {contador}"
        
    cursor.execute("INSERT INTO recetas (nombre, tipo, porciones_base, imagen, etiquetas, instrucciones) VALUES (?, 'Almuerzo', 1, '', '', '')", (nombre,))
    rec_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return (rec_id, nombre, 'Almuerzo', 1, '', '', '')

def crear_o_obtener_ingrediente(nombre, unidad="uds", categoria="Varios"):
        nombre_limpio = normalizar_nombre_ingrediente(nombre)
        conn = conectar()
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO ingredientes (nombre, unidad, categoria) VALUES (?, ?, ?)", 
                    (nombre_limpio, unidad, categoria))
        cursor.execute("SELECT id FROM ingredientes WHERE nombre = ?", (nombre_limpio,))
        ing_id = cursor.fetchone()[0]
        conn.commit()
        conn.close()
        return ing_id
