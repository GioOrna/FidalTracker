import ast
import requests
import pytz
from datetime import datetime, date
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import pandas as pd
import uvicorn
import time
from io import StringIO
from dateutil import parser

app = FastAPI()

def get_url():
    # This code runs the moment you call get_url()
    return f"https://raw.githubusercontent.com/GioOrna/FidalTracker/refs/heads/main/fidal_meets_data.csv?t={int(time.time())}"

def safe_eval(x):
    try:
        return ast.literal_eval(x)
    except:
        return x

def get_last_update():
    try:
        api_url = "https://api.github.com/repos/GioOrna/FidalTracker/commits?path=fidal_meets_data.csv&per_page=1"
        response = requests.get(api_url, timeout=10, headers={"Accept": "application/vnd.github+json"})
        if response.status_code == 200:
            data = response.json()
            if data:
                commit_date_str = data[0]['commit']['committer']['date']
                utctime = datetime.strptime(commit_date_str, '%Y-%m-%dT%H:%M:%SZ')
                utctime = utctime.replace(tzinfo=pytz.utc)
                italy_tz = pytz.timezone("Europe/Rome")
                local_time = utctime.astimezone(italy_tz)
                return local_time.strftime("%d/%m/%Y %H:%M")
    except Exception as e:
        print(f"DEBUG: get_last_update failed. Error: {e}")

    return "N/A"

def load_data():
    response = requests.get(get_url(), timeout=20)
    if not response.status_code == 200:
        return pd.DataFrame()
    df = pd.read_csv(StringIO(response.text))
    df["Data Inizio"] = pd.to_datetime(df["Data Inizio"], format="%d/%m/%Y", errors="coerce")
    df["Data Fine"] = pd.to_datetime(df["Data Fine"], format="%d/%m/%Y", errors="coerce")
    df["Categorie"] = df["Categorie"].apply(safe_eval)
    df = df.sort_values(by="Data Inizio", na_position="last")
    return df

_df_cache = None
_cache_mtime = None

def get_df():
    global _df_cache, _cache_mtime
    updated = False
    
    response = requests.head(get_url(), timeout=5)
    if not response.status_code == 200: #if file doesn't exist
        _df_cache = pd.DataFrame()
        _cache_mtime = None
        return _df_cache, updated

    current_mtime = response.headers.get('Last-Modified')
    
    if _df_cache is None or _cache_mtime is None or current_mtime != _cache_mtime:
        print(f"Reloading data... (file modified)")
        _df_cache = load_data()
        _cache_mtime = current_mtime
        updated = True
    
    return _df_cache, updated

@app.on_event("startup")
def startup():
    get_df()

@app.get("/api/filters")
def get_filters():
    df = get_df()[0]
    if df.empty:
        return {}
    anni = sorted(df["Data Inizio"].dropna().dt.year.unique().tolist(), reverse=True)
    regioni = sorted(df["Regione"].dropna().unique().tolist())
    categorie = sorted(df["Categorie"].explode().dropna().unique().tolist())
    livelli = df["Livello"].dropna().unique().tolist()
    tipi = sorted(df["Tipo"].dropna().unique().tolist())
    today = date.today()
    return {
        "anni": [int(a) for a in anni],
        "regioni": regioni,
        "categorie": categorie,
        "livelli": livelli,
        "tipi": tipi,
        "currentYear": today.year,
        "currentMonth": today.month,
        "lastUpdate": get_last_update(),
    }

@app.get("/api/data")
def get_data(
    anni: str = "",
    mesi: str = "",
    regioni: str = "",
    categorie: str = "",
    livelli: str = "",
    tipi: str = "",
    logic: str = "OR",
    sort: str = "data_asc",
    page: int = 0,
    page_size: int = 100,
):
    res = get_df()
    df = res[0]
    updated = res[1]
    if df.empty:
        return JSONResponse({"total": 0, "page": 0, "results": []})

    if anni:
        anni_list = [int(a) for a in anni.split(",") if a]
        df = df[df["Data Inizio"].dt.year.isin(anni_list)]
    if mesi:
        mesi_list = [int(m) for m in mesi.split(",") if m]
        df = df[df["Data Inizio"].dt.month.isin(mesi_list)]
    if regioni:
        reg_list = regioni.split(",")
        df = df[df["Regione"].isin(reg_list)]
    if categorie:
        cat_list = categorie.split(",")
        if logic == "AND":
            df = df[df["Categorie"].apply(
                lambda lst: all(c in lst for c in cat_list) if isinstance(lst, list) else False
            )]
        else:
            df = df[df["Categorie"].apply(
                lambda lst: any(c in lst for c in cat_list) if isinstance(lst, list) else False
            )]
    if livelli:
        liv_list = livelli.split(",")
        df = df[df["Livello"].isin(liv_list)]
    if tipi:
        tipo_list = tipi.split(",")
        df = df[df["Tipo"].isin(tipo_list)]

    ascending = sort != "data_desc"
    df = df.sort_values(by="Data Inizio", ascending=ascending, na_position="last")

    total = len(df)
    cols = ["Data Inizio", "Data Fine", "Link", "Località", "Livello", "Categorie", "Regione", "Tipo"]
    df = df[[c for c in cols if c in df.columns]].copy()
    df["Data Inizio"] = df["Data Inizio"].dt.strftime("%d/%m/%Y").fillna("")
    df["Data Fine"] = df["Data Fine"].dt.strftime("%d/%m/%Y").fillna("")
    df["Categorie"] = df["Categorie"].apply(lambda x: ", ".join(x) if isinstance(x, list) else str(x))
    page_df = df.iloc[page * page_size : (page + 1) * page_size]
    return JSONResponse({"total": total, "page": page, "results": page_df.fillna("").to_dict(orient="records"), "updated": updated})

HTML = r"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>FidalTracker</title>
<style>
  :root {
    --bg: #0f1117; --surface: #1a1d27; --surface2: #22263a;
    --accent: #3b82f6; --accent2: #60a5fa;
    --text: #e2e8f0; --muted: #64748b; --border: #2d3550;
    --radius: 10px; --sidebar: 280px;
    --tag-bg: #1e3a5f; --tag-text: #93c5fd;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

  .site-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem 2rem;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    top: 0;
    z-index: 100;
  }

  .header-right {
    display: flex;
    gap: 1rem;
    align-items: center;
  }

  .header-link {
    color: var(--text-primary, #fff);
    text-decoration: none;
    font-size: 0.9rem;
    font-weight: 500;
    padding: 0.5rem 1rem;
    border-radius: 6px;
    transition: all 0.2s ease;
    background: transparent;
    border: 1px solid transparent;
  }

  .header-link:hover {
    background: rgba(255, 255, 255, 0.1);
    border-color: var(--border);
  }

  /* Hide link if there's not enough space */
  @media (max-width: 370px) {
    .header-link {
      display: none;
    }
  }

  .header-left { font-size: 1.15rem; font-weight: 700; color: var(--accent2); }
  #last-update { font-size: 0.7rem; color: var(--muted); margin-top: 2px; }

  #layout { display: flex; flex: 1; overflow: hidden; min-height: 0; }

  /* SIDEBAR - independent scrolling */
  #sidebar { 
    width: var(--sidebar); 
    background: var(--surface); 
    border-right: 1px solid var(--border); 
    overflow-y: auto; 
    overflow-x: hidden;
    flex-shrink: 0; 
    display: flex; 
    flex-direction: column; 
    height: 100%;
  }
  
  #sidebar-content {
    padding: 16px 14px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  
  #sidebar h2 { 
    font-size: 0.7rem; 
    font-weight: 700; 
    color: var(--muted); 
    text-transform: uppercase; 
    letter-spacing: 0.08em; 
    margin-bottom: 4px;
  }

  .filter-group { display: flex; flex-direction: column; gap: 6px; }
  .filter-group > span { font-size: 0.72rem; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; }

  /* MULTISELECT */
  .ms-wrap { position: relative; }
  .ms-trigger { width: 100%; background: var(--surface2); border: 1px solid var(--border); border-radius: 7px; padding: 7px 10px; font-size: 0.8rem; color: var(--text); cursor: pointer; display: flex; justify-content: space-between; align-items: center; gap: 6px; text-align: left; min-height: 34px; }
  .ms-trigger:hover { border-color: var(--accent); }
  .ms-trigger .arrow { font-size: 0.6rem; color: var(--muted); flex-shrink: 0; transition: transform 0.15s; }
  .ms-trigger.open .arrow { transform: rotate(180deg); }
  .ms-trigger .label-text { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ms-dropdown { position: absolute; top: calc(100% + 4px); left: 0; right: 0; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; z-index: 500; max-height: 220px; overflow-y: auto; box-shadow: 0 8px 24px rgba(0,0,0,0.4); }
  .ms-dropdown.hidden { display: none; }
  .ms-option { padding: 8px 10px; font-size: 0.8rem; cursor: pointer; display: flex; align-items: center; gap: 8px; transition: background 0.1s; }
  .ms-option:hover { background: var(--surface2); }
  .ms-option.selected { color: var(--accent2); }
  .ms-option .chk { width: 14px; height: 14px; border: 1px solid var(--border); border-radius: 3px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; font-size: 0.6rem; }
  .ms-option.selected .chk { background: var(--accent); border-color: var(--accent); color: #fff; }

  /* LOGIC TOGGLE */
  .logic-row { display: flex; gap: 6px; }
  .logic-btn { flex: 1; background: var(--surface2); border: 1px solid var(--border); border-radius: 6px; padding: 6px 4px; font-size: 0.72rem; cursor: pointer; color: var(--muted); transition: all 0.15s; }
  .logic-btn.active { background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 600; }

  #apply-btn { width: 100%; background: var(--accent); color: #fff; border: none; border-radius: var(--radius); padding: 10px; font-size: 0.85rem; font-weight: 700; cursor: pointer; margin-top: 4px; }
  #apply-btn:hover { background: var(--accent2); }
  #reset-btn { width: 100%; background: transparent; color: var(--muted); border: 1px solid var(--border); border-radius: var(--radius); padding: 7px; font-size: 0.78rem; cursor: pointer; margin-bottom: 8px; }
  #reset-btn:hover { color: var(--text); border-color: var(--muted); }

  /* MAIN CONTENT - independent scrolling */
  #main { 
    flex: 1; 
    display: flex; 
    flex-direction: column; 
    overflow: hidden;
    min-width: 0;
  }
  
  #stats-bar { 
    padding: 9px 16px; 
    font-size: 0.75rem; 
    color: var(--muted); 
    background: var(--surface); 
    border-bottom: 1px solid var(--border); 
    flex-shrink: 0; 
    display: flex; 
    align-items: center; 
    justify-content: space-between; 
    gap: 8px; 
  }
  
  #sort-bar { display: flex; align-items: center; gap: 5px; }
  .sort-label { font-size: 0.7rem; color: var(--muted); }
  .sort-btn { background: var(--surface2); border: 1px solid var(--border); border-radius: 6px; padding: 3px 9px; font-size: 0.72rem; color: var(--muted); cursor: pointer; transition: all 0.15s; }
  .sort-btn:hover { color: var(--text); border-color: var(--muted); }
  .sort-btn.active { background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 600; }
  #result-count { font-weight: 700; color: var(--accent2); }
  
  /* Cards container - scrollable independently */
  #cards-container {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 12px;
  }
  
  #cards {
    display: flex;
    flex-direction: column;
    gap: 9px;
  }

  .card { 
    background: var(--surface); 
    border: 1px solid var(--border); 
    border-radius: var(--radius); 
    padding: 13px; 
    transition: border-color 0.15s; 
  }
  .card:hover { border-color: #3d4f6e; }
  .card-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; margin-bottom: 7px; }
  .card-name { font-size: 0.88rem; font-weight: 600; flex: 1; line-height: 1.35; }
  .card-name a { color: var(--text); text-decoration: none; }
  .card-name a:hover { color: var(--accent2); }
  .badge { font-size: 0.67rem; font-weight: 700; padding: 3px 8px; border-radius: 20px; white-space: nowrap; flex-shrink: 0; }
  .badge-P { background:#1e3a5f; color:#93c5fd; } .badge-R { background:#1a3a2a; color:#6ee7b7; }
  .badge-N { background:#3a2a1a; color:#fbbf24; } .badge-I { background:#3a1a2a; color:#f9a8d4; }
  .badge-G { background:#3a3010; color:#fde68a; } .badge-S { background:#2a2a2a; color:#d1d5db; }
  .badge-B { background:#2a1a10; color:#fdba74; } .badge-DEF { background:var(--surface2); color:var(--muted); }
  .card-meta { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; font-size: 0.73rem; color: var(--muted); }
  .sep { color: var(--border); }
  .tag { background: var(--tag-bg); color: var(--tag-text); border-radius: 4px; padding: 2px 6px; font-size: 0.68rem; }

  #empty { text-align: center; padding: 60px 20px; color: var(--muted); }
  #loading { text-align: center; padding: 40px; color: var(--muted); }
  .spinner { width: 28px; height: 28px; border: 3px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.7s linear infinite; margin: 0 auto 10px; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Custom scrollbar styling */
  #sidebar::-webkit-scrollbar,
  #cards-container::-webkit-scrollbar {
    width: 8px;
  }
  
  #sidebar::-webkit-scrollbar-track,
  #cards-container::-webkit-scrollbar-track {
    background: var(--surface);
  }
  
  #sidebar::-webkit-scrollbar-thumb,
  #cards-container::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: 4px;
  }
  
  #sidebar::-webkit-scrollbar-thumb:hover,
  #cards-container::-webkit-scrollbar-thumb:hover {
    background: var(--muted);
  }

  /* MOBILE: sidebar becomes bottom sheet */
  #mob-filter-btn { display: none; }
  @media (max-width: 640px) {
    body { height: auto; overflow: auto; }
    #layout { flex-direction: column; overflow: visible; }
    #sidebar { 
      display: none; 
      width: 100%; 
      height: auto;
      border-right: none; 
      border-top: 1px solid var(--border); 
      position: fixed; 
      bottom: 0; 
      left: 0; 
      right: 0; 
      z-index: 300; 
      max-height: 85vh; 
      border-radius: 18px 18px 0 0; 
      transform: translateY(100%); 
      transition: transform 0.3s ease; 
    }
    #sidebar.mob-open { transform: translateY(0); display: flex; }
    #mob-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 299; }
    #mob-overlay.open { display: block; }
    #mob-filter-btn { 
      display: flex; 
      align-items: center; 
      gap: 6px; 
      position: fixed; 
      bottom: 20px; 
      right: 20px; 
      z-index: 298; 
      background: var(--accent); 
      color: #fff; 
      border: none; 
      border-radius: 50px; 
      padding: 11px 18px; 
      font-size: 0.85rem; 
      font-weight: 700; 
      cursor: pointer; 
      box-shadow: 0 4px 16px rgba(59,130,246,0.4); 
    }
    #main { height: auto; }
    #cards-container { padding-bottom: 80px; }
  }
</style>
</head>
<body>

<header class="site-header">
  <div class="header-left">
    <h1>FidalTracker</h1>
    <div id="last-update">Caricamento…</div>
  </div>
  <div class="header-right">
    <a href="https://docs.google.com/forms/d/e/1FAIpQLScxYm4VHJun_DYzTH_XszFf92WKAs35j4wMJT_nF-tMMmqPYA/viewform?usp=dialog" class="header-link">Hai trovato un bug o hai un suggerimento?</a>
  </div>
</header>

<div id="layout">
  <!-- SIDEBAR with independent scrolling -->
  <div id="sidebar">
    <div id="sidebar-content">
      <h2>Filtri</h2>

      <div class="filter-group">
        <span>Anno</span>
        <div class="ms-wrap" id="wrap-anno"><button class="ms-trigger" onclick="toggleDD('anno')"><span class="label-text" id="lbl-anno">Tutti</span><span class="arrow">▼</span></button><div class="ms-dropdown hidden" id="dd-anno"></div></div>
      </div>
      <div class="filter-group">
        <span>Mese</span>
        <div class="ms-wrap" id="wrap-mese"><button class="ms-trigger" onclick="toggleDD('mese')"><span class="label-text" id="lbl-mese">Tutti</span><span class="arrow">▼</span></button><div class="ms-dropdown hidden" id="dd-mese"></div></div>
      </div>
      <div class="filter-group">
        <span>Regione</span>
        <div class="ms-wrap" id="wrap-regione"><button class="ms-trigger" onclick="toggleDD('regione')"><span class="label-text" id="lbl-regione">Tutte</span><span class="arrow">▼</span></button><div class="ms-dropdown hidden" id="dd-regione"></div></div>
      </div>
      <div class="filter-group">
        <span>Categorie</span>
        <div class="ms-wrap" id="wrap-cat"><button class="ms-trigger" onclick="toggleDD('cat')"><span class="label-text" id="lbl-cat">Tutte</span><span class="arrow">▼</span></button><div class="ms-dropdown hidden" id="dd-cat"></div></div>
        <div class="logic-row" style="margin-top:4px;">
          <button class="logic-btn active" id="btn-or" onclick="setLogic('OR')">Almeno una</button>
          <button class="logic-btn" id="btn-and" onclick="setLogic('AND')">Tutte (AND)</button>
        </div>
      </div>
      <div class="filter-group">
        <span>Livello</span>
        <div class="ms-wrap" id="wrap-liv"><button class="ms-trigger" onclick="toggleDD('liv')"><span class="label-text" id="lbl-liv">Tutti</span><span class="arrow">▼</span></button><div class="ms-dropdown hidden" id="dd-liv"></div></div>
      </div>
      <div class="filter-group">
        <span>Tipo</span>
        <div class="ms-wrap" id="wrap-tipo"><button class="ms-trigger" onclick="toggleDD('tipo')"><span class="label-text" id="lbl-tipo">Tutti</span><span class="arrow">▼</span></button><div class="ms-dropdown hidden" id="dd-tipo"></div></div>
      </div>

      <button id="apply-btn" onclick="applyFilters()">Applica filtri</button>
      <button id="reset-btn" onclick="resetFilters()">Reimposta</button>
    </div>
  </div>

  <!-- MAIN with independent scrolling -->
  <div id="main">
    <div id="stats-bar">
      <span>Gare trovate: <span id="result-count">—</span></span>
      <div id="sort-bar">
        <span class="sort-label">Ordina:</span>
        <button class="sort-btn active" id="sort-data_asc" onclick="setSort('data_asc')">Data ↑</button>
        <button class="sort-btn" id="sort-data_desc" onclick="setSort('data_desc')">Data ↓</button>
      </div>
    </div>
    <div id="cards-container">
      <div id="cards"><div id="loading"><div class="spinner"></div>Caricamento dati…</div></div>
    </div>
  </div>
</div>

<!-- MOBILE overlay + button -->
<div id="mob-overlay" onclick="closeMob()"></div>
<button id="mob-filter-btn" onclick="openMob()">
  <svg width="14" height="14" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM3 10a1 1 0 011-1h6a1 1 0 110 2H4a1 1 0 01-1-1zM3 15a1 1 0 011-1h4a1 1 0 110 2H4a1 1 0 01-1-1z" clip-rule="evenodd"/></svg>
  Filtri
</button>

<script>
const MESI = {1:"Gen",2:"Feb",3:"Mar",4:"Apr",5:"Mag",6:"Giu",7:"Lug",8:"Ago",9:"Set",10:"Ott",11:"Nov",12:"Dic"};
const CAT  = {ESO:"Esordienti",RAG:"Ragazzi",CAD:"Cadetti",ALL:"Allievi",JUN:"Juniores",PRO:"Promesse",SEN:"Seniores",MAS:"Master"};
const LIV  = {P:"Provinciale",R:"Regionale",N:"Nazionale",I:"Internazionale",G:"Gold",S:"Silver",B:"Bronze"};
const TIPO = {CROSS:"Cross",INDOOR:"Indoor","MARCIA SU STRADA":"Marcia su strada",MONTAGNA:"Montagna","MONTAGNA/TRAIL":"Montagna/Trail","NORDIC WALKING":"Nordic walking",OUTDOOR:"Outdoor","PIAZZA e altri ambiti":"Piazza/altri",STRADA:"Strada",TRAIL:"Trail",ULTRAMARATONA:"Ultramaratona","ULTRAMARATONA/TRAIL":"Ultra/Trail"};

let sel = {anno:[],mese:[],regione:[],cat:[],liv:[],tipo:[],logic:"OR",sort:"data_asc"};
let filtersData = {};
function buildDD(id, items, selKey, labelMap, defaultLabel) {
  const dd = document.getElementById("dd-" + id);
  dd.innerHTML = "";
  items.forEach(v => {
    const sv = String(v);
    const label = (labelMap && labelMap[v]) ? labelMap[v] : sv;
    const div = document.createElement("div");
    div.className = "ms-option" + (sel[selKey].includes(sv) ? " selected" : "");
    div.innerHTML = `<span class="chk">${sel[selKey].includes(sv) ? "✓" : ""}</span>${label}`;
    div.onclick = () => toggleOption(selKey, sv, id, items, labelMap, defaultLabel);
    dd.appendChild(div);
  });
  updateLabel(id, selKey, labelMap, defaultLabel);
}

function toggleOption(selKey, val, ddId, items, labelMap, defaultLabel) {
  const idx = sel[selKey].indexOf(val);
  if (idx === -1) sel[selKey].push(val); else sel[selKey].splice(idx, 1);
  buildDD(ddId, items, selKey, labelMap, defaultLabel);
}

function updateLabel(id, selKey, labelMap, defaultLabel) {
  const lbl = document.getElementById("lbl-" + id);
  const s = sel[selKey];
  if (!s.length) { lbl.textContent = defaultLabel; return; }
  const names = s.map(v => (labelMap && labelMap[v]) ? labelMap[v] : v);
  lbl.textContent = names.length <= 2 ? names.join(", ") : names[0] + " +" + (names.length - 1);
}

let openDD = null;
function toggleDD(id) {
  const dd = document.getElementById("dd-" + id);
  const btn = dd.previousElementSibling;
  const isHidden = dd.classList.contains("hidden");
  if (openDD && openDD !== id) {
    document.getElementById("dd-" + openDD).classList.add("hidden");
    document.getElementById("dd-" + openDD).previousElementSibling.classList.remove("open");
  }
  dd.classList.toggle("hidden", !isHidden);
  btn.classList.toggle("open", isHidden);
  openDD = isHidden ? id : null;
}

function setLogic(l) {
  sel.logic = l;
  document.getElementById("btn-or").classList.toggle("active", l === "OR");
  document.getElementById("btn-and").classList.toggle("active", l === "AND");
}

function applyFilters() { closeMob(); fetchData(true);}

function resetFilters() {
  const yr = filtersData.currentYear;
  const mo = filtersData.currentMonth;
  
  // Check if current year exists in available anni
  let defaultYear = [];
  if (yr && filtersData.anni && filtersData.anni.includes(yr)) {
    defaultYear = [String(yr)];
  } else if (filtersData.anni && filtersData.anni.length > 0) {
    // If current year not available don't set anything
    defaultYear = [];
  }
  
  // Check if current month exists (months 1-12 always exist, but just in case)
  let defaultMonth = [];
  if (mo && mo >= 1 && mo <= 12) {
    defaultMonth = [String(mo)];
  }
  
  sel = {
    anno: defaultYear, 
    mese: defaultMonth, 
    regione:[], 
    cat:[], 
    liv:[], 
    tipo:[], 
    logic:"OR", 
    sort:"data_asc"
  };
  rebuildAll();
  fetchData(true);
}

function rebuildAll() {
  buildDD("anno",    filtersData.anni    || [], "anno",    null,  "Tutti");
  buildDD("mese",    [1,2,3,4,5,6,7,8,9,10,11,12], "mese", MESI, "Tutti");
  buildDD("regione", filtersData.regioni || [], "regione", null,  "Tutte");
  buildDD("cat",     filtersData.categorie || [], "cat",   CAT,   "Tutte");
  buildDD("liv",     filtersData.livelli  || [], "liv",    LIV,   "Tutti");
  buildDD("tipo",    filtersData.tipi     || [], "tipo",   TIPO,  "Tutti");
}

function openMob()  { document.getElementById("sidebar").classList.add("mob-open"); document.getElementById("mob-overlay").classList.add("open"); document.body.style.overflow="hidden"; }
function closeMob() { document.getElementById("sidebar").classList.remove("mob-open"); document.getElementById("mob-overlay").classList.remove("open"); document.body.style.overflow=""; }

function extractRaceName(url) {
  if (!url) return "—";
  const m = url.match(/calendario\/(.+?)\/[^/]+\/?$/);
  if (m) return decodeURIComponent(m[1]).replace(/-/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  return url;
}

let currentPage = 0;
let currentTotal = 0;

function makeCardHtml(r) {
  const name = extractRaceName(r["Link"]);
  const cats = r["Categorie"] ? r["Categorie"].split(", ").map(c => `<span class="tag">${CAT[c]||c}</span>`).join("") : "";
  const dateStr = r["Data Inizio"] + (r["Data Fine"] && r["Data Fine"] !== r["Data Inizio"] ? " \u2192 " + r["Data Fine"] : "");
  const tipo = TIPO[r["Tipo"]] || r["Tipo"] || "";
  const liv = r["Livello"] || "";
  const badgeCls = "badge badge-" + (LIV[liv] ? liv : "DEF");
  const link = r["Link"] ? `href="${r['Link']}" target="_blank" rel="noopener"` : "";
  return `<div class="card">
    <div class="card-header">
      <div class="card-name"><a ${link}>${name}</a></div>
      <span class="${badgeCls}">${LIV[liv]||liv||'—'}</span>
    </div>
    <div class="card-meta">
      <span>\ud83d\udcc5 ${dateStr}</span>
      ${r['Localit\u00e0'] ? `<span class="sep">\u00b7</span><span>\ud83d\udccd ${r['Localit\u00e0']}</span>` : ''}
      ${r['Regione'] ? `<span class="sep">\u00b7</span><span>${r['Regione']}</span>` : ''}
      ${tipo ? `<span class="sep">\u00b7</span><span>${tipo}</span>` : ''}
    </div>
    ${cats ? `<div style="margin-top:7px;display:flex;flex-wrap:wrap;gap:4px;">${cats}</div>` : ''}
  </div>`;
}

function renderCards(rows, total, append) {
  const cardsContainer = document.getElementById("cards");
  const cardsWrapper = document.getElementById("cards");
  currentTotal = total;
  document.getElementById("result-count").textContent = total;
  if (!rows.length && !append) {
    cardsWrapper.innerHTML = `<div id="empty"><p style="font-size:2rem">\ud83d\udd0d</p><p style="margin-top:8px">Nessuna gara trovata.<br>Modifica i filtri.</p></div>`;
    return;
  }
  const html = rows.map(makeCardHtml).join("");
  if (append) {
    document.getElementById("load-more-wrap")?.remove();
    cardsWrapper.insertAdjacentHTML("beforeend", html);
  } else {
    cardsWrapper.innerHTML = html;
  }
  const loaded = cardsWrapper.querySelectorAll(".card").length;
  if (loaded < total) {
    cardsWrapper.insertAdjacentHTML("beforeend", `<div id="load-more-wrap" style="text-align:center;padding:16px 0 8px"><button onclick="loadMore()" style="background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);color:var(--accent2);padding:10px 24px;font-size:0.85rem;cursor:pointer;">Carica altri (${loaded}/${total})</button></div>`);
  }
}

function setSort(s) {
  sel.sort = s;
  document.querySelectorAll(".sort-btn").forEach(b => b.classList.toggle("active", b.id === "sort-" + s));
  fetchData(true);
}

async function fetchData(resetPage = true) {
  if (resetPage) {
    currentPage = 0;
    document.getElementById("cards").innerHTML = '<div id="loading"><div class="spinner"></div>Caricamento…</div>';
  }
  const p = new URLSearchParams({ 
    anni:sel.anno.join(","), 
    mesi:sel.mese.join(","), 
    regioni:sel.regione.join(","), 
    categorie:sel.cat.join(","), 
    livelli:sel.liv.join(","), 
    tipi:sel.tipo.join(","), 
    logic:sel.logic, 
    sort:sel.sort, 
    page:resetPage ? 0 : currentPage, 
    page_size:100 
  });
  const data = await (await fetch("/api/data?" + p)).json();
  if (resetPage) {
    renderCards(data.results, data.total, false);
  } else {
    renderCards(data.results, data.total, true);
  }
  if (data.updated){
    filtersData = await (await fetch("/api/filters")).json();
    rebuildAll();
    element = document.getElementById("last-update");
      element.textContent = "📊 Nuovi dati trovati!";
      element.style.background = "linear-gradient(135deg, #f093fb 0%, #f5576c 100%)";
      element.style.color = "white";
      element.style.borderRadius = "50px";
      element.style.fontSize = "0.9rem";
      element.style.fontWeight = "bold";
      element.style.fontFamily = "inherit";
      element.style.boxShadow = "0 4px 15px rgba(245, 87, 108, 0.4)";
      element.style.cursor = "pointer";
      element.style.transition = "all 0.3s ease";
      element.style.animation = "pop 0.5s ease-in-out";
      // Auto fade out after 2 seconds
      setTimeout(() => {
          element.style.transition = "opacity 0.5s ease";
          element.style.opacity = "0";
          
          // Remove all styles and reset after fade out completes
          setTimeout(() => {
              element.style.opacity = "";
              element.style.background = "";
              element.style.color = "";
              element.style.borderRadius = "";
              element.style.fontSize = "";
              element.style.fontWeight = "";
              element.style.fontFamily = "";
              element.style.boxShadow = "";
              element.style.cursor = "";
              element.style.animation = "";
              element.textContent = "Dati aggiornati al: " + (filtersData.lastUpdate || "N/A");
          }, 500); // Wait for fade out to complete
      }, 2000); // Show for 2 seconds
  }
}

async function loadMore() {
  currentPage++;
  await fetchData(false);
}

async function init() {
  filtersData = await (await fetch("/api/filters")).json();
  document.getElementById("last-update").textContent = "Dati aggiornati al: " + (filtersData.lastUpdate || "N/A");
  const yr = filtersData.currentYear, mo = filtersData.currentMonth;
  if (yr && filtersData.anni && filtersData.anni.includes(yr)) sel.anno = [String(yr)];
  if (mo) sel.mese = [String(mo)];
  rebuildAll();
  fetchData(true);
}

document.querySelectorAll('.ms-dropdown').forEach(dropdown => {
  const trigger = dropdown.previousElementSibling;
  const sidebar = document.querySelector('#sidebar');
  
  function setDropdownPosition() {
    const side = sidebar.getBoundingClientRect();
    const rect = trigger.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    const spaceAbove = rect.top - side.top;
    const dropdownHeight = 220;
    
    // Try bottom first, then top, then whichever has more space
    if (spaceBelow >= dropdownHeight) {
      // Opens downward
      dropdown.style.top = 'calc(100% + 4px)';
      dropdown.style.bottom = 'auto';
    } else if (spaceAbove >= dropdownHeight) {
      // Opens upward
      dropdown.style.top = 'auto';
      dropdown.style.bottom = 'calc(100% + 4px)';
    } else {
      // Opens upward
      dropdown.style.top = 'auto';
      dropdown.style.bottom = 'calc(100% + 4px)';
    }
  }
  
  // Attach events
  trigger.addEventListener('click', (e) => {
    e.stopPropagation();
    setDropdownPosition();
    // Toggle visibility logic here
  });
  
  window.addEventListener('resize', setDropdownPosition);
  window.addEventListener('scroll', setDropdownPosition);
});

init();
</script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
def root():
    return HTML

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)
