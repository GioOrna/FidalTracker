import pandas as pd
import requests
from bs4 import BeautifulSoup
import os
from datetime import datetime, date, timedelta
import json
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from huggingface_hub import HfApi

scraper_mode_all = False #if True we scrape all current and past information on the FIDAL site, if False we only scrape informations of the "current" year (in reality 2 days prior of today just to update information on eventual races on the 30-31 of December)
DATA_PATH = 'fidal_meets_data.csv'
Province_Regioni_PATH = 'Province-Regioni.json'

def load_region_map():
    with open(Province_Regioni_PATH, 'r', encoding='utf-8') as f:
        dati = json.load(f)
    # Creiamo un dizionario veloce {Sigla: Regione}
    return {p['sigla']: p['regione'] for p in dati}

# Carichiamo i dati una volta sola
map = load_region_map()

def get_region(sigla):
    regione = map.get(sigla, " Non specificata")
    return regione

#function to get years available to search trough
def get_fidal_years():
    url = "https://www.fidal.it/calendario.php"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        # 1. Estrazione ANNI
        # Cerchiamo il menu a tendina con name="anno"
        select_tag = soup.find('select', {'name': 'anno'})
        # Prendi il 'value' di ogni opzione, saltando quelle vuote
        anni = [opt.get('value') for opt in select_tag.find_all('option') if opt.get('value')]
        return anni
    except Exception as e:
        print(f"Errore durante il recupero dei dati: {e}")
        return [], {}

# Funzione per pulire e fondere le liste di categorie
def merge_cat(series):
    flat_list = []
    for element in series:
      flat_list.extend(element)
    # Rimuoviamo i duplicati e ordiniamo
    return sorted(list(set(flat_list)))

def data_splitter(data_str, anno):
    try:
        if len(data_str) > 10 and data_str.count('/') == 2:
          print(data_str)
        elif data_str.count('-') >= 2:
          print(data_str)
        # Caso 3: "31/0101/02" (Cambio mese, 10 caratteri)
        if len(data_str) == 10 and data_str.count('/') == 2:
            parte_inizio = data_str[:5]  # "31/01"
            parte_fine = data_str[5:]    # "01/02"
        # Caso 2: "24-25/01" (Range stesso mese)
        elif '-' in data_str:
            giorno_in, resto = data_str.split('-') # "24", "25/01"
            mese = resto.split('/')[-1]
            parte_inizio = f"{giorno_in}/{mese}"
            parte_fine = resto
        # Caso 1: "31/01" (Giorno singolo)
        else:
            parte_inizio = data_str
            parte_fine = data_str
        dt_inizio = pd.to_datetime(f"{parte_inizio}/{anno}", format='%d/%m/%Y', dayfirst=True)
        dt_fine = pd.to_datetime(f"{parte_fine}/{anno}", format='%d/%m/%Y', dayfirst=True)
        return dt_inizio, dt_fine
    except:
        return pd.NaT, pd.NaT

# We need to add COD or REG based on the type of the race (the Fidal site doesn't give a valid link when searching without specifying which level) and also adding the true name of the race instead of what the fidal site puts because it is irrelevant to the functioning of the link and we can use it to display the true name of the race while also using it as an hyperlink
def link_reconstructor(partial, liv, nome):
  split = partial.rsplit('/', 2)
  if liv == "P" or liv == "R":
    return f"{split[0]}/{nome}/REG{split[2]}"
  elif liv == "I" or liv == "N" or liv == "G" or liv == "S" or liv == "B":
    return f"{split[0]}/{nome}/COD{split[2]}"
  else:
    print("Problema nel formattamento del link")
  return "calendario/Link Errato/"

def safe_eval(x):
    try:
        return ast.literal_eval(x)
    except:
        return x

def load_data():
    if os.path.exists(DATA_PATH):
        # We load the pre-scraped data
        df = pd.read_csv(DATA_PATH)
        df['Data Inizio'] = pd.to_datetime(df['Data Inizio'], dayfirst=True, errors='coerce')
        df['Data Fine'] = pd.to_datetime(df['Data Fine'], dayfirst=True, errors='coerce')
        df['Categorie'] = df['Categorie'].apply(safe_eval)
        # Eliminiamo eventuali righe dove la data è corrotta (NaT = Not a Time)
        df = df.dropna(subset=['Data Inizio'])
        return df
    return pd.DataFrame()
  
def save_to_HF():
    api = HfApi()
    api.upload_file(
        repo_id=f"{os.environ.get('HF_USERNAME')}/fidal-meets-data",
        repo_type="dataset",
        path_in_repo="fidal_meets_data.csv",
        path_or_fileobj="fidal_meets_data.csv",
        token=os.environ.get("HF_TOKEN"),
        commit_message="Aggiornamento dati"
    )

def update_csv(df_merged, anno_to_merge):
  df_old = load_data()
  if not df_old.empty:
    # Ensure the new data columns are also definitely datetimes before concat
    df_merged['Data Inizio'] = pd.to_datetime(df_merged['Data Inizio'])
    df_merged['Data Fine'] = pd.to_datetime(df_merged['Data Fine'])
    df_filtered = df_old[(df_old["Data Inizio"].dt.year < anno_to_merge)]
    df_final = pd.concat([df_filtered, df_merged], ignore_index=True)
    df_final = df_final.sort_values(by='Data Inizio')
    df_final.to_csv(DATA_PATH, date_format='%d/%m/%Y', index=False)
    save_to_HF()

def run_full_scrape():
    if scraper_mode_all:
      anno_to_search = date.today().year
    else:
      anno_to_search = (date.today()-timedelta(days=2)).year
    # Configuration
    anni = get_fidal_years()
    categorie = ["ESO", "RAG", "CAD",
        "ALL", "JUN", "PRO",
        "SEN", "MAS"]
    all_results = []
    
    requests.Session().headers.update({'User-Agent': 'Mozilla/5.0'})
    # Configure retry strategy
    retry_strategy = Retry(
        total=10,                # Max 3 retries
        backoff_factor=1,       # Wait 1s, 2s, 4s between tries
        status_forcelist=[429, 500, 502, 503, 504], # Retry on these errors
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    requests.Session().mount("https://", adapter)
    requests.Session().mount("http://", adapter)
    for a in anni:
      if (scraper_mode_all==True and int(a) <= anno_to_search) or (scraper_mode_all==False and int(a) >= anno_to_search):
          for c in categorie:
              print("Searching: " +a+" "+c)
              url = f"https://www.fidal.it/calendario.php?anno={a}&mese=&livello=&new_regione=&new_categoria={c}&submit=Invia"
              try:
                  print(url)
                  res = requests.Session().get(url, timeout=20)
                  res.raise_for_status()
                  soup = BeautifulSoup(res.text, 'html.parser')
                  # Find the div containing informations
                  div = soup.find('div', class_="table_btm")
                  if not div:
                      return pd.DataFrame()
                  rows = div.find_all('tr')
                  # for each row of the table
                  for row in rows:
                      cols = row.find_all('td')
                      if len(cols) >= 5: #just to make sure we have the right informations
                          nome_tag = cols[3].find('a')
                          all_results.append({
                              'Data Inizio': data_splitter(cols[1].text.strip(), a)[0],
                              'Data Fine': data_splitter(cols[1].text.strip(), a)[1],
                              'Livello': cols[2].text.strip().split('-')[-1].strip(),
                              'Tipo': cols[4].text.strip(),
                              'Categorie': [c],
                              'Regione' : get_region(cols[5].text.strip().strip("()")[-2:]),
                              'Località': cols[5].text.strip(),
                              'Link': link_reconstructor(nome_tag['href'], cols[2].text.strip().split('-')[-1].strip(), nome_tag.text.strip() if nome_tag else cols[3].text.strip()) if nome_tag and 'href' in nome_tag.attrs else "calendario/Link Errato/"
                          })

              except Exception as e:
                  print(f"An error occurred: {e}")
                  raise RuntimeError("Failed to scrape FIDAL site.")
                  return

    #if we got some results we merge the data that have the same link (so they are the same event) and we merge the "Categorie" elements, than we save the result
    if all_results:
        df_raw = pd.DataFrame(all_results)
        df_merged = df_raw.groupby('Link').agg({
            'Data Inizio': 'first',
            'Data Fine': 'first',
            'Regione': 'first',
            'Livello': 'first',
            'Località': 'first',
            'Tipo': lambda x: " / ".join(x.unique()), # Unisce i testi
            'Categorie': merge_cat # Unisce le liste
        }).reset_index()
        df_merged = df_merged.sort_values(by='Data Inizio')
        # Save the file or merge it
        if scraper_mode_all:
          df_merged = df_merged.sort_values(by='Data Inizio')
          df_merged.to_csv(DATA_PATH, date_format='%d/%m/%Y', index=False)
          save_to_HF()
        else:
          update_csv(df_merged, anno_to_search)
        print(f"Scrape finished at {datetime.now()}. Saved to {DATA_PATH}")

if __name__ == "__main__":
    run_full_scrape()
