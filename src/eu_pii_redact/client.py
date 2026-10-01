"""Client for the EU PII Redaction API (https://rapidapi.com/JulianJohansen/api/eu-pii-redaction)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable, Literal

import httpx

DEFAULT_HOST = "eu-pii-redaction.p.rapidapi.com"
MAX_CHARS = 50_000  # per API request
ENTITY_TYPES = ("PERSON", "EMAIL", "PHONE", "IBAN", "CREDIT_CARD", "EU_VAT", "NATIONAL_ID", "IP_ADDRESS")
Mode = Literal["label", "mask"]


class RedactionError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Entity:
    type: str
    start: int  # offsets into the original text
    end: int
    placeholder: str | None = None  # label mode only, e.g. "[PERSON_1]"
    country: str | None = None  # NATIONAL_ID only
    scheme: str | None = None  # NATIONAL_ID only


@dataclass
class Redaction:
    text: str  # the redacted text
    entities: list[Entity]
    originals: dict[str, str] = field(default_factory=dict)  # placeholder -> original value

    def restore(self, text: str) -> str:
        """Put the original values back into `text` (e.g. an LLM's answer)."""
        return restore(text, self.originals)


def restore(text: str, originals: dict[str, str]) -> str:
    # Longest placeholder first, so "[PERSON_1]" never touches "[PERSON_10]".
    for placeholder in sorted(originals, key=len, reverse=True):
        text = text.replace(placeholder, originals[placeholder])
    return text


class Redactor:
    """Calls the API. The key comes from `api_key` or the RAPIDAPI_KEY environment variable."""

    def __init__(self, api_key: str | None = None, *, host: str = DEFAULT_HOST, timeout: float = 30.0,
                 http: httpx.Client | None = None):
        key = api_key or os.environ.get("RAPIDAPI_KEY")
        if not key and http is None:
            raise RedactionError("No API key: pass api_key= or set RAPIDAPI_KEY "
                                 "(free plan: https://rapidapi.com/JulianJohansen/api/eu-pii-redaction)")
        self._http = http or httpx.Client(
            base_url=f"https://{host}", timeout=timeout,
            headers={"X-RapidAPI-Key": key or "", "X-RapidAPI-Host": host,
                     "User-Agent": "eu-pii-redact-python/0.1"})

    def __enter__(self) -> "Redactor":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _call(self, text: str, types: Iterable[str] | None, mode: Mode) -> dict:
        body: dict = {"text": text, "mode": mode}
        if types is not None:
            body["types"] = list(types)
        try:
            r = self._http.post("/redact", json=body)
        except httpx.HTTPError as e:
            raise RedactionError(f"Request failed: {e}") from e
        if r.status_code == 200:
            return r.json()
        try:
            detail = r.json()
            detail = detail.get("message") or detail.get("detail") or detail
        except ValueError:
            detail = r.text[:200]
        hint = {401: " (check your RapidAPI key)",
                403: " (subscribe to a plan, free one included, and check your key)",
                429: " (plan quota or rate limit reached)"}.get(r.status_code, "")
        raise RedactionError(f"API error {r.status_code}: {detail}{hint}", r.status_code)

    def redact(self, text: str, types: Iterable[str] | None = None, mode: Mode = "label") -> Redaction:
        """Redact any length of text. Long text is sent in pieces of up to 50,000 characters
        (split at line breaks); placeholders stay consistent across pieces for repeated values."""
        types = list(types) if types is not None else None
        out: list[str] = []
        entities: list[Entity] = []
        originals: dict[str, str] = {}
        by_value: dict[tuple[str, str], str] = {}  # (type, first mention) -> global placeholder
        counters: dict[str, int] = {}
        for offset, chunk in _chunks(text):
            body = self._call(chunk, types, mode)
            raw = [Entity(**{k: e.get(k) for k in Entity.__dataclass_fields__}) for e in body["entities"]]
            if mode == "mask":
                out.append(body["redacted"])
                entities += [_shift(e, offset) for e in raw]
                continue
            # Map this piece's placeholders to global ones by the value they first stood for.
            local_first: dict[str, str] = {}
            for e in raw:
                local_first.setdefault(e.placeholder, chunk[e.start:e.end])
            local_to_global: dict[str, str] = {}
            for local, value in local_first.items():
                etype = local.strip("[]").rsplit("_", 1)[0]
                key = (etype, value)
                if key not in by_value:
                    counters[etype] = counters.get(etype, 0) + 1
                    by_value[key] = f"[{etype}_{counters[etype]}]"
                    originals[by_value[key]] = value
                local_to_global[local] = by_value[key]
            pieces, pos = [], 0
            for e in raw:
                pieces += [chunk[pos:e.start], local_to_global[e.placeholder]]
                pos = e.end
                entities.append(_shift(Entity(e.type, e.start, e.end, local_to_global[e.placeholder],
                                              e.country, e.scheme), offset))
            pieces.append(chunk[pos:])
            out.append("".join(pieces))
        return Redaction("".join(out), entities, originals)


def _shift(e: Entity, offset: int) -> Entity:
    return Entity(e.type, e.start + offset, e.end + offset, e.placeholder, e.country, e.scheme)


def _chunks(text: str, limit: int = MAX_CHARS):
    """Yield (offset, piece) with pieces <= limit, split after a newline where possible."""
    pos = 0
    while pos < len(text) or pos == 0:
        end = min(pos + limit, len(text))
        if end < len(text):
            cut = text.rfind("\n", pos, end)
            if cut > pos:
                end = cut + 1
        yield pos, text[pos:end]
        if end >= len(text):
            return
        pos = end


def redact(text: str, types: Iterable[str] | None = None, mode: Mode = "label", *,
           api_key: str | None = None) -> Redaction:
    """One-off convenience: `redact("Dear Mr Hansen, ...").text`."""
    with Redactor(api_key) as r:
        return r.redact(text, types, mode)
