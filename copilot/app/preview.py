"""Vorschau erzeugter Dateien als Bild, damit die KI ihr Ergebnis ansehen und nachbessern kann.

* PDF: wird mit pypdfium2 gezeichnet.
* Word und PowerPoint: LibreOffice (``soffice``) macht daraus erst ein PDF. Fehlt es im Add-on, sagt das Werkzeug das ehrlich.
* Bilder und SVG: werden verkleinert (SVG gezeichnet, ohne etwas nachzuladen).
Mehrere Seiten kommen als eine Übersicht (Kontaktbogen), ein bis zwei Seiten einzeln und größer.
"""
from __future__ import annotations

import asyncio
import io
import re
import shutil
import tempfile
from pathlib import Path

from . import pictures

MAX_PAGES = 12
SINGLE_WIDTH = 1100
SOFFICE_TIMEOUT = 120
OFFICE_KINDS = {"docx": "Word", "pptx": "PowerPoint", "odt": "Writer", "odp": "Impress"}
_locks: dict[int, asyncio.Lock] = {}  # je Ereignisschleife ein Schloss


class PreviewError(ValueError):
    """Keine Vorschau möglich (Meldung geht an die KI)."""


def soffice_path() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def parse_pages(spec: str | None, total: int) -> list[int]:
    """„3“, „2-5“ oder „1,3,5“ in nullbasierte Seitennummern; ohne Angabe die ersten Seiten."""
    text = str(spec or "").strip().lower()
    if not text or text in ("alle", "all"):
        return list(range(min(total, MAX_PAGES)))
    out: list[int] = []
    for part in re.split(r"[,;\s]+", text):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", part)
        if not m:
            raise PreviewError(f"pages „{spec}“ verstehe ich nicht. Beispiele: \"1\", \"2-5\", \"1,3,7\".")
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if a < 1 or b < a:
            raise PreviewError(f"pages „{part}“ ist ungültig.")
        out += [n - 1 for n in range(a, b + 1) if n - 1 < total]
    out = list(dict.fromkeys(out))
    if not out:
        raise PreviewError(f"Die Datei hat nur {total} Seite(n).")
    return out[:MAX_PAGES]


async def office_to_pdf(ext: str, data: bytes) -> bytes:
    exe = soffice_path()
    if not exe:
        raise PreviewError("Für Word- und PowerPoint-Dateien braucht die Vorschau LibreOffice, und das ist in diesem Add-on nicht installiert. "
                           "Prüfe den Inhalt mit file_read; sag der Person ehrlich, dass du das Ergebnis nicht gesehen hast.")
    loop_id = id(asyncio.get_running_loop())
    lock = _locks.setdefault(loop_id, asyncio.Lock())
    async with lock:  # ein LibreOffice zur Zeit: es ist schwer und nicht parallelfähig
        with tempfile.TemporaryDirectory(prefix="preview-") as tmp:
            work = Path(tmp)
            source = work / f"datei.{ext}"
            source.write_bytes(data)
            proc = await asyncio.create_subprocess_exec(
                exe, f"-env:UserInstallation=file://{work / 'profil'}", "--headless", "--norestore", "--convert-to", "pdf", "--outdir", str(work), str(source),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, cwd=tmp,
            )
            try:
                await asyncio.wait_for(proc.wait(), SOFFICE_TIMEOUT)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                raise PreviewError("Die Vorschau hat zu lange gedauert (LibreOffice). Versuche es mit weniger Inhalt.") from None
            result = work / "datei.pdf"
            if not result.is_file():
                raise PreviewError("LibreOffice konnte die Datei nicht in ein PDF umwandeln; die Datei ist möglicherweise beschädigt.")
            return result.read_bytes()


def _pdf_pages(pdf_bytes: bytes, pages: str | None, width: int) -> tuple[list, int]:
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise PreviewError("Vorschau braucht pypdfium2 und das ist hier nicht installiert.") from None
    try:
        doc = pdfium.PdfDocument(pdf_bytes)
    except Exception:
        raise PreviewError("Das PDF lässt sich nicht öffnen (beschädigt oder mit Kennwort geschützt).") from None
    total = len(doc)
    if total == 0:
        raise PreviewError("Das PDF hat keine Seiten.")
    chosen = parse_pages(pages, total)
    images = []
    for index in chosen:
        page = doc[index]
        scale = width / max(page.get_width(), 1)
        images.append((index + 1, page.render(scale=scale).to_pil().convert("RGB")))
    doc.close()
    return images, total


def _sheet(images: list, columns: int, tile: int):
    from PIL import Image, ImageDraw

    ratio = max(im.height / im.width for _, im in images)
    th = int(tile * ratio)
    pad, label = 12, 22
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * (tile + pad) + pad, rows * (th + pad + label) + pad), (225, 229, 234))
    draw = ImageDraw.Draw(sheet)
    for n, (number, im) in enumerate(images):
        small = im.resize((tile, max(1, int(tile * im.height / im.width))))
        x, y = pad + (n % columns) * (tile + pad), pad + (n // columns) * (th + pad + label)
        draw.text((x, y), str(number), fill=(60, 70, 80))
        sheet.paste(small, (x, y + label))
        draw.rectangle((x - 1, y + label - 1, x + tile, y + label + small.height), outline=(180, 188, 196))
    return sheet


def _encode(img, quality: int = 80) -> bytes:
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=quality, optimize=True)
    return out.getvalue()


def _compose(pages_images: list, total: int) -> tuple[list[tuple[bytes, str]], str]:
    numbers = [n for n, _ in pages_images]
    shown = f"Seite {numbers[0]}" if len(numbers) == 1 else f"Seiten {', '.join(map(str, numbers))}"
    if len(pages_images) <= 2:
        images = [(_encode(im), "image/jpeg") for _, im in pages_images]
        note = f"{shown} von {total} als Bild" + (" (einzeln)" if len(images) > 1 else "")
    else:
        columns = 2 if len(pages_images) <= 4 else 3
        tile = 700 if columns == 2 else 620
        images = [(_encode(_sheet(pages_images, columns, tile), 78), "image/jpeg")]
        note = f"{shown} von {total} als Übersicht, links oben beginnend, Seitennummer über jeder Seite"
    return images, note


async def preview(name: str, data: bytes, pages: str | None = None) -> tuple[list[tuple[bytes, str]], str]:
    """Vorschaubilder und eine Beschreibung. Wirft :class:`PreviewError`."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""

    if ext == "pdf":
        shown, total = await asyncio.to_thread(_pdf_pages, data, pages, SINGLE_WIDTH)
    elif ext in OFFICE_KINDS:
        pdf = await office_to_pdf(ext, data)
        shown, total = await asyncio.to_thread(_pdf_pages, pdf, pages, SINGLE_WIDTH)
    elif ext in ("png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"):
        def one():
            from PIL import Image

            pic = pictures.prepare(data, name)
            img = Image.open(io.BytesIO(pic.data)).convert("RGBA")
            background = Image.new("RGBA", img.size, (255, 255, 255, 255))
            background.alpha_composite(img)
            img = background.convert("RGB")
            if img.width > SINGLE_WIDTH:
                img = img.resize((SINGLE_WIDTH, max(1, int(img.height * SINGLE_WIDTH / img.width))))
            return [(1, img)], 1

        try:
            shown, total = await asyncio.to_thread(one)
        except pictures.PictureError as exc:
            raise PreviewError(str(exc)) from None
    elif ext in ("xlsx", "xls", "csv"):
        raise PreviewError("Für Excel-Dateien gibt es keine Bildvorschau. Lies sie mit file_read (Zellen, Formeln und Werte).")
    else:
        raise PreviewError("Eine Bildvorschau gibt es für Word, PowerPoint, PDF und Bilder (auch SVG). Textdateien liest du mit file_read.")
    images, note = await asyncio.to_thread(_compose, shown, total)
    return images, note
