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
from groq import Groq 
from dotenv import load_dotenv

load_dotenv()


# --- CONFIGURACIÓN GROQ (PON TU CLAVE AQUÍ) ---
# Sustituye "TU_CLAVE_REAL_AQUI" por la clave de GroqCloud
API_KEY=os.getenv("API_KEY")
client = Groq(api_key=API_KEY)
GROQ_MODEL = "llama-3.1-8b-instant" 

# Prompt maestro para forzar a la IA a devolver un JSON exacto
PROMPT_JSON = """
Devuelve ÚNICAMENTE un JSON válido con la siguiente estructura, sin texto antes ni después.
Asegúrate de clasificar estrictamente la categoria en una de estas: "Fruta/Verdura", "Carne/Pescado", "Lácteos/Huevos", "Despensa", "Congelados", "Varios".
Y la unidad en una de estas: "g", "ml", "uds", "cda", "pizca".

{
  "nombre": "Nombre del plato extraído",
  "ingredientes": [
    {"nombre": "Ingrediente 1", "cantidad": 100, "unidad": "g", "categoria": "Despensa"}
  ]
}
"""

def limpiar_respuesta_json(texto):
    """Fuerza la eliminación de cualquier formato markdown que rompa el JSON"""
    if not texto: return "{}"
    texto = texto.strip()
    if texto.startswith("```"):
        texto = re.sub(r"^```(?:json)?\n|\n```$", "", texto, flags=re.MULTILINE)
    return texto.strip()

def main(page: ft.Page):
    page.title = "CocinApp AI v3.0"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.spacing = 0
    
    # 1. Inicialización
    database.crear_tablas()

    # 2. CAPA DE CARGA VISUAL
    capa_carga = ft.Container(
        content=ft.Column([
            ft.ProgressRing(color="white", stroke_width=5, width=60, height=60),
            ft.Text("🧠 Procesando con Groq...", size=20, weight="bold", color="white"),
            ft.Text("Por favor, no cierres la aplicación.", size=12, color="white70")
        ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=ft.Colors.with_opacity(0.85, "black"),
        alignment=ft.Alignment.CENTER,
        visible=False,
        expand=True
    )

    scrollable_content = ft.Column(expand=True, scroll="auto", spacing=0)
    
    # --- VARIABLES Y CONSTANTES ---
    CATEGORIAS = ["Fruta/Verdura", "Carne/Pescado", "Lácteos/Huevos", "Despensa", "Congelados", "Varios"]
    UNIDADES = ["g", "ml", "uds", "cda", "pizca"]
    
    id_receta_activa = None
    id_ing_editar = None
    slot_activo_dia = None
    slot_activo_momento = None
    url_imagen_temporal = None

    # --- NOTIFICACIONES ---
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

    # --- HILOS PARA IA ---
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

    # --- LÓGICA DE EXTRACCIÓN CON GROQ ---
    def normalizar_receta(datos, nombre_defecto):
        nombre_ia = datos.get("nombre", datos.get("name", nombre_defecto)) if isinstance(datos, dict) else nombre_defecto
        ingredientes = []
        if isinstance(datos, list): ingredientes = datos
        elif isinstance(datos, dict):
            ingredientes = datos.get("ingredientes", datos.get("ingredients", []))
            if not ingredientes:
                for v in datos.values():
                    if isinstance(v, list): ingredientes = v; break
        return {"nombre": nombre_ia, "ingredientes": ingredientes}

    def ia_extraer_url(url_target):
        try:
            print(f"\n[DEBUG] Descargando web: {url_target}")
            req = urllib.request.Request(url_target, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as response:
                html = response.read().decode('utf-8', errors='ignore')
            
            print("[DEBUG] Limpiando HTML para ahorrar tokens...")
            # 1. Eliminamos los bloques <script> y <style> completos (no contienen receta y ocupan muchísimo)
            html = re.sub(r'<script.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<style.*?</style>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
            
            # 2. Eliminamos todas las etiquetas HTML restantes (<div...>, <p>, <a>...)
            texto_limpio = re.sub(r'<[^>]+>', ' ', html)
            
            # 3. Colapsamos los saltos de línea y espacios gigantes en un solo espacio
            texto_limpio = re.sub(r'\s+', ' ', texto_limpio).strip()
            
            # 4. Aseguramos el límite estricto de Groq: 15.000 caracteres son aprox 3.500 tokens.
            # (Sobra margen para los tokens de salida y el límite de 6000)
            texto_limpio = texto_limpio[:15000] 
            
            prompt = f"Extrae los datos de la receta del siguiente texto de una web:\n\nTEXTO:\n{texto_limpio}\n\n{PROMPT_JSON}"
            
            print("[DEBUG] Enviando texto limpio a Groq...")
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": "Eres un asistente experto. Responde sólo en JSON."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            
            texto_json = limpiar_respuesta_json(response.choices[0].message.content)
            reseta = normalizar_receta(json.loads(texto_json), "Receta Web")
            
            if database.importar_receta_json(reseta):
                notificar(f"✅ Guardada correctamente: {reseta['nombre']}")
                cambiar_vista(1)
            else:
                notificar("❌ Flet leyó la receta, pero la BD la rechazó.")
                
        except json.JSONDecodeError as e:
            notificar("❌ Groq no devolvió un JSON válido.")
            print(f"[ERROR JSON]: {e}")
        except Exception as e:
            notificar(f"❌ Error de red/API. Mira la consola.")
            print(f"[ERROR URL]: {e}")


    def ia_extraer_texto(texto):
        try:
            prompt = f"Extrae los datos de la receta del siguiente texto u OCR:\n\n{texto}\n\n{PROMPT_JSON}"
            
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": "Eres un asistente experto. Responde sólo en JSON."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            
            texto_json = limpiar_respuesta_json(response.choices[0].message.content)
            reseta = normalizar_receta(json.loads(texto_json), "Receta Lens")
            
            if database.importar_receta_json(reseta):
                notificar(f"✅ Guardada correctamente: {reseta['nombre']}")
                cambiar_vista(1)
            else:
                notificar("❌ Flet leyó la receta, pero la BD la rechazó.")
                
        except json.JSONDecodeError as e:
            notificar("❌ Groq no devolvió un JSON válido.")
            print(f"[ERROR JSON]: {e}")
        except Exception as e:
             notificar(f"❌ Error al procesar texto: {e}")
             print(f"[ERROR TEXTO]: {e}")

    def probar_conexion_ia(e):
        notificar("📡 Probando conexión con GroqCloud...")
        page.update()
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": "Responde únicamente con la palabra OK"}],
                temperature=0.1
            )
            respuesta = response.choices[0].message.content.strip()
            if "OK" in respuesta.upper():
                notificar("✅ ¡Conexión exitosa con Groq!")
            else:
                notificar("⚠️ Conexión establecida, pero respuesta extraña.")
        except Exception as err:
            notificar("❌ Error crítico de API. Mira la consola.")
            print(f"[DIAGNÓSTICO ERROR] {err}")

    def buscar_imagen_ia(nombre_plato):
        nonlocal url_imagen_temporal
        try:
            query = urllib.parse.quote(nombre_plato)
            url = f"[https://es.wikipedia.org/w/api.php?action=query&titles=](https://es.wikipedia.org/w/api.php?action=query&titles=){query}&prop=pageimages&format=json&pithumbsize=500"
            req = urllib.request.Request(url, headers={'User-Agent': 'CocinApp/3.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                pages = data.get('query', {}).get('pages', {})
                page = list(pages.values())[0]
                
                if 'thumbnail' in page:
                    url_imagen_temporal = page['thumbnail']['source']
                    img_previa_edicion.src = url_imagen_temporal
                    img_previa_edicion.visible = True
                    page.update()
                    notificar("✅ Imagen encontrada (Wikipedia)")
                else:
                    notificar("❌ Wikipedia no tiene imágenes para este plato.")
        except Exception as e:
            notificar(f"❌ Error al buscar imagen: {e}")

    # --- LÓGICA DE DETALLES Y EDICIÓN ---
    def guardar_edicion_receta(e):
        tags = []
        if chk_adulto.value: tags.append("Adultos")
        if chk_nino.value: tags.append("Niños")
        if ed_rec_etiquetas.value.strip(): tags.extend([t.strip() for t in ed_rec_etiquetas.value.split(',') if t.strip()])
        database.actualizar_receta(id_receta_activa, ed_rec_nombre.value, ", ".join(tags), url_imagen_temporal)
        notificar("✅ Cambios guardados")
        refrescar_recetas()
        cerrar_dialogos()

    def cargar_datos_receta(id_rec):
        detalles = database.obtener_detalles_receta(id_rec)
        lista_detalles_modal.controls.clear()
        for d in detalles:
            lista_detalles_modal.controls.append(ft.Row([ft.Text(f"• {d[0]}", expand=True), ft.Text(f"{d[1]} {d[2]}", weight="bold"), ft.TextButton("🗑️", on_click=lambda _, n=d[0]: [database.eliminar_ingrediente_a_receta(id_rec, n), cargar_datos_receta(id_rec)])]))
        page.update()

    def abrir_detalles_receta(receta):
        nonlocal id_receta_activa, url_imagen_temporal
        id_receta_activa = receta[0]
        url_imagen_temporal = receta[4]
        
        ed_rec_nombre.value = receta[1]
        tags_crudos = receta[5] if len(receta) > 5 and receta[5] else ""
        lista_tags = [t.strip().lower() for t in tags_crudos.split(',')]
        chk_adulto.value = any(x in lista_tags for x in ["adultos", "adulto"])
        chk_nino.value = any(x in lista_tags for x in ["niños", "niño"])
        otras = [t.strip() for t in tags_crudos.split(',') if t.strip().lower() not in ["adultos", "adulto", "niños", "niño"]]
        ed_rec_etiquetas.value = ", ".join(otras)
        
        if receta[4]:
            img_previa_edicion.src = receta[4]
            img_previa_edicion.visible = True
        else:
            img_previa_edicion.visible = False
            
        cargar_datos_receta(id_receta_activa)
        page.dialog = modal_detalles
        modal_detalles.open = True
        page.update()

    def generar_menu_automatico(e):
        recetas = database.obtener_recetas()
        if len(recetas) < 4:
            notificar("⚠️ Necesitas más platos guardados"); return
        for i in range(7):
            database.agregar_plan_multi(i, "Almuerzo", random.choice(recetas)[0])
            database.agregar_plan_multi(i, "Cena", random.choice(recetas)[0])
        notificar("✨ Menú generado")
        refrescar_menu()

    # --- CONTROLES DE EDICIÓN ---
    img_previa_edicion = ft.Image(src="", width=150, height=100, fit="cover", border_radius=10, visible=False)
    ed_rec_nombre = ft.TextField(label="Nombre de la receta", expand=True)
    chk_adulto = ft.Checkbox(label="Adultos")
    chk_nino = ft.Checkbox(label="Niños")
    ed_rec_etiquetas = ft.TextField(label="Otras etiquetas (Cuchareo, Pasta...)", expand=True)
    sel_ing_drop = ft.Dropdown(label="Añadir ingrediente", expand=True)
    txt_ing_cant = ft.TextField(label="Cant.", width=80)
    lista_detalles_modal = ft.Column(spacing=5, scroll="auto")

    modal_detalles = ft.AlertDialog(
        content=ft.Container(
            width=400,
            content=ft.Column([
                ft.Row([img_previa_edicion, ft.Button("🔍 Buscar Foto", on_click=lambda _: ejecutar_ia_background(buscar_imagen_ia, ed_rec_nombre.value))], alignment="center"),
                ed_rec_nombre,
                ft.Row([chk_adulto, chk_nino]),
                ed_rec_etiquetas,
                ft.Button("💾 Guardar Cambios", on_click=guardar_edicion_receta, bgcolor="blue", color="white"),
                ft.Divider(),
                ft.Container(content=lista_detalles_modal, bgcolor="#f5f5f5", height=150, padding=10, border_radius=10),
                ft.Row([sel_ing_drop, txt_ing_cant]),
                ft.Button("➕ Añadir", on_click=lambda _: [database.agregar_ingrediente_a_receta(id_receta_activa, int(sel_ing_drop.value), float(txt_ing_cant.value)), cargar_datos_receta(id_receta_activa)]),
                ft.Button("🗑️ Eliminar Receta", color="red", on_click=lambda _: [database.eliminar_receta(id_receta_activa), refrescar_recetas(), cerrar_dialogos()])
            ], tight=True, scroll="auto")
        ),
        actions=[ft.Button("Cerrar", on_click=cerrar_dialogos)]
    )

    # --- ALIMENTOS Y COMPRA ---
    txt_ed_nom = ft.TextField(label="Nombre")
    dr_ed_uni = ft.Dropdown(label="Unidad", options=[ft.dropdown.Option(u) for u in UNIDADES])
    dr_ed_cat = ft.Dropdown(label="Categoría", options=[ft.dropdown.Option(c) for c in CATEGORIAS])
    
    modal_editar_ing = ft.AlertDialog(
        title=ft.Text("Editar Ingrediente"), 
        content=ft.Column([txt_ed_nom, dr_ed_uni, dr_ed_cat], tight=True), 
        actions=[ft.Button("Guardar", on_click=lambda _: [database.actualizar_ingrediente(id_ing_editar, txt_ed_nom.value, dr_ed_uni.value, dr_ed_cat.value), cerrar_dialogos(), refrescar_alimentos()])]
    )

    ui_compra_list = ft.Column(spacing=10, scroll="auto")
    modal_compra = ft.AlertDialog(title=ft.Text("🛒 Lista de la Compra"), content=ft.Container(content=ui_compra_list, width=350, height=450), actions=[ft.Button("Cerrar", on_click=cerrar_dialogos)])

    # --- PLANIFICADOR MODAL ---
    grid_seleccion_platos = ft.Column(scroll="adaptive", height=300)
    modal_seleccionar_plato = ft.AlertDialog(
        title=ft.Text("Elegir Plato"),
        content=ft.Container(width=350, content=grid_seleccion_platos),
        actions=[ft.Button("Cerrar", on_click=cerrar_dialogos)]
    )

    def abrir_modal_plan(dia_idx, momento):
        nonlocal slot_activo_dia, slot_activo_momento
        slot_activo_dia, slot_activo_momento = dia_idx, momento
        grid_seleccion_platos.controls = [
            ft.ListTile(title=ft.Text(r[1]), subtitle=ft.Text(r[5] if len(r)>5 and r[5] else ""), on_click=lambda _, idr=r[0]: [database.agregar_plan_multi(slot_activo_dia, slot_activo_momento, idr), refrescar_menu()]) 
            for r in database.obtener_recetas()
        ]
        page.dialog = modal_seleccionar_plato
        modal_seleccionar_plato.open = True
        page.update()

    page.overlay.extend([modal_detalles, modal_editar_ing, modal_compra, modal_seleccionar_plato])

    # --- VISTAS GLOBALES ---
    ui_list_alimentos = ft.Column(spacing=8)
    ui_list_recetas = ft.Row(wrap=True, spacing=10)
    ui_grid_menu = ft.Column(spacing=20)

    def refrescar_alimentos():
        ui_list_alimentos.controls.clear()
        for ing in database.obtener_ingredientes():
            ui_list_alimentos.controls.append(ft.Container(bgcolor="white", border_radius=10, padding=10, border=ft.Border.all(1, "#f0f0f0"), content=ft.Row([ft.Column([ft.Text(ing[1], weight="bold", size=14), ft.Text(f"{ing[3]} | {ing[2]}", size=11, color="grey")], expand=True, spacing=2), ft.TextButton("✏️", on_click=lambda _, i=ing: [setattr(txt_ed_nom, 'value', i[1]), setattr(dr_ed_uni, 'value', i[2]), setattr(dr_ed_cat, 'value', i[3]), setattr(page, 'dialog', modal_editar_ing), setattr(modal_editar_ing, 'open', True), page.update()]), ft.TextButton("🗑️", on_click=lambda _, id_i=ing[0]: [database.eliminar_ingrediente(id_i), refrescar_alimentos()])])))
        page.update()

    def refrescar_recetas():
        ui_list_recetas.controls.clear()
        for rec in database.obtener_recetas():
            tags_ui = []
            if rec[5]:
                for t in rec[5].split(','):
                    tags_ui.append(ft.Container(content=ft.Text(t.strip().upper(), size=8, color="white"), bgcolor="blue", padding=3, border_radius=5))
            
            ui_list_recetas.controls.append(
                ft.Container(
                    width=160, height=200, bgcolor="white", border_radius=12, border=ft.Border.all(1, "#eeeeee"),
                    on_click=lambda _, r=rec: [setattr(sel_ing_drop, "options", [ft.dropdown.Option(key=str(i[0]), text=i[1]) for i in database.obtener_ingredientes()]), abrir_detalles_receta(r)],
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
            plan_dict[key].append(p[2])
        
        for i, dia in enumerate(["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]):
            slots = []
            for mom in ["Almuerzo", "Cena"]:
                nombres = plan_dict.get((i, mom), [])
                slots.append(ft.Container(bgcolor="#e3f2fd" if nombres else "#f9f9f9", expand=True, padding=12, border_radius=10, on_click=lambda _, d=i, m=mom: abrir_modal_plan(d, m),
                             content=ft.Column([ft.Row([ft.Text(mom, size=10, weight="bold", color="blue"), ft.Text("➕", size=14, color="blue")], alignment="spaceBetween"), ft.Text(" + ".join(nombres) if nombres else "Vacío", size=11, weight="bold")])))
            ui_grid_menu.controls.append(ft.Column([ft.Text(dia, weight="bold", size=16), ft.Row(slots, spacing=10)], spacing=5))
        page.update()

    # --- PESTAÑA IA ---
    url_in = ft.TextField(label="URL de receta", expand=True)
    txt_texto_ia = ft.TextField(label="Pega aquí el texto (Google Lens)", multiline=True, min_lines=5, expand=True)
    txt_ruta_imagen = ft.TextField(label="Nombre del archivo local", expand=True)

    def cambiar_vista(idx):
        scrollable_content.controls.clear()
        if idx == 0:
            refrescar_alimentos()
            scrollable_content.controls.append(ft.Container(padding=20, content=ft.Column([ft.Text("Alimentos", size=28, weight="bold"), ui_list_alimentos])))
        elif idx == 1:
            refrescar_recetas()
            scrollable_content.controls.append(ft.Container(padding=20, content=ft.Column([ft.Text("Recetas", size=28, weight="bold"), ui_list_recetas])))
        elif idx == 2:
            refrescar_menu()
            scrollable_content.controls.append(ft.Container(padding=20, content=ft.Column([
                ft.Row([ft.Text("Planificador", size=28, weight="bold", expand=True), ft.TextButton("✨ Auto", on_click=generar_menu_automatico), ft.TextButton("🛒 Compra", on_click=lambda _: [ui_compra_list.controls.clear(), [ui_compra_list.controls.extend([ft.Container(padding=ft.Padding(0,10,0,5), content=ft.Text(cat.upper(), weight="bold", color="orange", size=11)), *[ft.Row([ft.Checkbox(label=it[0], expand=True), ft.Text(f"{round(it[1],1)} {it[2]}", weight="bold")]) for it in database.generar_lista_compra() if it[3] == cat]]) for cat in CATEGORIAS], setattr(modal_compra, 'open', True), page.update()])]),
                ui_grid_menu
            ])))
        elif idx == 3:
            scrollable_content.controls.append(
                ft.Container(padding=20, content=ft.Column([
                    ft.Row([ft.Text("Estado de la Red:", size=16, weight="bold", expand=True), ft.Button("📡 Test de Conexión Groq", on_click=probar_conexion_ia)]),
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
    ft.run(main, view=ft.AppView.WEB_BROWSER, host="0.0.0.0", port=8550)

def main(page: ft.Page):
    page.title = "Flet 0.84+ Moderno"
    # Usamos constantes en MAYÚSCULAS
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    
    label = ft.Text("¡Funciona perfectamente!", size=30, color="blue")
    
    def cambiar_texto(e):
        label.value = "¡Actualizado y sin errores!"
        label.update()

    # Cambiamos ElevatedButton por FilledButton (el estándar nuevo)
    # Y corregimos el alignment a CENTER
    page.add(
        ft.Column(
            [
                label,
                ft.FilledButton("Haz clic aquí", on_click=cambiar_texto),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )
    )

if __name__ == "__main__":
    # Cambiamos app() por run() como pide el aviso
    ft.run(main, host="0.0.0.0", port=8550)
