import streamlit as st
import geopandas as gpd
import pandas as pd
import folium
from folium.plugins import Fullscreen
from streamlit_folium import st_folium
from datetime import datetime

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
    
    # Obtener el último movimiento por parcela de destino
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

    # Formatear la fecha a texto explícito
    mov_con_lotes['Fecha_Ingreso_Txt'] = mov_con_lotes['Fecha_Hora'].dt.strftime('%d/%m/%Y %H:%M')

    # Cruzar geometrías con la información de pastoreo
    gdf_resultado = gdf_parcelas.merge(
        mov_con_lotes,
        left_on='ID_Parcela',
        right_on='ID_Parcela_Destino',
        how='left'
    )

    # SANITIZACIÓN CRÍTICA PARA FOLIUM:
    # Eliminar o convertir cualquier columna de tipo Timestamp a string dentro de gdf_resultado
    for col in gdf_resultado.select_dtypes(include=['datetime64', 'datetime64[ns]', 'datetime64[ns, UTC]']).columns:
        gdf_resultado[col] = gdf_resultado[col].astype(str)

    # Definir ocupación
    gdf_resultado['Ocupado'] = gdf_resultado['ID_Lote'].notna()

    gdf_resultado['ID_Lote_Mostrar'] = gdf_resultado['ID_Lote'].fillna('Sin Lote (Libre)')
    gdf_resultado['Dias_En_Parcela_Mostrar'] = gdf_resultado['Dias_En_Parcela'].fillna(0).astype(int)

    # ==========================================
    # 3. CONSTRUCCIÓN DEL MAPA INTERACTIVO
    # ==========================================

    col1, col2 = st.columns([2, 1])

    with col1:
        centroide = gdf_todo.geometry.unary_union.centroid
        m = folium.Map(location=[centroide.y, centroide.x], zoom_start=14, tiles="OpenStreetMap")
# 2. AGREGAR PLUGIN DE PANTALLA COMPLETA
        Fullscreen(
            position='topright',
            title='Expandir a pantalla completa',
            titleCancel='Salir de pantalla completa',
            forceSeparateButton=True
        ).add_to(m)
        def estilar_parcela(feature):
            ocupado = feature['properties'].get('Ocupado', False)
            return {
                'fillColor': '#e74c3c' if ocupado else '#2ecc71',
                'color': '#2c3e50',
                'weight': 1.5,
                'fillOpacity': 0.6
            }

        folium.GeoJson(
            gdf_resultado,
            style_function=estilar_parcela,
            tooltip=folium.GeoJsonTooltip(
                fields=['Nombre', 'ID_Lote_Mostrar', 'Dias_En_Parcela_Mostrar'],
                aliases=['Nombre:', 'Lote:', 'Días en Potrero:'],
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
                'ID_Lote', 
                'Fecha_Ingreso_Txt', 
                'Dias_En_Parcela_Mostrar'
            ]].rename(columns={
                'ID_Parcela': 'ID',
                'Nombre': 'Potrero',
                'ID_Lote': 'Lote Actual',
                'Fecha_Ingreso_Txt': 'Fecha Ingreso',
                'Dias_En_Parcela_Mostrar': 'Días'
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
