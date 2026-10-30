"""Die Dokumentation im Repository (docs/, README) muss zum Add-on passen: Optionsliste, Links, Bilder."""
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
pytestmark = pytest.mark.skipif(not DOCS.is_dir(), reason="docs/ liegt nicht neben ki_chat/")

PAGES = [ROOT / "README.md", *sorted(DOCS.glob("*.md")), *sorted((DOCS / "screenshots").glob("*.md")), ROOT / "ki_chat" / "DOCS.md"]
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)\)")
IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")


def anchors(path: Path) -> set[str]:
    """Überschriften-Anker wie bei GitHub: klein, ohne Satzzeichen, Leerzeichen zu Bindestrichen."""
    found = set()
    in_code = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_code = not in_code
        if in_code:
            continue
        m = re.match(r"#{1,6}\s+(.*)", line)
        if m:
            text = re.sub(r"`", "", m.group(1)).strip().lower()
            text = re.sub(r"[^\w\s-]", "", text)
            found.add(re.sub(r"\s", "-", text))
    return found


def test_options_page_is_current():
    sys.path.insert(0, str(ROOT / "tools"))
    import gen_options_doc

    expected = gen_options_doc.render(ROOT)
    assert (DOCS / "einstellungen.md").read_text(encoding="utf-8") == expected, "python tools/gen_options_doc.py ausführen"


def test_every_option_is_documented():
    cfg = yaml.safe_load((ROOT / "ki_chat" / "config.yaml").read_text(encoding="utf-8"))
    page = (DOCS / "einstellungen.md").read_text(encoding="utf-8")
    names = set(cfg["schema"]) | set(cfg["schema"]["profiles"][0])
    missing = sorted(n for n in names if f"`{n}`" not in page)
    assert not missing, f"nicht in docs/einstellungen.md: {missing}"


def test_every_option_has_a_description_in_both_languages():
    for lang in ("de", "en"):
        tr = yaml.safe_load((ROOT / "ki_chat" / "translations" / f"{lang}.yaml").read_text(encoding="utf-8"))["configuration"]
        cfg = yaml.safe_load((ROOT / "ki_chat" / "config.yaml").read_text(encoding="utf-8"))
        missing = [k for k in cfg["schema"] if k not in tr]
        assert not missing, f"{lang}.yaml ohne Beschriftung: {missing}"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_and_images_exist(page):
    text = re.sub(r"```.*?```", "", page.read_text(encoding="utf-8"), flags=re.S)
    for target in [*LINK.findall(text), *IMAGE.findall(text)]:
        if re.match(r"^(https?:|mailto:)", target):
            continue
        path_part, _, fragment = target.partition("#")
        file = (page.parent / path_part).resolve() if path_part else page
        assert file.exists(), f"{page.name}: {target} zeigt ins Leere"
        if fragment and file.suffix == ".md":
            assert fragment in anchors(file), f"{page.name}: Anker #{fragment} fehlt in {file.name}"


def test_absolute_doc_links_in_addon_docs_point_to_existing_pages():
    text = (ROOT / "ki_chat" / "DOCS.md").read_text(encoding="utf-8")
    for name in re.findall(r"HA-Copilot/blob/main/docs/([\w-]+\.md)", text):
        assert (DOCS / name).exists(), name


def test_screenshots_referenced_exist_and_are_all_used():
    used = set()
    for page in PAGES:
        used |= {Path(t).name for t in IMAGE.findall(page.read_text(encoding="utf-8")) if "screenshots/" in t}
    on_disk = {p.name for p in (DOCS / "screenshots").glob("*.png")}
    assert used <= on_disk, f"fehlen: {sorted(used - on_disk)}"
    unused = on_disk - used - {"README.md"}
    assert not unused, f"nirgends eingebunden: {sorted(unused)}"


def test_docs_mention_current_version_and_slug_consistently():
    cfg = yaml.safe_load((ROOT / "ki_chat" / "config.yaml").read_text(encoding="utf-8"))
    assert f"Stand: {cfg['version']}" in (ROOT / "ki_chat" / "DOCS.md").read_text(encoding="utf-8")
    assert re.search(rf"^## {re.escape(cfg['version'])}$", (ROOT / "ki_chat" / "CHANGELOG.md").read_text(encoding="utf-8"), re.M)
    assert cfg["url"] in (DOCS / "installation.md").read_text(encoding="utf-8")


def test_docs_contain_no_secrets_or_real_hosts():
    pattern = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_\w{20,}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
    for page in PAGES:
        for match in pattern.findall(page.read_text(encoding="utf-8")):
            assert set(match.replace("-", "")) <= {"0"}, f"{page.name}: {match[:12]}…"
