import html
import json
import os
import re
import urllib.parse
from datetime import datetime
import requests

# ==========================================
# CONFIGURAZIONE PORTALE
# ==========================================
NOME_PORTALE = "RicambiRobot Check"
DOMINIO_SITO = "https://ricambi-robot.pages.dev"
AMAZON_TAG = "ricambirobot-21"
EBAY_CAMPID = "5339253914"
INDEXNOW_KEY = "8f4e2a9c1b7d40369e5a1c8b2d7f4e90"
MAX_AI_CALLS_PER_RUN = 15
OUTPUT_DIR = "public"
DB_FILE = "database.json"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def clean_search_term(text):
    """Pulisce barre e parentesi per evitare ricerche a zero risultati su Amazon ed eBay."""
    return text.split("/")[0].split("(")[0].strip()


def is_wired_device(item):
    spec = item.get("specifiche_batteria", "").lower()
    return ("230v" in spec) or ("a filo" in spec)


def parse_price_range(price_str):
    nums = re.findall(r"\d+(?:[.,]\d+)?", str(price_str))
    if len(nums) >= 2:
        low = float(nums[0].replace(",", "."))
        high = float(nums[1].replace(",", "."))
        return f"{min(low, high):.2f}", f"{max(low, high):.2f}"
    if len(nums) == 1:
        val = float(nums[0].replace(",", "."))
        return f"{val:.2f}", f"{val:.2f}"
    return "25.00", "65.00"


def get_cat_group(categoria):
    cat_lower = categoria.lower()
    if "tagliaerba" in cat_lower:
        return "robot-tagliaerba"
    if "scopa" in cat_lower or "lavapavimenti" in cat_lower:
        return "scope-senza-fili"
    return "robot-aspirapolvere"


CATEGORIES_META = {
    "robot-aspirapolvere": {
        "name": "Robot Aspirapolvere e Lavapavimenti",
        "short": "Robot Aspirapolvere",
        "desc": "Database tecnico di batterie OEM, filtri HEPA, panni rotanti e spazzole compatibili per robot aspirapolvere e lavapavimenti."
    },
    "scope-senza-fili": {
        "name": "Scope Elettriche e Lavapavimenti Senza Fili",
        "short": "Scope Senza Fili",
        "desc": "Codici batteria originali e compatibili, filtri lavabili e rulli per scope elettriche senza fili Dyson, Folletto, Tineco, Rowenta e Samsung."
    },
    "robot-tagliaerba": {
        "name": "Robot Tagliaerba Automatici",
        "short": "Robot Tagliaerba",
        "desc": "Batterie al litio 18V/20V/25.9V e kit lame in titanio o acciaio inox compatibili per robot rasaerba Worx, Husqvarna, Gardena, Bosch e Parkside."
    }
}


def call_gemini_ai(item):
    """Chiama Gemini Flash gratis per generare nota tecnica, FAQ e guida di smontaggio unica per ogni modello."""
    if not GEMINI_API_KEY:
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    wired_hint = "dispositivo alimentato a filo 230V (senza batteria, focus su sacchetti/filtri/accessori)" if is_wired_device(item) else "dispositivo a batteria (focus su sostituzione pacco batteria, connettore/attacco e reset errore)"

    prompt = f"""
    Sei un tecnico specializzato nella riparazione di elettrodomestici. Scrivi in italiano tecnico chiaro e concreto per {item['marca']} {item['modello']} ({item['categoria']} - {wired_hint}).
    Dati tecnici verificati: Codice OEM {item['codice_oem_batteria']}, specifiche {item['specifiche_batteria']}, misure {item['dimensioni_mm']}, consumabili {item['consumabili_inclusi']}.
    
    Restituisci ESCLUSAMENTE un oggetto JSON valido con questa struttura esatta (nessun markdown attorno):
    {{
      "nota_tecnica": "Un paragrafo di 60 parole con consigli pratici specifici per {item['marca']} {item['modello']} su come verificare codice OEM, connettori/attacchi ed evitare errori di montaggio.",
      "sintomo_guasto": "Una frase di 18-22 parole sul sintomo tipico di usura o errore LED/display su {item['marca']} {item['modello']} che richiede il cambio ricambi.",
      "faq": [
        {{"q": "Domanda tecnica specifica sul ricambio principale di {item['modello']}?", "a": "Risposta diretta e precisa di 30 parole."}},
        {{"q": "Domanda tecnica sulla compatibilita o durata su {item['modello']}?", "a": "Risposta diretta e precisa di 30 parole."}},
        {{"q": "Come ripristinare il funzionamento dopo il cambio ricambi su {item['modello']}?", "a": "Risposta procedurale di 30 parole."}}
      ],
      "guida_passi": [
        {{"name": "Titolo breve passaggio 1 (verifica codice)", "text": "Istruzione pratica di 30-35 parole specifica per {item['marca']} {item['modello']} citando il codice {item['codice_oem_batteria']}."}},
        {{"name": "Titolo breve passaggio 2 (apertura vano/sgancio)", "text": "Istruzione pratica di 30-35 parole su come aprire l'alloggiamento o sganciare il componente su {item['modello']}."}},
        {{"name": "Titolo breve passaggio 3 (montaggio e pulizia)", "text": "Istruzione pratica di 30-35 parole sul montaggio del nuovo ricambio e sostituzione di {item['consumabili_inclusi']}."}},
        {{"name": "Titolo breve passaggio 4 (calibrazione/test)", "text": "Istruzione pratica di 30-35 parole su ricarica iniziale, calibrazione BMS o test di tenuta su {item['modello']}."}}
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
    """Contenuto tecnico differenziato per architettura dispositivo se l'API AI non ha ancora elaborato il modello."""
    marca_l = item["marca"].lower()
    cat_l = item["categoria"].lower()
    wired = is_wired_device(item)

    if wired:
        sintomo = f"Calo improvviso della potenza di aspirazione, surriscaldamento del motore o fuoriuscita di polvere fine su {item['marca']} {item['modello']}."
        nota = (
            f"Su {item['marca']} {item['modello']} (alimentazione 230V), l'efficienza del motore dipende dalla tenuta dei sacchetti e dei filtri {item['codice_oem_batteria']}. "
            f"Verificare sempre l'integrità delle guarnizioni del vano ({item['dimensioni_mm']}) e sostituire regolarmente {item['consumabili_inclusi']} per evitare sovraccarichi termici."
        )
        steps = [
            {
                "name": "Controllo sigla sacchetti e filtri OEM",
                "text": f"Verifica sull'alloggiamento interno di {item['marca']} {item['modello']} la sigla {item['codice_oem_batteria']} per assicurarti che flangia e guarnizioni combacino perfettamente."
            },
            {
                "name": "Scollegamento dalla presa 230V e apertura vano",
                "text": f"Spegni l'interruttore principale e stacca sempre la spina dalla rete elettrica prima di sganciare il coperchio superiore o il vano filtri di {item['modello']}."
            },
            {
                "name": "Sostituzione consumabili e pulizia sede",
                "text": f"Estrai i ricambi esauriti ({item['consumabili_inclusi']}), rimuovi eventuali residui di polvere dai bordi in gomma e inserisci i nuovi filtri fino allo scatto."
            },
            {
                "name": "Verifica chiusura ermetica e prova flusso",
                "text": "Richiudi lo sportello controllando che non vi siano fessure lungo la guarnizione e avvia l'aspirazione per confermare il ripristino della depressione."
            }
        ]
    elif "tagliaerba" in cat_l:
        sintomo = f"Rientro anticipato alla stazione di ricarica, taglio irregolare del prato o avviso tensione bassa su {item['marca']} {item['modello']}."
        nota = (
            f"Per il robot tagliaerba {item['marca']} {item['modello']}, è indispensabile montare un pacco batteria con codice {item['codice_oem_batteria']} "
            f"e tensione {item['specifiche_batteria']}. Controllare la guarnizione impermeabile del vano ({item['dimensioni_mm']}) e bilanciare il disco sostituendo tutte le lame contemporaneamente."
        )
        steps = [
            {
                "name": "Verifica voltaggio e codice batteria OEM",
                "text": f"Controlla sull'etichetta della batteria originale di {item['marca']} {item['modello']} il codice {item['codice_oem_batteria']} e la tensione {item['specifiche_batteria']}."
            },
            {
                "name": "Spegnimento totale e apertura sportello stagno",
                "text": f"Premi il tasto STOP, porta l'interruttore generale su OFF e svita il coperchio inferiore del vano batteria (dimensioni {item['dimensioni_mm']})."
            },
            {
                "name": "Collegamento batteria e rinnovo lame",
                "text": f"Collega il connettore della nuova batteria senza forzare i pin, richiudi la guarnizione stagna e installa i consumabili nuovi ({item['consumabili_inclusi']})."
            },
            {
                "name": "Ricarica completa in base e sblocco PIN",
                "text": "Posiziona il robot sui contatti della base di ricarica fino al 100%, inserisci il codice PIN e avvia un ciclo di taglio di prova."
            }
        ]
    elif "dyson" in marca_l:
        sintomo = f"LED rosso lampeggiante sul corpo motore o spegnimento immediato dopo pochi secondi in modalità Max su {item['marca']} {item['modello']}."
        nota = (
            f"Prima di ordinare la batteria per {item['marca']} {item['modello']}, verifica se il tuo modello utilizza l'attacco a viti o a sgancio rapido Click-in ({item['codice_oem_batteria']}). "
            f"Rispetta sempre la tensione {item['specifiche_batteria']} e lascia asciugare il filtro HEPA per almeno 24 ore dopo il lavaggio prima di riaccendere."
        )
        steps = [
            {
                "name": "Identificazione attacco (Viti vs Click-in) e codice",
                "text": f"Controlla sotto l'impugnatura di {item['marca']} {item['modello']} il codice {item['codice_oem_batteria']} ({item['specifiche_batteria']}) e verifica la presenza di viti o pulsante rosso."
            },
            {
                "name": "Rimozione del pacco batteria esaurito",
                "text": "Svuota il contenitore della polvere, rimuovi la vite posteriore sull'impugnatura (o premi il tasto di sgancio Click-in) e sfila la batteria verso il basso."
            },
            {
                "name": "Inserimento nuova batteria e controllo filtri",
                "text": f"Allinea le guide del nuovo pacco batteria fino al clic di blocco e verifica la pulizia di {item['consumabili_inclusi']} per non ostruire il flusso d'aria."
            },
            {
                "name": "Ciclo di carica completa prima dell'uso",
                "text": "Collega il caricatore originale fino allo spegnimento del LED blu di ricarica (circa 3,5 - 4,5 ore) prima di utilizzare la modalità Boost."
            }
        ]
    elif "scopa" in cat_l or "lavapavimenti" in cat_l:
        sintomo = f"Autonomia inferiore a pochi minuti, ricarica interrotta o calo di aspirazione su {item['marca']} {item['modello']}."
        nota = (
            f"Per {item['marca']} {item['modello']}, assicurati che la batteria sostitutiva corrisponda al codice {item['codice_oem_batteria']} "
            f"e alle specifiche {item['specifiche_batteria']}. Pulisci regolarmente i rulli e i filtri ({item['consumabili_inclusi']}) per evitare il blocco della spazzola motorizzata."
        )
        steps = [
            {
                "name": "Controllo sigla batteria e specifiche elettriche",
                "text": f"Verifica sulla targhetta di {item['marca']} {item['modello']} la corrispondenza con il codice {item['codice_oem_batteria']} ({item['specifiche_batteria']})."
            },
            {
                "name": "Sgancio batteria e rimozione serbatoio/rullo",
                "text": f"Spegni l'apparecchio, scollegalo dalla base di ricarica e sblocca l'alloggiamento batteria o il coperchio vano ({item['dimensioni_mm']})."
            },
            {
                "name": "Installazione ricambio e manutenzione rulli/filtri",
                "text": f"Inserisci il nuovo pacco batteria verificando il fermo meccanico e rinnova i componenti soggetti a usura ({item['consumabili_inclusi']})."
            },
            {
                "name": "Ricarica di calibrazione iniziale",
                "text": "Riponi la scopa elettrica sulla stazione di ricarica per un ciclo completo ininterrotto prima di avviare la pulizia."
            }
        ]
    else:
        sintomo = f"Errore batteria sul display/app, mancato rientro alla base o arresto durante la pulizia su {item['marca']} {item['modello']}."
        nota = (
            f"Per il robot {item['marca']} {item['modello']}, è fondamentale verificare che la batteria sostitutiva rispetti il codice {item['codice_oem_batteria']} "
            f"e le specifiche {item['specifiche_batteria']}. Controllare la polarità del connettore, le misure {item['dimensioni_mm']} e rinnovare {item['consumabili_inclusi']}."
        )
        steps = [
            {
                "name": "Verifica codice OEM, tensione e connettore",
                "text": f"Controlla sull'etichetta della batteria di {item['marca']} {item['modello']} il codice {item['codice_oem_batteria']} ({item['specifiche_batteria']}) e il numero di pin del connettore."
            },
            {
                "name": "Spegnimento e apertura sportello inferiore",
                "text": f"Capovolgi {item['modello']} su un panno morbido, svita la spazzola laterale se necessario e rimuovi le viti del coperchio vano batteria ({item['dimensioni_mm']})."
            },
            {
                "name": "Montaggio nuova batteria e cambio consumabili",
                "text": f"Scollega il vecchio pacco, collega la nuova batteria rispettando la guida del connettore e sostituisci i ricambi usurati ({item['consumabili_inclusi']})."
            },
            {
                "name": "Calibrazione BMS di 6 ore sulla base",
                "text": "Richiudi il coperchio inferiore, posiziona il robot sui contatti della base e lascialo in carica continua per almeno 6 ore prima del primo avvio."
            }
        ]

    faq = [
        {
            "q": f"Qual è il codice ricambio originale per {item['marca']} {item['modello']}?",
            "a": f"Il codice OEM di riferimento è {item['codice_oem_batteria']} con specifiche {item['specifiche_batteria']} e ingombro {item['dimensioni_mm']}."
        },
        {
            "q": f"Posso montare ricambi compatibili certificati su {item['modello']}?",
            "a": "Sì, purché i parametri elettrici e gli attacchi meccanici siano identici all'originale per preservare motore e scheda elettronica."
        },
        {
            "q": f"Ogni quanto vanno sostituiti i consumabili ({item['consumabili_inclusi']})?",
            "a": "I filtri HEPA e le spazzole laterali vanno sostituiti ogni 3-4 mesi di utilizzo, mentre rulli, sacchetti e lame vanno rinnovati regolarmente per non sforzare il motore."
        }
    ]
    return {
        "nota_tecnica": nota,
        "sintomo_guasto": sintomo,
        "faq": faq,
        "guida_passi": steps
    }


def build_affiliate_links(item, suffix=""):
    clean_mod = clean_search_term(item["modello"])
    clean_oem = clean_search_term(item["codice_oem_batteria"])

    if is_wired_device(item):
        raw_primary = f"ricambi {item['marca']} {clean_mod} {clean_oem}"
    else:
        raw_primary = f"batteria {item['marca']} {clean_mod} {clean_oem}"

    q_primary = urllib.parse.quote_plus(raw_primary)
    q_amz_kit = urllib.parse.quote_plus(item["query_amazon"].replace("+", " "))
    q_eby_kit = urllib.parse.quote_plus(item["query_ebay"].replace("+", " "))

    tag_suffix = f"-{suffix}" if suffix else ""
    amz_batt_url = f"https://www.amazon.it/s?k={q_primary}&tag={AMAZON_TAG}"
    eby_batt_url = (
        f"https://www.ebay.it/sch/i.html?_nkw={q_primary}"
        f"&mkcid=1&mkrid=724-53478-19255-0&siteid=101&campid={EBAY_CAMPID}&customid={item['id']}-pri{tag_suffix}&toolid=10001&mkevt=1"
    )
    amz_kit_url = f"https://www.amazon.it/s?k={q_amz_kit}&tag={AMAZON_TAG}"
    eby_kit_url = (
        f"https://www.ebay.it/sch/i.html?_nkw={q_eby_kit}"
        f"&mkcid=1&mkrid=724-53478-19255-0&siteid=101&campid={EBAY_CAMPID}&customid={item['id']}-kit{tag_suffix}&toolid=10001&mkevt=1"
    )
    return amz_batt_url, eby_batt_url, amz_kit_url, eby_kit_url


def get_head_assets(title, desc, canonical_url, extra_head=""):
    return f"""<meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <meta name="description" content="{desc}">
    <link rel="canonical" href="{canonical_url}">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@500;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {{
            theme: {{
                extend: {{
                    fontFamily: {{
                        sans: ['"Plus Jakarta Sans"', 'sans-serif'],
                        mono: ['"JetBrains Mono"', 'monospace'],
                    }}
                }}
            }}
        }}
    </script>
    {extra_head}"""


def get_navbar(today_str):
    return f"""<header class="sticky top-0 z-50 bg-slate-950/95 backdrop-blur-md border-b border-slate-800 text-white">
        <div class="max-w-5xl mx-auto px-4 sm:px-6 h-16 flex justify-between items-center">
            <a href="/" class="flex items-center gap-2.5 group">
                <div class="w-9 h-9 rounded-lg bg-gradient-to-br from-emerald-400 to-teal-600 flex items-center justify-center shadow-lg shadow-emerald-500/20">
                    <svg class="w-5 h-5 text-slate-950" fill="none" stroke="currentColor" stroke-width="2.4" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
                    </svg>
                </div>
                <div>
                    <span class="font-extrabold text-lg tracking-tight text-white block leading-none">{NOME_PORTALE}</span>
                    <span class="text-[10px] font-medium uppercase tracking-widest text-emerald-400">Database Tecnico OEM</span>
                </div>
            </a>
            <div class="flex items-center gap-2 sm:gap-3">
                <span class="hidden md:inline-flex items-center gap-1.5 text-xs font-medium bg-slate-900 border border-slate-800 px-3 py-1.5 rounded-full text-slate-300">
                    <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                    Listino verificato: {today_str}
                </span>
                <a href="/categoria/robot-aspirapolvere.html" class="hidden sm:inline-block text-xs font-medium text-slate-300 hover:text-white px-2.5 py-1.5 transition">Robot</a>
                <a href="/categoria/scope-senza-fili.html" class="hidden sm:inline-block text-xs font-medium text-slate-300 hover:text-white px-2.5 py-1.5 transition">Scope</a>
                <a href="/categoria/robot-tagliaerba.html" class="hidden sm:inline-block text-xs font-medium text-slate-300 hover:text-white px-2.5 py-1.5 transition">Tagliaerba</a>
                <a href="/" class="text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-white px-3.5 py-2 rounded-lg transition">
                    Catalogo
                </a>
            </div>
        </div>
    </header>"""


def get_footer(brands_list):
    brand_links = " &middot; ".join(
        [f'<a href="/marca/{b["slug"]}.html" class="hover:text-emerald-400 transition">{b["name"]}</a>' for b in brands_list[:15]]
    )
    cat_links = " &middot; ".join(
        [f'<a href="/categoria/{slug}.html" class="hover:text-emerald-400 transition">{meta["name"]}</a>' for slug, meta in CATEGORIES_META.items()]
    )
    return f"""<footer class="bg-slate-950 text-slate-400 border-t border-slate-800 mt-16">
        <div class="max-w-5xl mx-auto px-4 sm:px-6 py-12">
            <div class="mb-6 pb-6 border-b border-slate-800/80 space-y-4">
                <div>
                    <p class="text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">Categorie Principali</p>
                    <div class="text-xs text-slate-300 leading-relaxed">{cat_links}</div>
                </div>
                <div>
                    <p class="text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">Archivio Ricambi per Marca</p>
                    <div class="text-xs text-slate-400 leading-relaxed">{brand_links}</div>
                </div>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-8 pb-8 border-b border-slate-800/80 text-xs leading-relaxed">
                <div>
                    <p class="text-white font-bold text-sm mb-2">{NOME_PORTALE} Italia</p>
                    <p class="text-slate-400">Archivio indipendente di specifiche elettriche, ingombri e codici ricambio OEM per robot aspirapolvere, tagliaerba automatici e scope elettriche.</p>
                </div>
                <div>
                    <p class="text-white font-bold text-sm mb-2">Metodologia di Verifica</p>
                    <p class="text-slate-400">I parametri di tensione (Volt), capacità (mAh) e compatibilità meccanica sono incrociati con i manuali di servizio ufficiali per prevenire danni alle schede BMS.</p>
                </div>
                <div>
                    <p class="text-white font-bold text-sm mb-2">Trasparenza Commerciale</p>
                    <p class="text-slate-400">In qualità di Affiliato Amazon e partner eBay Partner Network, il portale riceve una commissione sugli acquisti idonei senza alcun costo aggiuntivo per l'acquirente.</p>
                </div>
            </div>
            <div class="pt-6 flex flex-col sm:flex-row justify-between items-center gap-4 text-xs text-slate-500">
                <p>&copy; {datetime.now().year} {NOME_PORTALE} — Tutti i marchi citati appartengono ai rispettivi proprietari.</p>
                <a href="/" class="text-emerald-400 hover:text-emerald-300 font-medium">Torna all'indice dei modelli &uarr;</a>
            </div>
        </div>
    </footer>"""


def get_mobile_sticky_bar(item, amz_batt_url, amz_kit_url):
    pri_label = "Ricambi Amazon &rarr;" if is_wired_device(item) else "Batteria Amazon &rarr;"
    return f"""<div class="fixed bottom-0 inset-x-0 z-40 sm:hidden bg-slate-950/95 backdrop-blur-md border-t border-slate-800 px-3 py-2.5 shadow-2xl">
        <div class="grid grid-cols-2 gap-2">
            <a href="{amz_batt_url}" target="_blank" rel="nofollow sponsored noopener" class="flex items-center justify-center bg-amber-400 text-slate-950 font-extrabold text-xs py-2.5 px-3 rounded-lg shadow">
                {pri_label}
            </a>
            <a href="{amz_kit_url}" target="_blank" rel="nofollow sponsored noopener" class="flex items-center justify-center bg-emerald-500 text-slate-950 font-extrabold text-xs py-2.5 px-3 rounded-lg shadow">
                Kit Completo &rarr;
            </a>
        </div>
    </div>"""


def get_affiliate_buttons_block(item, amz_batt_url, eby_batt_url, amz_kit_url, eby_kit_url):
    wired = is_wired_device(item)
    pri_title = f"Ricambio Principale ({item['codice_oem_batteria']})" if wired else f"Batteria Compatibile ({item['codice_oem_batteria']})"
    pri_amz_btn = "Cerca Ricambio su Amazon.it" if wired else "Verifica Batteria su Amazon.it"
    pri_eby_btn = "Confronta Ricambio su eBay.it" if wired else "Confronta Batteria su eBay.it"

    return f"""<div class="space-y-4 mb-7">
        <div id="box-batteria" class="p-5 rounded-xl border-2 border-slate-200 bg-white transition-all">
            <div class="flex flex-wrap items-center justify-between gap-2 mb-3">
                <div>
                    <span class="text-[11px] font-bold uppercase tracking-wider text-amber-700 bg-amber-100 px-2 py-0.5 rounded">Ricambio Principale</span>
                    <h2 class="text-base font-extrabold text-slate-900 mt-1">{pri_title}</h2>
                </div>
                <span class="text-xs font-medium text-slate-500">Reso gratuito 30 giorni</span>
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <a href="{amz_batt_url}" target="_blank" rel="nofollow sponsored noopener" class="flex items-center justify-center gap-2 bg-amber-400 hover:bg-amber-500 text-slate-950 font-extrabold text-sm py-3.5 px-5 rounded-xl shadow-sm transition">
                    <span>{pri_amz_btn}</span>
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3"/></svg>
                </a>
                <a href="{eby_batt_url}" target="_blank" rel="nofollow sponsored noopener" class="flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 text-white font-extrabold text-sm py-3.5 px-5 rounded-xl shadow-sm transition">
                    <span>{pri_eby_btn}</span>
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3"/></svg>
                </a>
            </div>
        </div>

        <div id="box-kit" class="p-5 rounded-xl border-2 border-slate-200 bg-white transition-all">
            <div class="flex flex-wrap items-center justify-between gap-2 mb-3">
                <div>
                    <span class="text-[11px] font-bold uppercase tracking-wider text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded">Manutenzione Periodica</span>
                    <h2 class="text-base font-extrabold text-slate-900 mt-1">Kit Consumabili ({item['consumabili_inclusi'].split(',')[0]})</h2>
                </div>
                <span class="text-xs font-medium text-slate-500">Spedizione rapida</span>
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <a href="{amz_kit_url}" target="_blank" rel="nofollow sponsored noopener" class="flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white font-extrabold text-sm py-3.5 px-5 rounded-xl shadow-sm transition">
                    <span>Kit Ricambi su Amazon.it</span>
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3"/></svg>
                </a>
                <a href="{eby_kit_url}" target="_blank" rel="nofollow sponsored noopener" class="flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-900 text-white font-extrabold text-sm py-3.5 px-5 rounded-xl shadow-sm transition">
                    <span>Kit Ricambi su eBay.it</span>
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3"/></svg>
                </a>
            </div>
        </div>
    </div>"""


def get_related_grid(item, db):
    related = [x for x in db if x["marca"].lower() == item["marca"].lower() and x["id"] != item["id"]]
    if len(related) < 4:
        same_cat = [x for x in db if x["categoria"] == item["categoria"] and x["id"] != item["id"] and x not in related]
        related.extend(same_cat[:4 - len(related)])
    related = related[:4]

    related_html = ""
    for rel in related:
        related_html += f"""
        <a href="/modello/{rel['id']}.html" class="group block p-4 rounded-xl border border-slate-200/90 hover:border-emerald-500 bg-white hover:shadow-md transition-all">
            <span class="text-[10px] font-bold tracking-wider uppercase text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded">{rel['marca']}</span>
            <p class="font-bold text-slate-900 text-sm mt-2 group-hover:text-emerald-700 transition">{rel['modello']}</p>
            <p class="text-xs font-mono text-slate-500 mt-1.5 truncate">OEM: {rel['codice_oem_batteria']}</p>
        </a>
        """
    return related_html


def generate_model_page(item, db, brands_list, today_str):
    amz_batt_url, eby_batt_url, amz_kit_url, eby_kit_url = build_affiliate_links(item)
    brand_slug = slugify(item["marca"])
    cat_slug = get_cat_group(item["categoria"])
    wired = is_wired_device(item)

    title_prefix = "Ricambi e Consumabili" if wired else "Batteria e Ricambi"
    title = f"{title_prefix} {item['marca']} {item['modello']} ({item['codice_oem_batteria']}) - Scheda {today_str}"
    desc = f"Compatibilità verificata {item['marca']} {item['modello']}: codice OEM {item['codice_oem_batteria']}, misure {item['dimensioni_mm']}, kit filtri e confronto prezzi."
    oem_safe = item["codice_oem_batteria"].replace("'", "")
    low_p, high_p = parse_price_range(item["fascia_prezzo_ricambio"])

    related_html = get_related_grid(item, db)

    faq_schema_items = []
    faq_html_items = ""
    for f in item["faq_ai"]:
        faq_schema_items.append({
            "@type": "Question",
            "name": f["q"],
            "acceptedAnswer": {"@type": "Answer", "text": f["a"]}
        })
        faq_html_items += f"""
        <div class="p-5 rounded-xl bg-slate-50 border border-slate-200/80">
            <h3 class="font-bold text-slate-900 text-base flex items-start gap-2.5">
                <span class="text-emerald-600 font-mono text-sm mt-0.5">Q.</span>
                <span>{f['q']}</span>
            </h3>
            <p class="text-slate-600 text-sm mt-2 pl-6 leading-relaxed">{f['a']}</p>
        </div>
        """

    schemas_graph = json.dumps({
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Product",
                "name": f"{title_prefix} Compatibili {item['marca']} {item['modello']}",
                "description": desc,
                "brand": {"@type": "Brand", "name": item["marca"]},
                "mpn": clean_search_term(item["codice_oem_batteria"]),
                "category": item["categoria"],
                "offers": {
                    "@type": "AggregateOffer",
                    "priceCurrency": "EUR",
                    "lowPrice": low_p,
                    "highPrice": high_p,
                    "offerCount": "4",
                    "availability": "https://schema.org/InStock"
                }
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Catalogo", "item": f"{DOMINIO_SITO}/"},
                    {"@type": "ListItem", "position": 2, "name": item["marca"], "item": f"{DOMINIO_SITO}/marca/{brand_slug}.html"},
                    {"@type": "ListItem", "position": 3, "name": item["modello"], "item": f"{DOMINIO_SITO}/modello/{item['id']}.html"}
                ]
            },
            {
                "@type": "FAQPage",
                "mainEntity": faq_schema_items
            }
        ]
    }, ensure_ascii=False)

    head_html = get_head_assets(
        title,
        desc,
        f"{DOMINIO_SITO}/modello/{item['id']}.html",
        f'<script type="application/ld+json">{schemas_graph}</script>'
    )

    buttons_html = get_affiliate_buttons_block(item, amz_batt_url, eby_batt_url, amz_kit_url, eby_kit_url)

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
    {head_html}
</head>
<body class="bg-slate-100/80 text-slate-800 font-sans antialiased pb-16 sm:pb-0 selection:bg-emerald-200 selection:text-slate-900">
    {get_navbar(today_str)}

    <main class="max-w-4xl mx-auto px-4 sm:px-6 py-8">
        <nav class="flex items-center gap-2 text-xs font-medium text-slate-500 mb-5 overflow-x-auto whitespace-nowrap">
            <a href="/" class="hover:text-slate-900 transition">Catalogo</a>
            <span>/</span>
            <a href="/categoria/{cat_slug}.html" class="hover:text-emerald-700 transition">{CATEGORIES_META[cat_slug]['short']}</a>
            <span>/</span>
            <a href="/marca/{brand_slug}.html" class="hover:text-emerald-700 transition">{item['marca']}</a>
            <span>/</span>
            <span class="text-slate-900 font-semibold">{item['modello']}</span>
        </nav>

        <div class="bg-white rounded-2xl shadow-sm border border-slate-200/90 overflow-hidden mb-8">
            <div class="bg-gradient-to-r from-slate-900 via-slate-900 to-slate-800 px-6 py-7 text-white border-b border-slate-800">
                <div class="flex flex-wrap items-center gap-2 mb-3">
                    <span class="inline-flex items-center gap-1.5 bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 text-xs font-bold px-3 py-1 rounded-full">
                        <svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/></svg>
                        COMPATIBILITÀ VERIFICATA
                    </span>
                    <a href="/categoria/{cat_slug}.html" class="text-xs font-medium text-slate-300 hover:text-white bg-slate-800/80 px-2.5 py-1 rounded-full transition">{item['categoria']}</a>
                </div>
                <h1 class="text-2xl sm:text-3xl font-extrabold tracking-tight text-white">
                    {title_prefix} {item['marca']} {item['modello']}
                </h1>
                <p class="text-slate-300 text-sm mt-2 max-w-2xl leading-relaxed">
                    Scheda tecnica di riferimento con codice OEM, dimensioni esatte e kit consumabili compatibili al 100%.
                </p>
            </div>

            <div class="p-6 sm:p-8">
                <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5 mb-7">
                    <div class="p-4 rounded-xl bg-slate-50 border border-slate-200/80">
                        <p class="text-[11px] font-bold uppercase tracking-wider text-slate-400">Codice OEM</p>
                        <p class="font-mono text-sm font-bold text-emerald-700 mt-1 break-words">{item['codice_oem_batteria']}</p>
                    </div>
                    <div class="p-4 rounded-xl bg-slate-50 border border-slate-200/80">
                        <p class="text-[11px] font-bold uppercase tracking-wider text-slate-400">Specifiche Tecniche</p>
                        <p class="text-xs font-bold text-slate-900 mt-1 leading-snug">{item['specifiche_batteria']}</p>
                    </div>
                    <div class="p-4 rounded-xl bg-slate-50 border border-slate-200/80">
                        <p class="text-[11px] font-bold uppercase tracking-wider text-slate-400">Dimensioni / Misure</p>
                        <p class="font-mono text-xs font-bold text-slate-900 mt-1">{item['dimensioni_mm']}</p>
                    </div>
                    <div class="p-4 rounded-xl bg-slate-50 border border-slate-200/80">
                        <p class="text-[11px] font-bold uppercase tracking-wider text-slate-400">Prezzo Medio Stimato</p>
                        <p class="text-sm font-extrabold text-slate-900 mt-1">{item['fascia_prezzo_ricambio']}</p>
                    </div>
                </div>

                <div class="bg-slate-900 text-white rounded-xl p-5 mb-7 shadow-inner">
                    <div class="flex items-center justify-between mb-3">
                        <p class="text-xs font-bold uppercase tracking-wider text-emerald-400">Selettore Rapido Ricambio</p>
                        <span class="text-[11px] text-slate-400">Seleziona il sintomo</span>
                    </div>
                    <div class="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                        <button type="button" onclick="evidenziaRicambio('batteria')" class="flex items-center gap-2 text-left text-xs font-semibold bg-slate-800/90 hover:bg-emerald-600 px-3.5 py-3 rounded-lg border border-slate-700 transition">
                            <span class="text-amber-400">&#9889;</span>
                            <span>{"Ricambio principale / Sacchetti" if wired else "Autonomia ridotta / Non carica"}</span>
                        </button>
                        <button type="button" onclick="evidenziaRicambio('kit')" class="flex items-center gap-2 text-left text-xs font-semibold bg-slate-800/90 hover:bg-emerald-600 px-3.5 py-3 rounded-lg border border-slate-700 transition">
                            <span class="text-sky-400">&#128295;</span>
                            <span>Perdita potenza / Usura parti</span>
                        </button>
                        <button type="button" onclick="evidenziaRicambio('entrambi')" class="flex items-center gap-2 text-left text-xs font-semibold bg-slate-800/90 hover:bg-emerald-600 px-3.5 py-3 rounded-lg border border-slate-700 transition">
                            <span class="text-emerald-400">&#10004;</span>
                            <span>Manutenzione completa</span>
                        </button>
                    </div>
                    <p id="diagnosi-msg" class="hidden text-xs text-emerald-300 font-medium mt-3 pt-3 border-t border-slate-800"></p>
                </div>

                {buttons_html}

                <div class="mb-7 p-4 rounded-xl bg-amber-50/70 border border-amber-200/80 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <div>
                        <p class="text-xs font-extrabold text-amber-950">{item['sintomo_guasto_ai']}</p>
                        <p class="text-xs text-amber-800 mt-0.5">Leggi la procedura passo-passo di sostituzione e ripristino ottimale.</p>
                    </div>
                    <a href="/guida/sostituzione-batteria-{item['id']}.html" class="shrink-0 text-xs font-bold bg-amber-950 hover:bg-slate-900 text-white px-4 py-2.5 rounded-lg transition text-center">
                        Apri Guida Montaggio &rarr;
                    </a>
                </div>

                <div class="border border-slate-200 rounded-xl overflow-hidden">
                    <div class="bg-slate-50 px-4 py-3 border-b border-slate-200">
                        <h3 class="text-xs font-bold uppercase tracking-wider text-slate-700">Specifiche Tecniche Complete</h3>
                    </div>
                    <table class="w-full text-left text-sm border-collapse">
                        <tbody class="divide-y divide-slate-200">
                            <tr>
                                <th class="py-3 px-4 font-semibold text-slate-600 w-1/3 bg-slate-50/50">Dispositivo</th>
                                <td class="py-3 px-4 font-bold text-slate-900">{item['marca']} {item['modello']}</td>
                            </tr>
                            <tr>
                                <th class="py-3 px-4 font-semibold text-slate-600 bg-slate-50/50">Codici OEM Equivalenti</th>
                                <td class="py-3 px-4 font-mono text-emerald-700 font-bold">{item['codice_oem_batteria']}</td>
                            </tr>
                            <tr>
                                <th class="py-3 px-4 font-semibold text-slate-600 bg-slate-50/50">Alimentazione / Specifiche</th>
                                <td class="py-3 px-4 text-slate-800">{item['specifiche_batteria']}</td>
                            </tr>
                            <tr>
                                <th class="py-3 px-4 font-semibold text-slate-600 bg-slate-50/50">Dimensioni Alloggiamento</th>
                                <td class="py-3 px-4 font-mono text-slate-800">{item['dimensioni_mm']}</td>
                            </tr>
                            <tr>
                                <th class="py-3 px-4 font-semibold text-slate-600 bg-slate-50/50">Consumabili Compatibili</th>
                                <td class="py-3 px-4 text-slate-800">{item['consumabili_inclusi']}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <div class="bg-white rounded-2xl shadow-sm border border-slate-200/90 p-6 sm:p-8 mb-8">
            <h2 class="text-lg font-extrabold text-slate-900 mb-3">Note Tecniche di Installazione e Sicurezza</h2>
            <p class="text-slate-600 text-sm sm:text-base leading-relaxed">{item['nota_tecnica_ai']}</p>
        </div>

        <div class="bg-white rounded-2xl shadow-sm border border-slate-200/90 p-6 sm:p-8 mb-8">
            <h2 class="text-lg font-extrabold text-slate-900 mb-4">Domande Frequenti su {item['marca']} {item['modello']}</h2>
            <div class="space-y-3">
                {faq_html_items}
            </div>
        </div>

        <div>
            <h2 class="text-sm font-extrabold uppercase tracking-wider text-slate-500 mb-3">Altre Schede Verificate ({item['marca']})</h2>
            <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3.5">
                {related_html}
            </div>
        </div>
    </main>

    {get_footer(brands_list)}
    {get_mobile_sticky_bar(item, amz_batt_url, amz_kit_url)}

    <script>
    function evidenziaRicambio(tipo) {{
        const boxBatt = document.getElementById('box-batteria');
        const boxKit = document.getElementById('box-kit');
        const msg = document.getElementById('diagnosi-msg');
        boxBatt.classList.remove('border-emerald-500', 'bg-emerald-50/40', 'shadow-md');
        boxKit.classList.remove('border-emerald-500', 'bg-emerald-50/40', 'shadow-md');
        boxBatt.classList.add('border-slate-200');
        boxKit.classList.add('border-slate-200');
        if (tipo === 'batteria') {{
            boxBatt.classList.remove('border-slate-200');
            boxBatt.classList.add('border-emerald-500', 'bg-emerald-50/40', 'shadow-md');
            msg.textContent = 'Ricambio consigliato: codice OEM {oem_safe}.';
        }} else if (tipo === 'kit') {{
            boxKit.classList.remove('border-slate-200');
            boxKit.classList.add('border-emerald-500', 'bg-emerald-50/40', 'shadow-md');
            msg.textContent = 'Ricambio consigliato: kit filtri, spazzole o consumabili per ripristinare la capacità di raccolta.';
        }} else {{
            boxBatt.classList.remove('border-slate-200');
            boxKit.classList.remove('border-slate-200');
            boxBatt.classList.add('border-emerald-500', 'bg-emerald-50/40', 'shadow-md');
            boxKit.classList.add('border-emerald-500', 'bg-emerald-50/40', 'shadow-md');
            msg.textContent = 'Manutenzione completa: ricambio principale ({oem_safe}) + sostituzione consumabili usurati.';
        }}
        msg.classList.remove('hidden');
    }}
    </script>
</body>
</html>"""


def generate_guide_page(item, db, brands_list, today_str):
    amz_batt_url, eby_batt_url, amz_kit_url, eby_kit_url = build_affiliate_links(item, suffix="guida")
    brand_slug = slugify(item["marca"])
    wired = is_wired_device(item)
    steps = item["guida_passi_ai"]

    if wired:
        title = f"Sostituzione Filtri, Sacchetti e Manutenzione {item['marca']} {item['modello']} - Guida {today_str}"
        desc = f"Come sostituire filtri, sacchetti ({item['codice_oem_batteria']}) e accessori soggetti a usura su {item['marca']} {item['modello']}."
    else:
        title = f"Sostituzione Batteria e Reset Errore {item['marca']} {item['modello']} - Guida {today_str}"
        desc = f"Come sostituire la batteria ({item['codice_oem_batteria']}) e risolvere i problemi di ricarica o LED lampeggiante su {item['marca']} {item['modello']}."

    schemas_graph = json.dumps({
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "HowTo",
                "name": f"Manutenzione e cambio ricambi su {item['marca']} {item['modello']}",
                "description": desc,
                "step": [{"@type": "HowToStep", "name": s["name"], "text": s["text"]} for s in steps]
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Catalogo", "item": f"{DOMINIO_SITO}/"},
                    {"@type": "ListItem", "position": 2, "name": item["marca"], "item": f"{DOMINIO_SITO}/marca/{brand_slug}.html"},
                    {"@type": "ListItem", "position": 3, "name": item["modello"], "item": f"{DOMINIO_SITO}/modello/{item['id']}.html"},
                    {"@type": "ListItem", "position": 4, "name": "Guida Manutenzione", "item": f"{DOMINIO_SITO}/guida/sostituzione-batteria-{item['id']}.html"}
                ]
            }
        ]
    }, ensure_ascii=False)

    head_html = get_head_assets(
        title,
        desc,
        f"{DOMINIO_SITO}/guida/sostituzione-batteria-{item['id']}.html",
        f'<script type="application/ld+json">{schemas_graph}</script>'
    )

    steps_html = ""
    for idx, st in enumerate(steps, 1):
        steps_html += f"""
        <div class="flex gap-4 p-5 rounded-xl bg-slate-50 border border-slate-200/80">
            <div class="w-8 h-8 shrink-0 rounded-full bg-slate-900 text-emerald-400 font-mono font-bold text-sm flex items-center justify-center">
                {idx}
            </div>
            <div>
                <h3 class="font-bold text-slate-900 text-base">{st['name']}</h3>
                <p class="text-slate-600 text-sm mt-1.5 leading-relaxed">{st['text']}</p>
            </div>
        </div>
        """

    buttons_html = get_affiliate_buttons_block(item, amz_batt_url, eby_batt_url, amz_kit_url, eby_kit_url)
    related_html = get_related_grid(item, db)

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
    {head_html}
</head>
<body class="bg-slate-100/80 text-slate-800 font-sans antialiased pb-16 sm:pb-0">
    {get_navbar(today_str)}

    <main class="max-w-4xl mx-auto px-4 sm:px-6 py-8">
        <nav class="flex items-center gap-2 text-xs font-medium text-slate-500 mb-5 overflow-x-auto whitespace-nowrap">
            <a href="/" class="hover:text-slate-900">Catalogo</a>
            <span>/</span>
            <a href="/marca/{brand_slug}.html" class="hover:text-emerald-700">{item['marca']}</a>
            <span>/</span>
            <a href="/modello/{item['id']}.html" class="hover:text-emerald-700">{item['modello']}</a>
            <span>/</span>
            <span class="text-slate-900 font-semibold">Guida Manutenzione</span>
        </nav>

        <div class="bg-white rounded-2xl shadow-sm border border-slate-200/90 overflow-hidden mb-8">
            <div class="bg-slate-900 px-6 py-7 text-white border-b border-slate-800">
                <span class="inline-block bg-amber-500/20 border border-amber-400/30 text-amber-300 text-xs font-bold px-3 py-1 rounded-full mb-3">
                    PROCEDURA TECNICA E MANUTENZIONE
                </span>
                <h1 class="text-2xl sm:text-3xl font-extrabold tracking-tight text-white">
                    {"Sostituzione Filtri, Sacchetti e Ricambi" if wired else "Sostituzione Batteria e Risoluzione Errori"} {item['marca']} {item['modello']}
                </h1>
                <p class="text-slate-300 text-sm mt-2 leading-relaxed">
                    {item['sintomo_guasto_ai']} Verifica il codice OEM <span class="font-mono text-emerald-400 font-bold">{item['codice_oem_batteria']}</span> prima di procedere.
                </p>
            </div>

            <div class="p-6 sm:p-8">
                <div class="mb-7 p-4 rounded-xl bg-slate-50 border border-slate-200 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <div>
                        <p class="text-xs font-bold uppercase text-slate-400">Scheda Tecnica di Riferimento</p>
                        <p class="text-sm font-extrabold text-slate-900 mt-0.5">{item['marca']} {item['modello']} &mdash; {item['specifiche_batteria']}</p>
                    </div>
                    <a href="/modello/{item['id']}.html" class="shrink-0 text-xs font-bold text-emerald-700 hover:text-emerald-800 bg-emerald-50 border border-emerald-200 px-3.5 py-2 rounded-lg transition text-center">
                        &larr; Vai alla Tabella Completa
                    </a>
                </div>

                <h2 class="text-lg font-extrabold text-slate-900 mb-4">Procedura Passo-Passo</h2>
                <div class="space-y-3.5 mb-8">
                    {steps_html}
                </div>

                <h2 class="text-lg font-extrabold text-slate-900 mb-3">Ricambi Verificati Pronti per il Montaggio</h2>
                {buttons_html}

                <div class="bg-slate-50 rounded-xl p-5 border border-slate-200/80">
                    <h3 class="text-sm font-extrabold text-slate-900 mb-2">Avvertenze del Tecnico su {item['modello']}</h3>
                    <p class="text-slate-600 text-sm leading-relaxed">{item['nota_tecnica_ai']}</p>
                </div>
            </div>
        </div>

        <div>
            <h2 class="text-sm font-extrabold uppercase tracking-wider text-slate-500 mb-3">Altre Schede Verificate ({item['marca']})</h2>
            <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3.5">
                {related_html}
            </div>
        </div>
    </main>

    {get_footer(brands_list)}
    {get_mobile_sticky_bar(item, amz_batt_url, amz_kit_url)}
</body>
</html>"""


def generate_brand_page(brand_info, brand_items, brands_list, today_str):
    brand_name = brand_info["name"]
    brand_slug = brand_info["slug"]
    title = f"Batterie e Ricambi Compatibili {brand_name} - Catalogo OEM {today_str}"
    desc = f"Elenco completo dei modelli {brand_name} verificati: codici OEM, dimensioni vano e kit filtri/spazzole compatibili."

    cards_html = ""
    for item in brand_items:
        cards_html += f"""
        <div class="bg-white p-5 rounded-2xl border border-slate-200/90 shadow-sm flex flex-col justify-between">
            <div>
                <span class="text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2.5 py-0.5 rounded-full">{item['categoria']}</span>
                <h2 class="text-lg font-extrabold text-slate-900 mt-2.5">{item['marca']} {item['modello']}</h2>
                <p class="text-xs font-mono text-slate-600 mt-1.5">Cod. OEM: <strong>{item['codice_oem_batteria']}</strong></p>
                <p class="text-xs text-slate-500 mt-1">{item['specifiche_batteria']}</p>
            </div>
            <div class="mt-4 pt-3.5 border-t border-slate-100 flex items-center justify-between gap-2">
                <a href="/modello/{item['id']}.html" class="text-xs font-bold text-white bg-slate-900 hover:bg-emerald-600 px-3.5 py-2 rounded-lg transition">
                    Scheda Ricambi &rarr;
                </a>
                <a href="/guida/sostituzione-batteria-{item['id']}.html" class="text-xs font-semibold text-slate-600 hover:text-slate-900">
                    Guida cambio
                </a>
            </div>
        </div>
        """

    head_html = get_head_assets(
        title,
        desc,
        f"{DOMINIO_SITO}/marca/{brand_slug}.html"
    )

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
    {head_html}
</head>
<body class="bg-slate-100/80 text-slate-800 font-sans antialiased">
    {get_navbar(today_str)}

    <section class="bg-slate-950 text-white border-b border-slate-800 py-10 px-4 sm:px-6">
        <div class="max-w-5xl mx-auto">
            <nav class="text-xs text-slate-400 mb-3">
                <a href="/" class="hover:text-white">Catalogo Generale</a> / <span class="text-emerald-400 font-semibold">{brand_name}</span>
            </nav>
            <h1 class="text-2xl sm:text-4xl font-extrabold text-white">Batterie e Ricambi Compatibili {brand_name}</h1>
            <p class="text-slate-400 text-sm sm:text-base mt-2 max-w-2xl">
                Seleziona il tuo modello {brand_name} tra i {len(brand_items)} dispositivi verificati per visualizzare codice OEM e kit consumabili.
            </p>
        </div>
    </section>

    <main class="max-w-5xl mx-auto px-4 sm:px-6 py-8">
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {cards_html}
        </div>
    </main>

    {get_footer(brands_list)}
</body>
</html>"""


def generate_category_page(cat_slug, cat_meta, cat_items, brands_list, today_str):
    title = f"Batterie e Ricambi Compatibili {cat_meta['name']} - Archivio {today_str}"
    desc = cat_meta["desc"]

    cards_html = ""
    for item in cat_items:
        cards_html += f"""
        <div class="bg-white p-5 rounded-2xl border border-slate-200/90 shadow-sm flex flex-col justify-between">
            <div>
                <div class="flex items-center justify-between gap-2">
                    <span class="text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2.5 py-0.5 rounded-full">{item['marca']}</span>
                    <span class="text-[11px] text-slate-400">{item['fascia_prezzo_ricambio']}</span>
                </div>
                <h2 class="text-base font-extrabold text-slate-900 mt-2.5">{item['modello']}</h2>
                <p class="text-xs font-mono text-slate-600 mt-1.5">OEM: <strong>{clean_search_term(item['codice_oem_batteria'])}</strong></p>
                <p class="text-xs text-slate-500 mt-1">{item['specifiche_batteria']}</p>
            </div>
            <div class="mt-4 pt-3.5 border-t border-slate-100 flex items-center justify-between gap-2">
                <a href="/modello/{item['id']}.html" class="text-xs font-bold text-white bg-slate-900 hover:bg-emerald-600 px-3.5 py-2 rounded-lg transition">
                    Scheda &rarr;
                </a>
                <a href="/guida/sostituzione-batteria-{item['id']}.html" class="text-xs font-semibold text-slate-600 hover:text-slate-900">
                    Guida cambio
                </a>
            </div>
        </div>
        """

    head_html = get_head_assets(
        title,
        desc,
        f"{DOMINIO_SITO}/categoria/{cat_slug}.html"
    )

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
    {head_html}
</head>
<body class="bg-slate-100/80 text-slate-800 font-sans antialiased">
    {get_navbar(today_str)}

    <section class="bg-slate-950 text-white border-b border-slate-800 py-10 px-4 sm:px-6">
        <div class="max-w-5xl mx-auto">
            <nav class="text-xs text-slate-400 mb-3">
                <a href="/" class="hover:text-white">Catalogo Generale</a> / <span class="text-emerald-400 font-semibold">{cat_meta['short']}</span>
            </nav>
            <h1 class="text-2xl sm:text-4xl font-extrabold text-white">{cat_meta['name']}</h1>
            <p class="text-slate-400 text-sm sm:text-base mt-2 max-w-2xl">
                {cat_meta['desc']} ({len(cat_items)} modelli verificati).
            </p>
        </div>
    </section>

    <main class="max-w-5xl mx-auto px-4 sm:px-6 py-8">
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {cards_html}
        </div>
    </main>

    {get_footer(brands_list)}
</body>
</html>"""


def generate_index_page(db, brands_list, today_str):
    cards_html = ""
    for item in db:
        cat_group = get_cat_group(item["categoria"])
        cards_html += f"""
        <a href="/modello/{item['id']}.html" class="model-card group flex flex-col justify-between bg-white p-5 rounded-2xl border border-slate-200/90 shadow-sm hover:border-emerald-500 hover:shadow-lg hover:-translate-y-0.5 transition-all" data-cat="{cat_group}" data-search="{item['marca'].lower()} {item['modello'].lower()} {item['codice_oem_batteria'].lower()} {item['categoria'].lower()}">
            <div>
                <div class="flex items-center justify-between gap-2 mb-3">
                    <span class="text-[11px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-200/70 px-2.5 py-0.5 rounded-full">{item['marca']}</span>
                    <span class="text-[11px] font-medium text-slate-400">{item['fascia_prezzo_ricambio']}</span>
                </div>
                <h2 class="text-base font-extrabold text-slate-900 group-hover:text-emerald-700 transition leading-snug">{item['modello']}</h2>
                <p class="text-xs text-slate-500 mt-1">{item['categoria']}</p>
            </div>
            <div class="mt-4 pt-3.5 border-t border-slate-100">
                <div class="flex items-center justify-between text-xs mb-2">
                    <span class="text-slate-400 font-medium">Cod. OEM:</span>
                    <span class="font-mono font-bold text-slate-800 bg-slate-100 px-2 py-0.5 rounded">{clean_search_term(item['codice_oem_batteria'])}</span>
                </div>
                <div class="flex items-center justify-between text-xs font-bold text-emerald-600 group-hover:text-emerald-700">
                    <span>Verifica compatibilità</span>
                    <span>&rarr;</span>
                </div>
            </div>
        </a>
        """

    extra_head = f"""<meta name="google-site-verification" content="pBkbOhlZXa5p-vR2Xff77ujhx4NbinX1HerB6K08qRw" />
    <link rel="alternate" type="application/rss+xml" title="{NOME_PORTALE} RSS Feed" href="{DOMINIO_SITO}/feed.xml">"""

    head_html = get_head_assets(
        f"{NOME_PORTALE} - Database Compatibilità Batterie e Ricambi OEM ({today_str})",
        "Verifica subito codice batteria OEM, voltaggio, dimensioni e kit ricambi compatibili per robot aspirapolvere, tagliaerba e scope senza fili.",
        f"{DOMINIO_SITO}/",
        extra_head
    )

    brand_pills = "".join(
        [f'<a href="/marca/{b["slug"]}.html" class="bg-slate-900 hover:bg-emerald-600 text-slate-200 hover:text-white border border-slate-800 px-3 py-1 rounded-full transition">{b["name"]} ({b["count"]})</a>' for b in brands_list[:10]]
    )

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
    {head_html}
</head>
<body class="bg-slate-100/80 text-slate-800 font-sans antialiased selection:bg-emerald-200 selection:text-slate-900">
    {get_navbar(today_str)}

    <section class="bg-slate-950 text-white border-b border-slate-800">
        <div class="max-w-5xl mx-auto px-4 sm:px-6 py-12 sm:py-16 text-center">
            <div class="inline-flex items-center gap-2 bg-emerald-500/10 border border-emerald-500/25 text-emerald-300 text-xs font-bold px-3.5 py-1.5 rounded-full mb-5">
                <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M2.166 4.999A11.954 11.954 0 0010 1.944 11.954 11.954 0 0017.834 5c.11.65.166 1.32.166 2.001 0 5.225-3.34 9.67-8 11.317C5.34 16.67 2 12.225 2 7c0-.682.057-1.35.166-2.001zm11.541 3.708a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/></svg>
                <span>{len(db)} MODELLI VERIFICATI IN ARCHIVIO</span>
            </div>
            <h1 class="text-3xl sm:text-5xl font-extrabold tracking-tight text-white max-w-3xl mx-auto leading-tight">
                Trova il ricambio compatibile al 100% senza errori di codice.
            </h1>
            <p class="text-slate-400 text-base sm:text-lg mt-4 max-w-2xl mx-auto">
                Controlla voltaggio, misure del vano e sigla OEM della batteria per robot aspirapolvere, tagliaerba e scope senza fili.
            </p>

            <div class="max-w-2xl mx-auto mt-8 relative">
                <div class="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                    <svg class="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"/></svg>
                </div>
                <input type="text" id="searchInput" onkeyup="filterModels()" placeholder="Cerca marca, modello o codice OEM (es. Dyson V11, Dreame L10s, ABL-D1, WR141E)..." class="w-full pl-12 pr-5 py-4 rounded-2xl bg-white text-slate-900 font-medium text-sm sm:text-base shadow-xl focus:outline-none focus:ring-4 focus:ring-emerald-500/50">
            </div>

            <div class="flex flex-wrap justify-center gap-2 mt-5 text-xs">
                <span class="text-slate-500 py-1 font-medium">Cataloghi per marca:</span>
                {brand_pills}
            </div>
        </div>
    </section>

    <main class="max-w-5xl mx-auto px-4 sm:px-6 py-8">
        <div class="flex flex-wrap items-center justify-between gap-4 mb-6">
            <div class="flex flex-wrap gap-2" id="catTabs">
                <button type="button" onclick="setCategory('all', this)" class="cat-btn bg-slate-900 text-white text-xs font-bold px-4 py-2 rounded-xl shadow-sm transition">Tutti ({len(db)})</button>
                <button type="button" onclick="setCategory('robot-aspirapolvere', this)" class="cat-btn bg-white text-slate-600 hover:bg-slate-50 border border-slate-200 text-xs font-bold px-4 py-2 rounded-xl transition">Robot Aspirapolvere</button>
                <button type="button" onclick="setCategory('scope-senza-fili', this)" class="cat-btn bg-white text-slate-600 hover:bg-slate-50 border border-slate-200 text-xs font-bold px-4 py-2 rounded-xl transition">Scope Senza Fili</button>
                <button type="button" onclick="setCategory('robot-tagliaerba', this)" class="cat-btn bg-white text-slate-600 hover:bg-slate-50 border border-slate-200 text-xs font-bold px-4 py-2 rounded-xl transition">Robot Tagliaerba</button>
            </div>
            <p id="resultsCounter" class="text-xs font-semibold text-slate-500">Visualizzati: {len(db)} modelli</p>
        </div>

        <div id="modelsGrid" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {cards_html}
        </div>
    </main>

    {get_footer(brands_list)}

    <script>
    let currentCat = 'all';

    function setCategory(cat, btn) {{
        currentCat = cat;
        document.querySelectorAll('.cat-btn').forEach(b => {{
            b.className = 'cat-btn bg-white text-slate-600 hover:bg-slate-50 border border-slate-200 text-xs font-bold px-4 py-2 rounded-xl transition';
        }});
        btn.className = 'cat-btn bg-slate-900 text-white text-xs font-bold px-4 py-2 rounded-xl shadow-sm transition';
        filterModels();
    }}

    function filterModels() {{
        const q = document.getElementById('searchInput').value.toLowerCase().trim();
        const cards = document.querySelectorAll('#modelsGrid .model-card');
        let visible = 0;
        cards.forEach(card => {{
            const text = card.getAttribute('data-search');
            const cat = card.getAttribute('data-cat');
            const matchText = text.includes(q);
            const matchCat = (currentCat === 'all' || cat === currentCat);
            if (matchText && matchCat) {{
                card.style.display = 'flex';
                visible++;
            }} else {{
                card.style.display = 'none';
            }}
        }});
        document.getElementById('resultsCounter').textContent = 'Visualizzati: ' + visible + ' modelli';
    }}
    </script>
</body>
</html>"""


def ping_indexnow(url_list):
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
    os.makedirs(os.path.join(OUTPUT_DIR, "guida"), exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, "marca"), exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, "categoria"), exist_ok=True)

    today_str = datetime.now().strftime("%d/%m/%Y")
    today_iso = datetime.now().strftime("%Y-%m-%d")
    rss_date = datetime.now().strftime("%a, %d %b %Y 03:00:00 +0000")

    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)

    brands_map = {}
    cats_map = {k: [] for k in CATEGORIES_META.keys()}

    for item in db:
        b_name = item["marca"]
        b_slug = slugify(b_name)
        if b_slug not in brands_map:
            brands_map[b_slug] = {"name": b_name, "slug": b_slug, "items": []}
        brands_map[b_slug]["items"].append(item)

        c_slug = get_cat_group(item["categoria"])
        cats_map[c_slug].append(item)

    brands_list = sorted(
        [{"name": v["name"], "slug": v["slug"], "count": len(v["items"])} for v in brands_map.values()],
        key=lambda x: x["count"],
        reverse=True
    )

    ai_calls = 0
    db_modified = False

    for item in db:
        needs_ai = (not item.get("ai_enriched", False)) or (not item.get("guida_passi_ai"))
        if needs_ai and ai_calls < MAX_AI_CALLS_PER_RUN:
            ai_res = call_gemini_ai(item)
            if (
                ai_res
                and "nota_tecnica" in ai_res
                and "faq" in ai_res
                and "guida_passi" in ai_res
                and len(ai_res["guida_passi"]) >= 3
            ):
                item["nota_tecnica_ai"] = ai_res["nota_tecnica"]
                item["sintomo_guasto_ai"] = ai_res.get(
                    "sintomo_guasto",
                    f"Calo di autonomia o errore di funzionamento su {item['marca']} {item['modello']}."
                )
                item["faq_ai"] = ai_res["faq"]
                item["guida_passi_ai"] = ai_res["guida_passi"]
                item["ai_enriched"] = True
                ai_calls += 1
                db_modified = True
            else:
                fb = get_fallback_content(item)
                if not item.get("nota_tecnica_ai"):
                    item["nota_tecnica_ai"] = fb["nota_tecnica"]
                if not item.get("sintomo_guasto_ai"):
                    item["sintomo_guasto_ai"] = fb["sintomo_guasto"]
                if not item.get("faq_ai"):
                    item["faq_ai"] = fb["faq"]
                if not item.get("guida_passi_ai"):
                    item["guida_passi_ai"] = fb["guida_passi"]
        else:
            fb = get_fallback_content(item)
            if not item.get("nota_tecnica_ai"):
                item["nota_tecnica_ai"] = fb["nota_tecnica"]
            if not item.get("sintomo_guasto_ai"):
                item["sintomo_guasto_ai"] = fb["sintomo_guasto"]
            if not item.get("faq_ai"):
                item["faq_ai"] = fb["faq"]
            if not item.get("guida_passi_ai"):
                item["guida_passi_ai"] = fb["guida_passi"]

        page_html = generate_model_page(item, db, brands_list, today_str)
        with open(os.path.join(OUTPUT_DIR, "modello", f"{item['id']}.html"), "w", encoding="utf-8") as out:
            out.write(page_html)

        guide_html = generate_guide_page(item, db, brands_list, today_str)
        with open(os.path.join(OUTPUT_DIR, "guida", f"sostituzione-batteria-{item['id']}.html"), "w", encoding="utf-8") as out:
            out.write(guide_html)

    if db_modified:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)

    for b_slug, b_data in brands_map.items():
        brand_html = generate_brand_page(b_data, b_data["items"], brands_list, today_str)
        with open(os.path.join(OUTPUT_DIR, "marca", f"{b_slug}.html"), "w", encoding="utf-8") as out:
            out.write(brand_html)

    for c_slug, c_meta in CATEGORIES_META.items():
        cat_html = generate_category_page(c_slug, c_meta, cats_map[c_slug], brands_list, today_str)
        with open(os.path.join(OUTPUT_DIR, "categoria", f"{c_slug}.html"), "w", encoding="utf-8") as out:
            out.write(cat_html)

    index_html = generate_index_page(db, brands_list, today_str)
    with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as out:
        out.write(index_html)

    all_urls = [f"{DOMINIO_SITO}/"]
    urls_xml = [f"<url><loc>{DOMINIO_SITO}/</loc><lastmod>{today_iso}</lastmod><priority>1.0</priority></url>"]
    rss_items = []

    for c_slug in CATEGORIES_META.keys():
        c_url = f"{DOMINIO_SITO}/categoria/{c_slug}.html"
        all_urls.append(c_url)
        urls_xml.append(f"<url><loc>{c_url}</loc><lastmod>{today_iso}</lastmod><priority>0.9</priority></url>")

    for b in brands_list:
        b_url = f"{DOMINIO_SITO}/marca/{b['slug']}.html"
        all_urls.append(b_url)
        urls_xml.append(f"<url><loc>{b_url}</loc><lastmod>{today_iso}</lastmod><priority>0.85</priority></url>")

    for item in db:
        page_url = f"{DOMINIO_SITO}/modello/{item['id']}.html"
        guide_url = f"{DOMINIO_SITO}/guida/sostituzione-batteria-{item['id']}.html"
        all_urls.extend([page_url, guide_url])
        urls_xml.append(f"<url><loc>{page_url}</loc><lastmod>{today_iso}</lastmod><priority>0.8</priority></url>")
        urls_xml.append(f"<url><loc>{guide_url}</loc><lastmod>{today_iso}</lastmod><priority>0.75</priority></url>")

        safe_title = html.escape(f"Ricambi e Batteria {item['marca']} {item['modello']} ({item['codice_oem_batteria']})")
        safe_desc = html.escape(f"Specifiche verificate: {item['specifiche_batteria']}, misure {item['dimensioni_mm']}. Consumabili: {item['consumabili_inclusi']}.")
        rss_items.append(f"<item><title>{safe_title}</title><link>{page_url}</link><guid>{page_url}</guid><pubDate>{rss_date}</pubDate><description>{safe_desc}</description></item>")

    sitemap_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{"".join(urls_xml)}
</urlset>"""
    with open(os.path.join(OUTPUT_DIR, "sitemap.xml"), "w", encoding="utf-8") as out:
        out.write(sitemap_xml)

    feed_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>{html.escape(NOME_PORTALE)}</title>
<link>{DOMINIO_SITO}/</link>
<description>Aggiornamenti tecnici e compatibilità ricambi robot e aspirapolvere.</description>
{"".join(rss_items)}
</channel>
</rss>"""
    with open(os.path.join(OUTPUT_DIR, "feed.xml"), "w", encoding="utf-8") as out:
        out.write(feed_xml)

    robots_txt = f"User-agent: *\nAllow: /\nSitemap: {DOMINIO_SITO}/sitemap.xml\n"
    with open(os.path.join(OUTPUT_DIR, "robots.txt"), "w", encoding="utf-8") as out:
        out.write(robots_txt)

    with open(os.path.join(OUTPUT_DIR, f"{INDEXNOW_KEY}.txt"), "w", encoding="utf-8") as out:
        out.write(INDEXNOW_KEY)

    ping_indexnow(all_urls)

    print(f"Portale generato con successo: {len(all_urls)} pagine totali indicizzabili.")


if __name__ == "__main__":
    main()
