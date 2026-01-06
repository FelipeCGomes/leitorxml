# database.py
import sqlite3
import pandas as pd
from config import DB_FILE
from datetime import datetime

def get_connection():
    return sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)

def init_db():
    conn = get_connection()
    try: conn.execute("PRAGMA journal_mode=WAL;")
    except: pass
    c = conn.cursor()
    
    # Tabela CTE: Adicionado campo 'tp_cte' para diferenciar Complemento de Normal
    c.execute('''CREATE TABLE IF NOT EXISTS cte (
        chave_cte_propria TEXT,
        chave_nf TEXT,
        data TEXT, 
        numero_cte TEXT, 
        emitente TEXT, 
        cnpj_emit TEXT, 
        remetente TEXT, 
        destinatario TEXT, 
        frete_valor REAL, 
        peso_kg REAL, 
        numero_nf_cte TEXT, 
        cidade_origem TEXT, 
        cidade_destino TEXT, 
        pedagio_valor REAL, 
        chave_ref_cte TEXT, 
        tp_cte TEXT,
        arquivo TEXT,
        etapa_manual TEXT,
        UNIQUE(chave_cte_propria, chave_nf) ON CONFLICT IGNORE
    )''')
    
    # Tabela NFe
    c.execute('''CREATE TABLE IF NOT EXISTS nfe (
        chave_nf TEXT PRIMARY KEY, data TEXT, numero_nf TEXT, emitente TEXT, destinatario TEXT, 
        cnpj_emit TEXT, cnpj_dest TEXT, uf_dest TEXT, valor_nf REAL, peso_bruto REAL, 
        transportadora TEXT, cidade_origem TEXT, cidade_destino TEXT, mod_frete TEXT, 
        cfop_predominante TEXT, tipo_operacao TEXT, qtd_itens INTEGER, 
        cep_origem TEXT, cep_destino TEXT, distancia REAL, arquivo TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS itens (
        id INTEGER PRIMARY KEY AUTOINCREMENT, chave_nf TEXT, numero_nf TEXT, emitente TEXT, 
        item_num TEXT, produto TEXT, ncm TEXT, cfop TEXT, unidade TEXT, qtd_display TEXT, 
        qtd_float REAL, vl_total REAL, arquivo TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS memoria_ia (
        id INTEGER PRIMARY KEY AUTOINCREMENT, cfop TEXT, fluxo TEXT, tipo_definido TEXT, UNIQUE(cfop, fluxo)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, data_hora TEXT, arquivo TEXT, tipo_doc TEXT, status TEXT, mensagem TEXT
    )''')

    c.execute('CREATE INDEX IF NOT EXISTS idx_cte_propria ON cte (chave_cte_propria)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_cte_nf ON cte (chave_nf)')
    
    conn.commit()
    conn.close()

def destroy_db():
    conn = get_connection(); c = conn.cursor()
    tables = ['cte', 'nfe', 'itens', 'memoria_ia', 'logs']
    try:
        for t in tables: c.execute(f"DROP TABLE IF EXISTS {t}")
        conn.commit()
        init_db()
        return True, "Banco recriado com sucesso."
    except Exception as e: return False, str(e)
    finally: conn.close()

def insert_cte_many(lista_dados):
    if not lista_dados: return True, "Sem dados"
    conn = get_connection(); c = conn.cursor()
    cols = ','.join(lista_dados[0].keys())
    pl = ','.join(['?']*len(lista_dados[0]))
    try:
        c.executemany(f"INSERT OR IGNORE INTO cte ({cols}) VALUES ({pl})", [tuple(d.values()) for d in lista_dados])
        conn.commit()
        return True, f"{c.rowcount} registros."
    except Exception as e:
        return False, f"Erro CTE: {str(e)}"
    finally: conn.close()

def insert_nfe_many(lista_header, lista_items):
    conn = get_connection(); c = conn.cursor()
    try:
        if lista_header:
            cols = ','.join(lista_header[0].keys())
            pl = ','.join(['?']*len(lista_header[0]))
            c.executemany(f"INSERT OR IGNORE INTO nfe ({cols}) VALUES ({pl})", [tuple(d.values()) for d in lista_header])
        if lista_items:
            ic = ','.join(lista_items[0].keys())
            ip = ','.join(['?']*len(lista_items[0]))
            c.executemany(f"INSERT INTO itens ({ic}) VALUES ({ip})", [tuple(d.values()) for d in lista_items])
        conn.commit()
        return True, "Sucesso"
    except Exception as e:
        return False, f"Erro NFe: {str(e)}"
    finally: conn.close()

def insert_log_many(lista_logs):
    if not lista_logs: return
    conn = get_connection(); c = conn.cursor()
    try:
        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        dados = [(agora, l['arquivo'], l['tipo'], 'ERRO', l['msg']) for l in lista_logs]
        c.executemany("INSERT INTO logs (data_hora, arquivo, tipo_doc, status, mensagem) VALUES (?,?,?,?,?)", dados)
        conn.commit()
    except: pass
    finally: conn.close()

def update_cte_etapa(chave_cte, etapa):
    conn = get_connection(); c = conn.cursor()
    try:
        c.execute("UPDATE cte SET etapa_manual = ? WHERE chave_cte_propria = ?", (etapa, chave_cte))
        conn.commit(); return True
    except: return False
    finally: conn.close()

def update_ia_memory(cfop, fluxo, tipo, chave):
    conn = get_connection(); c = conn.cursor()
    try:
        if chave: c.execute("UPDATE nfe SET tipo_operacao=? WHERE chave_nf=?", (tipo, chave))
        c.execute("INSERT OR REPLACE INTO memoria_ia (cfop, fluxo, tipo_definido) VALUES (?, ?, ?)", (cfop, fluxo, tipo))
        conn.commit(); return True
    except: return False
    finally: conn.close()

def get_ia_memory(cfop, fluxo):
    conn = get_connection()
    try:
        res = conn.execute("SELECT tipo_definido FROM memoria_ia WHERE cfop=? AND fluxo=?", (cfop, fluxo)).fetchone()
        return res[0] if res else None
    except: return None
    finally: conn.close()

def get_all_logs():
    conn = get_connection()
    try: df = pd.read_sql("SELECT * FROM logs ORDER BY id DESC", conn)
    except: df = pd.DataFrame()
    conn.close()
    return df

def load_data(table):
    conn = get_connection()
    try: df = pd.read_sql(f"SELECT * FROM {table}", conn)
    except: df = pd.DataFrame()
    conn.close()
    return df