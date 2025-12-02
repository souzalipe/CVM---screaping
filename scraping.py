# scraping.py (versão atualizada: extrai coluna 'Valor Saldo' do balancete)
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import time
import sys
import re
import json

# pandas é usado para salvar CSV e visualizar
import pandas as pd

# --------------------------
# LOG SIMPLES
# --------------------------
def log(msg):
    print(f"[LOG] {msg}")


# --------------------------
# NORMALIZA CNPJ
# --------------------------
def normalize_cnpj(value):
    value = "".join([c for c in str(value) if c.isdigit()])
    if len(value) != 14:
        raise ValueError(f"CNPJ inválido: {value}")
    return value


# --------------------------
# LOCALIZA FRAME COM FRAGMENTO NA URL
# --------------------------
def find_frame_with_url_fragment(page, fragment):
    for f in page.frames:
        if fragment.lower() in (f.url or "").lower():
            return f
    return None


def wait_for_frame_by_fragment(page, fragment, retries=20, delay=0.5):
    for _ in range(retries):
        f = find_frame_with_url_fragment(page, fragment)
        if f:
            return f
        time.sleep(delay)
    return None


# --------------------------
# CONVERTE STRING BR PARA FLOAT
# --------------------------
def parse_num_br(s):
    """Converte '1.234.567,89' -> 1234567.89, retorna None se não for número."""
    if s is None:
        return None
    s = str(s).strip()
    if s == "":
        return None
    # manter dígitos, pontos, vírgulas, hífen
    s = re.sub(r"[^\d\-,\.]", "", s)
    # se ambos presentes, remover pontos (milhares) e trocar vírgula por ponto
    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        # trocar vírgula por ponto se for decimal
        if "," in s and s.count(",") == 1 and s.count(".") == 0:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", ".")
    try:
        return float(s)
    except:
        return None


# --------------------------
# PROCURA LINK EM TODOS OS FRAMES
# --------------------------
def find_link_in_all_frames(page, css_selector=None, text_contains=None, href_contains=None):
    """
    Procura um link/elemento em todos os frames.
    Retorna (frame, element) ou (None, None).
    """
    for f in page.frames:
        try:
            if css_selector:
                el = f.query_selector(css_selector)
                if el:
                    return f, el
            if text_contains:
                loc = f.locator(f"text={text_contains}")
                if loc.count() > 0:
                    return f, loc.nth(0)
            if href_contains:
                anchors = f.query_selector_all("a")
                for a in anchors:
                    href = (a.get_attribute("href") or "").lower()
                    if href_contains.lower() in href:
                        return f, a
        except Exception:
            continue
    return None, None


def find_link_by_multiple_strategies(page, selectors=None, texts=None, href_keywords=None, tries=10, delay=0.8):
    selectors = selectors or []
    texts = texts or []
    href_keywords = href_keywords or []
    for attempt in range(tries):
        log(f"Tentativa {attempt+1}/{tries} para localizar link...")
        for sel in selectors:
            f, el = find_link_in_all_frames(page, css_selector=sel)
            if el:
                return f, el
        for txt in texts:
            f, el = find_link_in_all_frames(page, text_contains=txt)
            if el:
                return f, el
        for kw in href_keywords:
            f, el = find_link_in_all_frames(page, href_contains=kw)
            if el:
                return f, el
        time.sleep(delay)
    return None, None


# --------------------------
# PROCURA TABELA EM TODOS OS FRAMES
# --------------------------
def find_table_frame(page, selectors=None, tries=8, delay=0.6):
    selectors = selectors or ["table#Table1", "table.BodyPP", "form#form1 table"]
    for attempt in range(tries):
        log(f"Procurando tabela (tentativa {attempt+1}/{tries})...")
        for f in page.frames:
            try:
                for sel in selectors:
                    el = f.query_selector(sel)
                    if el:
                        log(f"Encontrada tabela com seletor '{sel}' no frame: name='{f.name}' url='{f.url}'")
                        return f, el, sel
            except Exception:
                continue
        time.sleep(delay)
    return None, None, None


# --------------------------
# EXTRAI LINHAS DA TABELA DO BALANCETE
# --------------------------
def extract_balancete_table_from_frame(frame, table_handle=None):
    """
    Recebe um frame (contendo a tabela) e extrai as linhas.
    Retorna pandas.DataFrame com colunas: conta, descricao, valor_text, valor
    """
    if table_handle is None:
        table_handle = frame.query_selector("table#Table1") or frame.query_selector("table.BodyPP")
        if table_handle is None:
            log("❌ table_handle não fornecida e não encontrada no frame.")
            return None

    rows = table_handle.query_selector_all("tr")
    records = []
    for tr in rows:
        try:
            tds = tr.query_selector_all("td")
            if not tds or len(tds) < 2:
                continue
            texts = [td.inner_text().strip() for td in tds]
            # heurística: 1º = conta, 2º = descrição, último = valor
            conta = texts[0]
            descricao = texts[1] if len(texts) > 1 else ""
            valor_text = texts[-1]
            valor = parse_num_br(valor_text)
            records.append({
                "conta": conta,
                "descricao": descricao,
                "valor_text": valor_text,
                "valor": valor
            })
        except Exception:
            continue

    df = pd.DataFrame(records)
    return df


# --------------------------
# CAPTURA BALANCETE (procura tabela e salva)
# --------------------------
def capture_balancete_and_save(page, out_prefix="balancete"):
    """
    Procura a tabela do balancete em todos os frames, extrai e salva CSV/JSON.
    Retorna DataFrame.
    """
    f, table_handle, used_sel = find_table_frame(page, selectors=["table#Table1", "table.BodyPP", "form#form1 table"])
    if not f:
        log("❌ Não localizei a tabela do balancete em nenhum frame.")
        # salva debug
        page.screenshot(path=f"{out_prefix}_no_table.png", full_page=True)
        for i, fr in enumerate(page.frames):
            try:
                open(f"{out_prefix}_frame_{i}.html", "w", encoding="utf-8").write(fr.content())
            except:
                pass
        return None

    log(f"Extraindo tabela no frame '{f.name}' ({f.url}) com seletor '{used_sel}'...")
    df = extract_balancete_table_from_frame(f, table_handle=table_handle)
    if df is None or df.empty:
        log("❌ Extração retornou vazio.")
        return None

    # salvar
    csv_path = f"{out_prefix}.csv"
    json_path = f"{out_prefix}.json"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    df.to_json(json_path, orient="records", force_ascii=False)

    log(f"✅ Extração salva: {csv_path}, {json_path}")
    print(df.head(10))
    return df


# ==========================================================
# SCRAPER PRINCIPAL (mantém o seu fluxo original)
# ==========================================================
def main_scrape(raw_cnpj):
    cnpj = normalize_cnpj(raw_cnpj)
    URL = "https://cvmweb.cvm.gov.br/SWB/default.asp?sg_sistema=fundosreg"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        try:
            # 1) Página inicial
            log("Abrindo página inicial...")
            page.goto(URL, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")
            time.sleep(1)

            # 2) Localizar frame com formulário
            log("Localizando frame de busca...")
            search_frame = wait_for_frame_by_fragment(page, "FormBuscaParticFdo.aspx")
            if not search_frame:
                log("❌ Frame de busca não encontrado!")
                return

            log(f"Frame encontrado: {search_frame.url}")

            # 3) Preencher CNPJ
            log("Preenchendo CNPJ...")
            search_frame.fill("#txtCNPJNome", cnpj)
            time.sleep(0.3)

            log("Clicando em btnContinuar...")
            search_frame.click("#btnContinuar")
            page.wait_for_load_state("domcontentloaded")
            time.sleep(1)

            # 4) Achar lista de fundos
            log("Procurando links de fundos...")
            links = search_frame.query_selector_all("a[id*='Linkbutton4']")
            log(f"Fundos encontrados: {len(links)}")

            if not links:
                log("❌ Nenhum fundo encontrado.")
                return

            # 5) Clicar no primeiro fundo
            log("Clicando no primeiro fundo...")
            links[0].scroll_into_view_if_needed()
            links[0].click()
            time.sleep(1)

            # Debug
            log("=== FRAMES APÓS O CLIQUE DO FUNDO ===")
            for i, f in enumerate(page.frames):
                log(f"[{i}] name='{f.name}'  url='{f.url}'")
            log("======================================")

            # ==========================================================
            # BUSCAR O LINK DO BALANCETE (#Hyperlink5)
            # ==========================================================
            log("🔍 Buscando o link do BALANCETE (#Hyperlink5)...")

            selectors = [
                "#Hyperlink5",       # seletor exato
                "a[id*='Hyperlink5']"
            ]

            texts = [
                "Balancete",
                "Balançete"
            ]

            href_keywords = [
                "balanc",
                "balan"
            ]

            frame_link, link_handle = find_link_by_multiple_strategies(
                page,
                selectors=selectors,
                texts=texts,
                href_keywords=href_keywords,
                tries=15,
                delay=0.7
            )

            if not link_handle:
                log("❌ Não foi possível localizar o link #Hyperlink5 (Balancete).")
                log("Salvando debug...")
                page.screenshot(path="balancete_not_found.png", full_page=True)
                for i, f in enumerate(page.frames):
                    try:
                        open(f"frame_debug_{i}.html", "w", encoding="utf-8").write(f.content())
                    except:
                        pass
                return

            log(f"✅ Link do Balancete encontrado no frame '{frame_link.name}' ({frame_link.url})")

            # ==========================================================
            # CLICAR NO BALANCETE E CAPTURAR TABELA
            # ==========================================================
            log("Clicando no link do Balancete...")

            page_to_extract = page  # por padrão
            try:
                with page.expect_popup(timeout=3000) as popup_info:
                    try:
                        link_handle.click()
                    except:
                        frame_link.evaluate("el => el.click()", link_handle)
                popup = popup_info.value
                log("Balancete abriu em popup.")
                popup.wait_for_load_state("domcontentloaded", timeout=10000)
                popup.screenshot(path="balancete_popup.png", full_page=True)
                open("balancete_popup.html", "w", encoding="utf-8").write(popup.content())
                page_to_extract = popup
            except PlaywrightTimeoutError:
                log("Nenhum popup — a página abriu no mesmo frame.")
                # salvamos o HTML/screenshot do frame onde foi clicado (debug)
                try:
                    frame_link.screenshot(path="balancete_frame.png")
                    open("balancete_frame.html", "w", encoding="utf-8").write(frame_link.content())
                except:
                    page.screenshot(path="balancete_page.png", full_page=True)
                    open("balancete_page.html", "w", encoding="utf-8").write(page.content())
                # page_to_extract fica como page (contendo frames)

            # Agora: extração do balancete (procura tabela no contexto page_to_extract)
            log("Iniciando extração da tabela do balancete (valor saldo)...")
            df = capture_balancete_and_save(page_to_extract, out_prefix="balancete")
            if df is None:
                log("❌ Falha ao extrair tabela do balancete.")
            else:
                log("✅ Extração do balancete concluída com sucesso.")

            log("Processo finalizado.")
            input("Pressione ENTER para fechar...")
            browser.close()

        except Exception as e:
            log("❌ ERRO FATAL")
            log(str(e))
            try:
                page.screenshot(path="error_debug.png", full_page=True)
                open("error_debug.html", "w", encoding="utf-8").write(page.content())
            except:
                pass
            raise


# Execução
if __name__ == "__main__":
    if len(sys.argv) > 1:
        value = sys.argv[1]
    else:
        value = "32.811.422/0001-33"
    main_scrape(value)
