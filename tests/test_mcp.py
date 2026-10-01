import json
import stat

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from eu_pii_redact import mcp_server

TICKET = "Hi, my name is Karina Dahl. Refund to DK50 0040 0440 1162 43.\nKarina"


@pytest.fixture(autouse=True)
def use_local_api(redactor, monkeypatch):
    monkeypatch.setattr(mcp_server, "_redactor", redactor)


def test_redact_text_returns_no_originals():
    out = mcp_server.redact_text(TICKET)
    assert out["redacted"] == "Hi, my name is [PERSON_1]. Refund to [IBAN_1].\n[PERSON_1]"
    assert out["counts"] == {"PERSON": 2, "IBAN": 1}
    assert "Karina" not in json.dumps(out)


def test_redact_file_and_restore_file(tmp_path):
    src = tmp_path / "ticket.txt"
    src.write_text(TICKET, encoding="utf-8")
    out = mcp_server.redact_file(str(src), str(tmp_path / "ticket.redacted.txt"))
    assert "Karina" not in json.dumps(out)  # nothing personal goes back to the model
    assert out["counts"] == {"PERSON": 2, "IBAN": 1}
    redacted = (tmp_path / "ticket.redacted.txt").read_text(encoding="utf-8")
    assert "Karina" not in redacted
    mapping = tmp_path / "ticket.redacted.txt.map.json"
    assert stat.S_IMODE(mapping.stat().st_mode) == 0o600

    answer = tmp_path / "answer.txt"
    answer.write_text("Dear [PERSON_1], we refunded [IBAN_1].", encoding="utf-8")
    res = mcp_server.restore_file(str(answer), str(mapping), str(tmp_path / "answer.final.txt"))
    assert res["placeholders_restored"] == 2
    assert (tmp_path / "answer.final.txt").read_text(encoding="utf-8") == \
        "Dear Karina Dahl, we refunded DK50 0040 0440 1162 43."


def test_redact_file_refuses_to_overwrite(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")
    (tmp_path / "b.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(ToolError, match="already exists"):
        mcp_server.redact_file(str(src), str(tmp_path / "b.txt"))
    with pytest.raises(ToolError, match="must differ"):
        mcp_server.redact_file(str(src), str(src), overwrite=True)
    assert (tmp_path / "b.txt").read_text() == "keep me"


def test_server_speaks_mcp_over_stdio():
    # Launch the installed console script as a host would and list its tools.
    import shutil
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    command = shutil.which("eu-pii-redact")
    assert command, "console script not installed"

    async def run():
        params = StdioServerParameters(command=command, env={"RAPIDAPI_KEY": "dummy"})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return (await session.list_tools()).tools

    tools = {t.name: t for t in anyio.run(run)}
    assert set(tools) == {"redact_text", "redact_file", "restore_file"}
    types_schema = tools["redact_text"].input_schema["properties"]["types"]
    assert "NATIONAL_ID" in json.dumps(types_schema)
    assert tools["redact_text"].annotations.read_only_hint is True


def test_api_errors_reach_the_model_readably(monkeypatch):
    import httpx
    from eu_pii_redact import Redactor

    def handler(request):
        return httpx.Response(403, json={"message": "You are not subscribed to this API."})
    monkeypatch.setattr(mcp_server, "_redactor",
                        Redactor(http=httpx.Client(base_url="https://x", transport=httpx.MockTransport(handler))))
    with pytest.raises(ToolError, match="not subscribed.*subscribe to a plan"):
        mcp_server.redact_text("x")
