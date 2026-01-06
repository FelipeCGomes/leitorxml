# app.py
import streamlit as st
import pandas as pd
import time
import io
import zipfile
import pydeck as pdk
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import database as db
import parsers
import services
from config import CNPJS_CIA # Importação necessária para os nomes das filiais
from utils import br_money, br_weight, br_int, clean_txt, COORDS_UF

# --- FUNÇÕES DE CACHE ---
@st.cache_data(ttl=600, show_spinner="Carregando dados fiscais...")
def get_dados_dashboard():
    """Carrega e cacheia os dados do dashboard por 10 minutos (600s)"""
    return services.get_dashboard_data()

@st.cache_data(ttl=600, show_spinner="Processando CT-es...")
def get_dados_cte_agregados():
    """Carrega e cacheia os dados de CT-e agregados"""
    return services.get_cte_aggregated()

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Leitor Fiscal Master", layout="wide", page_icon="🚚")

# --- ESTILOS CSS ---
st.markdown("""<style>
    .kpi-card { background-color: #fff; border-left: 5px solid #007bff; padding: 15px; border-radius: 8px; margin-bottom: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.08); } 
    .kpi-title { font-size: 13px; color: #6c757d; font-weight: 700; text-transform: uppercase; } 
    .kpi-value { font-size: 24px; font-weight: 800; color: #212529; margin-top: 5px; } 
    .kpi-sub { font-size: 13px; color: #dc3545; font-weight: 600; margin-top: 4px; } 
    .kpi-normal-sub { font-size: 12px; color: #6c757d; margin-top: 4px; } 
    .exec-card { background-color: #002b55; color: white; padding: 20px; border-radius: 5px; text-align: center; } 
    .exec-title { font-size: 14px; text-transform: uppercase; opacity: 0.8; } 
    .exec-value { font-size: 32px; font-weight: bold; margin: 10px 0; } 
    .exec-sub { font-size: 14px; color: #4ade80; font-weight: bold; }
</style>""", unsafe_allow_html=True)

# --- INICIALIZAÇÃO ---
try: db.init_db()
except: pass

services.iniciar_worker()

# --- FUNÇÕES DE FORMAT E UI ---
def br_percent(v): return f"{v:,.2f}".replace(".", ",") + "%" if not pd.isna(v) else "0,00%"
def display_kpi(l, v, s=None, a=False): st.markdown(f'<div class="kpi-card"><div class="kpi-title">{l}</div><div class="kpi-value">{v}</div><div class="{"kpi-sub" if a else "kpi-normal-sub"}">{s if s else ""}</div></div>', unsafe_allow_html=True)
def load_ui(l, k): return st.file_uploader(l, accept_multiple_files=True, type=["xml","zip"], key=f"upl_{k}")

# --- NOVA FUNÇÃO: FORMATAÇÃO DE PARTICIPANTE (FILIAIS) ---
def formatar_participante(doc_num, nome_xml=None):
    if not doc_num: return "ND"
    # Remove pontuação para garantir o match com as chaves do config.py
    clean_doc = str(doc_num).replace('.', '').replace('/', '').replace('-', '').strip()
    
    # Verifica se está na nossa lista de filiais (CNPJS_CIA agora é dict)
    if clean_doc in CNPJS_CIA:
        nome_filial = CNPJS_CIA[clean_doc]
        return f"🏢 {nome_filial}"
    
    # Se não for filial, usa o nome do XML ou o próprio documento
    nome_exibicao = nome_xml if nome_xml else clean_doc
    # Limita tamanho do nome para não quebrar layout
    if len(str(nome_exibicao)) > 25: nome_exibicao = str(nome_exibicao)[:25] + "..."
    
    return f"{nome_exibicao} ({clean_doc})"

# --- GRÁFICOS ---

def plot_evolution_simple(df, title):
    if df.empty: return None
    df_sorted = df.sort_values('Sort_YM')
    agg_bar = df.groupby(['Periodo_Label', 'Sort_YM'])['peso_bruto'].sum().reset_index().sort_values('Sort_YM')
    df_valid = df[df['frete_valor'] > 0]
    
    if df_valid.empty: 
        agg_line = pd.DataFrame({'Periodo_Label': agg_bar['Periodo_Label'], 'rs_ton': 0})
    else:
        agg_line = df_valid.groupby(['Periodo_Label', 'Sort_YM']).agg({'frete_valor':'sum', 'peso_bruto':'sum'}).reset_index()
        agg_line['rs_ton'] = agg_line['frete_valor'] / (agg_line['peso_bruto']/1000)
        agg_line = agg_line.sort_values('Sort_YM')
        
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # Trace de Barras (Peso)
    fig.add_trace(go.Bar(
        x=agg_bar['Periodo_Label'], 
        y=agg_bar['peso_bruto']/1000, 
        name="Peso (Ton)", 
        marker_color='#2E86C1', 
        text=agg_bar['peso_bruto'].apply(lambda x: f"{x/1000:,.0f}t".replace(",",".")), 
        textposition='auto'
    ), secondary_y=False)
    
    # Trace de Linha (R$/Ton) - REMOVIDO TEXTO DIRETO
    fig.add_trace(go.Scatter(
        x=agg_line['Periodo_Label'], 
        y=agg_line['rs_ton'], 
        name="R$/Ton", 
        mode='lines+markers', # Removemos '+text'
        line=dict(width=3, color='#000')
    ), secondary_y=True)
    
    # ADICIONADO: Anotações Manuais com Fundo Cinza
    for i, row in agg_line.iterrows():
        fig.add_annotation(
            x=row['Periodo_Label'],
            y=row['rs_ton'],
            text=f"<b>{br_money(row['rs_ton'])}</b>", # Negrito
            showarrow=False,
            yshift=20, # Sobe um pouco acima do ponto
            bgcolor="#e0e0e0", # Fundo Cinza Claro (Igual ao outro gráfico)
            bordercolor="#cccccc",
            font=dict(size=11, color="black"),
            yref="y2" # Importante: Referencia o eixo secundário
        )
    
    fig.update_layout(title=title, height=450, legend=dict(orientation="h", y=1.1), xaxis=dict(type='category'))
    fig.update_yaxes(title_text="Volume (Ton)", showgrid=False, secondary_y=False)
    fig.update_yaxes(title_text="R$ / Ton", showgrid=True, secondary_y=True)
    return fig

def plot_top10(df):
    if df.empty: return None
    df_filtered = df[~df['Transportadora_Final'].str.contains("FVO", case=False, na=False)].copy()
    if df_filtered.empty: return None

    agg = df_filtered.groupby('Transportadora_Final').agg({'peso_bruto':'sum', 'frete_valor':'sum'}).reset_index()
    agg = agg[agg['peso_bruto']>0]
    agg['rs_ton'] = agg['frete_valor'] / (agg['peso_bruto']/1000)
    agg = agg.sort_values('peso_bruto', ascending=True).tail(10)
    
    fig = go.Figure()
    fig.add_trace(go.Bar(y=agg['Transportadora_Final'], x=agg['peso_bruto']/1000, orientation='h', name='Peso', marker_color='#5c9ce6', text=agg['peso_bruto'].apply(lambda x: f"{x/1000:,.0f}t".replace(",",".")), textposition='auto'))
    annot = []
    mx = agg['peso_bruto'].max()/1000 * 1.15
    for i, r in agg.iterrows(): 
        # Mantive o bgcolor aqui também para garantir padrão
        annot.append(dict(x=r['peso_bruto']/1000, y=r['Transportadora_Final'], text=f" <b>{br_money(r['rs_ton'])}</b> ", xanchor='left', showarrow=False, bgcolor='#e0e0e0', bordercolor='#ccc'))
    fig.update_layout(title="Top 10 Transportadoras (Excluindo FVO)", height=500, xaxis_title="Ton", annotations=annot, margin=dict(r=80))
    fig.update_xaxes(range=[0, mx])
    return fig

def plot_transp_pedagio(df):
    if df.empty: return None
    agg = df[df['pedagio_valor']>0].groupby('Transportadora_Final')['pedagio_valor'].sum().sort_values(ascending=True).tail(10).reset_index()
    agg['fmt_pedagio'] = agg['pedagio_valor'].apply(br_money)
    fig = px.bar(agg, x='pedagio_valor', y='Transportadora_Final', orientation='h', title="Top Transportadoras com Pedágio", text='fmt_pedagio')
    fig.update_traces(textposition='auto')
    return fig

def plot_map_heat(df):
    if df.empty: return None
    agg = df.groupby('UF_Dest')['frete_valor'].sum().reset_index()
    agg_peso = df.groupby('UF_Dest')['peso_bruto'].sum().reset_index()
    agg = pd.merge(agg, agg_peso, on='UF_Dest')
    agg['lat'] = agg['UF_Dest'].apply(lambda x: COORDS_UF.get(x, (0,0))[0])
    agg['lon'] = agg['UF_Dest'].apply(lambda x: COORDS_UF.get(x, (0,0))[1])
    
    def fmt_peso(v):
        if v >= 1000: return f"{v/1000:,.2f} Tons".replace(",", "X").replace(".", ",").replace("X", ".")
        else: return f"{v:,.0f} Kg".replace(",", ".")
    agg['Peso Formatado'] = agg['peso_bruto'].apply(fmt_peso)
    agg['Frete Formatado'] = agg['frete_valor'].apply(br_money)
    
    hover_conf = {'frete_valor':False, 'Frete Formatado':True, 'Peso Formatado':True, 'lat':False, 'lon':False}
    
    try: 
        return px.density_map(agg, lat='lat', lon='lon', z='frete_valor', radius=40, center=dict(lat=-15, lon=-50), zoom=3, map_style="carto-positron", title="Mapa Logístico (Calor Frete)", hover_name='UF_Dest', hover_data=hover_conf)
    except: 
        return px.density_mapbox(agg, lat='lat', lon='lon', z='frete_valor', radius=40, center=dict(lat=-15, lon=-50), zoom=3, mapbox_style="carto-positron", title="Mapa Logístico (Calor Frete)", hover_name='UF_Dest', hover_data=hover_conf)

def plot_vol_regiao_custom(df):
    if df.empty: return None
    agg = df.groupby('Regiao').agg({'peso_bruto':'sum', 'frete_valor':'sum'}).reset_index()
    agg['rs_ton'] = agg.apply(lambda x: x['frete_valor'] / (x['peso_bruto']/1000) if x['peso_bruto']>0 else 0, axis=1)
    
    fig = go.Figure()
    fig.add_trace(go.Bar(x=agg['Regiao'], y=agg['peso_bruto'], marker_color='#5c9ce6', name='Volume'))
    annotations = []
    for i, row in agg.iterrows():
        peso_txt = br_weight(row['peso_bruto']/1000) + " t"
        annotations.append(dict(x=row['Regiao'], y=row['peso_bruto'] / 2, text=peso_txt, showarrow=False, font=dict(color='black', size=11, weight='bold'), bgcolor='#e0e0e0', opacity=0.9, borderpad=4))
        rs_txt = br_money(row['rs_ton'])
        annotations.append(dict(x=row['Regiao'], y=row['peso_bruto'], text=rs_txt, yshift=15, showarrow=False, font=dict(color='#333', size=12, weight='bold')))
    fig.update_layout(title="Volume por Região", annotations=annotations)
    return fig

def plot_ranking_horizontal(df, group_col, metric_col, title, color='#5c9ce6'):
    if df.empty: return None
    if metric_col == 'rs_ton':
        agg = df.groupby(group_col).agg({'peso_bruto':'sum', 'frete_valor':'sum'}).reset_index()
        agg = agg[agg['peso_bruto']>0]
        agg['val'] = agg['frete_valor'] / (agg['peso_bruto']/1000)
        fmt = br_money
    else:
        agg = df.groupby(group_col)[metric_col].sum().reset_index()
        agg.rename(columns={metric_col: 'val'}, inplace=True)
        if metric_col == 'peso_bruto':
            agg['val'] = agg['val'] / 1000 
            fmt = lambda x: f"{x:,.0f}t".replace(",",".")
        else: # frete_valor
            fmt = br_money

    agg = agg.sort_values('val', ascending=True).tail(10)
    fig = go.Figure()
    fig.add_trace(go.Bar(y=agg[group_col], x=agg['val'], orientation='h', marker_color=color, text=agg['val'].apply(fmt), textposition='auto'))
    fig.update_layout(title=title, height=350, margin=dict(l=10, r=10, t=40, b=10))
    return fig

# --- PLOT COMBO ---
def plot_combo_chart(df, x, g, t, stack=False):
    if df.empty: return None
    return plot_evolution_simple(df, t)

# --- PROCESSAMENTO DE ARQUIVOS ---
def proc_ui(fs, t):
    if not fs: return
    p = st.progress(0, text="Iniciando..."); v = []
    
    for f in fs:
        if f.name.endswith(".xml"): v.append((f.name, f.read()))
        elif f.name.endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(f.read())) as zf:
                    for n in zf.namelist(): 
                        if n.endswith(".xml"): v.append((n, zf.read(n)))
            except: pass
    
    if not v: st.warning("Sem XML válido."); p.empty(); return
    
    batch_data = []; batch_items = []; logs = []
    total = len(v)
    
    for i, (fn, c) in enumerate(v):
        perc = int(((i+1)/total)*100)
        p.progress((i+1)/total, text=f"Lendo XML {i+1}/{total} ({perc}%)")
        
        if t=="cte":
            rows, err = parsers.parse_cte(c, fn)
            if err: logs.append({'arquivo': fn, 'tipo': 'CT-e', 'msg': err})
            else: batch_data.extend(rows)
        elif t=="nfe":
            h, err = parsers.parse_nfe_header(c, fn)
            if err: logs.append({'arquivo': fn, 'tipo': 'NF-e', 'msg': err})
            else:
                batch_data.append(h)
                it, _ = parsers.parse_nfe_items(c, fn)
                batch_items.extend(it)
            
    p.progress(0.99, text="Salvando no Banco...")
    
    sucesso = True
    msg_erro = ""
    if t=="cte":
        ok, msg = db.insert_cte_many(batch_data)
        if not ok: sucesso = False; msg_erro = msg
    elif t=="nfe":
        ok, msg = db.insert_nfe_many(batch_data, batch_items)
        if not ok: sucesso = False; msg_erro = msg
        
    if logs: db.insert_log_many(logs)
    
    if sucesso:
        st.cache_data.clear() # LIMPA CACHE APOS UPLOAD
        st.toast(f"Sucesso! {len(batch_data)} registros.", icon="🚀")
        time.sleep(1)
        st.rerun()
    else:
        st.error(f"❌ ERRO BANCO: {msg_erro}")

# --- SIDEBAR E DADOS ---
with st.sidebar:
    st.title("🎛️ Filtros")
    if st.button("🗑️ Limpar Banco", type="primary"): 
        ok, msg = db.destroy_db()
        if ok: st.toast("Banco limpo!"); time.sleep(1); st.rerun()
        else: st.error(f"Erro: {msg}")
    
    st.divider()
    
    dr = get_dados_dashboard()
    
    if not dr.empty:
        dr['Dia'] = dr['Dt_Ref'].dt.day.fillna(0).astype(int)
        meses = {1:'Jan',2:'Fev',3:'Mar',4:'Abr',5:'Mai',6:'Jun',7:'Jul',8:'Ago',9:'Set',10:'Out',11:'Nov',12:'Dez'}
        dr['Periodo_Label'] = dr.apply(lambda x: f"{meses.get(x['Mes'],'')}-{str(x['Ano'])[-2:]}", axis=1)

        dr['Label_Emitente'] = dr.apply(lambda x: formatar_participante(x['cnpj_emit'], x['emitente']), axis=1)
        dr['Label_Destinatario'] = dr.apply(lambda x: formatar_participante(x['cnpj_dest'], x['destinatario']), axis=1)

        with st.expander("📅 Período (NF-e)", expanded=True):
            sa = st.multiselect("Ano", sorted(list(dr['Ano'].unique()), reverse=True), key="sb_ano")
            dt = dr[dr['Ano'].isin(sa)] if sa else dr
            sm = st.multiselect("Mês", sorted(list(dt['Mes'].unique())), key="sb_mes")
            sd = st.multiselect("Dia", sorted(list(dt['Dia'].unique())), key="sb_dia")
        
        with st.expander("🚚 Logística"):
            strop = st.multiselect("Transportadora", sorted(list(dr['Transportadora_Final'].unique())), key="sb_transp")
            sft = st.multiselect("Tipo Frete", sorted(list(dr['Frete_Tipo'].unique())), key="sb_frete")
            sop = st.multiselect("Operação", sorted(list(dr['Operacao'].unique())), key="sb_operacao")
            
        with st.expander("🌎 Geografia"):
            suf = st.multiselect("UF Destino", sorted(list(dr['UF_Dest'].unique())), key="sb_uf")
            sor = st.multiselect("Cidade Origem", sorted(list(dr['cidade_origem'].astype(str).unique())), key="sb_origem")
            sde = st.multiselect("Cidade Destino", sorted(list(dr['cidade_destino'].astype(str).unique())), key="sb_destino")

        with st.expander("👥 Participantes"):
            semit = st.multiselect("Emitente", sorted(list(dr['Label_Emitente'].unique())), key="sb_emitente")
            sdest = st.multiselect("Destinatário", sorted(list(dr['Label_Destinatario'].unique())), key="sb_destinatario")
            
        df = dr.copy()
        if sa: df = df[df['Ano'].isin(sa)]
        if sm: df = df[df['Mes'].isin(sm)]
        if sd: df = df[df['Dia'].isin(sd)]
        if strop: df = df[df['Transportadora_Final'].isin(strop)]
        if sft: df = df[df['Frete_Tipo'].isin(sft)]
        if sop: df = df[df['Operacao'].isin(sop)]
        if suf: df = df[df['UF_Dest'].isin(suf)]
        if sor: df = df[df['cidade_origem'].isin(sor)]
        if sde: df = df[df['cidade_destino'].isin(sde)]
        if semit: df = df[df['Label_Emitente'].isin(semit)]
        if sdest: df = df[df['Label_Destinatario'].isin(sdest)]
    else: df = pd.DataFrame()

# --- DEFINIÇÃO DE CARDS ---
def cards_gerais(d):
    if d.empty: return
    tnf=d['valor_nf'].sum(); tp=d['peso_bruto'].sum(); tf=d['frete_valor'].sum(); tped=d['pedagio_valor'].sum()
    
    if 'Frete_Tipo' not in d.columns: d['Frete_Tipo'] = 'Outros'
    
    perc = (tf/tnf*100) if tnf>0 else 0
    c_cif = len(d[d['Frete_Tipo']=='CIF'])
    c_fob = len(d[d['Frete_Tipo']=='FOB'])
    
    c1,c2,c3,c4,c5 = st.columns(5)
    with c1: display_kpi("Custo NFs", br_money(tnf))
    with c2: display_kpi("Peso Bruto", f"{br_weight(tp/1000)} t")
    with c3: display_kpi("Valor Frete", br_money(tf))
    with c4: display_kpi("Pedágio", br_money(tped))
    with c5: display_kpi("% Frete/Nota", br_percent(perc))
    
    c6,c7,c8,c9 = st.columns(4)
    rst = (tf/(tp/1000)) if tp>0 else 0
    rskg = (tf/tp) if tp>0 else 0
    
    with c6: display_kpi("Custo/Ton", f"R$ {br_int(rst)}")
    with c7: display_kpi("Custo/Kg", f"R$ {rskg:.2f}")
    with c8: display_kpi("Qtd Viagens", f"{len(d):,}".replace(",", "."))
    with c9: display_kpi("Modalidade", f"CIF: {c_cif} | FOB: {c_fob}")

# --- ABAS ---
t_home, t_dash, t_analise, t_classificacao, t_cte, t_nfe, t_logs, t_sim = st.tabs(["🏠 HOME", "📊 DASHBOARD", "🔍 ANÁLISE CT-E", "🧠 CLASSIFICAÇÃO", "🚚 CT-e", "📦 NF-e", "⚠️ LOG DE ERROS", "🌎 SIMULADOR"])

with t_home:
    if df.empty: st.info("Sem dados. Faça upload na aba CT-e ou NF-e.")
    else:
        cards_gerais(df); st.divider(); c1, c2 = st.columns(2)
        with c1: st.plotly_chart(px.pie(df, names='Operacao', values='peso_bruto', title="Volume: Venda vs Transferência", hole=0.4), use_container_width=True, key="home_pie_op")
        with c2: 
            f = plot_map_heat(df)
            if f: st.plotly_chart(f, use_container_width=True, key="home_map")
            else: st.info("Sem dados de localização.")
        st.divider(); c3, c4 = st.columns(2)
        with c3: 
            f = plot_transp_pedagio(df)
            if f: st.plotly_chart(f, use_container_width=True, key="home_pedagio")
            else: st.info("Sem dados de Pedágio.")
        with c4: 
            f = plot_evolution_simple(df, "Evolução Mensal (Total)")
            if f: st.plotly_chart(f, use_container_width=True, key="home_evol")
            else: st.info("Sem dados de Data.")

with t_dash:
    if df.empty: st.info("Sem dados.")
    else:
        d1,d2=st.columns(2)
        with d1: 
            f = plot_evolution_simple(df, "Evolução do Custo (R$/Ton)")
            if f: st.plotly_chart(f, use_container_width=True, key="dash_evol")
        with d2: 
            f = plot_top10(df)
            if f: st.plotly_chart(f, use_container_width=True, key="dash_top10")
            else: st.info("Sem dados para Top 10.")
        
        d3,d4=st.columns(2)
        with d3: st.plotly_chart(plot_map_heat(df), use_container_width=True, key="dash_map")
        with d4:
            f = plot_vol_regiao_custom(df)
            if f: st.plotly_chart(f, use_container_width=True, key="dash_vol_reg")
            
        st.divider()
        
        st.markdown("#### 🏆 Top 10 Clientes (Destinatário)")
        c_c1, c_c2, c_c3 = st.columns(3)
        with c_c1: st.plotly_chart(plot_ranking_horizontal(df, 'destinatario', 'peso_bruto', 'Maior Volume (Tons)'), use_container_width=True, key="cli_vol")
        with c_c2: st.plotly_chart(plot_ranking_horizontal(df, 'destinatario', 'frete_valor', 'Maior Custo Frete (R$)'), use_container_width=True, key="cli_custo")
        with c_c3: st.plotly_chart(plot_ranking_horizontal(df, 'destinatario', 'rs_ton', 'Maior R$ / Ton'), use_container_width=True, key="cli_rston")
        
        st.markdown("#### 🏙️ Top 10 Cidades (Destino)")
        c_t1, c_t2, c_t3 = st.columns(3)
        with c_t1: st.plotly_chart(plot_ranking_horizontal(df, 'cidade_destino', 'peso_bruto', 'Maior Volume (Tons)', color='#ff7f0e'), use_container_width=True, key="cid_vol")
        with c_t2: st.plotly_chart(plot_ranking_horizontal(df, 'cidade_destino', 'frete_valor', 'Maior Custo Frete (R$)', color='#fb4b4b'), use_container_width=True, key="cid_custo")
        with c_t3: st.plotly_chart(plot_ranking_horizontal(df, 'cidade_destino', 'rs_ton', 'Maior R$ / Ton', color='#ff7f0e'), use_container_width=True, key="cid_rston")

with t_analise:
    st.header("🔍 Análise Detalhada (CT-e / NF-e)")
    if df.empty: st.info("Carregue dados.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        l_cte = sorted(list(df[df['numero_cte'].notnull()]['numero_cte'].astype(str).unique()))
        l_nf = sorted(list(df['numero_nf'].astype(str).unique()))
        l_tr = sorted(list(df['Transportadora_Final'].unique()))
        l_de = sorted(list(df['destinatario'].astype(str).unique()))
        
        sel_cte = c1.selectbox("Buscar por CT-e", [""] + l_cte, key="an_sel_cte")
        sel_nf = c2.selectbox("Buscar por NF-e", [""] + l_nf, key="an_sel_nf")
        sel_tr = c3.multiselect("Transportadora", l_tr, key="an_sel_tr")
        sel_de = c4.multiselect("Destinatário", l_de, key="an_sel_de")
        
        target = df.copy()
        if sel_cte: target = target[target['numero_cte'].astype(str) == str(sel_cte)]
        if sel_nf: target = target[target['numero_nf'].astype(str) == str(sel_nf)]
        if sel_tr: target = target[target['Transportadora_Final'].isin(sel_tr)]
        if sel_de: target = target[target['destinatario'].isin(sel_de)]
        
        if target.empty: st.warning("Nenhum registro encontrado.")
        else:
            st.divider()
            k1, k2, k3 = st.columns(3)
            total_frete = target['frete_valor'].sum(); total_peso = target['peso_bruto'].sum(); total_valor_nf = target['valor_nf'].sum()
            kpi_ton = total_frete / (total_peso / 1000) if total_peso > 0 else 0
            kpi_kg = total_frete / total_peso if total_peso > 0 else 0
            kpi_perc = (total_frete / total_valor_nf * 100) if total_valor_nf > 0 else 0
            qtd_registros = len(target)

            with k1: display_kpi("Total Frete", br_money(total_frete))
            with k2: display_kpi("Peso Total (NFs)", br_weight(total_peso/1000) + " t")
            with k3: display_kpi("Registros Encontrados", str(qtd_registros))
            
            k4, k5, k6 = st.columns(3)
            with k4: display_kpi("Custo R$/Ton", f"R$ {br_int(kpi_ton)}")
            with k5: display_kpi("Custo R$/Kg", f"R$ {kpi_kg:.4f}")
            with k6: display_kpi("% Frete/Nota", br_percent(kpi_perc))
            st.divider()

            st.subheader("Registros Encontrados")
            st.info("💡 Clique em uma linha para ver os detalhes abaixo.")
            
            view = target.copy().reset_index(drop=True)
            view['valor_nf_fmt'] = view['valor_nf'].apply(br_money)
            view['peso_fmt'] = view['peso_bruto'].apply(br_weight)
            view['frete_fmt'] = view['frete_valor'].apply(br_money)
            
            cols_show = ['data', 'numero_cte', 'numero_nf', 'Transportadora_Final', 'cidade_origem', 'cidade_destino', 'destinatario', 'valor_nf_fmt', 'frete_fmt']
            
            event = st.dataframe(
                view[cols_show], 
                use_container_width=True,
                on_select="rerun",
                selection_mode="single-row"
            )
            
            target_bottom = target 
            
            if event.selection.rows:
                idx = event.selection.rows[0]
                target_bottom = view.iloc[[idx]]
                n_nf = target_bottom['numero_nf'].values[0] if 'numero_nf' in target_bottom else ''
                st.info(f"Detalhando NF: {n_nf}")
            
            st.divider()
            
            c_left, c_right = st.columns(2)
            
            with c_left:
                st.subheader("📋 Clientes & Volumes")
                if not target_bottom.empty:
                    df_clients = target_bottom.groupby(['destinatario', 'cidade_destino', 'uf_dest']).agg({
                        'peso_bruto': 'sum'
                    }).reset_index().rename(columns={'peso_bruto': 'Peso Total'})
                    
                    df_clients = df_clients.sort_values('Peso Total', ascending=False)
                    df_clients['Peso Total'] = df_clients['Peso Total'].apply(lambda x: br_weight(x))
                    st.dataframe(df_clients, use_container_width=True)
                else: st.write("Nenhum dado.")
                
            with c_right:
                st.subheader("📦 Detalhamento de Produtos")
                df_items = services.get_items_data()
                if not df_items.empty and not target_bottom.empty:
                    df_items['chave_nf'] = df_items['chave_nf'].astype(str).str.strip()
                    
                    if event.selection.rows:
                        idx_sel = event.selection.rows[0]
                        ref_key = str(view.iloc[idx_sel]['chave_nf']).strip() 
                        ref_date = view.iloc[idx_sel]['data']
                        items_view = df_items[df_items['chave_nf'] == ref_key].copy()
                        items_view['Data Emissão'] = ref_date
                    else:
                        target['chave_nf'] = target['chave_nf'].astype(str).str.strip()
                        items_view = pd.merge(
                            df_items[['chave_nf', 'produto', 'qtd_display']],
                            target[['chave_nf', 'data']],
                            on='chave_nf',
                            how='inner'
                        ).rename(columns={'data': 'Data Emissão'})

                    if not items_view.empty:
                        st.dataframe(
                            items_view[['Data Emissão', 'produto', 'qtd_display']].rename(columns={'qtd_display': 'Qtd', 'produto': 'Produto'}), 
                            use_container_width=True,
                            hide_index=True
                        )
                    else:
                        st.info("Itens não encontrados para estas notas.")
                else:
                    st.info("Sem dados de itens no banco.")

with t_classificacao:
    st.header("🧠 Classificação Inteligente de Operações")
    st.info("Utilize esta aba para auditar e corrigir o Tipo de Operação (Venda, Transferência, etc.) e a Etapa Logística (Coleta, Entrega).")
    
    df_cte_class = get_dados_cte_agregados()
    
    if not df_cte_class.empty:
        df_cte_class['Label_Emitente'] = df_cte_class.apply(lambda x: formatar_participante(x['CNPJ Emitente']), axis=1)
        df_cte_class['Label_Destinatario'] = df_cte_class.apply(lambda x: formatar_participante(x['CNPJ Destinatário']), axis=1)

        c1, c2, c3, c4 = st.columns(4)
        
        l_ncte = sorted(list(df_cte_class['N° CTE'].astype(str).unique()))
        f_cte = c1.selectbox("Filtrar por N° CT-e", [""] + l_ncte, key="cl_sel_cte")
        
        l_transp = sorted(list(df_cte_class['Transportadora'].astype(str).unique()))
        f_transp = c2.selectbox("Filtrar por Transportadora", [""] + l_transp, key="cl_sel_transp")
        
        l_emit = sorted(list(df_cte_class['Label_Emitente'].unique()))
        f_emit = c3.selectbox("Filtrar por Emitente", [""] + l_emit, key="cl_sel_emit")
        
        l_dest = sorted(list(df_cte_class['Label_Destinatario'].unique()))
        f_dest = c4.selectbox("Filtrar por Destinatário", [""] + l_dest, key="cl_sel_dest")
        
        st.markdown("---")
        c_nf_search = st.columns([1, 3])[0]
        nfe_search = c_nf_search.text_input("🔍 Buscar CT-e pelo Número da Nota Fiscal (Digite e Enter)", key="class_nfe_search")
        
        view_class = df_cte_class.copy()
        
        if f_cte: view_class = view_class[view_class['N° CTE'].astype(str) == f_cte]
        if f_transp: view_class = view_class[view_class['Transportadora'] == f_transp]
        if f_emit: view_class = view_class[view_class['Label_Emitente'] == f_emit]
        if f_dest: view_class = view_class[view_class['Label_Destinatario'] == f_dest]
        
        if nfe_search:
            df_dash = get_dados_dashboard()
            found_nfs = df_dash[df_dash['numero_nf'].astype(str) == nfe_search]['chave_nf'].unique()
            
            if len(found_nfs) > 0:
                found_ctes = df_dash[df_dash['numero_nf'].astype(str) == nfe_search]['numero_cte'].dropna().unique()
                valid_ctes = []
                for c_str in found_ctes:
                    valid_ctes.extend([x.strip() for x in str(c_str).split(',')])
                
                if valid_ctes:
                    view_class = view_class[view_class['N° CTE'].astype(str).isin(valid_ctes)]
                    st.success(f"Nota {nfe_search} encontrada nos CT-es: {', '.join(valid_ctes)}")
                else:
                    st.warning(f"Nota {nfe_search} encontrada, mas sem CT-e vinculado.")
                    view_class = view_class.iloc[0:0]
            else:
                st.warning(f"Nota Fiscal {nfe_search} não encontrada.")
                view_class = view_class.iloc[0:0]

        st.markdown("### 📝 Editor de Classificação")
        
        cols_editor = ['Data Emissão', 'N° CTE', 'Transportadora', 'Valor Frete', 'Tipo de Frete', 'Tipo de Operação', 'Etapa Logística', 'cfop_predominante', 'chave_cte_propria', 'CNPJ Emitente', 'CNPJ Destinatário']
        cols_editor = [c for c in cols_editor if c in view_class.columns]
        
        event_class = st.dataframe(
            view_class[cols_editor],
            use_container_width=True,
            on_select="rerun",
            selection_mode="single-row",
            hide_index=True
        )
        
        st.caption("Edite abaixo 'Tipo de Operação' e 'Etapa Logística' e clique em Salvar.")
        edited_class = st.data_editor(
            view_class[cols_editor],
            key="editor_classificacao",
            num_rows="fixed",
            column_config={
                "Tipo de Operação": st.column_config.SelectboxColumn("Operação", options=["Venda","Transferência","Compra","Outros"], required=True),
                "Etapa Logística": st.column_config.SelectboxColumn("Etapa", options=["Entrega", "Coleta", "Redespacho", "Reentrega"], required=True),
                "cfop_predominante": st.column_config.TextColumn("CFOP", disabled=True),
                "chave_cte_propria": None, "CNPJ Emitente": None, "CNPJ Destinatário": None
            },
            use_container_width=True
        )
        
        if st.button("💾 Salvar Alterações", key="btn_save_class"):
            count_upd = 0
            for idx, row in edited_class.iterrows():
                cfop = row.get('cfop_predominante')
                op_nova = row.get('Tipo de Operação')
                etapa = row.get('Etapa Logística')
                chave = row.get('chave_cte_propria')
                c_emit = row.get('CNPJ Emitente')
                c_dest = row.get('CNPJ Destinatário')
                
                if cfop and op_nova:
                    fl = services.get_fluxo(c_emit, c_dest)
                    db.update_ia_memory(cfop, fl, op_nova, None)
                
                if chave and etapa:
                    db.update_cte_etapa(chave, etapa)
                    count_upd += 1
            
            st.cache_data.clear()
            st.toast(f"{count_upd} registros atualizados com sucesso!", icon="✅")
            time.sleep(1)
            st.rerun()

        st.divider()
        
        if event_class.selection.rows:
            idx_sel = event_class.selection.rows[0]
            row_sel = view_class.iloc[idx_sel]
            cte_sel = row_sel['N° CTE']
            chave_cte_sel = row_sel['chave_cte_propria']
            
            st.subheader(f"📦 Produtos das Notas vinculadas ao CT-e {cte_sel}")
            
            df_dash = get_dados_dashboard()
            mask_cte = df_dash['numero_cte'].astype(str).apply(lambda x: str(cte_sel) in [s.strip() for s in x.split(',')])
            nfs_linked = df_dash[mask_cte]
            
            if not nfs_linked.empty:
                df_items = services.get_items_data()
                valid_nfs = nfs_linked['chave_nf'].astype(str).str.strip().tolist()
                
                df_items['chave_nf'] = df_items['chave_nf'].astype(str).str.strip()
                items_show = df_items[df_items['chave_nf'].isin(valid_nfs)].copy()
                
                if not items_show.empty:
                    nfs_map = nfs_linked[['chave_nf', 'numero_nf', 'valor_nf', 'data']].rename(columns={'data':'Data Emissão'})
                    nfs_map['chave_nf'] = nfs_map['chave_nf'].astype(str).str.strip()
                    
                    items_final = pd.merge(items_show, nfs_map, on='chave_nf', how='left')
                    
                    st.dataframe(
                        items_final[['numero_nf', 'Data Emissão', 'produto', 'qtd_display', 'vl_total']].rename(
                            columns={'numero_nf': 'Nota Fiscal', 'produto': 'Produto', 'qtd_display': 'Qtd', 'vl_total': 'Valor Item'}
                        ),
                        use_container_width=True
                    )
                else:
                    st.warning("Nenhum produto encontrado para as notas deste CT-e.")
            else:
                st.warning("Não foi possível encontrar as Notas Fiscais deste CT-e.")

    else:
        st.info("Nenhum dado disponível para classificação.")

with t_cte:
    st.header("CT-e"); up = load_ui("XML CT-e", "c")
    if up and st.button("Processar", key="btn_proc_cte"): proc_ui(up, "cte")
    
    df_cte_view = get_dados_cte_agregados()
    if not df_cte_view.empty:
        st.subheader("Visão Geral")
        st.dataframe(df_cte_view, use_container_width=True)
    else: st.info("Nenhum CT-e processado.")

with t_nfe:
    st.header("NF-e"); up = load_ui("XML NF-e", "n")
    if up and st.button("Processar", key="btn_proc_nfe"): proc_ui(up, "nfe")
    if not df.empty:
        cards_gerais(df)
        st.dataframe(df[['data','numero_nf','emitente','destinatario','cidade_origem','cidade_destino','distancia','numero_cte','peso_bruto','valor_nf','cfop_predominante','Frete_Tipo','tipo_operacao','Transportadora_Final']], use_container_width=True)

with t_logs:
    st.header("⚠️ Logs de Erros"); dlogs = db.get_all_logs()
    if not dlogs.empty:
        st.dataframe(dlogs, use_container_width=True)
        csv = dlogs.to_csv(index=False).encode('utf-8')
        st.download_button("Baixar Log (CSV)", data=csv, file_name="logs_erros.csv", mime="text/csv")
    else: st.success("Nenhum erro registrado.")

with t_sim:
    st.header("Simulador"); st.info("Simulador de rotas desativado para otimização.")