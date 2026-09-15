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
def obtener_color_dias(dias, dias_maximos=30):
    if pd.isna(dias) or dias is None:
        return '#ffffff'
    
    factor = min(max(dias / dias_maximos, 0.0), 1.0)
    r = int(46 + factor * (231 - 46))
    g = int(204 + factor * (76 - 204))
    b = int(113 + factor * (60 - 113))
    return f'#{r:02x}{g:02x}{b:02x}'

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
    
    # Obtener el último movimiento POR LOTE para conocer la ubicación actual de cada uno
    ultimos_mov_lote = (
        df_movimientos.sort_values('Fecha_Hora')
        .groupby('ID_Lote')
        .last()
        .reset_index()
    )

    # Fusionar con la información de los lotes
    mov_con_lotes = ultimos_mov_lote.merge(
        df_lotes, 
        on='ID_Lote', 
        how='left'
    )

    # Calcular días de permanencia individuales
    hoy = datetime.now()
    mov_con_lotes['Dias_En_Parcela'] = (hoy - mov_con_lotes['Fecha_Hora']).dt.days
    mov_con_lotes['Fecha_Ingreso_Txt'] = mov_con_lotes['Fecha_Hora'].dt.strftime('%d/%m/%Y %H:%M')

    # Agrupar por parcela destino para permitir múltiples lotes
    resumen_parcela = mov_con_lotes.groupby('ID_Parcela_Destino').agg(
        Lotes_Presentes=('ID_Lote', lambda x: ' + '.join(x.astype(str))),
        Dias_Maximos=('Dias_En_Parcela', 'max'),
        Fechas_Ingreso=('Fecha_Ingreso_Txt', lambda x: ' | '.join(x.astype(str)))
    ).reset_index()

    # Cruzar geometrías con la información agregada de pastoreo
    gdf_resultado = gdf_parcelas.merge(
        resumen_parcela,
        left_on='ID_Parcela',
        right_on='ID_Parcela_Destino',
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
            dias = feature['properties'].get('Dias_En_Parcela_Mostrar', 0)
            return {
                'fillColor': obtener_color_dias(dias, 30) if ocupado else '#ffffff',
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
