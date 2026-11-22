# Stufe 1: der Linux-Server-Agent (Go, ohne Netz gebaut: die Abhängigkeit liegt unter agent/vendor). Der Hub im Add-on liefert die
# beiden Dateien (und die Fassung in VERSION, aus der der Hub Aktualisierungen anbietet) an die Server aus; sie landen unter /opt/copilot/agent-bin.
# Sind sie vom Release signiert, liegen daneben die .sig-Dateien und update_key.pub.
FROM golang:1.27-bookworm AS agent
ARG BUILD_VERSION=dev
WORKDIR /src
COPY agent/ ./
ENV CGO_ENABLED=0 GOFLAGS=-mod=vendor
RUN GOOS=linux GOARCH=amd64 go build -trimpath -ldflags "-s -w -X main.version=${BUILD_VERSION}" -o /out/copilot-agent-linux-amd64 ./cmd/copilot-agent \
 && GOOS=linux GOARCH=arm64 go build -trimpath -ldflags "-s -w -X main.version=${BUILD_VERSION}" -o /out/copilot-agent-linux-arm64 ./cmd/copilot-agent \
 && printf '%s\n' "${BUILD_VERSION}" > /out/VERSION

# Signierte Programme aus dem GitHub-Release (siehe .github/workflows/release-agent.yml) ersetzen die eben gebauten, wenn Signatur und
# öffentlicher Schlüssel (agent/update_key.pub) stimmen. Sonst bleiben die lokal gebauten, unsignierten Dateien; der Bau schlägt nie fehl.
ARG AGENT_RELEASES=https://github.com/dominikramachers/HA-Copilot/releases/download
RUN go build -trimpath -o /tmp/copilot-sign ./cmd/copilot-sign \
 && sh ./fetch-signed.sh "${BUILD_VERSION}" "${AGENT_RELEASES}" update_key.pub /tmp/copilot-sign /out

# Stufe 2: das Add-on
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

COPY --from=agent /out /opt/copilot/agent-bin
COPY app ./app
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
