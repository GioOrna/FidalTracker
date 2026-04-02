FROM python:3.9-slim

WORKDIR /app

# Installa dipendenze di sistema necessarie
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copia e installa dipendenze Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia tutti i file
COPY FidalTracker.py .
COPY Scraper.py .
COPY fidal_meets_data.csv .  # Se esiste già, altrimenti verrà creato

# Esponi la porta
EXPOSE 7860

# Comando per avviare l'app
CMD ["uvicorn", "FidalTracker:app", "--host", "0.0.0.0", "--port", "7860"]