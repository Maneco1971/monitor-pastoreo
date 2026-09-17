import streamlit as st
import geopandas as gpd
import pandas as pd
import folium
from folium.plugins import Fullscreen
from streamlit_folium import st_folium
from datetime import datetime

# ==========================================
# FUNCIONES AUXILIARES
# ==========================================

# Configuración de la página
st.set_page_config(
    page_title="Monitor de Pastoreo",
    page_icon="🌾",
    layout="wide"
)

st.title("GLENCOE - Monitor de Pastoreo")

# ==========================================
# 1. CARGA DE DATOS Y FILTRADO
# ==========================================

SHEET_ID = "1uDFTp_B8NMuu4vteXgAY_ACiStijAr6UZdC6bYSCVgA"

url_movimientos = "https://docs.google.com/spreadsheets/d/1uDFTp_B8NMuu4vteXgAY_ACiStijAr6UZdC6bYSCVgA/gviz/tq?tqx=out:csv&sheet=Movimientos"
url_lotes = "https://docs.google.com/spreadsheets/d/1uDFTp_B8NMuu4vteXgAY_ACiStijAr6UZdC6bYSCVgA/gviz/tq?tqx=out:csv&sheet=Lotes"

@st.cache_data(ttl=300)
def cargar_datos():
    gdf_raw = gpd.read_file("mapa_predio.geojson")
    
    if gdf_raw.crs != "EPSG:4326":
        gdf_raw = gdf_raw.to_crs(epsg=4326)
    
    df_mov = pd.read_csv(url_movimientos)
    df_lot = pd.read_csv(url_lotes)
    
    return gdf_raw, df_mov, df_lot

try:
    gdf_todo, df_movimientos, df_lotes = cargar_datos()

    # Separar polígono de control (Área excluida)
    gdf_borde = gdf_todo[gdf_todo['ID_Parcela'] == 'EXCLUIDO']
    gdf_parcelas = gdf_todo[gdf_todo['ID_Parcela'] != 'EXCLUIDO'].copy()

    # ==========================================
    # 2. PROCESAMIENTO DE ESTADO ACTUAL
    # ==========================================
    
    df_movimientos['Fecha_Hora'] = pd.to_datetime(df_movimientos['Fecha_Hora'])
    
    # 1. Tomar la tabla Lotes como base
    lotes_estado = df_lotes.copy()

    # --- NUEVO: Construcción de etiqueta descriptiva ---
    def construir_etiqueta(row):
        # Convertir cabezas a entero para quitar decimales, asumiendo 0 si está vacío
        cabezas = str(int(row['Cabezas'])) if pd.notna(row['Cabezas']) else "0"
        categoria = str(row['Categoria_Animal']) if pd.notna(row['Categoria_Animal']) else ""
        observaciones = str(row['Observaciones']) if pd.notna(row['Observaciones']) else ""
        
        # Ensamblar: "45 Vacas de cría"
        texto = f"{cabezas} {categoria}".strip()
        
        # Añadir observaciones solo si existen: "45 Vacas de cría (Hereford)"
        if observaciones.strip():
            texto += f" ({observaciones})"
            
        return texto

    # Aplicar la función fila por fila
    lotes_estado['Etiqueta_Lote'] = lotes_estado.apply(construir_etiqueta, axis=1)
    # ---------------------------------------------------

    # 2. Extraer el último movimiento si la tabla no está vacía
    if not df_movimientos.empty:
        ultimos_mov = df_movimientos.sort_values('Fecha_Hora').groupby('ID_Lote').last().reset_index()
        lotes_estado = lotes_estado.merge(ultimos_mov[['ID_Lote', 'ID_Parcela_Destino', 'Fecha_Hora']], on='ID_Lote', how='left')
    else:
        lotes_estado['ID_Parcela_Destino'] = None
        lotes_estado['Fecha_Hora'] = pd.NaT

    # 3. Lógica de "Punto Cero"
    if 'ID_Parcela_Inicial' not in lotes_estado.columns:
        lotes_estado['ID_Parcela_Inicial'] = None
        
    lotes_estado['Parcela_Actual'] = lotes_estado['ID_Parcela_Destino'].fillna(lotes_estado['ID_Parcela_Inicial'])
    lotes_estado = lotes_estado.dropna(subset=['Parcela_Actual'])

    # 4. Calcular días 
    hoy = datetime.now()
    lotes_estado['Fecha_Hora'] = pd.to_datetime(lotes_estado['Fecha_Hora'])
    lotes_estado['Dias_En_Parcela'] = (hoy - lotes_estado['Fecha_Hora']).dt.days.fillna(0)
    lotes_estado['Fecha_Ingreso_Txt'] = lotes_estado['Fecha_Hora'].dt.strftime('%d/%m/%Y %H:%M').fillna('Origen Inicial')

    # 5. Agrupar por ubicación usando la nueva etiqueta descriptiva
    resumen_parcela = lotes_estado.groupby('Parcela_Actual').agg(
        Lotes_Presentes=('Etiqueta_Lote', lambda x: ' + '.join(x.astype(str))),
        Dias_Maximos=('Dias_En_Parcela', 'max'),
        Fechas_Ingreso=('Fecha_Ingreso_Txt', lambda x: ' | '.join(x.astype(str)))
    ).reset_index()

    # --- NUEVA LÓGICA DE COLORES RELATIVOS ---
    # Paleta: Verde oscuro, Verde claro, Amarillo, Naranja, Rojo
    paleta = ['#27ae60', '#2ecc71', '#f1c40f', '#e67e22', '#e74c3c']

    if not resumen_parcela.empty:
        dias_min = resumen_parcela['Dias_Maximos'].min()
        dias_max = resumen_parcela['Dias_Maximos'].max()
        
        if dias_max == dias_min:
            # Si todos tienen los mismos días, asignar verde claro
            resumen_parcela['Color_Mapa'] = paleta[1]
        else:
            # Dividir el rango entre min y max en 5 niveles exactos
            resumen_parcela['Nivel_Color'] = pd.cut(
                resumen_parcela['Dias_Maximos'], 
                bins=5, 
                labels=False, 
                include_lowest=True
            )
            resumen_parcela['Color_Mapa'] = resumen_parcela['Nivel_Color'].apply(lambda x: paleta[int(x)])
    else:
        resumen_parcela['Color_Mapa'] = None
    # -----------------------------------------

    # 6. Cruzar geometrías
    gdf_resultado = gdf_parcelas.merge(
        resumen_parcela,
        left_on='ID_Parcela',
        right_on='Parcela_Actual',
        how='left'
    )   
    # SANITIZACIÓN CRÍTICA PARA FOLIUM:
    for col in gdf_resultado.select_dtypes(include=['datetime64', 'datetime64[ns]', 'datetime64[ns, UTC]']).columns:
        gdf_resultado[col] = gdf_resultado[col].astype(str)

    # Definir variables consolidadas para visualización
    gdf_resultado['Ocupado'] = gdf_resultado['Lotes_Presentes'].notna()
    gdf_resultado['ID_Lote_Mostrar'] = gdf_resultado['Lotes_Presentes'].fillna('Sin Lote (Libre)')
    gdf_resultado['Dias_En_Parcela_Mostrar'] = gdf_resultado['Dias_Maximos'].fillna(0).astype(int)
    gdf_resultado['Fechas_Ingreso_Mostrar'] = gdf_resultado['Fechas_Ingreso'].fillna('-')

    # ==========================================
    # 3. CONSTRUCCIÓN DEL MAPA INTERACTIVO
    # ==========================================

    col1, col2 = st.columns([2, 1])

    with col1:
        centroide = gdf_todo.geometry.unary_union.centroid
        m = folium.Map(location=[centroide.y, centroide.x], zoom_start=14, tiles="OpenStreetMap")
        
        # AGREGAR PLUGIN DE PANTALLA COMPLETA
        Fullscreen(
            position='topright',
            title='Expandir a pantalla completa',
            titleCancel='Salir de pantalla completa',
            forceSeparateButton=True
        ).add_to(m)
        
    def estilar_parcela(feature):
            ocupado = feature['properties'].get('Ocupado', False)
            color_asignado = feature['properties'].get('Color_Mapa')
            
            # Manejo de nulos si el potrero está vacío
            if not color_asignado or pd.isna(color_asignado):
                color_asignado = '#ffffff'
                
            return {
                'fillColor': color_asignado if ocupado else '#ffffff',
                'color': '#2c3e50',
                'weight': 1.5,
                'fillOpacity': 0.7 if ocupado else 0.4
            }

    folium.GeoJson(
            gdf_resultado,
            style_function=estilar_parcela,
            tooltip=folium.GeoJsonTooltip(
                fields=['Nombre', 'ID_Lote_Mostrar', 'Dias_En_Parcela_Mostrar'],
                aliases=['Nombre:', 'Lote(s):', 'Días en Potrero (Max):'],
                localize=True
            ),
            name="Parcelas"
        ).add_to(m)

        if not gdf_borde.empty:
            capa_borde = folium.GeoJson(
                gdf_borde,
                style_function=lambda feature: {
                    'color': 'black',
                    'weight': 3,
                    'fillOpacity': 0,
                    'dashArray': '5, 5'
                },
                name="Área Excluida"
            )
            folium.Tooltip("ELP").add_to(capa_borde)
            capa_borde.add_to(m)

        st_folium(m, height=750, use_container_width=True)

    # ==========================================
    # 4. TABLA RESUMEN DE PARCELAS OCUPADAS
    # ==========================================

    with col2:
        st.subheader("📋 Parcelas Ocupadas")
        
        df_ocupadas = gdf_resultado[gdf_resultado['Ocupado'] == True].copy()

        if not df_ocupadas.empty:
            tabla_mostrar = df_ocupadas[[
                'ID_Parcela', 
                'Nombre', 
                'ID_Lote_Mostrar', 
                'Fechas_Ingreso_Mostrar', 
                'Dias_En_Parcela_Mostrar'
            ]].rename(columns={
                'ID_Parcela': 'ID',
                'Nombre': 'Potrero',
                'ID_Lote_Mostrar': 'Lote(s) Actual(es)',
                'Fechas_Ingreso_Mostrar': 'Fecha(s) Ingreso',
                'Dias_En_Parcela_Mostrar': 'Días (Máx)'
            })

            st.dataframe(
                tabla_mostrar, 
                hide_index=True, 
                use_container_width=True
            )
            
            st.metric("Total Parcelas Ocupadas", len(df_ocupadas))
        else:
            st.info("No hay parcelas ocupadas en este momento.")

except Exception as e:
    st.error(f"Error al cargar o procesar los datos: {e}")
