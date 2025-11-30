from playwright.sync_api import sync_playwright
import time

def consultar_cvm(cnpj):
    URL = "https://cvmweb.cvm.gov.br/SWB/default.asp?sg_sistema=fundosreg"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(URL)

        print("Aguardando todos os iframes carregarem...")
        page.wait_for_load_state("load")
        time.sleep(2)

        print("\n=== FRAMES ENCONTRADOS ===")
        for i, f in enumerate(page.frames):
            print(f"[{i}] -> {f.url}")

        target_frame_url = "FormBuscaParticFdo.aspx"
        frame = None

        for f in page.frames:
            if target_frame_url in f.url:
                frame = f
                break

        if not frame:
            print("❌ Não achei o frame do formulário da CVM!")
            return
        
        print("✅ Frame correto encontrado:", frame.url)

        print("Preenchendo CNPJ...")
        frame.fill("#txtCNPJNome", cnpj)

        print("Clicando em Continuar...")
        frame.click("#btnContinuar")

        print("Aguardando resposta...")
        frame.wait_for_load_state("domcontentloaded")
        time.sleep(2)

        print("Procurando links de fundos na tabela...")
        links = frame.query_selector_all("a[id*='Linkbutton4']")

        print(f"Quantidade de links encontrados: {len(links)}")

        if len(links) >= 1:
            print("Clicando no primeiro fundo (index 0)...")
            links[0].click()
        else:
            print("❌ Nenhum link encontrado na tabela!")
            return

        print("Aguardando página de detalhes do fundo...")
        frame.wait_for_load_state("load")
        time.sleep(3)

        print("📄 Página carregada!")
        print("URL atual dentro do frame:", frame.url)

        input("\nPressione ENTER para fechar... ")
        browser.close()


if __name__ == "__main__":
    consultar_cvm("04.093.184/0001-32")
