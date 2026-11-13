import flet as ft
import database
import urllib.request
import urllib.parse
import urllib.error
import json
import random
import os
import threading
import re
import time
from groq import Groq 
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURACIÓN GROQ ---
API_KEY = os.getenv("API_KEY")
client = Groq(
    api_key=API_KEY,
    timeout=45.0 
)

GROQ_MODEL = None

def actualizar_modelo_groq():
    global GROQ_MODEL
    print("\n[IA INFO] Consultando modelos disponibles en tu cuenta...")
    try:
        modelos = client.models.list()
        nombres_modelos = [m.id for m in modelos.data]
        print(f"[IA INFO] Modelos encontrados: {nombres_modelos}")
        
        # Filtramos modelos de audio y guards
        modelos_texto = [m for m in nombres_modelos if "whisper" not in m.lower() and "guard" not in m.lower()]
        
        # Preferimos Qwen o GPT-OSS que sabemos que razonan bien los ingredientes
        for m in ["qwen/qwen3.6-27b", "openai/gpt-oss-20b", "openai/gpt-oss-120b"]:
            if m in modelos_texto:
                GROQ_MODEL = m
                break
                
        if not GROQ_MODEL and modelos_texto:
            GROQ_MODEL = modelos_texto[0]
            
        print(f"✅ [IA AUTO-SELECCIÓN] Modelo configurado para usar: {GROQ_MODEL}\n")
    except Exception as e:
        print(f"❌ [IA ERROR] Fallo al consultar: {e}\n")
        GROQ_MODEL = "qwen/qwen3.6-27b"

threading.Thread(target=actualizar_modelo_groq, daemon=True).start()

# PROMPT BLINDADO
PROMPT_JSON = """
Extrae todos los ingredientes del texto.
Por cada ingrediente, escribe UNA línea JSON exacta con este formato (cambiando los valores según el texto):
{"nombre": "Pescado blanco", "cantidad": 800, "unidad": "g", "categoria": "Carne/Pescado", "raciones": 4}
{"nombre": "Cebolla morada", "cantidad": 2, "unidad": "uds", "categoria": "Fruta/Verdura", "raciones": 4}

REGLAS ESTRICTAS:
- "cantidad": Pon el número EXACTO que dice la receta original (ej. 800, 2, 0.5, 150). PROHIBIDO poner 1 si el texto indica gramos, mililitros u otra cifra.
- "raciones": Número de personas/raciones para las que está pensada la receta completa (si no lo dice, pon 2).
- "nombre": SIEMPRE en singular, primera letra en mayúscula y SIN adjetivos de corte o estado (ej. "Tomate", "Ajo", "Cebolla").
- "unidad": SOLO una de estas: "g", "ml", "uds", "cda", "pizca".
- "categoria": SOLO una de estas: "Fruta/Verdura", "Carne/Pescado", "Lácteos/Huevos", "Despensa", "Congelados", "Varios".
- Genera TODOS los ingredientes uno debajo de otro, sin texto adicional.
- Al terminar todos los JSON de ingredientes, escribe una línea con exactamente ---PASOS--- y debajo redacta los pasos de preparación en formato Markdown limpio (usando lista numerada 1., 2. y **negritas** para tiempos e ingredientes clave).
"""


def extraer_ingredientes_resiliente(texto_bruto, texto_original=""):
    ingredientes_validos = []
    raciones = 1
    
    # 1. Buscamos primero en el texto original si dice "4 personas", "6 raciones", etc.
    match_rac = re.search(r'(?:para\s+|raciones\s*:?\s*|personas\s*:?\s*|comensales\s*:?\s*)(\d+)\s*(?:personas|raciones|comensales|porciones|unidades)?', texto_original, re.IGNORECASE)
    if match_rac and 0 < int(match_rac.group(1)) <= 20:
        raciones = int(match_rac.group(1))

    patron = r'\{[^{}]+\}'
    for match in re.finditer(patron, texto_bruto):
        try:
            obj = json.loads(match.group(0))
            if all(k in obj for k in ("nombre", "cantidad", "unidad", "categoria")):
                obj["cantidad"] = float(obj["cantidad"])
                # Si la IA detectó las raciones del plato, las tomamos
                if "raciones" in obj and int(obj["raciones"]) > 0:
                    raciones = int(obj["raciones"])
                ingredientes_validos.append(obj)
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # 2. Dividimos entre el número de raciones para dejar la cantidad POR PERSONA
    for ing in ingredientes_validos:
        cant_por_persona = ing["cantidad"] / max(1, raciones)
        # Si son gramos o ml grandes redondeamos a 1 decimal, si son unidades pequeñas a 2 decimales
        ing["cantidad"] = round(cant_por_persona, 2)
        
    print(f"[DEBUG] Raciones detectadas del plato original: {raciones}")
    return ingredientes_validos

def extraer_pasos_markdown(texto_bruto, texto_respaldo=""):
    # Si la IA llegó a generar el bloque ---PASOS---, lo extraemos limpio
    if "---PASOS---" in texto_bruto:
        partes = texto_bruto.split("---PASOS---", 1)
        # Quitamos posibles etiquetas residuales si el modelo las escupió
        pasos = re.sub(r'</?think>', '', partes[1], flags=re.IGNORECASE).strip()
        if len(pasos) > 20:
            return pasos
    return texto_respaldo

def main(page: ft.Page):
    page.title = "CocinApp AI v3.0"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.spacing = 0
    
    database.crear_tablas()

    # CAPA DE CARGA
    capa_carga = ft.Container(
        content=ft.Column([
            ft.ProgressRing(color="white", stroke_width=5, width=60, height=60),
            ft.Text("🧠 Procesando con IA...", size=20, weight="bold", color="white"),
            ft.Text("Esto puede tardar un poco. No cierres la app.", size=12, color="white70")
        ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=ft.Colors.with_opacity(0.85, "black"),
        alignment=ft.Alignment.CENTER,
        visible=False,
        expand=True
    )

    scrollable_content = ft.Column(expand=True, scroll="auto", spacing=0)
    CATEGORIAS = ["Fruta/Verdura", "Carne/Pescado", "Lácteos/Huevos", "Despensa", "Congelados", "Varios"]
    UNIDADES = ["g", "ml", "uds", "cda", "pizca"]
    
    id_receta_activa = None
    id_ing_editar = None
    slot_activo_dia = None
    slot_activo_momento = None
    url_imagen_temporal = None

    def notificar(msg):
        page.snack_bar = ft.SnackBar(ft.Text(msg))
        page.snack_bar.open = True
        page.update()

    def cerrar_dialogos(e=None):
        modal_detalles.open = False
        modal_editar_ing.open = False
        modal_compra.open = False
        modal_seleccionar_plato.open = False
        page.update()

    def ejecutar_ia_background(tarea_func, *args):
        def wrapper():
            capa_carga.visible = True
            page.update()
            try:
                tarea_func(*args)
            except Exception as e:
                notificar(f"Error general: {e}")
                print(f"[ERROR HILO]: {e}")
            finally:
                capa_carga.visible = False
                page.update()
        threading.Thread(target=wrapper, daemon=True).start()

    def ia_extraer_url(url_target):
        try:
            print(f"\n[DEBUG] Descargando web: {url_target}")
            req = urllib.request.Request(url_target, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as respuesta_web:
                html = respuesta_web.read().decode('utf-8', errors='ignore')
            
            # Sacamos el título usando Python para quitarle trabajo a la IA
            titulo_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
            img_match = re.search(r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\'](http[^"\']+)["\']', html, re.IGNORECASE)
            img_web = img_match.group(1) if img_match else ""
            titulo_receta = titulo_match.group(1)[:40].strip() if titulo_match else "Receta de Internet"
            
            print("[DEBUG] Limpiando HTML...")
            # 1. Intentamos rescatar los datos estructurados de receta (JSON-LD) antes de borrar los <script>
            bloques_receta = re.findall(r'"recipeIngredient"\s*:\s*\[(.*?)\]', html, flags=re.DOTALL)
            bloques_pasos = re.findall(r'"recipeInstructions"\s*:\s*(\[.*?\]|".*?")', html, flags=re.DOTALL) # <-- AÑADIR
            yield_match = re.search(r'"recipeYield"\s*:\s*["\']?(\d+)', html)
            
            if bloques_receta:
                raciones_ld = f"Para {yield_match.group(1)} personas.\n" if yield_match else ""
                pasos_ld = re.sub(r'<[^>]+>', ' ', bloques_pasos[0])[:2000] if bloques_pasos else "" # <-- AÑADIR
                texto_limpio = f"{raciones_ld}Ingredientes: {bloques_receta[0]}\nPreparación: {pasos_ld}" # <-- MODIFICAR
                print(f"[DEBUG] ¡Ficha estructurada encontrada en la web!: {texto_limpio[:300]}...")
            else:
                # 2. Si la web no tiene ficha estructurada, limpiamos el HTML normal
                html_sin_scripts = re.sub(r'<script.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
                html_sin_estilos = re.sub(r'<style.*?</style>', ' ', html_sin_scripts, flags=re.DOTALL | re.IGNORECASE)
                texto_limpio = re.sub(r'<[^>]+>', ' ', html_sin_estilos)
                texto_limpio = re.sub(r'\s+', ' ', texto_limpio).strip()
                
                # Buscamos todas las apariciones de "ingrediente" y nos saltamos la primera si está muy arriba (menú web)
                matches_ing = [m.start() for m in re.finditer(r'ingrediente', texto_limpio, re.IGNORECASE)]
                if len(matches_ing) > 1 and matches_ing[0] < 600:
                    idx_ingredientes = matches_ing[1]
                elif matches_ing:
                    idx_ingredientes = matches_ing[0]
                else:
                    idx_ingredientes = 0
                texto_limpio = texto_limpio[max(0, idx_ingredientes - 100):idx_ingredientes + 3000]
            
            prompt = f"{PROMPT_JSON}\n\nRECETA:\n{texto_limpio}"
            
            print(f"[DEBUG] Enviando a {GROQ_MODEL}...")
            respuesta_ia = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=4000
            )
            
            texto_bruto = respuesta_ia.choices[0].message.content
            print(f"\n[DEBUG] LA IA RESPONDIÓ ESTO:\n{texto_bruto}\n")
            
            # LA MAGIA OCURRE AQUÍ: Salvamos los ingredientes aunque se haya cortado
            ingredientes_extraidos = extraer_ingredientes_resiliente(texto_bruto, texto_limpio)
            print(f"[DEBUG] INGREDIENTES SALVADOS: {len(ingredientes_extraidos)}")
            
            if not ingredientes_extraidos:
                notificar("❌ La IA no logró extraer ningún ingrediente válido.")
                return

            instrucciones_md = extraer_pasos_markdown(texto_bruto, texto_limpio)
            reseta = {"nombre": titulo_receta, "ingredientes": ingredientes_extraidos, "imagen": img_web, "instrucciones": instrucciones_md}
            
            if database.importar_receta_json(reseta):
                notificar(f"✅ Guardada correctamente: {titulo_receta}")
                cambiar_vista(1)
            else:
                notificar("❌ Error al guardar en base de datos.")
                
        except Exception as e:
            notificar(f"❌ Error de red/API. Mira la consola.")
            print(f"[ERROR URL]: {e}")

    def ia_extraer_texto(texto):
        try:
            texto_recortado = texto[:1500]
            prompt = f"{PROMPT_JSON}\n\nTEXTO:\n{texto_recortado}"
            
            print(f"[DEBUG] Procesando texto con {GROQ_MODEL}...")
            respuesta_ia = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=4000
            )
            
            texto_bruto = respuesta_ia.choices[0].message.content
            ingredientes_extraidos = extraer_ingredientes_resiliente(texto_bruto, texto_recortado)
            
            if not ingredientes_extraidos:
                notificar("❌ La IA no logró extraer ningún ingrediente válido.")
                return

            primera_linea = texto.strip().split('\n')[0][:35].strip()
            nombre_auto = primera_linea if len(primera_linea) > 3 else f"Receta Escaneada ({int(time.time()) % 10000})"
            instrucciones_md = extraer_pasos_markdown(texto_bruto, texto_recortado)
            reseta = {"nombre": nombre_auto, "ingredientes": ingredientes_extraidos, "instrucciones": instrucciones_md}
            
            if database.importar_receta_json(reseta):
                notificar(f"✅ Guardada correctamente")
                cambiar_vista(1)
            else:
                notificar("❌ Error en BD.")
                
        except Exception as e:
             notificar(f"❌ Error al procesar texto: {e}")
             print(f"[ERROR TEXTO]: {e}")

    def probar_conexion_ia(e):
        notificar("📡 Probando conexión...")
        page.update()
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": "Responde OK"}],
                max_tokens=10
            )
            notificar(f"✅ ¡Conexión exitosa! ({GROQ_MODEL})")
        except Exception as err:
            notificar("❌ Error de API.")
            print(f"[DIAGNÓSTICO] {err}")

    def seleccionar_miniatura(url_elegida):
        nonlocal url_imagen_temporal
        url_imagen_temporal = url_elegida
        img_previa_edicion.src = url_elegida
        img_previa_edicion.visible = True
        page.update()

    def buscar_imagen_ia(nombre_plato):
        try:
            limpio = re.sub(r'\b(receta|de|con|al|la|el|los|las|del|casero|casera|fácil|rápido|rápida)\b', ' ', nombre_plato, flags=re.IGNORECASE)
            limpio = " ".join(limpio.split())
            query = urllib.parse.quote(limpio if limpio else nombre_plato)
            headers = {'User-Agent': 'CocinApp/3.0 (https://localhost; contacto@cocinapp.local) Python-urllib/3.12'}
            
            urls = []
            # 1. Buscamos en Wikipedia Español y Wikimedia Commons
            for api_base in [
                f"https://es.wikipedia.org/w/api.php?action=query&generator=search&gsrsearch={query}&gsrlimit=6&prop=pageimages&piprop=thumbnail&pithumbsize=400&format=json",
                f"https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrsearch=filetype:bitmap+{query}&gsrlimit=8&prop=imageinfo&iiprop=url&iiurlwidth=400&format=json"
            ]:
                req = urllib.request.Request(api_base, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as response:
                    data = json.loads(response.read().decode('utf-8'))
                    pages = data.get('query', {}).get('pages', {})
                    for wiki_page in pages.values():
                        if 'thumbnail' in wiki_page and 'source' in wiki_page['thumbnail']:
                            u = wiki_page['thumbnail']['source']
                            if u not in urls: urls.append(u)
                        elif 'imageinfo' in wiki_page and wiki_page['imageinfo']:
                            u = wiki_page['imageinfo'][0].get('thumburl') or wiki_page['imageinfo'][0].get('url')
                            if u and u not in urls: urls.append(u)

            galeria_fotos_opciones.controls.clear()
            if urls:
                for u in urls[:8]:
                    galeria_fotos_opciones.controls.append(
                        ft.Container(
                            content=ft.Image(src=u, width=75, height=60, fit="cover", border_radius=6),
                            border=ft.Border.all(2, "blue"), border_radius=8,
                            on_click=lambda _, url_sel=u: seleccionar_miniatura(url_sel)
                        )
                    )
                galeria_fotos_opciones.visible = True
                seleccionar_miniatura(urls[0])
                notificar(f"🖼️ {len(urls[:8])} fotos encontradas. Toca una para elegirla.")
            else:
                galeria_fotos_opciones.visible = False
                notificar("❌ No se encontraron fotos. Prueba con un nombre más corto (ej. 'Lentejas').")
            page.update()
        except Exception as e:
            print(f"[ERROR FOTOS]: {e}")
            notificar(f"❌ Error buscando fotos: {e}")

    TAGS_BASICOS = ["Almuerzo", "Cena", "Adultos", "Niños"]
    tags_basicos_activos = set()

    def color_por_etiqueta(tag):
        t = tag.strip().lower()
        mapa = {
            "almuerzo": "#ef6c00",  # Naranja cálido
            "cena": "#283593",      # Azul noche
            "adultos": "#00695c",   # Verde azulado oscuro
            "adulto": "#00695c",
            "niños": "#8e24aa",     # Morado vivo
            "niño": "#8e24aa",
            "cuchareo": "#6d4c41",  # Marrón tierra
            "pasta": "#f9a825",     # Amarillo trigo
            "rápido": "#2e7d32",    # Verde
        }
        if t in mapa: return mapa[t]
        # Para cualquier etiqueta nueva, le asigna un color fijo basado en sus letras
        paleta_extra = ["#0277bd", "#00838f", "#558b2f", "#ad1457", "#4527a0", "#d84315"]
        return paleta_extra[sum(ord(c) for c in t) % len(paleta_extra)]

    
    def cargar_datos_receta(id_rec):
        detalles = database.obtener_detalles_receta(id_rec)
        lista_detalles_modal.controls.clear()
        for d in detalles:
            lista_detalles_modal.controls.append(ft.Row([ft.Text(f"• {d[0]}", expand=True), ft.Text(f"{d[1]} {d[2]}", weight="bold"), ft.TextButton("🗑️", on_click=lambda _, n=d[0]: [database.eliminar_ingrediente_a_receta(id_rec, n), cargar_datos_receta(id_rec)])]))
        page.update()

    

    def insertar_md_inline(prefijo):
        actual = ed_rec_instrucciones.value or ""
        salto = "\n" if actual and not actual.endswith("\n") and prefijo.startswith(("#", "-", "1")) else ""
        ed_rec_instrucciones.value = f"{actual}{salto}{prefijo}"
        md_preview_modal.value = ed_rec_instrucciones.value
        page.update()

    barra_md_inline = ft.Row([
        ft.Button("H2", width=42, height=28, style=ft.ButtonStyle(padding=0), on_click=lambda _: insertar_md_inline("## ")),
        ft.Button("B", width=36, height=28, style=ft.ButtonStyle(padding=0), on_click=lambda _: insertar_md_inline("**texto** ")),
        ft.Button("• Lista", height=28, style=ft.ButtonStyle(padding=4), on_click=lambda _: insertar_md_inline("- ")),
        ft.Button("1. Paso", height=28, style=ft.ButtonStyle(padding=4), on_click=lambda _: insertar_md_inline("1. ")),
        ft.Button("⏱️", width=40, height=28, style=ft.ButtonStyle(padding=0), on_click=lambda _: insertar_md_inline("⏱️ **10 min** ")),
    ], spacing=4, visible=False, wrap=True)

    def toggle_edicion_md_inline(e=None):
        editando = not ed_rec_instrucciones.visible
        ed_rec_instrucciones.visible = editando
        barra_md_inline.visible = editando
        box_preview_md.visible = not editando
        md_preview_modal.value = ed_rec_instrucciones.value or "*Sin pasos. Pulsa '✏️ Editar' para añadir la preparación.*"
        page.update()

    def guardar_edicion_receta(e):
        tags = list(tags_basicos_activos)
        if ed_rec_etiquetas.value.strip():
            tags.extend([t.strip() for t in ed_rec_etiquetas.value.split(',') if t.strip()])
        database.actualizar_receta(id_receta_activa, ed_rec_nombre.value, ", ".join(tags), url_imagen_temporal, ed_rec_instrucciones.value)
        notificar("✅ Cambios guardados")
        refrescar_recetas()
        cerrar_dialogos()

    def abrir_detalles_receta(receta):
        nonlocal id_receta_activa, url_imagen_temporal
        recargar_opciones_ing_drop()
        id_receta_activa = receta[0]
        url_imagen_temporal = receta[4]
        galeria_fotos_opciones.visible = False
        
        ed_rec_nombre.value = receta[1]
        tags_crudos = [t.strip() for t in (receta[5] if len(receta) > 5 and receta[5] else "").split(',') if t.strip()]
        
        tags_basicos_activos.clear()
        otras = []
        for t in tags_crudos:
            tl = t.lower()
            if tl in ["adultos", "adulto"]: tags_basicos_activos.add("Adultos")
            elif tl in ["niños", "niño"]: tags_basicos_activos.add("Niños")
            elif tl == "almuerzo": tags_basicos_activos.add("Almuerzo")
            elif tl == "cena": tags_basicos_activos.add("Cena")
            else: otras.append(t)
        renderizar_chips_basicos()
        ed_rec_etiquetas.value = ", ".join(otras)
        
        instrucciones_txt = receta[6] if len(receta) > 6 and receta[6] else ""
        ed_rec_instrucciones.value = instrucciones_txt
        ed_rec_instrucciones.visible = False
        barra_md_inline.visible = False
        box_preview_md.visible = True
        md_preview_modal.value = instrucciones_txt if instrucciones_txt.strip() else "*Sin instrucciones todavía. Pulsa '✏️ Editar' para escribirlas.*"
        
        if receta[4]:
            img_previa_edicion.src = receta[4]
            img_previa_edicion.visible = True
        else:
            img_previa_edicion.visible = False
            
        cargar_datos_receta(id_receta_activa)
        page.dialog = modal_detalles
        modal_detalles.open = True
        page.update()
    
    comensales_base_auto = 4

    def cambiar_comensales_auto(delta):
        nonlocal comensales_base_auto
        comensales_base_auto = max(1, comensales_base_auto + delta)
        lbl_comensales_auto.value = f"👥 {comensales_base_auto}"
        page.update()

    lbl_comensales_auto = ft.Text(f"👥 {comensales_base_auto}", size=12, weight="bold")

    def generar_menu_automatico(e):
        recetas = database.obtener_recetas()
        if len(recetas) < 2:
            notificar("⚠️ Necesitas más platos guardados"); return
            
        database.limpiar_todo_el_plan() # Limpia antes de generar para no acumular encima
        
        almuerzos, cenas = [], []
        for r in recetas:
            tags = (r[5] or "").lower()
            tipo = (r[2] or "").lower()
            if "cena" in tags or "cena" in tipo:
                cenas.append(r)
            if "almuerzo" in tags or "comida" in tags or "cuchareo" in tags or "almuerzo" in tipo:
                almuerzos.append(r)
                
        if not almuerzos: almuerzos = recetas
        if not cenas: cenas = recetas

        for i in range(7):
            plato_alm = random.choice(almuerzos)
            plato_cen = random.choice(cenas)
            database.agregar_plan_multi(i, "Almuerzo", plato_alm[0], comensales_base_auto)
            database.agregar_plan_multi(i, "Cena", plato_cen[0], comensales_base_auto)
            
        notificar("✨ Menú generado según tipos y etiquetas")
        refrescar_menu()

    img_previa_edicion = ft.Image(src="", width=150, height=100, fit="cover", border_radius=10, visible=False)
    galeria_fotos_opciones = ft.Row(scroll="auto", spacing=8, visible=False)
    ed_rec_nombre = ft.TextField(label="Nombre de la receta", expand=True)
    fila_chips_basicos = ft.Row(spacing=6, wrap=True)

    def renderizar_chips_basicos():
        fila_chips_basicos.controls.clear()
        for tb in TAGS_BASICOS:
            activo = tb in tags_basicos_activos
            fila_chips_basicos.controls.append(
                ft.Container(
                    padding=ft.Padding(10, 5, 10, 5),
                    border_radius=16,
                    bgcolor=color_por_etiqueta(tb) if activo else "#eeeeee",
                    on_click=lambda _, t=tb: toggle_chip_basico(t),
                    content=ft.Text(f"{'✓ ' if activo else '+ '}{tb}", size=11, weight="bold", color="white" if activo else "grey800")
                )
            )

    def toggle_chip_basico(tb):
        if tb in tags_basicos_activos: tags_basicos_activos.remove(tb)
        else: tags_basicos_activos.add(tb)
        renderizar_chips_basicos()
        page.update()
    ed_rec_etiquetas = ft.TextField(label="Otras etiquetas (Cuchareo, Pasta...)", expand=True)
    md_preview_modal = ft.Markdown("", selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB)
    box_preview_md = ft.Container(content=md_preview_modal, bgcolor="#f8f9fa", padding=10, border_radius=8, width=380)
    ed_rec_instrucciones = ft.TextField(label="Escribe los pasos en Markdown...", multiline=True, min_lines=4, max_lines=8, visible=False, on_change=lambda _: setattr(md_preview_modal, "value", ed_rec_instrucciones.value))
    sel_ing_drop = ft.Dropdown(
        label="Buscar/Elegir ingrediente", 
        expand=True,
        editable=True,
        enable_filter=True,
        enable_search=True
    )
    txt_ing_cant = ft.TextField(label="Cant./pers.", width=95)

    # Controles para crear un ingrediente nuevo directamente desde la receta
    txt_nuevo_ing_nom = ft.TextField(label="Nuevo ingrediente", expand=True, text_size=12)
    dr_nuevo_ing_uni = ft.Dropdown(label="Unid.", width=80, text_size=12, value="g", options=[ft.dropdown.Option(u) for u in UNIDADES])
    dr_nuevo_ing_cat = ft.Dropdown(label="Categoría", width=130, text_size=12, value="Despensa", options=[ft.dropdown.Option(c) for c in CATEGORIAS])
    
    fila_crear_ing_rapido = ft.Column([
        ft.Row([txt_nuevo_ing_nom, dr_nuevo_ing_uni]),
        ft.Row([
            dr_nuevo_ing_cat,
            ft.Button("✨ Crear y Añadir al plato", bgcolor="orange", color="white", expand=True, on_click=lambda _: crear_y_anadir_ing_receta())
        ])
    ], visible=False, spacing=5)

    def recargar_opciones_ing_drop():
        sel_ing_drop.options = [
            ft.dropdown.Option(key=str(i[0]), text=f"{i[1]} ({i[2]})") 
            for i in sorted(database.obtener_ingredientes(), key=lambda x: x[1].lower())
        ]

    def crear_y_anadir_ing_receta():
        if not txt_nuevo_ing_nom.value or not txt_nuevo_ing_nom.value.strip():
            notificar("⚠️ Escribe el nombre del nuevo ingrediente")
            return
        cant = float((txt_ing_cant.value or "1").replace(",", "."))
        nuevo_id = database.crear_o_obtener_ingrediente(
            txt_nuevo_ing_nom.value, 
            dr_nuevo_ing_uni.value or "uds", 
            dr_nuevo_ing_cat.value or "Varios"
        )
        database.agregar_ingrediente_a_receta(id_receta_activa, nuevo_id, cant)
        
        # Limpiamos y refrescamos desplegable y lista de la receta
        txt_nuevo_ing_nom.value = ""
        txt_ing_cant.value = ""
        fila_crear_ing_rapido.visible = False
        recargar_opciones_ing_drop()
        sel_ing_drop.value = str(nuevo_id)
        cargar_datos_receta(id_receta_activa)
        notificar("✅ Ingrediente creado y añadido a la receta")

    lista_detalles_modal = ft.Column(spacing=5, scroll="auto")

    modal_detalles = ft.AlertDialog(
        content=ft.Container(
            width=400,
            content=ft.Column([
                ft.Button("📖 Ver / Editar Receta a Pantalla Completa", bgcolor="green", color="white", on_click=lambda _: abrir_pantalla_completa()),
                ft.Row([img_previa_edicion, ft.Button("🔍 Buscar Fotos", on_click=lambda _: ejecutar_ia_background(buscar_imagen_ia, ed_rec_nombre.value))], alignment="center"),
                galeria_fotos_opciones, # <-- AÑADIR AQUÍ
                ed_rec_nombre,
                fila_chips_basicos,
                ed_rec_etiquetas,
                ft.Divider(),
                ft.Row([
                    ft.Text("👩‍🍳 Preparación", weight="bold", size=14, expand=True),
                    ft.TextButton("✏️ Editar / 👁️ Ver", on_click=toggle_edicion_md_inline),
                    ft.TextButton("⛶ Ampliar", on_click=lambda _: abrir_pantalla_completa())
                ]),
                barra_md_inline,
                ed_rec_instrucciones,
                box_preview_md,
                ft.Button("💾 Guardar Cambios", on_click=guardar_edicion_receta, bgcolor="blue", color="white"),
                ft.Divider(),
                ft.Container(content=lista_detalles_modal, bgcolor="#f5f5f5", height=150, padding=10, border_radius=10),
                ft.Row([sel_ing_drop, txt_ing_cant]),
                ft.Row([
                    ft.Button("➕ Añadir al plato", expand=True, on_click=lambda _: [database.agregar_ingrediente_a_receta(id_receta_activa, int(sel_ing_drop.value), float((txt_ing_cant.value or "1").replace(",", "."))), setattr(txt_ing_cant, "value", ""), cargar_datos_receta(id_receta_activa)] if sel_ing_drop.value else notificar("⚠️ Selecciona un ingrediente primero")),
                    ft.TextButton("🆕 ¿No existe? Crear", on_click=lambda _: [setattr(fila_crear_ing_rapido, "visible", not fila_crear_ing_rapido.visible), page.update()])
                ]),
                fila_crear_ing_rapido,
                ft.Button("🗑️ Eliminar Receta", color="red", on_click=lambda _: [database.eliminar_receta(id_receta_activa), refrescar_recetas(), cerrar_dialogos()])
            ], tight=True, scroll="auto")
        ),
        actions=[ft.Button("Cerrar", on_click=cerrar_dialogos)]
    )
    
    modo_edicion_md = False

    md_visor_instrucciones = ft.Markdown(
        "", selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB
    )
    txt_editor_md = ft.TextField(
        label="Escribe o edita los pasos...", multiline=True, min_lines=12, max_lines=20, visible=False
    )

    def insertar_tag_md(prefijo, sufijo=""):
        # Añade el formato del "sobreteclado" al texto y actualiza
        actual = txt_editor_md.value or ""
        nueva_linea = "\n" if actual and not actual.endswith("\n") and prefijo.startswith(("#", "-", "1")) else ""
        txt_editor_md.value = f"{actual}{nueva_linea}{prefijo}{sufijo}"
        md_visor_instrucciones.value = txt_editor_md.value
        page.update()

    barra_sobreteclado = ft.Row([
        ft.Button("H2", width=48, height=32, style=ft.ButtonStyle(padding=0), tooltip="Subtítulo", on_click=lambda _: insertar_tag_md("## ")),
        ft.Button("B", width=40, height=32, style=ft.ButtonStyle(padding=0), tooltip="Negrita", on_click=lambda _: insertar_tag_md("**texto** ")),
        ft.Button("• Lista", height=32, style=ft.ButtonStyle(padding=4), on_click=lambda _: insertar_tag_md("- ")),
        ft.Button("1. Paso", height=32, style=ft.ButtonStyle(padding=4), on_click=lambda _: insertar_tag_md("1. ")),
        ft.Button("⏱️ Min", height=32, style=ft.ButtonStyle(padding=4), on_click=lambda _: insertar_tag_md("⏱️ **15 min** ")),
    ], spacing=5, visible=False, wrap=True)

    def alternar_modo_md(e=None):
        nonlocal modo_edicion_md
        modo_edicion_md = not modo_edicion_md
        barra_sobreteclado.visible = modo_edicion_md
        txt_editor_md.visible = modo_edicion_md
        md_visor_instrucciones.visible = not modo_edicion_md
        md_visor_instrucciones.value = txt_editor_md.value or "*Sin instrucciones todavía. Pulsa Editar para escribirlas.*"
        btn_toggle_md.text = "👁️ Ver Renderizado" if modo_edicion_md else "✏️ Editar con Sobreteclado"
        # Si pasa a modo vista, guardamos automáticamente en la BD
        if not modo_edicion_md and id_receta_activa:
            ed_rec_instrucciones.value = txt_editor_md.value
            guardar_edicion_receta(None)
        page.update()

    btn_toggle_md = ft.Button("✏️ Editar con Sobreteclado", on_click=alternar_modo_md)
    lbl_titulo_fullscreen = ft.Text("", size=22, weight="bold", expand=True)
    md_lista_ing_fullscreen = ft.Markdown("")

    modal_pantalla_completa = ft.AlertDialog(
        inset_padding=ft.Padding(10, 10, 10, 10), # Ocupa casi toda la pantalla
        content=ft.Container(
            width=800, height=650,
            content=ft.Column([
                ft.Row([lbl_titulo_fullscreen, btn_toggle_md, ft.IconButton(icon=ft.Icons.CLOSE, on_click=lambda _: [setattr(modal_pantalla_completa, 'open', False), page.update()])]),
                ft.Divider(),
                ft.Container(
                    bgcolor="#f8f9fa", padding=12, border_radius=10,
                    content=ft.Column([ft.Text("🥗 Ingredientes (por persona)", weight="bold", size=14, color="blue"), md_lista_ing_fullscreen])
                ),
                ft.Text("👩‍🍳 Preparación", weight="bold", size=16),
                barra_sobreteclado,
                txt_editor_md,
                ft.Container(content=md_visor_instrucciones, padding=5, expand=True)
            ], scroll="auto", expand=True)
        )
    )

    def abrir_pantalla_completa(e=None):
        nonlocal modo_edicion_md
        modo_edicion_md = False
        barra_sobreteclado.visible = False
        txt_editor_md.visible = False
        md_visor_instrucciones.visible = True
        btn_toggle_md.text = "✏️ Editar con Sobreteclado"
        
        lbl_titulo_fullscreen.value = ed_rec_nombre.value
        detalles = database.obtener_detalles_receta(id_receta_activa)
        md_lista_ing_fullscreen.value = "\n".join([f"- **{d[0]}**: {d[1]} {d[2]}" for d in detalles]) if detalles else "*Sin ingredientes*"
        
        texto_md = ed_rec_instrucciones.value or ""
        txt_editor_md.value = texto_md
        md_visor_instrucciones.value = texto_md if texto_md.strip() else "*Sin instrucciones todavía. Pulsa 'Editar con Sobreteclado' arriba a la derecha.*"
        
        modal_detalles.open = False
        modal_pantalla_completa.open = True
        page.update()

    
    txt_ed_nom = ft.TextField(label="Nombre")
    dr_ed_uni = ft.Dropdown(label="Unidad", options=[ft.dropdown.Option(u) for u in UNIDADES])
    dr_ed_cat = ft.Dropdown(label="Categoría", options=[ft.dropdown.Option(c) for c in CATEGORIAS])
    
    def guardar_edicion_ing(e):
        if database.actualizar_ingrediente(id_ing_editar, txt_ed_nom.value, dr_ed_uni.value, dr_ed_cat.value):
            notificar(f"✅ Actualizado: {txt_ed_nom.value}")
        else:
            notificar("❌ No se pudo actualizar el ingrediente")
        cerrar_dialogos()
        refrescar_alimentos()

    modal_editar_ing = ft.AlertDialog(
        title=ft.Text("Editar Ingrediente"), 
        content=ft.Column([txt_ed_nom, dr_ed_uni, dr_ed_cat], tight=True), 
        actions=[ft.Button("Guardar", on_click=guardar_edicion_ing)]
    )

    ui_compra_list = ft.Column(spacing=10, scroll="auto")
    modal_compra = ft.AlertDialog(title=ft.Text("🛒 Lista de la Compra"), content=ft.Container(content=ui_compra_list, width=350, height=450), actions=[ft.Button("Cerrar", on_click=cerrar_dialogos)])

    grid_seleccion_platos = ft.Column(scroll="adaptive", height=300)
    txt_personas_plan = ft.TextField(label="Nº de personas para este plato", value="1", width=220, keyboard_type=ft.KeyboardType.NUMBER)
    grid_seleccion_platos = ft.Column(scroll="adaptive", height=300)
    modal_seleccionar_plato = ft.AlertDialog(
        title=ft.Text("Elegir Plato"),
        content=ft.Container(width=350, content=ft.Column([txt_personas_plan, ft.Divider(), grid_seleccion_platos], tight=True)),
        actions=[ft.Button("Cerrar", on_click=cerrar_dialogos)]
    )

    def abrir_modal_plan(dia_idx, momento):
        nonlocal slot_activo_dia, slot_activo_momento
        slot_activo_dia, slot_activo_momento = dia_idx, momento
        grid_seleccion_platos.controls = [
            ft.ListTile(
                title=ft.Text(r[1]), 
                subtitle=ft.Text(r[5] if len(r)>5 and r[5] else ""), 
                on_click=lambda _, idr=r[0]: [
                    database.agregar_plan_multi(slot_activo_dia, slot_activo_momento, idr, int(txt_personas_plan.value or 4)), 
                    cerrar_dialogos(),
                    refrescar_menu()
                ]
            ) 
            for r in database.obtener_recetas()
        ]
        page.dialog = modal_seleccionar_plato
        modal_seleccionar_plato.open = True
        page.update()

    page.overlay.extend([modal_detalles, modal_editar_ing, modal_compra, modal_seleccionar_plato, modal_pantalla_completa])

    ui_list_alimentos = ft.Column(spacing=8)
    ui_list_recetas = ft.Row(wrap=True, spacing=10)
    ui_grid_menu = ft.Column(spacing=20)

    txt_buscar_alimento = ft.TextField(label="🔍 Buscar alimento...", expand=True, height=40, text_size=13, content_padding=10, on_change=lambda _: refrescar_alimentos())
    
    txt_add_alim_nom = ft.TextField(label="Nombre", width=180, height=40, text_size=13, content_padding=10) # <-- Cambiado expand=True por width=180
    dr_add_alim_uni = ft.Dropdown(label="Unid.", width=90, text_size=12, value="g", options=[ft.dropdown.Option(u) for u in UNIDADES])
    dr_add_alim_cat = ft.Dropdown(label="Categoría", width=150, text_size=12, value="Despensa", options=[ft.dropdown.Option(c) for c in CATEGORIAS])
    
    panel_nuevo_alimento = ft.Container(
        visible=False, bgcolor="white", padding=12, border_radius=10, border=ft.Border.all(1, "#e0e0e0"),
        content=ft.Row([
            txt_add_alim_nom, dr_add_alim_uni, dr_add_alim_cat,
            ft.Button("💾 Crear", bgcolor="blue", color="white", on_click=lambda _: [
                database.crear_o_obtener_ingrediente(txt_add_alim_nom.value, dr_add_alim_uni.value, dr_add_alim_cat.value),
                setattr(txt_add_alim_nom, "value", ""),
                setattr(panel_nuevo_alimento, "visible", False),
                refrescar_alimentos()
            ] if txt_add_alim_nom.value.strip() else notificar("⚠️ Escribe un nombre"))
        ], wrap=True)
    )

    def abrir_edicion_ing(ing):
        nonlocal id_ing_editar
        id_ing_editar = ing[0]
        txt_ed_nom.value = ing[1]
        dr_ed_uni.value = ing[2]
        dr_ed_cat.value = ing[3]
        modal_editar_ing.open = True
        page.update()

    def refrescar_alimentos():
        ui_list_alimentos.controls.clear()
        busq = (txt_buscar_alimento.value or "").strip().lower()
        for ing in database.obtener_ingredientes():
            if busq and busq not in ing[1].lower() and busq not in ing[3].lower() and busq not in ing[4].lower():
                continue
            recetas_uso = f"🥘 En: {ing[4]}" if ing[4] else "Sin usar en recetas aún"
            ui_list_alimentos.controls.append(
                ft.Container(
                    bgcolor="white", border_radius=10, padding=10, border=ft.Border.all(1, "#f0f0f0"),
                    content=ft.Row([
                        ft.Column([
                            ft.Text(ing[1], weight="bold", size=14),
                            ft.Text(f"{ing[3]} | {ing[2]}", size=11, color="grey"),
                            ft.Text(recetas_uso, size=11, color="blue700" if ing[4] else "grey400", italic=not bool(ing[4]))
                        ], expand=True, spacing=2),
                        ft.TextButton("✏️", on_click=lambda _, i=ing: abrir_edicion_ing(i)),
                        ft.TextButton("🗑️", on_click=lambda _, id_i=ing[0]: [database.eliminar_ingrediente(id_i), refrescar_alimentos()])
                    ])
                )
            )
        page.update()

    txt_buscar_receta = ft.TextField(label="🔍 Buscar por nombre o etiqueta...", expand=True, height=40, text_size=13, content_padding=10, on_change=lambda _: refrescar_recetas())
    dr_filtro_tag = ft.Dropdown(
        label="Etiqueta", width=140, text_size=12, value="Todas",
        options=[ft.dropdown.Option("Todas"), ft.dropdown.Option("Adultos"), ft.dropdown.Option("Niños"), ft.dropdown.Option("Almuerzo"), ft.dropdown.Option("Cena"), ft.dropdown.Option("Cuchareo"), ft.dropdown.Option("Pasta")],
        on_select=lambda _: refrescar_recetas()
    )

    def nueva_receta_manual(e):
        nueva = database.crear_receta_manual("Nueva Receta")
        refrescar_recetas()
        abrir_detalles_receta(nueva)

    def refrescar_recetas():
        ui_list_recetas.controls.clear()
        texto_busq = (txt_buscar_receta.value or "").strip().lower()
        tag_sel = dr_filtro_tag.value or "Todas"

        for rec in database.obtener_recetas():
            nombre_rec = (rec[1] or "").lower()
            tags_rec = (rec[5] or "").lower()
            
            # Filtro por palabra y por etiqueta
            if texto_busq and texto_busq not in nombre_rec and texto_busq not in tags_rec:
                continue
            if tag_sel != "Todas" and tag_sel.lower() not in tags_rec and tag_sel.lower() != (rec[2] or "").lower():
                continue

            tags_ui = []
            if rec[5]:
                for t in rec[5].split(','):
                    if t.strip():
                        tags_ui.append(ft.Container(content=ft.Text(t.strip().upper(), size=8, weight="bold", color="white"), bgcolor=color_por_etiqueta(t), padding=ft.Padding(5, 2, 5, 2), border_radius=6))
            
            ui_list_recetas.controls.append(
                ft.Container(
                    width=160, height=200, bgcolor="white", border_radius=12, border=ft.Border.all(1, "#eeeeee"),
                    on_click=lambda _, r=rec: abrir_detalles_receta(r),
                    content=ft.Column([
                        ft.Image(src=rec[4], height=90, width=160, fit="cover") if rec[4] else ft.Container(height=90, bgcolor="#f0f0f0", content=ft.Text("🥘", size=25), alignment=ft.Alignment(0,0)),
                        ft.Container(padding=10, content=ft.Column([
                            ft.Text(rec[1], size=12, weight="bold", max_lines=2, overflow="ellipsis"), 
                            ft.Row(tags_ui, wrap=True, spacing=2)
                        ], spacing=5))
                    ], spacing=0)
                )
            )
        page.update()

    def refrescar_menu():
        ui_grid_menu.controls.clear()
        plan = database.obtener_plan_semanal()
        plan_dict = {}
        for p in plan:
            key = (p[0], p[1])
            if key not in plan_dict: plan_dict[key] = []
            plan_dict[key].append((p[2], p[4], p[5])) # (nombre_receta, id_plan, personas)
        
        for i, dia in enumerate(["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]):
            slots = []
            for mom in ["Almuerzo", "Cena"]:
                items = plan_dict.get((i, mom), [])
                chips_platos = [
                    ft.Container(
                        bgcolor="white", padding=ft.Padding(8, 2, 2, 2), border_radius=8,
                        content=ft.Row([
                            ft.Text(nom, size=11, weight="bold", expand=True, max_lines=1, overflow="ellipsis"),
                            ft.IconButton(
                                icon=ft.Icons.REMOVE_ROUNDED, icon_size=14, width=22, height=24,
                                style=ft.ButtonStyle(padding=0), tooltip="Restar comensal",
                                on_click=lambda _, idp=id_plan, pr=pers: [database.actualizar_personas_plan(idp, max(1, pr - 1)), refrescar_menu()]
                            ),
                            ft.Text(f"👥{pers}", size=11, weight="bold", color="#1565c0"),
                            ft.IconButton(
                                icon=ft.Icons.ADD_ROUNDED, icon_size=14, width=22, height=24,
                                style=ft.ButtonStyle(padding=0), tooltip="Sumar comensal",
                                on_click=lambda _, idp=id_plan, pr=pers: [database.actualizar_personas_plan(idp, pr + 1), refrescar_menu()]
                            ),
                            ft.IconButton(
                                icon=ft.Icons.CLOSE_ROUNDED, icon_size=15, icon_color="#757575",
                                tooltip="Quitar plato", style=ft.ButtonStyle(padding=0), width=24, height=24,
                                on_click=lambda _, idp=id_plan: [database.eliminar_item_plan(idp), refrescar_menu()]
                            )
                        ], spacing=1, vertical_alignment=ft.CrossAxisAlignment.CENTER)
                    ) for nom, id_plan, pers in items
                ] if items else [ft.Text("Vacío", size=11, color="grey")]

                slots.append(ft.Container(
                    bgcolor="#e3f2fd" if items else "#f9f9f9", expand=True, padding=10, border_radius=10,
                    content=ft.Column([
                        ft.Row([
                            ft.Text(mom, size=10, weight="bold", color="blue"),
                            ft.IconButton(icon=ft.Icons.ADD_CIRCLE_OUTLINE_ROUNDED, icon_size=18, icon_color="blue", width=28, height=28, style=ft.ButtonStyle(padding=0), on_click=lambda _, d=i, m=mom: abrir_modal_plan(d, m))
                        ], alignment="spaceBetween"),
                        *chips_platos
                    ], spacing=5)
                ))
            ui_grid_menu.controls.append(ft.Column([ft.Text(dia, weight="bold", size=16), ft.Row(slots, spacing=10)], spacing=5))
        page.update()

    url_in = ft.TextField(label="URL de receta", expand=True)
    txt_texto_ia = ft.TextField(label="Pega aquí el texto (Google Lens)", multiline=True, min_lines=5, expand=True)
    txt_ruta_imagen = ft.TextField(label="Nombre del archivo local", expand=True)

    def cambiar_vista(idx):
        scrollable_content.controls.clear()
        if idx == 0:
            refrescar_alimentos()
            scrollable_content.controls.append(ft.Container(padding=20, content=ft.Column([
                ft.Row([
                    ft.Text("Alimentos", size=28, weight="bold", expand=True),
                    ft.Button("➕ Añadir", bgcolor="blue", color="white", on_click=lambda _: [setattr(panel_nuevo_alimento, "visible", not panel_nuevo_alimento.visible), page.update()])
                ]),
                panel_nuevo_alimento,
                txt_buscar_alimento,
                ui_list_alimentos
            ], spacing=10)))
        elif idx == 1:
            refrescar_recetas()
            scrollable_content.controls.append(ft.Container(padding=20, content=ft.Column([
                ft.Row([
                    ft.Text("Recetas", size=28, weight="bold", expand=True),
                    ft.Button("➕ Nueva", bgcolor="blue", color="white", on_click=nueva_receta_manual)
                ]),
                ft.Row([txt_buscar_receta, dr_filtro_tag], spacing=10),
                ft.Divider(height=10, color="transparent"),
                ui_list_recetas
            ])))
        elif idx == 2:
            refrescar_menu()
            scrollable_content.controls.append(ft.Container(padding=20, content=ft.Column([
                ft.Row([
                    ft.Text("Planificador", size=22, weight="bold"), # <-- QUITAR expand=True
                    ft.Container(
                        bgcolor="#f0f4f8", border_radius=8, padding=ft.Padding(4, 0, 4, 0),
                        content=ft.Row([
                            ft.IconButton(icon=ft.Icons.REMOVE, icon_size=14, width=24, height=28, style=ft.ButtonStyle(padding=0), on_click=lambda _: cambiar_comensales_auto(-1)),
                            lbl_comensales_auto,
                            ft.IconButton(icon=ft.Icons.ADD, icon_size=14, width=24, height=28, style=ft.ButtonStyle(padding=0), on_click=lambda _: cambiar_comensales_auto(1)),
                            ft.TextButton("✨ Auto", on_click=generar_menu_automatico),
                        ], spacing=2)
                    ),
                    ft.TextButton("🗑️ Vaciar", on_click=lambda _: [database.limpiar_todo_el_plan(), refrescar_menu()]),
                    ft.TextButton("🛒 Compra", on_click=lambda _: [ui_compra_list.controls.clear(), [ui_compra_list.controls.extend([ft.Container(padding=ft.Padding(0,10,0,5), content=ft.Text(cat.upper(), weight="bold", color="orange", size=11)), *[ft.Row([ft.Checkbox(label=it[0], expand=True), ft.Text(f"{round(it[1],1)} {it[2]}", weight="bold")]) for it in database.generar_lista_compra() if it[3] == cat]]) for cat in CATEGORIAS], setattr(modal_compra, 'open', True), page.update()])
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True), # <-- Ahora sí puede llevar wrap=True sin romper Flutter
                ui_grid_menu
            ])))
        elif idx == 3:
            scrollable_content.controls.append(
                ft.Container(padding=20, content=ft.Column([
                    ft.Row([ft.Text("Estado de la Red:", size=16, weight="bold", expand=True), ft.Button("📡 Test", on_click=probar_conexion_ia)]),
                    ft.Divider(),
                    ft.Text("1. Importar desde Internet", size=16, weight="bold"),
                    ft.Row([url_in, ft.Button("🔍", on_click=lambda _: ejecutar_ia_background(ia_extraer_url, url_in.value))]),
                    ft.Divider(),
                    ft.Text("2. Importar desde Texto (Recomendado)", size=16, weight="bold"),
                    ft.Text("Usa Google Lens en tu móvil y pega el texto.", size=11, color="grey"),
                    txt_texto_ia,
                    ft.Button("📝 Procesar", on_click=lambda _: ejecutar_ia_background(ia_extraer_texto, txt_texto_ia.value)),
                    ft.Divider(),
                    ft.Text("3. Importar desde Archivo", size=16, weight="bold"),
                    ft.Row([txt_ruta_imagen, ft.Button("📄", on_click=lambda _: notificar("Próximamente"))])
                ], spacing=15))
            )
        
        for i, item in enumerate(nav_bar.controls):
            item.bgcolor = "#e3f2fd" if i == idx else "transparent"
        page.update()

    def nav_btn(e, l, i):
        return ft.Container(content=ft.Column([ft.Text(e, size=24), ft.Text(l, size=9, weight="bold")], horizontal_alignment="center", spacing=0), on_click=lambda _: cambiar_vista(i), expand=True, padding=5, border_radius=10)

    nav_bar = ft.Row([nav_btn("🥑", "Alimentos", 0), nav_btn("🥘", "Recetas", 1), nav_btn("📅", "Menú", 2), nav_btn("🧠", "IA", 3)], alignment="spaceEvenly")

    page.add(
        ft.Stack([
            ft.Column([scrollable_content, ft.Container(nav_bar, bgcolor="#f8f9fa", height=85, border=ft.Border(top=ft.BorderSide(1, "#eeeeee")))], expand=True, spacing=0),
            capa_carga
        ], expand=True)
    )
    cambiar_vista(2)

if __name__ == "__main__":
<<<<<<< HEAD
    ft.run(main, view=ft.AppView.WEB_BROWSER, host="0.0.0.0", port=8550, web_renderer=ft.WebRenderer.CANVAS_KIT)
=======
    ft.run(main, view=ft.AppView.WEB_BROWSER, host="0.0.0.0", port=8550)
>>>>>>> 87d7a1b0f338b5e466f6d00c973d58b7eb96186c
