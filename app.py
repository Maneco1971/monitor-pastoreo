import streamlit as st
import pandas as pd
import geopandas as gpd
import folium
from streamlit_folium import st_folium
from datetime import datetime

st.set_page_config(page_title="Monitor de Pastoreo", layout="wide")

# 1. Carga de datos espaciales y transaccionales
@st.cache_data(ttl=300) # Recarga cada 5 minutos
def load_data():
    # Cargar archivo de polígonos (KML convertido a GeoJSON)
    gdf_parcelas = gpd.read_file("glencoe.geojson")
    
    # Enlace de exportación CSV directo desde Google Sheets
    SHEET_ID = "1uDFTp_B8NMuu4vteXgAY_ACiStijAr6UZdC6bYSCVgA"
    
    url_movimientos = f"https://docs.google.com/spreadsheets/d/1uDFTp_B8NMuu4vteXgAY_ACiStijAr6UZdC6bYSCVgA/gviz/tq?tqx=out:csv&sheet=Movimientos"
    url_lotes = f"https://docs.google.com/spreadsheets/d/1uDFTp_B8NMuu4vteXgAY_ACiStijAr6UZdC6bYSCVgA/gviz/tq?tqx=out:csv&sheet=Lotes"
    
    df_mov = pd.read_csv(url_movimientos)
    df_lotes = pd.read_csv(url_lotes)
    
    return gdf_parcelas, df_mov, df_lotes

gdf_parcelas, df_mov, df_lotes = load_data()

# 2. Procesamiento transaccional (Event Sourcing)
df_mov['Fecha_Hora'] = pd.to_datetime(df_mov['Fecha_Hora'])
df_mov = df_mov.sort_values('Fecha_Hora')

# Identificar la ubicación actual de cada lote (último movimiento)
df_pos_actual = df_mov.groupby('ID_Lote').last().reset_index()

# Cruzar con información del lote (Categoría y Cabezas)
df_pos_actual = df_pos_actual.merge(df_lotes, on='ID_Lote', how='left')

# Calcular días de estancia actual por lote
ahora = pd.Timestamp.now()
df_pos_actual['Dias_Ocupacion'] = (ahora - df_pos_actual['Fecha_Hora']).dt.days

# Agrupar por parcela para soportar pastoreo mixto (múltiples lotes en un potrero)
resumen_parcelas = df_pos_actual.groupby('ID_Parcela_Destino').agg(
    Lotes_Presentes=('ID_Lote', lambda x: ", ".join(x)),
    Categorias=('Categoria_Animal', lambda x: ", ".join(x.dropna().unique())),
    Total_Cabezas=('Cabezas', 'sum'),
    Dias_Ocupacion_Max=('Dias_Ocupacion', 'max')
).reset_index()

# 3. Integración con el GeoDataFrame
gdf_mapa = gdf_parcelas.merge(resumen_parcelas, left_on='ID_Parcela', right_on='ID_Parcela_Destino', how='left')

# Asignar estado espacial
gdf_mapa['Estado'] = gdf_mapa['Lotes_Presentes'].apply(lambda x: 'Ocupado' if pd.notnull(x) else 'Libre')

# 4. Renderizado del Mapa con Folium
st.title("🛰️ Monitor Geográfico de Pastoreo")

m = folium.Map(location=[gdf_mapa.geometry.centroid.y.mean(), gdf_mapa.geometry.centroid.x.mean()], zoom_start=14)

def style_function(feature):
    estado = feature['properties']['Estado']
    return {
        'fillColor': '#ff4b4b' if estado == 'Ocupado' else '#00c853',
        'color': 'black',
        'weight': 1,
        'fillOpacity': 0.6
    }

# Tooltip interactivo al pasar el cursor sobre la parcela
tooltip = folium.GeoJsonTooltip(
    fields=['ID_Parcela', 'Nombre', 'Estado', 'Lotes_Presentes', 'Categorias', 'Total_Cabezas', 'Dias_Ocupacion_Max'],
    aliases=['Parcela:', 'Nombre:', 'Estado:', 'Lotes:', 'Categorías:', 'Cabezas Totales:', 'Días Ocupación:'],
    localize=True
)

folium.GeoJson(
    gdf_mapa,
    style_function=style_function,
    tooltip=tooltip
).add_to(m)

# Despliegue en la interfaz Streamlit
col1, col2 = st.columns([3, 1])

with col1:
    st_folium(m, width=900, height=600)

with col2:
    st.metric("Potreros Ocupados", len(gdf_mapa[gdf_mapa['Estado'] == 'Ocupado']))
    st.metric("Potreros Libres", len(gdf_mapa[gdf_mapa['Estado'] == 'Libre']))
    
    st.subheader("Detalle de Lotes")
    st.dataframe(df_pos_actual[['ID_Lote', 'Categoria_Animal', 'Cabezas', 'ID_Parcela_Destino', 'Dias_Ocupacion']])