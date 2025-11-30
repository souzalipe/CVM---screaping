from playwright.sync_api import sync_playwright
import json

URL = "https://cvmweb.cvm.gov.br/SWB/default.asp?sg_sistema=fundosreg"

def extract_inputs(frame):
    inputs = []
    for tag in ["input", "button", "select", "textarea"]:
        elements = frame.query_selector_all(tag)
        for el in elements:
            info = {
                "tag": tag,
                "id": el.get_attribute("id"),
                "name": el.get_attribute("name"),
                "type": el.get_attribute("type"),
                "value": el.get_attribute("value"),
                "placeholder": el.get_attribute("placeholder"),
                "text": el.inner_text()
            }
            inputs.append(info)
    return inputs

def explore_frame(frame, depth=0):
    frame_info = {
        "frame_url": frame.url,
        "depth": depth,
        "inputs": extract_inputs(frame)
    }

    subframes = frame.child_frames
    frame_info["child_frames"] = [explore_frame(sf, depth + 1) for sf in subframes]

    return frame_info

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        
        print("🌐 Carregando página...")
        page.goto(URL, wait_until="load", timeout=60000)

        print("🔍 Analisando frames e inputs...")
        root_frame_data = explore_frame(page.main_frame)

        with open("cvm_structure.json", "w", encoding="utf-8") as f:
            json.dump(root_frame_data, f, ensure_ascii=False, indent=4)

        print("\n✅ Arquivo gerado: cvm_structure.json")
        print("📌 Me envie esse arquivo ou cole aqui o conteúdo dele!\n")

        browser.close()

if __name__ == "__main__":
    main()
