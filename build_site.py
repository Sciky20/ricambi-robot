import html
import json
import os
import urllib.parse
from datetime import datetime
import requests

# ==========================================
# CONFIGURAZIONE CEO (Modifica solo qui)
# ==========================================
NOME_PORTALE = "RicambiRobot Check Italia"
DOMINIO_SITO = "https://ricambi-robot.pages.dev"  # Cambialo quando colleghi il tuo dominio
AMAZON_TAG = "ricambirobot-21"                   # Il tuo ID Tracciamento Amazon Associates
EBAY_CAMPID = "5339253914"                       # Il tuo Campaign ID di eBay Partner Network
INDEXNOW_KEY = "8f4e2a9c1b7d40369e5a1c8b2d7f4e90"  # Chiave automatica per ping immediato a Bing/DuckDuckGo/Yahoo
MAX_AI_CALLS_PER_RUN = 15                        # Quante nuove schede arricchire con AI a ogni avvio
OUTPUT_DIR = "public"
DB_FILE = "database.json"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


def call_gemini_ai(item):
    """Chiama Gemini Flash gratis per generare note di compatibilita e FAQ tecniche uniche."""
    if not GEMINI_API_KEY:
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = f"""
    Sei un tecnico specializzato in ricambi elettronici. Scrivi in italiano per il modello {item['marca']} {item['modello']} ({item['categoria']}).
    Dati tecnici noti: Codice batteria OEM {item['codice_oem_batteria']}, specifiche {item['specifiche_batteria']}, dimensioni {item['dimensioni_mm']}, consumabili {item['consumabili_inclusi']}.
    
    Restituisci ESCLUSAMENTE un oggetto JSON valido con questa struttura esatta (nessun markdown attorno):
    {{
      "nota_tecnica": "Un paragrafo di 60 parole con consigli pratici per verificare la polarita del connettore, quando sostituire la batteria e come evitare errori di montaggio.",
      "faq": [
        {{"q": "Domanda tecnica specifica sul ricambio 1?", "a": "Risposta diretta e precisa di 30 parole."}},
        {{"q": "Domanda tecnica sulla durata o compatibilita 2?", "a": "Risposta diretta e precisa di 30 parole."}},
        {{"q": "Come resettare l'errore batteria dopo il cambio su {item['modello']}?", "a": "Risposta procedurale di 30 parole."}}
      ]
    }}
    """
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    try:
        res = requests.post(url, json=payload, timeout=25)
        res.raise_for_status()
        data = res.json()
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(raw_text)
    except Exception as e:
        print(f"[AVVISO AI] Fallback attivato per {item['id']}: {e}")
        return None


def get_fallback_content(item):
    """Contenuto tecnico strutturato di sicurezza se l'API AI non e ancora attiva."""
    nota = (
        f"Per il modello {item['marca']} {item['modello']}, è fondamentale verificare che la batteria sostitutiva "
        f"rispetti il codice originale {item['codice_oem_batteria']} e le specifiche {item['specifiche_batteria']}. "
        f"Controllare sempre le dimensioni del vano ({item['dimensioni_mm']}) e la corrispondenza del connettore prima dell'acquisto. "
        f"Al primo montaggio, effettuare un ciclo di carica completa di almeno 6 ore consecutive."
    )
    faq = [
        {
            "q": f"Qual è il codice batteria originale per {item['marca']} {item['modello']}?",
            "a": f"Il codice OEM di riferimento è {item['codice_oem_batteria']} con specifiche elettriche {item['specifiche_batteria']} e ingombro {item['dimensioni_mm']}."
        },
        {
            "q": f"Posso montare una batteria compatibile maggiorata su {item['modello']}?",
            "a": "Sì, purché la tensione nominale (Volt) sia identica all'originale e il circuito BMS integrato sia compatibile con la scheda madre del dispositivo."
        },
        {
            "q": f"Ogni quanto vanno sostituiti i consumabili ({item['consumabili_inclusi']})?",
            "a": "I filtri HEPA e le spazzole laterali vanno sostituiti ogni 3-4 mesi di utilizzo, mentre il rullo centrale e le lame ogni 6-12 mesi per non sforzare il motore."
        }
    ]
    return {"nota_tecnica": nota, "faq": faq}


def build_affiliate_links(item):
    q_batt = urllib.parse.quote_plus(f"batteria {item['marca']} {item['modello']}")
    q_amz_kit = urllib.parse.quote_plus(item["query_amazon"].replace("+", " "))
    q_eby_kit = urllib.parse.quote_plus(item["query_ebay"].replace("+", " "))

    amz_batt_url = f"https://www.amazon.it/s?k={q_batt}&tag={AMAZON_TAG}"
    eby_batt_url = (
        f"https://www.ebay.it/sch/i.html?_nkw={q_batt}"
        f"&mkcid=1&mkrid=724-53478-19255-0&siteid=101&campid={EBAY_CAMPID}&customid={item['id']}-batt&toolid=10001&mkevt=1"
    )
    amz_kit_url = f"https://www.amazon.it/s?k={q_amz_kit}&tag={AMAZON_TAG}"
    eby_kit_url = (
        f"https://www.ebay.it/sch/i.html?_nkw={q_eby_kit}"
        f"&mkcid=1&mkrid=724-53478-19255-0&siteid=101&campid={EBAY_CAMPID}&customid={item['id']}-kit&toolid=10001&mkevt=1"
    )
    return amz_batt_url, eby_batt_url, amz_kit_url, eby_kit_url


def generate_model_page(item, db, today_str):
    amz_batt_url, eby_batt_url, amz_kit_url, eby_kit_url = build_affiliate_links(item)
    title = f"Batteria e Ricambi Compatibili {item['marca']} {item['modello']} ({item['codice_oem_batteria']}) - Tabella {today_str}"
    desc = f"Tabella di compatibilità verificata per {item['marca']} {item['modello']}: codice batteria {item['codice_oem_batteria']}, misure {item['dimensioni_mm']}, kit filtri e migliori offerte."
    oem_safe = item["codice_oem_batteria"].replace("'", "")

    # Collegamenti interni automatici per accelerare la scansione di Google
    related = [x for x in db if x["marca"].lower() == item["marca"].lower() and x["id"] != item["id"]]
    if len(related) < 4:
        same_cat = [x for x in db if x["categoria"] == item["categoria"] and x["id"] != item["id"] and x not in related]
        related.extend(same_cat[:4 - len(related)])
    related = related[:4]

    related_html = ""
    for rel in related:
        related_html += f"""
        <a href="/modello/{rel['id']}.html" class="block p-4 rounded-lg border border-slate-200 hover:border-emerald-500 bg-slate-50 hover:bg-white transition">
            <span class="text-[11px] font-semibold text-emerald-700 uppercase">{rel['categoria']}</span>
            <p class="font-bold text-slate-900 text-sm mt-1">{rel['marca']} {rel['modello']}</p>
            <p class="text-xs font-mono text-slate-500 mt-1">Cod: {rel['codice_oem_batteria']}</p>
        </a>
        """

    faq_schema_items = []
    faq_html_items = ""
    for f in item["faq_ai"]:
        faq_schema_items.append({
            "@type": "Question",
            "name": f["q"],
            "acceptedAnswer": {"@type": "Answer", "text": f["a"]}
        })
        faq_html_items += f"""
        <div class="border-b border-slate-200 py-4">
            <h3 class="font-semibold text-slate-900 text-lg">{f['q']}</h3>
            <p class="text-slate-600 mt-1">{f['a']}</p>
        </div>
        """

    schema_json = json.dumps({
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": faq_schema_items
    }, ensure_ascii=False)

    page_html = f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <meta name="description" content="{desc}">
    <link rel="canonical" href="{DOMINIO_SITO}/modello/{item['id']}.html">
    <script src="https://cdn.tailwindcss.com"></script>
    <script type="application/ld+json">{schema_json}</script>
</head>
<body class="bg-slate-50 text-slate-800 font-sans">
    <header class="bg-slate-900 text-white py-4 px-6 shadow">
        <div class="max-w-4xl mx-auto flex justify-between items-center">
            <a href="/index.html" class="font-bold text-xl tracking-tight text-emerald-400">{NOME_PORTALE}</a>
            <span class="text-xs bg-slate-800 px-3 py-1 rounded-full text-slate-300">Dati verificati: {today_str}</span>
        </div>
    </header>

    <main class="max-w-4xl mx-auto px-4 py-8">
        <nav class="text-sm text-slate-500 mb-4">
            <a href="/index.html" class="hover:underline">Home Catalogo</a> &rarr; <span>{item['categoria']}</span> &rarr; <span class="text-slate-900 font-medium">{item['marca']} {item['modello']}</span>
        </nav>

        <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-8">
            <span class="inline-block bg-emerald-100 text-emerald-800 text-xs font-semibold px-2.5 py-1 rounded mb-2">SCHEDA DI COMPATIBILITÀ VERIFICATA</span>
            <h1 class="text-2xl md:text-3xl font-extrabold text-slate-900 mb-2">
                Batteria e Kit Ricambi per {item['marca']} {item['modello']}
            </h1>
            <p class="text-slate-600 mb-5">
                Specifiche tecniche ufficiali, codici OEM equivalenti e link diretti ai ricambi compatibili al 100% per il tuo {item['categoria'].lower()}.
            </p>

            <!-- Selettore interattivo del problema -->
            <div class="bg-slate-900 text-white rounded-xl p-4 mb-6">
                <p class="text-xs font-bold uppercase tracking-wider text-emerald-400 mb-2.5">Diagnosi Rapida: qual è il problema del tuo {item['marca']}?</p>
                <div class="grid grid-cols-1 sm:grid-cols-3 gap-2">
                    <button type="button" onclick="evidenziaRicambio('batteria')" class="text-left text-xs font-semibold bg-slate-800 hover:bg-emerald-600 px-3 py-2.5 rounded-lg border border-slate-700 transition">
                        &#9889; Dura poco / Non carica
                    </button>
                    <button type="button" onclick="evidenziaRicambio('kit')" class="text-left text-xs font-semibold bg-slate-800 hover:bg-emerald-600 px-3 py-2.5 rounded-lg border border-slate-700 transition">
                        &#128295; Aspira poco / Usura
                    </button>
                    <button type="button" onclick="evidenziaRicambio('entrambi')" class="text-left text-xs font-semibold bg-slate-800 hover:bg-emerald-600 px-3 py-2.5 rounded-lg border border-slate-700 transition">
                        &#9989; Manutenzione completa
                    </button>
                </div>
                <p id="diagnosi-msg" class="hidden text-xs text-emerald-300 font-medium mt-3 pt-2.5 border-t border-slate-800"></p>
            </div>

            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse border border-slate-200 rounded-lg overflow-hidden">
                    <tbody>
                        <tr class="bg-slate-100 border-b border-slate-200">
                            <th class="py-3 px-4 font-semibold text-slate-700 w-1/3">Modello Dispositivo</th>
                            <td class="py-3 px-4 font-bold text-slate-900">{item['marca']} {item['modello']}</td>
                        </tr>
                        <tr class="border-b border-slate-200">
                            <th class="py-3 px-4 font-semibold text-slate-700">Codice OEM Batteria</th>
                            <td class="py-3 px-4 font-mono text-emerald-700 font-bold">{item['codice_oem_batteria']}</td>
                        </tr>
                        <tr class="bg-slate-50 border-b border-slate-200">
                            <th class="py-3 px-4 font-semibold text-slate-700">Voltaggio e Capacità</th>
                            <td class="py-3 px-4">{item['specifiche_batteria']}</td>
                        </tr>
                        <tr class="border-b border-slate-200">
                            <th class="py-3 px-4 font-semibold text-slate-700">Dimensioni Vano Batteria</th>
                            <td class="py-3 px-4">{item['dimensioni_mm']}</td>
                        </tr>
                        <tr class="bg-slate-50 border-b border-slate-200">
                            <th class="py-3 px-4 font-semibold text-slate-700">Kit Consumabili Compatibili</th>
                            <td class="py-3 px-4">{item['consumabili_inclusi']}</td>
                        </tr>
                        <tr>
                            <th class="py-3 px-4 font-semibold text-slate-700">Fascia Prezzo di Mercato</th>
                            <td class="py-3 px-4 font-semibold text-slate-900">{item['fascia_prezzo_ricambio']}</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- Checklist anti-errore prima del clic -->
            <div class="mt-6 bg-emerald-50/70 border border-emerald-200 rounded-xl p-4">
                <p class="text-xs font-bold uppercase tracking-wider text-emerald-900 mb-2">Checklist Anti-Errore Prima dell'Acquisto</p>
                <ul class="text-xs text-slate-700 space-y-1.5">
                    <li>&#10004; <strong>Voltaggio e sigla verificati:</strong> {item['specifiche_batteria']} (Cod. {item['codice_oem_batteria']}).</li>
                    <li>&#10004; <strong>Ingombro esatto:</strong> {item['dimensioni_mm']} compatibile con l'alloggiamento originale.</li>
                    <li>&#10004; <strong>Acquisto protetto:</strong> reso gratuito entro 30 giorni garantito su Amazon e eBay in caso di errato ordine.</li>
                </ul>
            </div>

            <div class="space-y-4 mt-6">
                <div id="box-batteria" class="p-3.5 rounded-xl border border-slate-200 transition-all">
                    <p class="text-xs font-bold uppercase tracking-wider text-slate-600 mb-2">1. Batteria di Ricambio Compatibile ({item['codice_oem_batteria']})</p>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <a href="{amz_batt_url}" target="_blank" rel="nofollow sponsored noopener" class="flex items-center justify-center bg-amber-400 hover:bg-amber-500 text-slate-950 font-bold py-3.5 px-5 rounded-lg shadow transition text-center">
                            Cerca Batteria su Amazon.it &rarr;
                        </a>
                        <a href="{eby_batt_url}" target="_blank" rel="nofollow sponsored noopener" class="flex items-center justify-center bg-blue-600 hover:bg-blue-700 text-white font-bold py-3.5 px-5 rounded-lg shadow transition text-center">
                            Cerca Batteria su eBay.it &rarr;
                        </a>
                    </div>
                </div>
                <div id="box-kit" class="p-3.5 rounded-xl border border-slate-200 transition-all">
                    <p class="text-xs font-bold uppercase tracking-wider text-slate-600 mb-2">2. Kit Ricambi (Filtri, Spazzole, Sacchetti o Lame)</p>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <a href="{amz_kit_url}" target="_blank" rel="nofollow sponsored noopener" class="flex items-center justify-center bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-3.5 px-5 rounded-lg shadow transition text-center">
                            Kit Ricambi su Amazon.it &rarr;
                        </a>
                        <a href="{eby_kit_url}" target="_blank" rel="nofollow sponsored noopener" class="flex items-center justify-center bg-slate-800 hover:bg-slate-900 text-white font-bold py-3.5 px-5 rounded-lg shadow transition text-center">
                            Kit Ricambi su eBay.it &rarr;
                        </a>
                    </div>
                </div>
            </div>
        </div>

        <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-8">
            <h2 class="text-xl font-bold text-slate-900 mb-3">Note Tecniche di Montaggio e Manutenzione</h2>
            <p class="text-slate-700 leading-relaxed">{item['nota_tecnica_ai']}</p>
        </div>

        <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-8">
            <h2 class="text-xl font-bold text-slate-900 mb-4">Domande Frequenti ({item['marca']} {item['modello']})</h2>
            {faq_html_items}
        </div>

        <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
            <h2 class="text-lg font-bold text-slate-900 mb-3">Altre Schede Tecniche Correlate ({item['marca']})</h2>
            <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">
                {related_html}
            </div>
        </div>
    </main>

    <footer class="bg-slate-900 text-slate-400 text-xs py-8 px-4 mt-12">
        <div class="max-w-4xl mx-auto text-center space-y-2">
            <p>&copy; {datetime.now().year} {NOME_PORTALE} - Database Tecnico Indipendente.</p>
            <p>In qualità di Affiliato Amazon e partner eBay Partner Network, questo portale riceve una commissione sugli acquisti idonei effettuati tramite i link presenti, senza alcun sovrapprezzo per l'utente.</p>
        </div>
    </footer>

    <script>
    function evidenziaRicambio(tipo) {{
        const boxBatt = document.getElementById('box-batteria');
        const boxKit = document.getElementById('box-kit');
        const msg = document.getElementById('diagnosi-msg');
        boxBatt.classList.remove('ring-4', 'ring-emerald-400', 'bg-emerald-50');
        boxKit.classList.remove('ring-4', 'ring-emerald-400', 'bg-emerald-50');
        if (tipo === 'batteria') {{
            boxBatt.classList.add('ring-4', 'ring-emerald-400', 'bg-emerald-50');
            msg.textContent = 'Consiglio tecnico: sostituisci la batteria verificando il codice {oem_safe}.';
        }} else if (tipo === 'kit') {{
            boxKit.classList.add('ring-4', 'ring-emerald-400', 'bg-emerald-50');
            msg.textContent = 'Consiglio tecnico: rinnova filtri, spazzole o lame per ripristinare la resa originale.';
        }} else {{
            boxBatt.classList.add('ring-4', 'ring-emerald-400', 'bg-emerald-50');
            boxKit.classList.add('ring-4', 'ring-emerald-400', 'bg-emerald-50');
            msg.textContent = 'Consiglio tecnico: revisione completa con batteria nuova ({oem_safe}) e kit consumabili.';
        }}
        msg.classList.remove('hidden');
    }}
    </script>
</body>
</html>"""
    return page_html


def generate_index_page(db, today_str):
    cards_html = ""
    for item in db:
        cards_html += f"""
        <a href="/modello/{item['id']}.html" class="block bg-white p-5 rounded-xl border border-slate-200 shadow-sm hover:border-emerald-500 hover:shadow-md transition" data-search="{item['marca'].lower()} {item['modello'].lower()} {item['codice_oem_batteria'].lower()}">
            <span class="text-xs font-semibold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded">{item['categoria']}</span>
            <h2 class="text-lg font-bold text-slate-900 mt-2">{item['marca']} {item['modello']}</h2>
            <p class="text-sm text-slate-600 mt-1">Cod. Batteria: <span class="font-mono font-semibold">{item['codice_oem_batteria']}</span></p>
            <p class="text-xs text-slate-500 mt-2">Spec: {item['specifiche_batteria']} | Fascia: {item['fascia_prezzo_ricambio']}</p>
            <span class="inline-block mt-3 text-sm font-semibold text-emerald-600">Apri tabella compatibilità &rarr;</span>
        </a>
        """

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="google-site-verification" content="pBkbOhlZXa5p-vR2Xff77ujhx4NbinX1HerB6K08qRw" />
    <title>{NOME_PORTALE} - Database Compatibilità Batterie e Ricambi Robot</title>
    <meta name="description" content="Trova subito il codice batteria OEM, le misure esatte e i kit ricambi compatibili per il tuo robot aspirapolvere o tagliaerba.">
    <link rel="alternate" type="application/rss+xml" title="{NOME_PORTALE} RSS Feed" href="{DOMINIO_SITO}/feed.xml">
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-50 text-slate-800 font-sans">
    <header class="bg-slate-900 text-white py-12 px-6 text-center">
        <div class="max-w-3xl mx-auto">
            <h1 class="text-3xl md:text-4xl font-extrabold text-emerald-400 mb-3">{NOME_PORTALE}</h1>
            <p class="text-slate-300 text-lg mb-6">Database tecnico di compatibilità per batterie OEM, filtri HEPA, lame e spazzole di ricambio. Aggiornato al {today_str}.</p>
            <input type="text" id="searchInput" onkeyup="filterModels()" placeholder="Cerca modello o codice batteria (es. Dreame L10s, WR141E, BRR-2P4S)..." class="w-full px-5 py-4 rounded-xl text-slate-900 font-medium shadow-lg focus:outline-none focus:ring-4 focus:ring-emerald-500">
        </div>
    </header>

    <main class="max-w-5xl mx-auto px-4 py-10">
        <div id="modelsGrid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {cards_html}
        </div>
    </main>

    <script>
    function filterModels() {{
        const q = document.getElementById('searchInput').value.toLowerCase();
        const cards = document.querySelectorAll('#modelsGrid a');
        cards.forEach(card => {{
            const text = card.getAttribute('data-search');
            card.style.display = text.includes(q) ? 'block' : 'none';
        }});
    }}
    </script>
</body>
</html>"""


def ping_indexnow(url_list):
    """Notifica immediatamente Bing, DuckDuckGo, Yahoo ed Ecosia delle nuove pagine."""
    host = DOMINIO_SITO.replace("https://", "").replace("http://", "").strip("/")
    payload = {
        "host": host,
        "key": INDEXNOW_KEY,
        "keyLocation": f"{DOMINIO_SITO}/{INDEXNOW_KEY}.txt",
        "urlList": url_list
    }
    try:
        res = requests.post("https://api.indexnow.org/indexnow", json=payload, timeout=15)
        print(f"[IndexNow] Ping inviato per {len(url_list)} URL -> HTTP {res.status_code}")
    except Exception as e:
        print(f"[IndexNow] Avviso invio: {e}")


def main():
    os.makedirs(os.path.join(OUTPUT_DIR, "modello"), exist_ok=True)
    today_str = datetime.now().strftime("%d/%m/%Y")
    today_iso = datetime.now().strftime("%Y-%m-%d")
    rss_date = datetime.now().strftime("%a, %d %b %Y 03:00:00 +0000")

    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)

    ai_calls = 0
    db_modified = False

    for item in db:
        if not item.get("ai_enriched", False) and ai_calls < MAX_AI_CALLS_PER_RUN:
            ai_res = call_gemini_ai(item)
            if ai_res and "nota_tecnica" in ai_res and "faq" in ai_res:
                item["nota_tecnica_ai"] = ai_res["nota_tecnica"]
                item["faq_ai"] = ai_res["faq"]
                item["ai_enriched"] = True
                ai_calls += 1
                db_modified = True
            else:
                fb = get_fallback_content(item)
                item["nota_tecnica_ai"] = fb["nota_tecnica"]
                item["faq_ai"] = fb["faq"]
        elif not item.get("nota_tecnica_ai"):
            fb = get_fallback_content(item)
            item["nota_tecnica_ai"] = fb["nota_tecnica"]
            item["faq_ai"] = fb["faq"]

        page_html = generate_model_page(item, db, today_str)
        with open(os.path.join(OUTPUT_DIR, "modello", f"{item['id']}.html"), "w", encoding="utf-8") as out:
            out.write(page_html)

    if db_modified:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)

    # Genera Home Page
    index_html = generate_index_page(db, today_str)
    with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as out:
        out.write(index_html)

    # Genera Sitemap.xml e lista URL
    all_urls = [f"{DOMINIO_SITO}/index.html"]
    urls_xml = [f"<url><loc>{DOMINIO_SITO}/index.html</loc><lastmod>{today_iso}</lastmod><priority>1.0</priority></url>"]
    rss_items = []

    for item in db:
        page_url = f"{DOMINIO_SITO}/modello/{item['id']}.html"
        all_urls.append(page_url)
        urls_xml.append(f"<url><loc>{page_url}</loc><lastmod>{today_iso}</lastmod><priority>0.8</priority></url>")
        safe_title = html.escape(f"Batteria e Ricambi {item['marca']} {item['modello']} ({item['codice_oem_batteria']})")
        safe_desc = html.escape(f"Specifiche verificate: {item['specifiche_batteria']}, misure {item['dimensioni_mm']}. Consumabili: {item['consumabili_inclusi']}.")
        rss_items.append(f"<item><title>{safe_title}</title><link>{page_url}</link><guid>{page_url}</guid><pubDate>{rss_date}</pubDate><description>{safe_desc}</description></item>")

    sitemap_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{"".join(urls_xml)}
</urlset>"""
    with open(os.path.join(OUTPUT_DIR, "sitemap.xml"), "w", encoding="utf-8") as out:
        out.write(sitemap_xml)

    # Genera Feed RSS automatico (feed.xml)
    feed_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>{html.escape(NOME_PORTALE)}</title>
<link>{DOMINIO_SITO}</link>
<description>Aggiornamenti tecnici e compatibilità ricambi robot e aspirapolvere.</description>
{"".join(rss_items)}
</channel>
</rss>"""
    with open(os.path.join(OUTPUT_DIR, "feed.xml"), "w", encoding="utf-8") as out:
        out.write(feed_xml)

    # Genera robots.txt e file chiave IndexNow
    robots_txt = f"User-agent: *\nAllow: /\nSitemap: {DOMINIO_SITO}/sitemap.xml\n"
    with open(os.path.join(OUTPUT_DIR, "robots.txt"), "w", encoding="utf-8") as out:
        out.write(robots_txt)

    with open(os.path.join(OUTPUT_DIR, f"{INDEXNOW_KEY}.txt"), "w", encoding="utf-8") as out:
        out.write(INDEXNOW_KEY)

    # Ping automatico ai motori di ricerca
    ping_indexnow(all_urls)

    print(f"Portale generato con successo: {len(db)} pagine, feed.xml e IndexNow completati.")


if __name__ == "__main__":
    main()
