"""Diagramme für erzeugte Dateien.

Die KI schreibt in Markdown einen Block ````chart` mit JSON::

    {"type": "column", "title": "Umsatz je Quartal", "unit": "€",
     "labels": ["Q1", "Q2", "Q3"], "series": [{"name": "2026", "values": [120, 150, 170]}]}

``type``: ``column`` (senkrechte Balken), ``bar`` (waagerechte Balken), ``line``, ``pie``. Mehrere Reihen sind bei column, bar und line
möglich; ``pie`` nimmt genau eine. ``series`` darf auch ein Objekt ``{"2026": [..], "2027": [..]}`` sein, bei einer Reihe genügt ``values``.

* PowerPoint und Excel bekommen echte, bearbeitbare Diagramme (:func:`add_pptx_chart`, :func:`add_xlsx_chart`).
* Word und PDF bekommen ein Bild (:func:`draw_png`), mit Pillow gezeichnet, also ohne Matplotlib.
"""
from __future__ import annotations

import io
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import design

KINDS = {"column": "column", "spalten": "column", "saeulen": "column", "säulen": "column", "bar": "bar", "balken": "bar",
         "line": "line", "linie": "line", "pie": "pie", "kreis": "pie", "torte": "pie"}
MAX_POINTS = 60
MAX_SERIES = 8


class ChartError(ValueError):
    """Die Diagrammangabe ist unbrauchbar (Meldung geht an die KI)."""


@dataclass
class Series:
    name: str
    values: list[float]


@dataclass
class Chart:
    kind: str
    title: str
    unit: str
    labels: list[str]
    series: list[Series] = field(default_factory=list)


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool):
        raise ChartError(f"Diagramm: {where} ist keine Zahl.")
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ChartError(f"Diagramm: {where} ist keine endliche Zahl.")
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(" ", "").replace(" ", "")
        if "," in text and "." in text:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", ".")
        try:
            return float(text)
        except ValueError:
            pass
    raise ChartError(f"Diagramm: {where} ist keine Zahl ({str(value)[:20]!r}). Werte als Zahlen schreiben, z. B. 12.5.")


def parse(text: str) -> Chart:
    """Diagrammblock lesen und prüfen; wirft :class:`ChartError` mit einer Meldung, die die KI beheben kann."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ChartError(f"Diagramm: kein gültiges JSON ({str(exc)[:80]}). Erwartet: {{\"type\":\"column\",\"labels\":[…],\"series\":[{{\"name\":\"…\",\"values\":[…]}}]}}.") from None
    if not isinstance(data, dict):
        raise ChartError("Diagramm: erwartet wird ein JSON-Objekt mit type, labels und series.")
    kind = KINDS.get(str(data.get("type") or "column").strip().lower())
    if not kind:
        raise ChartError("Diagramm: type muss column, bar, line oder pie sein.")
    labels = [str(x) for x in (data.get("labels") or data.get("categories") or [])]
    raw = data.get("series")
    if raw is None and "values" in data:
        raw = [{"name": data.get("name") or data.get("title") or "Werte", "values": data["values"]}]
    if isinstance(raw, dict):
        raw = [{"name": k, "values": v} for k, v in raw.items()]
    if not isinstance(raw, list) or not raw:
        raise ChartError("Diagramm: series fehlt (Liste von {\"name\":…, \"values\":[…]}).")
    if len(raw) > MAX_SERIES:
        raise ChartError(f"Diagramm: höchstens {MAX_SERIES} Reihen.")
    series: list[Series] = []
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict) or not isinstance(item.get("values"), list) or not item["values"]:
            raise ChartError(f"Diagramm: Reihe {i} braucht values als Liste von Zahlen.")
        values = [_number(v, f"Wert {n} der Reihe {i}") for n, v in enumerate(item["values"], 1)]
        series.append(Series(str(item.get("name") or f"Reihe {i}"), values))
    count = len(series[0].values)
    if any(len(s.values) != count for s in series):
        raise ChartError("Diagramm: alle Reihen brauchen gleich viele Werte.")
    if count > MAX_POINTS:
        raise ChartError(f"Diagramm: höchstens {MAX_POINTS} Werte je Reihe; fasse zusammen.")
    if not labels:
        labels = [str(n) for n in range(1, count + 1)]
    if len(labels) != count:
        raise ChartError(f"Diagramm: {len(labels)} labels, aber {count} Werte je Reihe. Beides muss gleich lang sein.")
    if kind == "pie":
        if len(series) != 1:
            raise ChartError("Diagramm: ein Kreisdiagramm (pie) hat genau eine Reihe.")
        if any(v < 0 for v in series[0].values) or sum(series[0].values) <= 0:
            raise ChartError("Diagramm: ein Kreisdiagramm braucht positive Werte.")
        if count > 8:
            raise ChartError("Diagramm: ein Kreisdiagramm hat höchstens 8 Teile; fasse kleine Teile zu „Sonstige“ zusammen oder nimm bar.")
    return Chart(kind, str(data.get("title") or "").strip()[:120], str(data.get("unit") or "").strip()[:12], labels, series)


def palette(theme: design.Theme, n: int) -> list[str]:
    """Reihenfarben: Akzent, Kopfton und abgestufte Mischungen; bei Linien und Säulen gut unterscheidbar."""
    base = [theme.accent, theme.head, design.mix(theme.accent, "FFFFFF", 0.45), design.mix(theme.head, "FFFFFF", 0.5),
            design.mix(theme.accent, "000000", 0.35), design.mix(theme.head, "FFFFFF", 0.7), design.mix(theme.accent, "FFFFFF", 0.7), theme.grey]
    return [base[i % len(base)] for i in range(n)]


def fmt(value: float, unit: str = "", digits: int | None = None) -> str:
    """Zahl in deutscher Schreibweise: 1.234,5 €."""
    if digits is None:
        digits = 0 if abs(value) >= 100 or value == int(value) else 1 if abs(value) >= 10 else 2
    text = f"{value:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} {unit}".strip() if unit else text


def nice_ticks(low: float, high: float, target: int = 5) -> list[float]:
    if high <= low:
        high = low + 1
    span = high - low
    raw = span / max(target, 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.floor(low / step) * step
    ticks, v = [], start
    while v <= high + step * 0.999:
        ticks.append(round(v, 10))
        v += step
        if len(ticks) > 12:
            break
    return ticks


# --------------------------------------------------------------------------- Pillow

def _font(path: Path | None, size: int):
    from PIL import ImageFont

    try:
        return ImageFont.truetype(str(path), size) if path else ImageFont.load_default(size)
    except (OSError, TypeError):
        return ImageFont.load_default()


def draw_png(chart: Chart, theme: design.Theme, fonts: tuple[Path | None, Path | None] = (None, None), width: int = 1600, height: int = 900) -> bytes:
    """Diagramm als PNG (zweifach gezeichnet und verkleinert, damit die Kanten glatt sind)."""
    from PIL import Image, ImageDraw

    k = 2
    W, H = width * k, height * k
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    regular, bold = _font(fonts[0], 30 * k), _font(fonts[1] or fonts[0], 30 * k)
    small, title_font = _font(fonts[0], 26 * k), _font(fonts[1] or fonts[0], 40 * k)
    ink, grey, line = design.rgb(theme.dark), design.rgb(theme.grey), design.rgb("DDE3E9")
    colors = [design.rgb(c) for c in palette(theme, len(chart.series) if chart.kind != "pie" else len(chart.labels))]

    def text_w(text: str, font) -> int:
        return int(d.textlength(text, font=font))

    def clip(text: str, font, limit: int) -> str:
        if text_w(text, font) <= limit:
            return text
        while text and text_w(text + "…", font) > limit:
            text = text[:-1]
        return text + "…"

    top = 40 * k
    if chart.title:
        d.text((60 * k, top), clip(chart.title, title_font, W - 120 * k), font=title_font, fill=ink)
        top += 80 * k
    legend_names = [s.name for s in chart.series] if chart.kind != "pie" else chart.labels
    show_legend = len(legend_names) > 1
    bottom = H - 40 * k
    if show_legend and chart.kind != "pie":
        x = 60 * k
        for i, name in enumerate(legend_names):
            d.rectangle((x, top + 6 * k, x + 24 * k, top + 30 * k), fill=colors[i])
            label = clip(name, small, 300 * k)
            d.text((x + 36 * k, top), label, font=small, fill=grey)
            x += 36 * k + text_w(label, small) + 40 * k
        top += 60 * k

    if chart.kind == "pie":
        values = chart.series[0].values
        total = sum(values)
        size = min(bottom - top, W // 2) - 20 * k
        cx0, cy0 = 60 * k, top + ((bottom - top) - size) // 2
        box = (cx0, cy0, cx0 + size, cy0 + size)
        angle = -90.0
        for i, v in enumerate(values):
            sweep = 360 * v / total
            d.pieslice(box, angle, angle + sweep, fill=colors[i], outline="white", width=3 * k)
            angle += sweep
        lx, ly = cx0 + size + 70 * k, max(top, top + (bottom - top) // 2 - len(values) * 28 * k)
        for i, (name, v) in enumerate(zip(chart.labels, values)):
            d.rectangle((lx, ly + 4 * k, lx + 28 * k, ly + 32 * k), fill=colors[i])
            d.text((lx + 44 * k, ly), clip(f"{name}: {fmt(v, chart.unit)} ({v / total * 100:.0f} %)".replace(".", ","), regular, W - lx - 100 * k), font=regular, fill=ink)
            ly += 56 * k
    else:
        allv = [v for s in chart.series for v in s.values]
        low, high = min(0.0, min(allv)), max(0.0, max(allv))
        ticks = nice_ticks(low, high)
        low, high = ticks[0], ticks[-1]
        n = len(chart.labels)
        horizontal = chart.kind == "bar"
        step = ticks[1] - ticks[0] if len(ticks) > 1 else 1.0
        digits = 0 if float(step).is_integer() else min(2, len(f"{step:.10g}".split(".")[1]))
        tick_labels = [fmt(t, "", digits) for t in ticks]
        if horizontal:
            left = 60 * k + min(max(text_w(clip(s, regular, 360 * k), regular) for s in chart.labels), 360 * k) + 24 * k
            right, plot_top, plot_bottom = W - 150 * k, top, bottom - 50 * k
            span = right - left

            def pos(v: float) -> float:
                return left + (v - low) / (high - low) * span

            for t, tl in zip(ticks, tick_labels):
                x = pos(t)
                d.line((x, plot_top, x, plot_bottom), fill=line, width=2 * k)
                d.text((x - text_w(tl, small) / 2, plot_bottom + 12 * k), tl, font=small, fill=grey)
            band = (plot_bottom - plot_top) / n
            bar = band * 0.72 / len(chart.series)
            for i, label in enumerate(chart.labels):
                y0 = plot_top + i * band + band * 0.14
                d.text((left - 16 * k - text_w(clip(label, regular, 360 * k), regular), y0 + band * 0.36 - 18 * k), clip(label, regular, 360 * k), font=regular, fill=ink)
                for j, s in enumerate(chart.series):
                    y = y0 + j * bar
                    x1, x2 = sorted((pos(0), pos(s.values[i])))
                    d.rectangle((x1, y, max(x2, x1 + 2), y + bar - 4 * k), fill=colors[j])
                    if n * len(chart.series) <= 14:
                        d.text((x2 + 12 * k, y + bar / 2 - 17 * k), fmt(s.values[i], chart.unit), font=small, fill=ink)
            d.line((pos(0), plot_top, pos(0), plot_bottom), fill=grey, width=2 * k)
        else:
            axis_w = max(text_w(tl, small) for tl in tick_labels)
            left, right = 60 * k + axis_w + 20 * k, W - 60 * k
            plot_top, plot_bottom = top + 20 * k, bottom - 70 * k
            span = plot_bottom - plot_top

            def pos(v: float) -> float:
                return plot_bottom - (v - low) / (high - low) * span

            for t, tl in zip(ticks, tick_labels):
                y = pos(t)
                d.line((left, y, right, y), fill=line, width=2 * k)
                d.text((left - 16 * k - text_w(tl, small), y - 16 * k), tl, font=small, fill=grey)
            band = (right - left) / n
            for i, label in enumerate(chart.labels):
                text = clip(label, small, int(band) - 8 * k)
                d.text((left + i * band + band / 2 - text_w(text, small) / 2, plot_bottom + 18 * k), text, font=small, fill=grey)
            if chart.kind == "column":
                bar = band * 0.7 / len(chart.series)
                for i in range(n):
                    x0 = left + i * band + band * 0.15
                    for j, s in enumerate(chart.series):
                        y1, y2 = sorted((pos(0), pos(s.values[i])))
                        d.rectangle((x0 + j * bar, y1, x0 + (j + 1) * bar - 4 * k, max(y2, y1 + 2)), fill=colors[j])
                        if n * len(chart.series) <= 14:
                            lab = fmt(s.values[i], chart.unit)
                            d.text((x0 + j * bar + (bar - 4 * k) / 2 - text_w(lab, small) / 2, pos(max(s.values[i], 0)) - 38 * k), lab, font=small, fill=ink)
            else:
                for j, s in enumerate(chart.series):
                    pts = [(left + i * band + band / 2, pos(v)) for i, v in enumerate(s.values)]
                    if len(pts) > 1:
                        d.line(pts, fill=colors[j], width=6 * k, joint="curve")
                    for x, y in pts:
                        d.ellipse((x - 9 * k, y - 9 * k, x + 9 * k, y + 9 * k), fill=colors[j], outline="white", width=2 * k)
                    if len(chart.series) == 1 and n <= 14:
                        for (x, y), v in zip(pts, s.values):
                            lab = fmt(v, chart.unit)
                            d.text((x - text_w(lab, small) / 2, y - 44 * k), lab, font=small, fill=ink)
            d.line((left, pos(0), right, pos(0)), fill=grey, width=2 * k)
    out = io.BytesIO()
    img.resize((width, height), Image.LANCZOS).save(out, "PNG", optimize=True)
    return out.getvalue()


# ------------------------------------------------------------------ PowerPoint, Excel

def add_pptx_chart(slide, chart: Chart, theme: design.Theme, left, top, width, height) -> None:
    """Echtes, in PowerPoint bearbeitbares Diagramm."""
    from pptx.chart.data import CategoryChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
    from pptx.util import Pt

    data = CategoryChartData()
    data.categories = chart.labels
    for s in chart.series:
        data.add_series(s.name, s.values)
    kind = {"column": XL_CHART_TYPE.COLUMN_CLUSTERED, "bar": XL_CHART_TYPE.BAR_CLUSTERED, "line": XL_CHART_TYPE.LINE_MARKERS, "pie": XL_CHART_TYPE.PIE}[chart.kind]
    frame = slide.shapes.add_chart(kind, left, top, width, height, data)
    ch = frame.chart
    ch.font.size = Pt(14)
    ch.font.name = theme.body_font
    ch.font.color.rgb = RGBColor(*design.rgb(theme.dark))
    ch.has_title = bool(chart.title)
    if chart.title:
        ch.chart_title.text_frame.text = chart.title
        run = ch.chart_title.text_frame.paragraphs[0].runs[0]
        run.font.size, run.font.bold = Pt(16), True
    colors = [RGBColor(*design.rgb(c)) for c in palette(theme, len(chart.labels) if chart.kind == "pie" else len(chart.series))]
    plot = ch.plots[0]
    many = len(chart.labels) * len(chart.series) > 14
    if chart.kind == "pie":
        ch.has_legend, plot.has_data_labels = True, True
        ch.legend.position, ch.legend.include_in_layout = XL_LEGEND_POSITION.RIGHT, False
        plot.data_labels.number_format, plot.data_labels.number_format_is_linked = '0%', False
        plot.data_labels.show_percentage, plot.data_labels.show_value = True, False
        plot.data_labels.font.size = Pt(13)
        plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
        for i, point_color in enumerate(colors):
            point = plot.series[0].points[i]
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = point_color
        return
    ch.has_legend = len(chart.series) > 1
    if ch.has_legend:
        ch.legend.position, ch.legend.include_in_layout = XL_LEGEND_POSITION.BOTTOM, False
    value_axis, category_axis = ch.value_axis, ch.category_axis
    value_axis.major_gridlines.format.line.color.rgb = RGBColor(*design.rgb("DDE3E9"))
    value_axis.format.line.fill.background()
    category_axis.format.line.color.rgb = RGBColor(*design.rgb(theme.grey))
    value_axis.tick_labels.font.size = category_axis.tick_labels.font.size = Pt(13)
    if chart.unit:
        value_axis.tick_labels.number_format, value_axis.tick_labels.number_format_is_linked = f'#,##0.##" {chart.unit}"', False
    if not many:
        plot.has_data_labels = True
        plot.data_labels.font.size = Pt(12)
        plot.data_labels.number_format, plot.data_labels.number_format_is_linked = (f'#,##0.##" {chart.unit}"' if chart.unit else '#,##0.##'), False
    for s, color in zip(plot.series, colors):
        if chart.kind == "line":
            s.format.line.color.rgb = color
            s.format.line.width = Pt(3)
            s.smooth = False
            s.marker.format.fill.solid()
            s.marker.format.fill.fore_color.rgb = color
            s.marker.format.line.color.rgb = RGBColor(255, 255, 255)
        else:
            s.format.fill.solid()
            s.format.fill.fore_color.rgb = color
    if chart.kind in ("column", "bar"):
        plot.gap_width = 60
        plot.overlap = -5 if len(chart.series) > 1 else 0


def add_xlsx_chart(ws, spec: dict, rows: int, cols: int) -> str | None:
    """Echtes Excel-Diagramm aus den Daten des Blattes. ``spec``: ``{"type", "title", "series"?: [Kopfnamen], "unit"?}``.

    Rubrik = erste Spalte, Reihen = die genannten Spalten (Standard: alle übrigen mit Zahlen). Gibt eine Warnung zurück oder ``None``.
    """
    from openpyxl.chart import BarChart, LineChart, PieChart, Reference
    from openpyxl.utils import get_column_letter

    kind = KINDS.get(str(spec.get("type") or "column").strip().lower())
    if not kind:
        return "Diagramm: type muss column, bar, line oder pie sein."
    if rows < 2 or cols < 2:
        return "Diagramm: das Blatt braucht eine Kopfzeile, eine Rubrikenspalte und mindestens eine Wertespalte."
    heads = {str(ws.cell(row=1, column=c).value): c for c in range(1, cols + 1)}
    wanted = spec.get("series")
    if isinstance(wanted, list) and wanted:
        missing = [str(w) for w in wanted if str(w) not in heads]
        if missing:
            return f"Diagramm: Spalte(n) {', '.join(missing)} nicht in der Kopfzeile (vorhanden: {', '.join(heads)})."
        columns = [heads[str(w)] for w in wanted]
    else:
        columns = [c for c in range(2, cols + 1) if isinstance(ws.cell(row=2, column=c).value, (int, float))]
    if not columns:
        return "Diagramm: keine Spalte mit Zahlen gefunden."
    last = min(rows, 200)
    chart = {"column": BarChart, "bar": BarChart, "line": LineChart, "pie": PieChart}[kind]()
    if kind == "bar":
        chart.type = "bar"
    elif kind == "column":
        chart.type = "col"
    chart.title = str(spec.get("title") or "") or None
    for c in columns[: 1 if kind == "pie" else MAX_SERIES]:
        chart.add_data(Reference(ws, min_col=c, min_row=1, max_row=last), titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=1, min_row=2, max_row=last))
    chart.width, chart.height = 18, 9.5
    ws.add_chart(chart, f"{get_column_letter(cols + 2)}2")
    return None
