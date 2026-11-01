# Debian-Basis, weil das mitgelieferte Claude-CLI des Agent SDK nur für glibc gebaut wird (nicht Alpine/musl).
FROM python:3.15-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /opt/ki_chat

COPY requirements.txt .
RUN pip install -r requirements.txt

# Dateien, die die KI erzeugt (Word, Excel, PowerPoint, PDF). Optional: schlägt die Installation fehl, startet das Add-on
# trotzdem, und die KI kann dann nur Textdateien (Skripte, CSV, …) erzeugen. Die Schrift wird für PDF mit Umlauten und € gebraucht.
RUN (apt-get update && apt-get install -y --no-install-recommends fonts-liberation2 && rm -rf /var/lib/apt/lists/*) \
    || echo "Hinweis: Schrift fuer PDF nicht installiert, PDF nutzt die Standardschrift"
COPY requirements-files.txt .
RUN pip install -r requirements-files.txt \
    || echo "Hinweis: Office-Bibliotheken nicht installiert, es sind nur Textdateien moeglich"

COPY app ./app
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
