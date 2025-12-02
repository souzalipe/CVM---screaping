# extract_table_from_cvm.py
# Requisitos: playwright (já ok), pandas
# pip install pandas

import re
import time
import json
import pandas as pd
from playwright.sync_api import Page

def log(msg):
    print(f"[LOG] {msg}")

def parse_num_br(s):
    """
    Converte string com formato brasileiro '1.234.567,89' para float 1234567.89
    Retorna None se não for número.
    """
    if s is None:
        return None
    s = str(s).strip()
    if s == "":
        return None
    # remover espaços e caracteres extras (ex.: "R$ 1.234,56" -> "1.234,56")
    s = re.sub(r"[^\d\-,\.]", "", s)
    # se tem vírgula decimal, transformar: remove pontos (milhares) e troca vírgula por ponto
    if "," in s and "." in s:
        # assume formato BR: remove pontos milhares, vírgula -> .
        s = s.replace(".", "").replace(",", ".")
    else:
        # trocar vírgula por ponto se vírgula for decimal
        if "," in s and s.count(",") == 1 and s.count(".") == 0:
            s = s.replace(",", ".")
        # remover possíveis pontos residuais (milhares)
        s = s.replace(",", ".")
    # agora tentar converter
    try:
        return float(s)
    except:
        return None


def find_frame_with_selector(page: Page, selector: str, tries=10, delay=0.6):
    """
    Procura um seletor (CSS) em todos os frames recursivamente.
    Retorna o frame que contém o seletor (ElementHandle não retornado).
    """
    for attempt in range(tries):
        log(f"Procurando seletor '{selector}' em todos os frames (tentativa {attempt+1}/{tries})...")
        for f in page.frames:
            try:
                el = f.query_selector(selector)
                if el:
                    log(f"Encontrado no frame: name='{f.name}' url='{f.url}'")
                    return f, el
            except Exception as e:
                # alguns frames podem ser cross-origin ou lançar erros: ignorar
                continue
        time.sleep(delay)
    log(f"Não encontrou '{selector}' após {tries} tentativas.")
    return None, None


def extract_table_from_frame(frame, table_selector="table#Table1"):
    """
    Extrai a tabela do frame. Retorna pandas.DataFrame e lista de dicts.
    table_selector: CSS para localizar a tabela (ex.: "table#Table1", "table.BodyPP", etc.)
    """
    # localizar a tabela
    table = frame.query_selector(table_selector)
    if not table:
        # fallback: primeira table dentro do form#form1 ou table[class*='BodyPP']
        table = frame.query_selector("form#form1 table")
    if not table:
        table = frame.query_selector("table[class*='BodyPP']")
    if not table:
        log("❌ Não encontrei tabela com os seletores padrão dentro do frame.")
        return None, None

    # coletar linhas (tr)
    rows = table.query_selector_all("tr")
    data = []
    for tr in rows:
        try:
            tds = tr.query_selector_all("td")
            # pular linhas sem tds (pode ser header tr)
            if not tds or len(tds) == 0:
                continue

            # extrair texto de cada td (strip)
            cols = [td.inner_text().strip() for td in tds]

            # heurística: tabela da CVM normalmente tem 3 colunas:
            # [conta, descricao, valor] — mas pode variar; vamos tentar mapear
            # Vamos tentar pegar os últimos 1 ou 2 colunas como "valor"
            # e primeiras como conta/descricao

            # remover colunas totalmente vazias
            cols = [c for c in cols]

            # decidir mapeamento
            if len(cols) >= 3:
                conta = cols[0]
                descricao = cols[1]
                # juntar o resto como valor (por segurança)
                valor_text = cols[-1]
            elif len(cols) == 2:
                conta = cols[0]
                descricao = ""
                valor_text = cols[1]
            else:
                # caso coluna única (pouco provável)
                conta = ""
                descricao = cols[0]
                valor_text = ""
            valor = parse_num_br(valor_text)

            data.append({
                "conta_raw": conta,
                "descricao_raw": descricao,
                "valor_text": valor_text,
                "valor": valor
            })
        except Exception as e:
            # pular linha se der erro
            continue

    # converter para DataFrame
    df = pd.DataFrame(data)
    return df, data


# ============================
# FUNÇÃO PRINCIPAL PARA USAR NO SEU FLUXO
# ============================
def capture_balancete_table(page, out_prefix="balancete"):
    """
    page: Playwright Page (já posicionado onde a tabela pode aparecer)
    Procura a tabela em todos os frames, extrai e salva CSV/JSON.
    Retorna dataframe.
    """
    # Preferência de selectors (baseado no seu print)
    possible_table_selectors = ["table#Table1", "table.BodyPP", "form#form1 table#Table1", "table[width='100%']"]

    found_frame = None
    found_table_handle = None
    for sel in possible_table_selectors:
        f, el = find_frame_with_selector(page, sel, tries=4, delay=0.4)
        if el:
            found_frame = f
            found_table_handle = el
            table_selector_used = sel
            break

    # se não encontrou por seletor direto, usar varredura completa por 'table' com heurística de conteúdo
    if not found_frame:
        log("Tentando varredura completa por todas as <table> em todos os frames...")
        for attempt in range(6):
            for i, f in enumerate(page.frames):
                try:
                    tables = f.query_selector_all("table")
                    for t in tables:
                        txt = t.inner_text()[:200].lower()
                        # heurística: a tabela do balancete contém palavras como "Conta", "Descrição da Conta", "Valor"
                        if ("descrição" in txt or "descricao" in txt) and ("valor" in txt or "saldo" in txt):
                            found_frame = f
                            found_table_handle = t
                            table_selector_used = "heuristic_table"
                            break
                    if found_frame:
                        break
                except Exception:
                    continue
            if found_frame:
                break
            time.sleep(0.6)

    if not found_frame:
        log("❌ Não localizei a tabela do balancete em nenhum frame. Salvando debug.")
        page.screenshot(path=f"{out_prefix}_no_table.png", full_page=True)
        for i, f in enumerate(page.frames):
            try:
                open(f"{out_prefix}_frame_{i}.html", "w", encoding="utf-8").write(f.content())
            except Exception:
                pass
        return None

    log(f"✅ Tabela detectada no frame: name='{found_frame.name}' url='{found_frame.url}' (selector: {table_selector_used})")

    # Extrair dados
    df, data = extract_table_from_frame(found_frame, table_selector="table#Table1")
    if df is None:
        # tentar extrair usando o handle que já temos
        try:
            # se temos o handle 'found_table_handle', vamos processá-lo
            # porém para simplicidade, só pedimos o HTML e reprocessamos com pandas.read_html
            html = found_table_handle.inner_html()
            # montar mini-HTML
            mini = f"<table>{html}</table>"
            dfs = pd.read_html(mini)
            if dfs and len(dfs) > 0:
                df = dfs[0]
                # normalizar colunas se possível
                df.columns = [str(c).strip() for c in df.columns]
        except Exception as e:
            log("Falha extraindo a partir do handle: " + str(e))
            return None

    # limpar e converter coluna de valor caso exista
    # procurar coluna que pareça com 'valor' e converter
    valor_col = None
    for col in df.columns:
        if "valor" in str(col).lower() or "saldo" in str(col).lower():
            valor_col = col
            break
    if valor_col:
        df["valor_normalizado"] = df[valor_col].astype(str).apply(parse_num_br)

    # salvar
    csv_path = f"{out_prefix}.csv"
    json_path = f"{out_prefix}.json"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    df.to_json(json_path, orient="records", force_ascii=False)

    log(f"Dados salvos: {csv_path}, {json_path}")
    log("Preview das primeiras linhas:")
    print(df.head(10))

    return df


# ============================
# EXEMPLO DE USO (coloque isso no final do seu fluxo)
# ============================
# Depois de clicar no 'Balancete' e de a página estar carregada, chame:
#
# df = capture_balancete_table(page, out_prefix="balancete_1042025")
#
# onde `page` é o objeto Playwright Page do seu script principal.
#
# Se você preferir integrar dentro do seu main_scrape, faça:
#
# frame_with_table, handle = find_frame_with_selector(page, "table#Table1")
# if frame_with_table:
#     df = capture_balancete_table(page)
#
# ============================
