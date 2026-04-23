#!/usr/bin/env python3
"""
Forge — PWA Builder Agent (two-pass: HTML first, then JS)
Usage: forge.py "Product Name" | forge.py --next | forge.py --list
"""

import os, sys, json, random, subprocess, re
from datetime import datetime
import urllib.request, urllib.parse
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
CATEGORIES_FILE = "/root/clearfolks/categories.json"
PRODUCTS_FILE = "/root/clearfolks/products.json"
WWW_ROOT = "/var/www/clearfolk"
NGINX_CONF = "/etc/nginx/sites-available/clearfolk"
LOGS_DIR = "/root/clearfolks/logs"

HTML_PROMPT = '''You are Forge, building a PWA for Clearfolks Templates.

PASS 1 — Generate the complete HTML structure and CSS only. No JavaScript.
End the file with <script id="app-script"></script></body></html>
This is a placeholder — JavaScript will be injected separately.

DESIGN RULES:
- Google Fonts: DM Sans + DM Mono
- CSS variables: --bg:#F5F5F7; --surface:#fff; --s2:#F9F9FB; --border:#E5E5EA; --text:#1C1C1E; --t2:#636366; --t3:#AEAEB2; --accent:#2C6BED; --red:#FF3B30; --orange:#FF9500; --green:#34C759; --purple:#5856D6; --dark:#1C1C1E; --r:12px; --rsm:8px; --sh:0 1px 3px rgba(0,0,0,.06),0 4px 16px rgba(0,0,0,.04); --f:'DM Sans',-apple-system,sans-serif; --mono:'DM Mono',monospace; --sat:env(safe-area-inset-top,0px); --sab:env(safe-area-inset-bottom,0px)
- Dark sidebar on desktop, bottom nav on mobile
- Cards border-radius 12px, subtle shadow
- PWA meta tags, manifest link, apple touch icon
- Brand footer: "Made by Clearfolk · Practical tools for life's complicated moments · clearfolks.com"
- All sections present but hidden (display:none) except first
- Use onclick="app.METHOD()" pattern for ALL interactive elements
- Minimum 5 nav sections + Export section

PRODUCT: {NAME}
CATEGORY: {CATEGORY}
PAIN: {PAIN}

Output only the HTML file. No markdown fences.'''

JS_PROMPT = '''You are Forge, completing a PWA for Clearfolks Templates.

PASS 2 — Generate ONLY the JavaScript for this PWA.
The HTML structure already exists. Your JS will be injected into <script id="app-script">.

ALL functions must be methods on a single global object: const app = {{ ... }}
This prevents naming conflicts. HTML uses onclick="app.METHOD()"

REQUIREMENTS:
- Single global object: const app = {{ switchSection, openModal, closeModal, save, load, render*, export* }}
- localStorage key: "{STORAGE_KEY}"
- Initial state object with all data arrays
- switchSection(name) — hide all .section, show matching one, update nav active state
- Full CRUD for each data type
- Export to CSV for each data type
- importData() and clearAllData()
- Call app.init() at the end to load data and render

PRODUCT: {NAME}
SECTIONS: {SECTIONS}
DATA TYPES: {DATA_TYPES}

Output ONLY the JavaScript code. No HTML, no markdown fences, no explanation.'''

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15)
    except Exception as e:
        print(f"Telegram error: {e}")

def generate_slug():
    return "cf-" + "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=8))

def extract_sections(html):
    sections = re.findall(r'id="(\w+)"\s+class="section', html)
    return sections if sections else ["overview", "list", "add", "notes", "export"]

def extract_data_types(html):
    inputs = re.findall(r'id="(\w+)Input"', html)
    return list(set([re.sub(r'(Name|Title|Date|Amount|Notes|Status|Type)$', '', i) for i in inputs if len(i) > 4]))

def call_claude(prompt, max_tokens=6000):
    msg = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text.strip()

def clean_code(text, expected="html"):
    text = re.sub(r'^```\w*\n?', '', text)
    text = re.sub(r'\n?```$', '', text)
    return text.strip()

def qa_check(html):
    issues = []
    if not html.strip().endswith("</html>"):
        issues.append("CRITICAL: missing </html>")
    if "</body>" not in html:
        issues.append("CRITICAL: missing </body>")
    if "app-script" not in html:
        issues.append("CRITICAL: missing script placeholder")
    return issues

def deploy(slug, html):
    folder = f"{WWW_ROOT}/{slug}"
    os.makedirs(folder, exist_ok=True)
    with open(f"{folder}/index.html", "w") as f:
        f.write(html)
    print(f"  Deployed to {folder}")

def add_nginx_route(slug, name):
    with open(NGINX_CONF) as f:
        config = f.read()
    if f"/{slug}" in config:
        print(f"  Route /{slug} exists")
        return
    route = f"""
    # {name}
    location /{slug} {{
        alias {WWW_ROOT}/{slug};
        try_files $uri $uri/ /{slug}/index.html;
        add_header Cache-Control "public, max-age=3600, must-revalidate";
    }}
"""
    marker = "    # Default — show product index or redirect to Etsy"
    with open(NGINX_CONF, "w") as f:
        f.write(config.replace(marker, route + "\n    " + marker.strip()))
    print(f"  Nginx route: /{slug}")

def reload_nginx():
    r = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  Nginx test failed: {r.stderr}")
        return False
    subprocess.run(["systemctl", "reload", "nginx"], check=True)
    print("  Nginx reloaded")
    return True

def register(name, slug, category, url):
    data = json.load(open(PRODUCTS_FILE)) if os.path.exists(PRODUCTS_FILE) else {"products": []}
    ids = [int(p["id"].replace("P","")) for p in data["products"]]
    pid = f"P{(max(ids)+1):04d}" if ids else "P0006"
    data["products"].append({"id": pid, "name": name, "slug": slug, "url": url, "status": "live", "category": category, "etsy_listing": "pending"})
    data["updated"] = datetime.now().strftime("%Y-%m-%d")
    json.dump(data, open(PRODUCTS_FILE, "w"), indent=2)
    print(f"  Registered as {pid}")
    return pid

def build(category_data, force_slug=None):
    name = category_data.get("suggested_product_name", "")
    category = category_data.get("category", "")
    pain = category_data.get("pain_summary", "")
    slug = force_slug or generate_slug()
    storage_key = name.lower().replace(" ", "_")

    print(f"\nForge building: {name}")
    print(f"  Slug: {slug}")

    # Pass 1 — HTML + CSS
    print("  Pass 1: Generating HTML structure...")
    html_prompt = HTML_PROMPT.replace("{NAME}", name).replace("{CATEGORY}", category).replace("{PAIN}", pain)
    html = clean_code(call_claude(html_prompt, max_tokens=5000))

    issues = qa_check(html)
    if issues:
        print(f"  HTML issues: {issues}")
        send_telegram(f"Forge WARNING: HTML issues for *{name}*:\n" + "\n".join(issues))
        return

    print(f"  HTML: {len(html):,} chars")

    # Extract structure for JS generation
    sections = extract_sections(html)
    data_types = extract_data_types(html)
    print(f"  Sections: {sections}")
    print(f"  Data types: {data_types}")

    # Pass 2 — JavaScript
    print("  Pass 2: Generating JavaScript...")
    js_prompt = JS_PROMPT.replace("{NAME}", name).replace("{STORAGE_KEY}", storage_key)
    js_prompt = js_prompt.replace("{SECTIONS}", str(sections)).replace("{DATA_TYPES}", str(data_types))
    js = clean_code(call_claude(js_prompt, max_tokens=5000), "js")

    # Inject JS into HTML
    final_html = html.replace(
        '<script id="app-script"></script>',
        f'<script id="app-script">\n{js}\n</script>'
    )

    # Final QA
    missing_fns = []
    onclick_calls = set(re.findall(r'onclick="app\.(\w+)\(', final_html))
    for fn in onclick_calls:
        if fn not in js:
            missing_fns.append(fn)

    if missing_fns:
        print(f"  WARNING: Missing JS functions: {missing_fns}")
    else:
        print(f"  JS QA: all {len(onclick_calls)} functions present")

    deploy(slug, final_html)
    add_nginx_route(slug, name)

    if not reload_nginx():
        send_telegram(f"Forge ERROR: Nginx reload failed for *{name}*")
        return

    url = f"https://app.clearfolks.com/{slug}"
    pid = register(name, slug, category, url)

    with open(f"{LOGS_DIR}/forge.log", "a") as log:
        log.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M')}: [{pid}] {name} → {url} | missing_fns: {missing_fns}\n")

    send_telegram(
        f"*Forge: {pid} live*\n\n*{name}*\n{url}\n\n"
        + (f"⚠️ Missing functions: {missing_fns}" if missing_fns else "✓ All JS functions present")
    )
    print(f"\nDone. {pid} at {url}")

def load_categories():
    with open(CATEGORIES_FILE) as f:
        return json.load(f)

def main():
    if len(sys.argv) < 2 or sys.argv[1] == "--list":
        data = load_categories()
        print("BUILD categories:")
        for c in data["categories"]:
            if c["verdict"] == "build":
                print(f"  - {c['suggested_product_name']}")
        sys.exit(0)

    data = load_categories()

    if sys.argv[1] == "--next":
        builds = [c for c in data["categories"] if c["verdict"] == "build"]
        if not builds:
            print("No BUILD categories")
            sys.exit(1)
        build(builds[0])
    elif sys.argv[1] == "--rebuild-caregiver":
        target = next((c for c in data["categories"] if c.get("suggested_product_name") == "Caregiver Command Center"), None)
        if target:
            build(target, force_slug="caregiver")
        else:
            print("Caregiver not found in categories")
    else:
        name = " ".join(sys.argv[1:])
        target = next((c for c in data["categories"] if c.get("suggested_product_name","").lower() == name.lower()), None)
        if not target:
            print(f"'{name}' not found. Run --list to see options.")
            sys.exit(1)
        build(target)

if __name__ == "__main__":
    main()
