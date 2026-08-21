import flet as ft
import database
import urllib.request
import urllib.parse
import urllib.error
import json
import random
import os
import mimetypes
import threading  # LIBRERÍA AÑADIDA PARA HILOS EN SEGUNDO PLANO

URL_INTERMEDIARIO = "http://intermediario-cocina:8000"

def main(page: ft.Page):
    page.title = "CocinApp AI v3.0"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.spacing = 0
    page.scroll = None

    database.crear_tablas()

    # --- INDICADOR DE CARGA GLOBAL ---
    barra_progreso = ft.ProgressBar(visible=False, color="blue", bgcolor="#eeeeee")

    # --- VARIABLES DE ESTADO ---
    id_receta_activa = None
    id_ing_editar = None
    slot_activo_dia = None
    slot_activo_momento = None

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

    # --- EJECUTOR DE TAREAS EN SEGUNDO PLANO CORREGIDO ---
    def ejecutar_ia_background(tarea_func, *args):
        def wrapper():
            barra_progreso.visible = True
            page.update()
            try:
                tarea_func(*args)
            except Exception as e:
                notificar(f"Error interno: {e}")
            finally:
                barra_progreso.visible = False
                page.update()
        # En lugar de run_task, usamos un hilo nativo que no requiere async
        threading.Thread(target=wrapper, daemon=True).start()

    def normalizar_receta(datos, nombre_defecto):
        # Tomamos el nombre dictado por la IA de forma autónoma
        nombre_ia = datos.get("nombre", datos.get("name", nombre_defecto)) if isinstance(datos, dict) else nombre_defecto
        
        if isinstance(datos, list):
            return {"nombre": nombre_ia, "ingredientes": datos}
        elif isinstance(datos, dict):
            ingredientes = datos.get("ingredientes", datos.get("ingredients", []))
            if not ingredientes:
                for v in datos.values():
                    if isinstance(v, list): ingredientes = v; break
            return {"nombre": nombre_ia, "ingredientes": ingredientes}
        return {"nombre": nombre_ia, "ingredientes": []}

    def extraer_desde_texto(texto_plano):
        if not texto_plano:
            notificar("⚠️ Pega el texto de la receta primero.")
            return
        notificar("🧠 IA Leyendo texto (segundo plano)...")
        try:
            url = f"{URL_INTERMEDIARIO}/extraer-texto"
            payload = json.dumps({"texto": texto_plano}).encode('utf-8')
            req = urllib.request.Request(url, data=payload, method='POST')
            req.add_header('Content-Type', 'application/json')
            
            with urllib.request.urlopen(req, timeout=300) as response:
                raw_data = response.read().decode('utf-8')
                data = json.loads(raw_data)
                if isinstance(data, str): data = json.loads(data)
                
                datos_normalizados = normalizar_receta(data, "Receta de Google Lens")
                if database.importar_receta_json(datos_normalizados):
                    notificar(f"✅ ¡{datos_normalizados['nombre']} guardada!")
                    txt_texto_ia.value = ""
                    cambiar_vista(1)
                else:
                    notificar("❌ Error al guardar en la base de datos")
        except Exception as e: 
            notificar("⚠️ Error de red o Timeout en IA.")

    def extraer_desde_url(url_target):
        if not url_target:
            notificar("⚠️ Introduce una URL válida.")
            return
        notificar("🧠 IA Analizando Web (segundo plano)...")
        try:
            params = urllib.parse.urlencode({"url": url_target})
            url = f"{URL_INTERMEDIARIO}/extraer-url?{params}"
            
            with urllib.request.urlopen(url, timeout=300) as response:
                raw_data = response.read().decode('utf-8')
                data = json.loads(raw_data)
                if isinstance(data, str): data = json.loads(data)
                
                datos_normalizados = normalizar_receta(data, "Receta Importada")
                if database.importar_receta_json(datos_normalizados):
                    notificar(f"✅ ¡{datos_normalizados['nombre']} guardada!")
                    url_in.value = ""
                    cambiar_vista(1)
                else:
                    notificar("❌ Error al guardar en la base de datos")
        except Exception as e: 
            notificar("⚠️ Error de red o Timeout en IA.")

    def procesar_archivo_local(file_path):
        if not file_path or not os.path.exists(file_path):
            notificar("⚠️ Archivo no encontrado. Súbelo primero.")
            return
            
        notificar("🧠 IA Procesando Imagen (segundo plano)...")
        try:
            boundary = '----FletBoundary' + str(random.randint(10000000000, 100000000000))
            with open(file_path, "rb") as f: file_content = f.read()
            filename = os.path.basename(file_path)
            mime_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
            
            body = (f"--{boundary}\r\n"
                    f"Content-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
                    f"Content-Type: {mime_type}\r\n\r\n").encode('utf-8') + file_content + f"\r\n--{boundary}--\r\n".encode('utf-8')
            
            req = urllib.request.Request(f"{URL_INTERMEDIARIO}/extraer-imagen", data=body, method='POST')
            req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
            req.add_header('Content-Length', str(len(body)))
            
            with urllib.request.urlopen(req, timeout=300) as response:
                if response.getcode() == 200:
                    raw_data = response.read().decode('utf-8')
                    data = json.loads(raw_data)
                    if isinstance(data, str): data = json.loads(data)
                    
                    datos_normalizados = normalizar_receta(data, "Receta desde Imagen")
                    if database.importar_receta_json(datos_normalizados):
                        notificar(f"✅ ¡{datos_normalizados['nombre']} guardada!")
                        txt_ruta_imagen.value = "" 
                        cambiar_vista(1)
                    else:
                        notificar("❌ Error al guardar en la base de datos")
        except Exception as ex:
            notificar("⚠️ Error de red o Timeout en IA.")

    def cargar_datos_receta(id_rec):
        detalles = database.obtener_detalles_receta(id_rec)
        lista_detalles_modal.controls.clear()
        for d in detalles:
            lista_detalles_modal.controls.append(
                ft.Row([
                    ft.Text(f"• {d[0]}", expand=True, size=13), 
                    ft.Text(f"{d[1]} {d[2]}", weight="bold", color="blue", size=13),
                    ft.TextButton("🗑️", on_click=lambda _, n=d[0]: [database.eliminar_ingrediente_a_receta(id_rec, n), cargar_datos_receta(id_rec)])
                ])
            )
        page.update()

    def abrir_detalles_receta(receta):
        nonlocal id_receta_activa
        id_receta_activa = receta[0]
        sel_ing_drop.options = [ft.dropdown.Option(key=str(i[0]), text=i[1]) for i in database.obtener_ingredientes()]
        
        # Cargar datos para edición (nombre y etiquetas)
        ed_rec_nombre.value = receta[1]
        
        tags_crudos = receta[5] if len(receta) > 5 and receta[5] else ""
        lista_tags = [t.strip().lower() for t in tags_crudos.split(',')]
        
        chk_adulto.value = "adultos" in lista_tags or "adulto" in lista_tags
        chk_nino.value = "niños" in lista_tags or "niño" in lista_tags
        
        # Filtramos etiquetas generales (quitando adulto/niño) para ponerlas en el TextField
        otras_etiquetas = [t.strip() for t in tags_crudos.split(',') if t.strip().lower() not in ["adultos", "adulto", "niños", "niño"]]
        ed_rec_etiquetas.value = ", ".join(otras_etiquetas)
        
        cargar_datos_receta(id_receta_activa)
        page.dialog = modal_detalles
        modal_detalles.open = True
        page.update()

    def guardar_edicion_receta(e):
        etiquetas_finales = []
        if chk_adulto.value: etiquetas_finales.append("Adultos")
        if chk_nino.value: etiquetas_finales.append("Niños")
        
        if ed_rec_etiquetas.value.strip(): 
            etiquetas_finales.extend([t.strip() for t in ed_rec_etiquetas.value.split(',') if t.strip()])
            
        tags_str = ", ".join(etiquetas_finales)
        
        try:
            database.actualizar_receta(id_receta_activa, ed_rec_nombre.value, tags_str)
            notificar("✅ Cambios guardados exitosamente")
            refrescar_recetas()
        except Exception as ex:
            notificar(f"❌ Error al guardar: {ex}")

    def generar_menu_automatico(e):
        recetas = database.obtener_recetas()
        if len(recetas) < 4:
            notificar("⚠️ Necesitas más platos guardados"); return
        for i in range(7):
            database.agregar_plan_multi(i, "Almuerzo", random.choice(recetas)[0])
            database.agregar_plan_multi(i, "Cena", random.choice(recetas)[0])
        notificar("✨ Menú semanal generado")
        refrescar_menu()

    # ==========================================
    # DEFINICIÓN DE CONTROLES E INTERFAZ
    # ==========================================
    CATEGORIAS = ["Fruta/Verdura", "Carne/Pescado", "Lácteos/Huevos", "Despensa", "Congelados", "Varios"]
    UNIDADES = ["g", "ml", "uds", "cda", "pizca"]
    DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    MOMENTOS = ["Almuerzo", "Cena"]  # Solo almuerzo y cena como solicitaste

    scrollable_content = ft.Column(expand=True, scroll="auto", spacing=0)
    sel_ing_drop = ft.Dropdown(label="Alimento", expand=True, border_radius=10)
    txt_ing_cant = ft.TextField(label="Cant.", width=80, keyboard_type="number")
    lista_detalles_modal = ft.Column(spacing=5, scroll="auto")
    grid_seleccion_platos = ft.Column(scroll="adaptive", height=250)
    
    url_in = ft.TextField(label="URL de la receta", expand=True)
    txt_ruta_imagen = ft.TextField(label="Nombre del archivo (ej. receta.jpg)", expand=True)
    txt_texto_ia = ft.TextField(label="Pega aquí el texto extraído (ej. Google Lens)", expand=True, multiline=True, min_lines=3, max_lines=6)

    # Controles de Edición de Receta
    ed_rec_nombre = ft.TextField(label="Nombre de la receta", expand=True)
    chk_adulto = ft.Checkbox(label="Adultos")
    chk_nino = ft.Checkbox(label="Niños")
    ed_rec_etiquetas = ft.TextField(label="Otras (ej: Italiana, Cuchareo)", expand=True)

    modal_detalles = ft.AlertDialog(
        content=ft.Container(
            width=400,
            content=ft.Column([
                ft.Text("Editar Receta", weight="bold", color="blue"),
                ed_rec_nombre,
                ft.Row([chk_adulto, chk_nino]),
                ed_rec_etiquetas,
                ft.Button("💾 Guardar Cambios", on_click=guardar_edicion_receta, bgcolor="blue", color="white"),
                ft.Divider(),
                ft.Text("Ingredientes", weight="bold"),
                ft.Container(content=lista_detalles_modal, padding=10, bgcolor="#f5f5f5", border_radius=10, height=150), 
                ft.Row([sel_ing_drop, txt_ing_cant], spacing=10), 
                ft.Button("➕ Añadir Ingrediente", on_click=lambda _: [database.agregar_ingrediente_a_receta(id_receta_activa, int(sel_ing_drop.value), float(txt_ing_cant.value)) if sel_ing_drop.value else None, cargar_datos_receta(id_receta_activa)]), 
                ft.Divider(), 
                ft.Button("🗑️ Eliminar Receta", color="red", on_click=lambda _: [database.eliminar_receta(id_receta_activa), cerrar_dialogos(), refrescar_recetas()])
            ], tight=True, scroll="auto")
        ),
        actions=[ft.Button("Cerrar", on_click=cerrar_dialogos)]
    )

    txt_ed_nom = ft.TextField(label="Nombre")
    dr_ed_uni = ft.Dropdown(label="U", options=[ft.dropdown.Option(u) for u in UNIDADES])
    dr_ed_cat = ft.Dropdown(label="Categoría", options=[ft.dropdown.Option(c) for c in CATEGORIAS])
    modal_editar_ing = ft.AlertDialog(
        title=ft.Text("Editar"), 
        content=ft.Column([txt_ed_nom, dr_ed_uni, dr_ed_cat], tight=True), 
        actions=[ft.Button("Guardar", on_click=lambda _: [database.actualizar_ingrediente(id_ing_editar, txt_ed_nom.value, dr_ed_uni.value, dr_ed_cat.value), cerrar_dialogos(), refrescar_alimentos()])]
    )

    ui_compra_list = ft.Column(spacing=10, scroll="auto")
    modal_compra = ft.AlertDialog(
        title=ft.Text("🛒 Lista de la Compra"), 
        content=ft.Container(content=ui_compra_list, width=350, height=450), 
        actions=[ft.Button("Cerrar", on_click=cerrar_dialogos)]
    )

    modal_seleccionar_plato = ft.AlertDialog(
        title=ft.Text("Planificar Turno"), 
        content=ft.Container(width=350, content=grid_seleccion_platos), 
        actions=[
            ft.Button("Limpiar Turno", color="red", on_click=lambda _: [database.limpiar_plan_turno(slot_activo_dia, slot_activo_momento), refrescar_menu(), cerrar_dialogos()]),
            ft.Button("Cerrar", on_click=cerrar_dialogos)
        ]
    )

    page.overlay.extend([modal_detalles, modal_editar_ing, modal_compra, modal_seleccionar_plato])

    ui_list_alimentos = ft.Column(spacing=8)
    ui_list_recetas = ft.Row(wrap=True, spacing=10)
    ui_grid_menu = ft.Column(spacing=20)

    def refrescar_alimentos():
        ui_list_alimentos.controls.clear()
        for ing in database.obtener_ingredientes():
            ui_list_alimentos.controls.append(
                ft.Container(
                    bgcolor="white", border_radius=10, padding=10, border=ft.Border.all(1, "#f0f0f0"), 
                    content=ft.Row([
                        ft.Column([ft.Text(ing[1], weight="bold", size=14), ft.Text(f"{ing[3]} | {ing[2]}", size=11, color="grey")], expand=True, spacing=2), 
                        ft.TextButton("✏️", on_click=lambda _, i=ing: [setattr(txt_ed_nom, 'value', i[1]), setattr(dr_ed_uni, 'value', i[2]), setattr(dr_ed_cat, 'value', i[3]), setattr(page, 'dialog', modal_editar_ing), setattr(modal_editar_ing, 'open', True), page.update()]), 
                        ft.TextButton("🗑️", on_click=lambda _, id_i=ing[0]: [database.eliminar_ingrediente(id_i), refrescar_alimentos()])
                    ])
                )
            )
        page.update()

    def refrescar_recetas():
        ui_list_recetas.controls.clear()
        for rec in database.obtener_recetas():
            etiquetas_ui = []
            tags_str = rec[5] if len(rec) > 5 and rec[5] else ""
            if tags_str:
                for tag in tags_str.split(','):
                    tag = tag.strip()
                    if tag:
                        color_bg = "green" if tag.lower() in ["niños", "niño"] else "orange" if tag.lower() in ["adultos", "adulto"] else "indigo"
                        etiquetas_ui.append(ft.Container(content=ft.Text(tag.upper(), size=8, weight="bold", color="white"), bgcolor=color_bg, padding=3, border_radius=5))
            
            ui_list_recetas.controls.append(
                ft.Container(
                    width=150, height=180, bgcolor="white", border_radius=12, border=ft.Border.all(1, "#eeeeee"), 
                    on_click=lambda _, r=rec: abrir_detalles_receta(r), 
                    ink=True, 
                    content=ft.Column([
                        ft.Stack([
                            ft.Image(src=rec[4], height=85, fit="cover", width=150) if rec[4] else ft.Container(height=85, width=150, bgcolor="#f5f5f5", content=ft.Text("🥘", size=25), alignment=ft.Alignment(0,0)), 
                        ]), 
                        ft.Container(padding=8, content=ft.Column([
                            ft.Text(rec[1], size=12, weight="bold", max_lines=2, overflow="ellipsis"), 
                            ft.Row(etiquetas_ui, wrap=True, spacing=2) if etiquetas_ui else ft.Text("Sin clasificar", size=9, color="grey")
                        ], spacing=4))
                    ], spacing=0)
                )
            )
        page.update()

    def abrir_modal_plan(dia_idx, momento):
        nonlocal slot_activo_dia, slot_activo_momento
        slot_activo_dia = dia_idx
        slot_activo_momento = momento
        
        grid_seleccion_platos.controls = [
            ft.ListTile(
                title=ft.Text(r[1]), 
                subtitle=ft.Text(f"{(r[5] if len(r)>5 else '')}"), 
                on_click=lambda _, idr=r[0]: [database.agregar_plan_multi(slot_activo_dia, slot_activo_momento, idr), notificar("✅ Añadido (puedes elegir otro)"), refrescar_menu()]
            ) for r in database.obtener_recetas()
        ]
        page.dialog = modal_seleccionar_plato
        modal_seleccionar_plato.open = True
        page.update()

    def refrescar_menu():
        ui_grid_menu.controls.clear()
        
        plan_dict = {}
        for p in database.obtener_plan_semanal():
            dia, mom, nom = p[0], p[1], p[2]
            key = (dia, mom)
            if key not in plan_dict: plan_dict[key] = []
            plan_dict[key].append(nom)

        for i, dia_nom in enumerate(DIAS):
            slots = []
            for mom in MOMENTOS:
                nombres = plan_dict.get((i, mom), [])
                nombres_combinados = " + ".join(nombres)
                
                slots.append(
                    ft.Container(
                        bgcolor="#e3f2fd" if nombres else "#f9f9f9", border_radius=10, padding=10, expand=True, border=ft.Border.all(1, "#eeeeee"), alignment=ft.Alignment(-1, -1), 
                        on_click=lambda _, d=i, m=mom: abrir_modal_plan(d, m), 
                        ink=True, 
                        content=ft.Column([
                            ft.Row([
                                ft.Text(mom, size=10, weight="bold", color="blue"),
                                ft.Text("➕", size=14, color="blue")
                            ], alignment="spaceBetween"), 
                            ft.Text(nombres_combinados, size=12, weight="bold", color="#333333") if nombres_combinados else ft.Text("Vacío", size=11, italic=True, color="grey")
                        ], spacing=4)
                    )
                )
            ui_grid_menu.controls.append(ft.Column([ft.Text(dia_nom, size=18, weight="bold"), ft.Row(slots, spacing=10)], spacing=8))
        page.update()

    def cambiar_vista(idx):
        scrollable_content.controls.clear()
        if idx == 0:
            scrollable_content.controls.extend([ft.Container(content=ft.Row([ft.Text("Alimentos", size=28, weight="bold", expand=True), ft.Text("🥑", size=28)]), padding=20), ft.Container(padding=20, content=ui_list_alimentos)])
            refrescar_alimentos()
        elif idx == 1:
            scrollable_content.controls.extend([ft.Container(content=ft.Row([ft.Text("Platos", size=28, weight="bold", expand=True), ft.Text("🥘", size=28)]), padding=20), ft.Container(padding=20, content=ui_list_recetas)])
            refrescar_recetas()
        elif idx == 2:
            scrollable_content.controls.extend([
                ft.Container(content=ft.Row([ft.Text("Planificador", size=28, weight="bold", expand=True), ft.Text("📅", size=28)]), padding=20), 
                ft.Container(padding=ft.Padding(20, 0, 20, 10), content=ft.Row([
                    ft.TextButton("✨ Asistente", on_click=generar_menu_automatico), 
                    ft.TextButton("🛒 Lista Compra", on_click=lambda _: [ui_compra_list.controls.clear(), [ui_compra_list.controls.extend([ft.Container(padding=ft.Padding(0,10,0,5), content=ft.Text(cat.upper(), weight="bold", color="orange", size=11)), *[ft.Row([ft.Checkbox(label=it[0], expand=True), ft.Text(f"{round(it[1],1)} {it[2]}", weight="bold")]) for it in database.generar_lista_compra() if it[3] == cat]]) for cat in CATEGORIAS], setattr(modal_compra, 'open', True), page.update()]),
                ], alignment="spaceBetween")), 
                ft.Container(content=ui_grid_menu, padding=20)
            ])
            refrescar_menu()
        else:
            scrollable_content.controls.extend([
                ft.Container(content=ft.Row([ft.Text("IA Local", size=28, weight="bold", expand=True), ft.Text("🧠", size=28)]), padding=20), 
                ft.Container(padding=20, content=ft.Column([
                    ft.Text("1. Importar desde Internet", weight="bold"), 
                    ft.Row([url_in, ft.Button("🔍 Extraer", on_click=lambda _: ejecutar_ia_background(extraer_desde_url, url_in.value))]), 
                    ft.Divider(),
                    ft.Text("2. Importar desde Texto (Google Lens)", weight="bold"),
                    ft.Text("Pega el texto copiado de Lens aquí.", size=11, color="grey"),
                    txt_texto_ia,
                    ft.Button("📝 Extraer desde Texto", on_click=lambda _: ejecutar_ia_background(extraer_desde_texto, txt_texto_ia.value)),
                    ft.Divider(), 
                    ft.Text("3. Importar desde Imagen", weight="bold"),
                    ft.Row([txt_ruta_imagen, ft.Button("📄 Extraer", on_click=lambda _: ejecutar_ia_background(procesar_archivo_local, txt_ruta_imagen.value))])
                ], spacing=15))
            ])
        for i, item in enumerate(nav_bar.controls):
            item.bgcolor = "#e3f2fd" if i == idx else "transparent"
        page.update()

    def nav_btn(e, l, i):
        return ft.Container(
            content=ft.Column([ft.Text(e, size=24), ft.Text(l, size=9, weight="bold")], alignment="center", horizontal_alignment="center", spacing=2), 
            on_click=lambda _: cambiar_vista(i), 
            expand=True, padding=10, border_radius=12, ink=True
        )
    
    nav_bar = ft.Row([
        nav_btn("🥑","Alimentos",0), 
        nav_btn("🥘","Platos",1), 
        nav_btn("📅","Menú",2), 
        nav_btn("🧠","IA Local",3)
    ], alignment="spaceEvenly")
    
    # LA ESTRUCTURA AHORA INCLUYE LA BARRA DE PROGRESO ARRIBA DEL TODO
    page.add(
        ft.Column([
            barra_progreso,
            scrollable_content, 
            ft.Container(content=nav_bar, bgcolor="#f8f9fa", height=85, border=ft.Border(top=ft.BorderSide(1, "#eeeeee")), padding=ft.Padding(5, 0, 5, 0))
        ], expand=True, spacing=0)
    )
    
    cambiar_vista(2)

if __name__ == "__main__":
    ft.run(main, view=ft.AppView.WEB_BROWSER, host="0.0.0.0", port=8550)