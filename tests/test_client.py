import httpx
import pytest

from eu_pii_redact import RedactionError, Redactor
from eu_pii_redact.client import _chunks

TICKET = ("Hi, my name is Karina Dahl. I was charged twice for order 88412.\n"
          "Please refund to DK50 0040 0440 1162 43 or call me on +45 32 12 34 56.\nKarina")


def test_round_trip(redactor):
    r = redactor.redact(TICKET)
    assert r.text == ("Hi, my name is [PERSON_1]. I was charged twice for order 88412.\n"
                      "Please refund to [IBAN_1] or call me on [PHONE_1].\n[PERSON_1]")
    assert r.originals == {"[PERSON_1]": "Karina Dahl", "[IBAN_1]": "DK50 0040 0440 1162 43",
                           "[PHONE_1]": "+45 32 12 34 56"}
    assert r.restore("Hi [PERSON_1], refunded to [IBAN_1].") == "Hi Karina Dahl, refunded to DK50 0040 0440 1162 43."


def test_entity_offsets_point_into_the_original(redactor):
    r = redactor.redact(TICKET)
    assert [TICKET[e.start:e.end] for e in r.entities] == [
        "Karina Dahl", "DK50 0040 0440 1162 43", "+45 32 12 34 56", "Karina"]


def test_long_text_is_split_and_placeholders_stay_consistent(redactor):
    filler = "Nothing personal on this line, just order 12345.\n" * 1200  # ~60k chars
    text = "Dear Mr Hansen,\nmail jan@example.nl\n" + filler + "Signed by Hansen, jan@example.nl, ole@example.dk\n"
    assert len(text) > 50_000
    r = redactor.redact(text)
    assert r.text.startswith("Dear Mr [PERSON_1],\nmail [EMAIL_1]\n")
    assert r.text.endswith("Signed by [PERSON_1], [EMAIL_1], [EMAIL_2]\n")
    assert [text[e.start:e.end] for e in r.entities][-3:] == ["Hansen", "jan@example.nl", "ole@example.dk"]
    assert r.restore(r.text) == text


def test_mask_mode(redactor):
    r = redactor.redact("Karina Dahl <karina.dahl@example.com>", types=["EMAIL"], mode="mask")
    assert r.text == "Karina Dahl <***********************>"
    assert r.originals == {}


def test_chunks_cover_text_exactly():
    text = ("x" * 30 + "\n") * 5000
    pieces = list(_chunks(text, limit=1000))
    assert "".join(p for _, p in pieces) == text
    assert all(len(p) <= 1000 for _, p in pieces)
    assert all(p.endswith("\n") for _, p in pieces)


def test_api_errors_carry_a_hint():
    def handler(request):
        return httpx.Response(403, json={"message": "You are not subscribed to this API."})
    r = Redactor(http=httpx.Client(base_url="https://x", transport=httpx.MockTransport(handler)))
    with pytest.raises(RedactionError, match="not subscribed.*subscribe to a plan") as e:
        r.redact("x")
    assert e.value.status == 403


def test_missing_key_is_explained(monkeypatch):
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    with pytest.raises(RedactionError, match="RAPIDAPI_KEY"):
        Redactor()


def test_sends_rapidapi_headers(monkeypatch):
    seen = {}
    real_client = httpx.Client

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(200, json={"redacted": "", "entities": []})
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    Redactor("k3y").redact("")
    assert seen["x-rapidapi-key"] == "k3y"
    assert seen["x-rapidapi-host"] == "eu-pii-redaction.p.rapidapi.com"
    assert seen["user-agent"].startswith("eu-pii-redact-python/")  # Python-urllib is blocked upstream
