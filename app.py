import streamlit as st
import geopandas as gpd
import pandas as pd
import folium
from streamlit_folium import st_folium
from datetime import datetime

# Configuración de la página
st.set_page_config(
    page_title="Monitor de Pastoreo",
    page_icon="🌾",
    layout="wide"
)

st.title("🌾 Monitor de Pastoreo y Estado de Parcelas")

# ==========================================
# 1. CARGA DE DATOS Y FILTRADO
# ==========================================

SHEET_ID = "1uDFTp_B8NMuu4vteXgAY_ACiStijAr6UZdC6bYSCVgA"

url_movimientos = f"https://docs.google.com/spreadsheets/d/1uDFTp_B8NMuu4vteXgAY_ACiStijAr6UZdC6bYSCVgA/gviz/tq?tqx=out:csv&sheet=Movimientos"
url_lotes = f"https://docs.google.com/spreadsheets/d/1uDFTp_B8NMuu4vteXgAY_ACiStijAr6UZdC6bYSCVgA/gviz/tq?tqx=out:csv&sheet=Lotes"

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
    
    # Obtener el último movimiento para cada parcela de destino
    ultimos_mov = (
        df_movimientos.sort_values('Fecha_Hora')
        .groupby('ID_Parcela_Destino')
        .last()
        .reset_index()
    )

    # Fusionar con lotes
    mov_con_lotes = ultimos_mov.merge(
        df_lotes, 
        left_on='ID_Lote', 
        right_on='ID_Lote', 
        how='left'
    )

    # Calcular días de permanencia
    hoy = datetime.now()
    mov_con_lotes['Dias_En_Parcela'] = (hoy - mov_con_lotes['Fecha_Hora']).dt.days

    # CONVERSIÓN CRÍTICA: Transformar Timestamp a texto para evitar error de serialización JSON en Folium
    mov_con_lotes['Fecha_Hora'] = mov_con_lotes['Fecha_Hora'].dt.strftime('%Y-%m-%d %H:%M')

    # Cruzar geometrías con la información procesada
    gdf_resultado = gdf_parcelas.merge(
        mov_con_lotes,
        left_on='ID_Parcela',
        right_on='ID_Parcela_Destino',
        how='left'
    )

    # Determinar estado de ocupación
    gdf_resultado['Ocupado'] = gdf_resultado['ID_Lote'].notna()

    # Llenar valores nulos para mostrar textos limpios en la etiqueta (Tooltip)
    gdf_resultado['ID_Lote'] = gdf_resultado['ID_Lote'].fillna('Sin Lote (Libre)')
    gdf_resultado['Dias_En_Parcela'] = gdf_resultado['Dias_En_Parcela'].fillna(0).astype(int)

    # ==========================================
    # 3. CONSTRUCCIÓN DEL MAPA INTERACTIVO
    # ==========================================

    centroide = gdf_todo.geometry.unary_union.centroid
    m = folium.Map(location=[centroide.y, centroide.x], zoom_start=14, tiles="OpenStreetMap")

    def estilar_parcela(feature):
        ocupado = feature['properties'].get('Ocupado', False)
        return {
            'fillColor': '#e74c3c' if ocupado else '#2ecc71',  # Rojo = Ocupado, Verde = Libre
            'color': '#2c3e50',
            'weight': 1.5,
            'fillOpacity': 0.6
        }

    folium.GeoJson(
        gdf_resultado,
        style_function=estilar_parcela,
        tooltip=folium.GeoJsonTooltip(
            fields=['ID_Parcela', 'Nombre', 'ID_Lote', 'Dias_En_Parcela'],
            aliases=['Parcela:', 'Nombre:', 'Estado / Lote:', 'Días en Potrero:'],
            localize=True
        ),
        name="Parcelas"
    ).add_to(m)

    # ==========================================
    # 4. AGREGAR BORDE EXCLUIDO (ELP)
    # ==========================================

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

    # ==========================================
    # 5. MOSTRAR EN STREAMLIT
    # ==========================================

    st_folium(m, width=1000, height=600)

except Exception as e:
    st.error(f"Error al cargar o procesar los datos: {e}")
