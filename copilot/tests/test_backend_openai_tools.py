"""Die Responses-Schnittstelle erlaubt höchstens 128 Werkzeuge je Anfrage; mehr würden die ganze Antwort scheitern lassen."""
from app.backend_openai import MAX_FUNCTIONS, function_tools
from app.ha_tools import ToolSpec


def spec(i):
    return ToolSpec(f"t{i}", "Werkzeug", {"type": "object"}, None)


def test_function_tools_keeps_everything_up_to_the_limit():
    assert len(function_tools([spec(i) for i in range(MAX_FUNCTIONS)])) == MAX_FUNCTIONS


def test_function_tools_never_exceeds_the_api_limit(caplog):
    offered = function_tools([spec(i) for i in range(200)])
    assert len(offered) == MAX_FUNCTIONS <= 127 and offered[0]["name"] == "t0"
    assert "höchstens 128" in caplog.text
