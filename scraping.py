# scraping.py
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import time
import sys


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


# ==========================================================
# VARREDURA DE LINKS EM TODOS OS FRAMES
# ==========================================================
def find_link_in_all_frames(page, css_selector=None, text_contains=None, href_contains=None):
    """
    Procura um link em TODOS os frames.
    Retorna (frame, element) ou (None, None).
    """
    for f in page.frames:
        try:
            # 1) CSS seletor exato
            if css_selector:
                el = f.query_selector(css_selector)
                if el:
                    return f, el

            # 2) Texto semelhante
            if text_contains:
                loc = f.locator(f"text={text_contains}")
                if loc.count() > 0:
                    return f, loc.nth(0)

            # 3) href parcial
            if href_contains:
                anchors = f.query_selector_all("a")
                for a in anchors:
                    href = (a.get_attribute("href") or "").lower()
                    if href_contains.lower() in href:
                        return f, a

        except:
            continue

    return None, None


def find_link_by_multiple_strategies(page, selectors=None, texts=None, href_keywords=None, tries=10, delay=0.8):
    """
    Tenta vários métodos repetidamente até achar um link.
    """
    selectors = selectors or []
    texts = texts or []
    href_keywords = href_keywords or []

    for attempt in range(tries):
        log(f"Tentativa {attempt + 1}/{tries} para localizar o link do Balancete...")

        # CSS
        for sel in selectors:
            f, el = find_link_in_all_frames(page, css_selector=sel)
            if el:
                return f, el

        # Texto
        for txt in texts:
            f, el = find_link_in_all_frames(page, text_contains=txt)
            if el:
                return f, el

        # href
        for kw in href_keywords:
            f, el = find_link_in_all_frames(page, href_contains=kw)
            if el:
                return f, el

        time.sleep(delay)

    return None, None


# ==========================================================
# SCRAPER PRINCIPAL
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
            # CLICAR NO BALANCETE
            # ==========================================================
            log("Clicando no link do Balancete...")

            try:
                with page.expect_popup(timeout=3000) as popup_info:
                    try:
                        link_handle.click()
                    except:
                        frame_link.evaluate("el => el.click()", link_handle)

                popup = popup_info.value
                popup.wait_for_load_state("domcontentloaded")
                popup.screenshot(path="balancete_popup.png", full_page=True)
                open("balancete_popup.html", "w", encoding="utf-8").write(popup.content())
                log("Popup do Balancete salvo.")

            except PlaywrightTimeoutError:
                log("Nenhum popup — a página abriu no mesmo frame.")
                frame_link.screenshot(path="balancete_frame.png")
                open("balancete_frame.html", "w", encoding="utf-8").write(frame_link.content())

            log("✅ Processo finalizado com sucesso!")
            input("Pressione ENTER para fechar...")
            browser.close()

        except Exception as e:
            log("❌ ERRO FATAL")
            log(str(e))

            page.screenshot(path="error_debug.png", full_page=True)
            open("error_debug.html", "w", encoding="utf-8").write(page.content())

            raise


# Execução
if __name__ == "__main__":
    if len(sys.argv) > 1:
        value = sys.argv[1]
    else:
        value = "32.811.422/0001-33"
    main_scrape(value)
