# Debian-Basis, weil das mitgelieferte Claude-CLI des Agent SDK nur für glibc gebaut wird (nicht Alpine/musl).
FROM python:3.15-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /opt/copilot

COPY requirements.txt .
RUN pip install -r requirements.txt

# Dateien, die die KI erzeugt (Word, Excel, PowerPoint, PDF). Optional: schlägt die Installation fehl, startet das Add-on
# trotzdem, und die KI kann dann nur Textdateien (Skripte, CSV, …) erzeugen. Die Schrift wird für PDF mit Umlauten und € gebraucht.
RUN (apt-get update && apt-get install -y --no-install-recommends fonts-liberation2 && rm -rf /var/lib/apt/lists/*) \
    || echo "Hinweis: Schrift fuer PDF nicht installiert, PDF nutzt die Standardschrift"
COPY requirements-files.txt .
RUN pip install -r requirements-files.txt \
    || echo "Hinweis: Office-Bibliotheken nicht installiert, es sind nur Textdateien moeglich"

# Bilder in Dateien (SVG zeichnen) und Vorschau der erzeugten Dateien fuer die KI. Zwei getrennte, optionale Schritte:
# * libcairo2 zeichnet SVG-Zeichnungen (cairosvg). Fehlt es, lassen sich nur PNG/JPEG einbetten.
# * LibreOffice (Writer + Impress, ohne Java) macht aus Word und PowerPoint ein PDF fuer die Vorschau. Es braucht rund 400 MB Platz im Image.
#   Wer das nicht moechte, entfernt den Block: alles andere laeuft weiter, nur file_preview meldet dann ehrlich, dass LibreOffice fehlt.
RUN (apt-get update && apt-get install -y --no-install-recommends libcairo2 && rm -rf /var/lib/apt/lists/*) \
    || echo "Hinweis: libcairo2 nicht installiert, SVG-Bilder lassen sich nicht in Dateien einbetten"
RUN (apt-get update && apt-get install -y --no-install-recommends libreoffice-writer libreoffice-impress fonts-crosextra-carlito fonts-dejavu-core && rm -rf /var/lib/apt/lists/*) \
    || echo "Hinweis: LibreOffice nicht installiert, die Vorschau gibt es dann nur fuer PDF und Bilder"

COPY app ./app
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
