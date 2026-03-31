import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from datetime import datetime, date
import ast
import os
import pytz

st.set_page_config(page_title="FidalTracker", layout="wide")

DATA_PATH = 'fidal_meets_data.csv'

def safe_eval(x):
    try:
        return ast.literal_eval(x)
    except:
        return x

def get_data_time_last_update():
    if os.path.exists(DATA_PATH):
        # We load the pre-scraped data from Drive
        df = pd.read_csv(DATA_PATH)
        mtime = os.path.getmtime(DATA_PATH)
        # 2. Convertilo in un oggetto datetime UTC
        utctime = datetime.fromtimestamp(mtime, tz=pytz.utc)
        
        # 3. Trasformalo in orario italiano
        italy_tz = pytz.timezone("Europe/Rome")
        local_time = utctime.astimezone(italy_tz)
        last_update = local_time.strftime("%d/%m/%Y %H:%M")
        return last_update

def load_data():
    if os.path.exists(DATA_PATH):
        # We load the pre-scraped data from Drive
        df = pd.read_csv(DATA_PATH)
        df['Data Inizio'] = pd.to_datetime(df['Data Inizio'], format='%d/%m/%Y', errors='coerce')
        df['Categorie'] = df['Categorie'].apply(safe_eval)
        df = df.sort_values(by='Data Inizio', na_position='last')
        return df
    return pd.DataFrame()

st.title("FidalTracker")
st.caption(f"Dati aggiornati al: {get_data_time_last_update()}")
st.markdown("[Hai trovato un bug o hai un suggerimento?](https://docs.google.com/forms/d/e/1FAIpQLScxYm4VHJun_DYzTH_XszFf92WKAs35j4wMJT_nF-tMMmqPYA/viewform?usp=dialog)")

df = load_data()
st.session_state['fidal_df'] = df

# Inject JS to strip 'inputmode' and set 'readonly' on all multiselects to avoid opening the keyboard on mobile
components.html(
    """
    <script>
    function disableKeyboard() {
        // Find all input fields inside Streamlit multiselect components
        const inputs = window.parent.document.querySelectorAll('.stMultiSelect input');
        inputs.forEach(input => {
            // Tells mobile browsers NOT to show a virtual keyboard
            input.setAttribute('inputmode', 'none'); 
            // Prevents the cursor from triggering the keyboard while allowing clicks
            input.setAttribute('readonly', 'true');
            
            // Optional: allow the dropdown to still open on click
            input.parentElement.onclick = () => {
                input.blur(); // Immediately remove focus to hide keyboard if it peaked
            };
        });
    }

    // Run once, then keep watching for new elements (like when users interact)
    const observer = new MutationObserver(disableKeyboard);
    observer.observe(window.parent.document.body, { childList: true, subtree: true });
    disableKeyboard();
    </script>
    """,
    height=0,
)

if not df.empty:
    with st.sidebar:
        st.header("🔍 Filtri")
        anno_sel = st.multiselect("Anno", options = sorted(df["Data Inizio"].dt.year.unique().tolist(), reverse=True), default=[date.today().year] if date.today().year in df["Data Inizio"].dt.year.unique().tolist() else [df["Data Inizio"].dt.year.unique().tolist()[-1]])
        mesi_nomi = {"1":"Gen", "2":"Feb", "3":"Mar", "4":"Apr", "5":"Mag", "6":"Giu", "7":"Lug", "8":"Ago", "9":"Set", "10":"Ott", "11":"Nov", "12":"Dic"}
        mesi_sel = st.multiselect("Seleziona Mesi", options=list(mesi_nomi.keys()), format_func=lambda x: mesi_nomi[x], default=[str(date.today().month)])
        reg_sel = st.multiselect("Seleziona Regioni", options=sorted(df["Regione"].unique().tolist()))
        logic_mode = st.radio(
            "Modalità di ricerca per Categorie:",
            options=["Almeno una Categoria selezionata (OR)", "Tutte le Categorie selezionate (AND)"],
            horizontal=True,
            help="OR mostra più risultati, AND restringe la ricerca alle gare con tutte le Categoria selezionate."
        )
        cat_nomi = {"ESO": "Esordienti", "RAG": "Ragazzi", "CAD": "Cadetti", "ALL": "Allievi", "JUN": "Juniores", "PRO": "Promesse", "SEN": "Seniores", "MAS": "Master"}
        cat_sel = st.multiselect("Seleziona Categorie", options=sorted(df["Categorie"].explode().dropna().unique().tolist(), key=lambda x: list(cat_nomi.keys()).index(x) if x in list(cat_nomi.keys()) else 999), format_func=lambda x: cat_nomi.get(x, x))
        liv_nomi = {"P": "Provinciale", "R": "Regionale", "N": "Nazionale", "I": "Internazionale", "G": "Gold", "S": "Silver", "B": "Bronze"}
        liv_sel = st.multiselect("Seleziona Livello", options=sorted(df["Livello"].dropna().unique().tolist(), key=lambda x: list(liv_nomi.keys()).index(x) if x in list(liv_nomi.keys()) else 999), format_func=lambda x: liv_nomi.get(x, x))
        tipo_nomi = {"CROSS": "Cross", "INDOOR": "Indoor", "MARCIA SU STRADA": "Marcia su strada", "MONTAGNA": "Montagna", "MONTAGNA/TRAIL": "Montagna/trail", "NORDIC WALKING": "Nordic walking", "OUTDOOR": "Outdoor", "PIAZZA e altri ambiti": "Piazza e altri ambiti", "STRADA": "Strada", "TRAIL": "Trail", "ULTRAMARATONA": "Ultramaratona", "ULTRAMARATONA/TRAIL": "Ultramaratona/trail" }#P.S. sul sito della fidal PISTA c'è solo se la ricerca è per tipologia Regionale, se non è specificata la tipologia PISTA diventa OUTDOOR
        tipo_sel = st.multiselect("Seleziona Tipo", options=sorted(df["Tipo"].dropna().unique().tolist()), format_func=lambda x: tipo_nomi.get(x, x))

    df_final = df.copy()
    if anno_sel and not df_final.empty: df_final = df_final[df_final['Data Inizio'].dt.year.isin([int(a) for a in anno_sel])]
    if mesi_sel and not df_final.empty: df_final = df_final[df_final['Data Inizio'].dt.month.isin([int(a) for a in mesi_sel])]
    if reg_sel and not df_final.empty: df_final = df_final[df_final['Regione'].isin(reg_sel)]
    if logic_mode == "Almeno una Categoria selezionata (OR)":
      if cat_sel and not df_final.empty: df_final = df_final[df_final['Categorie'].apply(
          lambda lista_gara: any(c in lista_gara for c in cat_sel)
          if isinstance(lista_gara, list) else False
      )]
    elif logic_mode == "Tutte le Categorie selezionate (AND)":
      if cat_sel and not df_final.empty: df_final = df_final[df_final['Categorie'].apply(
          lambda lista_gara: all(c in lista_gara for c in cat_sel)
          if isinstance(lista_gara, list) else False
      )]
    if liv_sel and not df_final.empty: df_final = df_final[df_final['Livello'].isin(liv_sel)]
    if tipo_sel and not df_final.empty: df_final = df_final[df_final['Tipo'].isin(tipo_sel)]

    df_final["Nome_con_link"] = df.apply(lambda x: f"[{x['Nome']}]({x['Link']})", axis=1)
# 2. Setup columns and configuration
    cols_to_display = ['Data Inizio', 'Data Fine', 'Nome_con_link', 'Località', 'Livello', 'Categorie', 'Regione', 'Tipo']
    config = {
     "Data Inizio": st.column_config.DateColumn("Inizio", format="DD MMM YY"),
     "Data Fine": st.column_config.DateColumn("Fine", format="DD MMM YY"),
     "Nome_con_link": st.column_config.TextColumn(
            "Link Gara",
            help="Click to open the race details",
            width="medium"
        )
    }

# 3. The "Silent Start" Display Logic
# We check if df_final has the columns AND if it's not empty
    if not df_final.empty and all(c in df_final.columns for c in cols_to_display):
     st.markdown(
        """
        <style>
            [data-testid="stDataFrameResizable"] {
                min-height: 75vh !important;
            }
        </style>
        /* Target links inside the dataframe */
            [data-testid="stTable"] a:visited, 
            [data-testid="stDataFrame"] a:visited {
                color: #ff4b4b !important; /* Changes to Streamlit Red after click */
                text-decoration: none;
            }
            </style>
        """,
        unsafe_allow_html=True
    )
     #dynamic_height = min(len(df_final) * 35 + 40, 800)
     st.dataframe(
        df_final[cols_to_display],
        column_config=config,
        use_container_width=True,
       # height=dynamic_height,
        hide_index=True
     )
    else:
    # This shows a clean empty state instead of a red error on first load
     st.info("Seleziona i filtri per visualizzare le gare.")
     st.dataframe(
        # This shows the headers even when empty, without crashing
        df_final.reindex(columns=cols_to_display),
        column_config=config,
        use_container_width=True
     )
