# services.py
import pandas as pd
import database as db
from config import CNPJS_CIA, TABELA_ANTT
from utils import limpar_cnpj, get_regiao, COORDS_UF
from functools import lru_cache

# --- UTILITÁRIOS ---
def get_fluxo(emit, dest):
    # Verifica se Emitente (e) e Destinatário (d) são da empresa
    e = limpar_cnpj(emit) in CNPJS_CIA
    d = limpar_cnpj(dest) in CNPJS_CIA
    
    # 1. Entre filiais da mesma empresa
    if e and d: return "Transferência"
    
    # 2. Nossa empresa emitindo para fora
    if e and not d: return "Venda"
    
    # 3. Alguém de fora emitindo (Seja para nós ou terceiro)
    # Regra alterada: Se não sou eu emitindo, assumo "Compra" (Entrada).
    # Isso cobre Fornecedores -> Nós.
    # Casos de "Devolução de Cliente" cairão aqui inicialmente como Compra,
    # mas serão corrigidos pela memória da IA (classificar_operacao) baseada no CFOP.
    if not e: return "Compra"
    
    return "Outros"

def classificar_operacao(cfop, emit, dest):
    # Pega o fluxo padrão (Venda, Compra, Transferência)
    f = get_fluxo(emit, dest)
    
    # Verifica se já aprendemos algo diferente para este CFOP nesse fluxo
    # Ex: Se o fluxo deu "Compra" (pq veio de fora), mas o CFOP é de Devolução,
    # e você já corrigiu isso antes, o banco retornará "Devolução".
    r = db.get_ia_memory(cfop, f)
    
    return r if r else f

def get_antt_coef(t, e): return TABELA_ANTT.get(t, {}).get(e, (0.0, 0.0))

@lru_cache(maxsize=5000)
def get_coords(query):
    try:
        uf = str(query).split("-")[-1].strip()
        if uf in COORDS_UF: return COORDS_UF[uf]
    except: pass
    return None

def iniciar_worker(): pass
def get_route_data(a,b,c,d): return 0.0, []

def get_items_data(): return db.load_data("itens")

def get_dashboard_data():
    """
    Gera a tabela principal de NF-e enriquecida com dados do CT-e (Rateado).
    """
    df_n = db.load_data("nfe"); df_c = db.load_data("cte")
    if df_n.empty and df_c.empty: return pd.DataFrame()

    # Prepara colunas NF
    cols_n = ['chave_nf','numero_nf','destinatario','cnpj_dest','cnpj_emit','emitente','uf_dest','valor_nf','peso_bruto','data','mod_frete','tipo_operacao','cfop_predominante','cidade_origem','cidade_destino','transportadora','qtd_itens','cep_origem','cep_destino']
    for c in cols_n: 
        if c not in df_n.columns: df_n[c] = None
    df_n = df_n[cols_n].copy()
    
    # Garante tipos numéricos na NF
    for c in ['valor_nf','peso_bruto']: 
        df_n[c] = pd.to_numeric(df_n.get(c,0), errors='coerce').fillna(0)

    # Prepara chaves para merge
    df_n['chave_nf'] = df_n['chave_nf'].astype(str).str.strip()

    if not df_c.empty:
        df_c['chave_nf'] = df_c['chave_nf'].astype(str).str.strip()
        df_c['chave_cte_propria'] = df_c['chave_cte_propria'].astype(str).str.strip()
        
        # Garante valores numéricos no CTE
        df_c['frete_valor'] = pd.to_numeric(df_c['frete_valor'], errors='coerce').fillna(0)
        df_c['pedagio_valor'] = pd.to_numeric(df_c['pedagio_valor'], errors='coerce').fillna(0)

        # ---------------------------------------------------------------------
        # LÓGICA DE RATEIO DO FRETE POR PESO DA NOTA
        # ---------------------------------------------------------------------
        # 1. Traz o peso da nota (df_n) para dentro da tabela de ligação (df_c)
        #    Isso é necessário porque o CTE pode ter NFs que não estão na tabela NFe,
        #    mas precisamos do peso para ratear corretamente.
        
        # Subset de pesos das notas disponíveis
        pesos_nf = df_n[['chave_nf', 'peso_bruto']].rename(columns={'peso_bruto': 'peso_nf_ref'})
        
        # Merge CTE -> Pesos NF
        df_c_calc = pd.merge(df_c, pesos_nf, on='chave_nf', how='left')
        df_c_calc['peso_nf_ref'] = df_c_calc['peso_nf_ref'].fillna(0) # Se não achar nota, peso 0
        
        # 2. Calcula o Peso Total vinculado a cada CT-e (Soma dos pesos das NFs dentro dele)
        #    Agrupa por Chave CTE Propria
        cte_totals = df_c_calc.groupby('chave_cte_propria').agg(
            total_peso_cte=('peso_nf_ref', 'sum'),
            qtd_notas=('chave_nf', 'count')
        ).reset_index()
        
        df_c_calc = pd.merge(df_c_calc, cte_totals, on='chave_cte_propria', how='left')
        
        # 3. Calcula o Rateio (Proporcional ou Igualitário)
        def calcular_parcela(row):
            total_frete = row['frete_valor']
            total_peso = row['total_peso_cte']
            peso_indiv = row['peso_nf_ref']
            qtd = row['qtd_notas']
            
            if total_frete == 0: return 0.0
            
            # Se tem peso cadastrado nas notas, faz rateio ponderado
            if total_peso > 0:
                return total_frete * (peso_indiv / total_peso)
            else:
                # Se não tem peso (ou peso é 0), divide igualmente entre as notas
                return total_frete / qtd if qtd > 0 else total_frete

        df_c_calc['frete_rateado'] = df_c_calc.apply(calcular_parcela, axis=1)
        
        # Mesmo racional para pedágio
        def calcular_parcela_pedagio(row):
            total_ped = row['pedagio_valor']
            total_peso = row['total_peso_cte']
            peso_indiv = row['peso_nf_ref']
            qtd = row['qtd_notas']
            if total_ped == 0: return 0.0
            if total_peso > 0: return total_ped * (peso_indiv / total_peso)
            else: return total_ped / qtd if qtd > 0 else total_ped

        df_c_calc['pedagio_rateado'] = df_c_calc.apply(calcular_parcela_pedagio, axis=1)

        # 4. Agrupa de volta por chave_nf (caso uma NF tenha mais de 1 CTE - ex: Redespacho)
        #    Aqui somamos as parcelas de frete de todos os CTEs que a nota participou
        nf_costs = df_c_calc.groupby('chave_nf').agg({
            'frete_rateado': 'sum',
            'pedagio_rateado': 'sum',
            'numero_cte': lambda x: ', '.join(sorted(list(set(x.astype(str))))), # Lista única
            'emitente': 'first' # Pega a primeira transp encontrada
        }).reset_index().rename(columns={
            'frete_rateado': 'frete_valor', # Substitui valor total pelo rateado
            'pedagio_rateado': 'pedagio_valor',
            'emitente': 'transportadora_cte'
        })
        
        # Merge final na tabela de notas
        df = pd.merge(df_n, nf_costs, on='chave_nf', how='left')
        
    else:
        df = df_n.copy()
        for c in ['frete_valor','pedagio_valor']: df[c] = 0
        df['numero_cte'] = None
        df['transportadora_cte'] = None

    # Preenchimento final e formatação
    if 'transportadora_cte' not in df.columns: df['transportadora_cte'] = None
    for c in ['frete_valor','pedagio_valor']: df[c] = df[c].fillna(0)
    
    df['distancia'] = 0
    s_cte = df['transportadora_cte']; s_nfe = df['transportadora']
    df['Transportadora_Final'] = s_cte.fillna(s_nfe).fillna('---')
    
    df['Dt_Ref'] = pd.to_datetime(df['data'], format='%d/%m/%Y', errors='coerce')
    df['Ano'] = df['Dt_Ref'].dt.year.fillna(0).astype(int)
    df['Mes'] = df['Dt_Ref'].dt.month.fillna(0).astype(int)
    
    def ext_uf(x): return str(x).split('-')[-1].strip() if '-' in str(x) else "ND"
    df['UF_Dest'] = df['cidade_destino'].apply(ext_uf)
    df['Regiao'] = df['UF_Dest'].apply(get_regiao)
    df['Sort_YM'] = df['Ano'].astype(str) + df['Mes'].astype(str).str.zfill(2)

    if 'mod_frete' in df.columns:
        df['Frete_Tipo'] = df['mod_frete'].apply(lambda x: 'CIF' if str(x)=='0' else ('FOB' if str(x)=='1' else 'Outros'))
    else: df['Frete_Tipo'] = 'Outros'

    if 'tipo_operacao' in df.columns:
        df['Operacao'] = df['tipo_operacao'].fillna('Outros')
    else: df['Operacao'] = 'Outros'

    return df

# --- NOVA LÓGICA DE AGREGAÇÃO CTE ---
def get_cte_aggregated():
    # Carrega dados
    df_raw = db.load_data("cte")
    if df_raw.empty: return pd.DataFrame()

    # Tipos
    for c in ['frete_valor','peso_kg','pedagio_valor']: 
        df_raw[c] = pd.to_numeric(df_raw[c], errors='coerce').fillna(0)
            
    df_raw['chave_cte_propria'] = df_raw['chave_cte_propria'].astype(str).str.strip()
    df_raw['chave_ref_cte'] = df_raw['chave_ref_cte'].fillna("").astype(str).str.strip()
    if 'tp_cte' not in df_raw.columns: df_raw['tp_cte'] = '0'
    
    # Filtra Complementos Reais
    mask_is_complement = (df_raw['chave_ref_cte'] != "") & (df_raw['tp_cte'].astype(str) == '1')
    
    df_compl = df_raw[mask_is_complement].copy()
    df_main = df_raw[~mask_is_complement].copy()
    
    if not df_compl.empty:
        agg_compl = df_compl.groupby('chave_ref_cte').agg({
            'frete_valor': 'sum',
            'numero_cte': lambda x: ', '.join(x.astype(str))
        }).reset_index().rename(columns={'chave_ref_cte': 'chave_cte_propria', 'frete_valor': 'vl_compl', 'numero_cte': 'nums_compl'})
        
        df_main = pd.merge(df_main, agg_compl, on='chave_cte_propria', how='left')
        df_main['vl_compl'] = df_main['vl_compl'].fillna(0)
        df_main['nums_compl'] = df_main['nums_compl'].fillna('')
        df_main['frete_total'] = df_main['frete_valor'] + df_main['vl_compl']
    else:
        df_main['frete_total'] = df_main['frete_valor']
        df_main['nums_compl'] = ''

    df_main = df_main.rename(columns={'emitente': 'transportadora_nome','cnpj_emit': 'transportadora_cnpj','nums_compl': 'cte_complementar'})

    # Merge NFe
    df_nfe = db.load_data("nfe")
    df_main['transportadora_cnpj'] = df_main['transportadora_cnpj'].fillna('ND')
    df_main['numero_cte'] = df_main['numero_cte'].fillna('ND')
    df_main['chave_nf'] = df_main['chave_nf'].astype(str).str.strip()
    
    if not df_nfe.empty:
        df_nfe['chave_nf'] = df_nfe['chave_nf'].astype(str).str.strip()
        cols_nfe = ['chave_nf', 'valor_nf', 'peso_bruto', 'mod_frete', 'tipo_operacao', 'cfop_predominante', 'cnpj_emit', 'cnpj_dest']
        cols_final = [c for c in cols_nfe if c in df_nfe.columns]
        df_subset = df_nfe[cols_final].copy()
        df_subset = df_subset.rename(columns={'cnpj_emit': 'nfe_emit_cnpj', 'cnpj_dest': 'nfe_dest_cnpj'})
        df_merged = pd.merge(df_main, df_subset, on='chave_nf', how='left')
    else:
        df_merged = df_main.copy()
        for c in ['valor_nf', 'peso_bruto']: df_merged[c] = 0
        df_merged['mod_frete'] = 'Outros'
        df_merged['tipo_operacao'] = 'Outros'
        df_merged['nfe_emit_cnpj'] = ''
        df_merged['nfe_dest_cnpj'] = ''
        df_merged['cfop_predominante'] = ''

    if 'mod_frete' in df_merged.columns:
        df_merged['Frete_Tipo'] = df_merged['mod_frete'].apply(lambda x: 'CIF' if str(x)=='0' else ('FOB' if str(x)=='1' else 'Outros'))
    else: df_merged['Frete_Tipo'] = 'Outros'

    def definir_etapa(row):
        if row.get('etapa_manual'): return row['etapa_manual']
        return "Entrega"

    df_merged['Etapa'] = df_merged.apply(definir_etapa, axis=1)

    agg_rules = {
        'data': 'first', 'cte_complementar': 'first', 'cidade_origem': 'first',
        'nfe_emit_cnpj': 'first', 'cidade_destino': 'first', 'nfe_dest_cnpj': 'first',
        'transportadora_nome': 'first', 'peso_kg': 'max', 'peso_bruto': 'sum', 
        'valor_nf': 'sum', 'frete_total': 'max', 'chave_nf': 'count', 
        'Frete_Tipo': 'first', 'tipo_operacao': 'first',
        'cfop_predominante': 'first', 'Etapa': 'first',
        'chave_cte_propria': 'first', 'etapa_manual': 'first'
    }
    
    for c in agg_rules.keys():
        if c not in df_merged.columns: 
             if c == 'data' and 'data_cte' in df_merged.columns: continue
             df_merged[c] = 0 if 'valor' in c or 'peso' in c else ''

    grouped = df_merged.groupby(['numero_cte', 'transportadora_cnpj']).agg(agg_rules).reset_index()
    
    grouped['$/Ton'] = grouped.apply(lambda x: x['frete_total'] / (x['peso_kg']/1000) if x['peso_kg']>0 else 0, axis=1)
    
    grouped = grouped.rename(columns={
        'data': 'Data Emissão', 'numero_cte': 'N° CTE', 'cte_complementar': 'N° CTE Compl.',
        'cidade_origem': 'Cidade Emitente', 'nfe_emit_cnpj': 'CNPJ Emitente', 
        'cidade_destino': 'Cidade Destinatário', 'nfe_dest_cnpj': 'CNPJ Destinatário', 
        'transportadora_nome': 'Transportadora', 'transportadora_cnpj': 'CNPJ Transportadora', 
        'peso_kg': 'Peso Bruto CTE', 'peso_bruto': 'Soma Peso Bruto NFs',
        'chave_nf': 'QTD Nfe', 'Frete_Tipo': 'Tipo de Frete', 
        'tipo_operacao': 'Tipo de Operação', 'frete_total': 'Valor Frete',
        'Etapa': 'Etapa Logística'
    })
    return grouped