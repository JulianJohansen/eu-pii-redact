"""MCP server: redact personal data in text and files via the EU PII Redaction API.

The file tools keep personal data out of the model's context: the server reads and writes
the files itself and only reports counts. Needs RAPIDAPI_KEY (free plan available).
"""
from __future__ import annotations

import functools
import json
import os
from collections import Counter
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from .client import ENTITY_TYPES, RedactionError, Redactor, restore

EntityType = Literal["PERSON", "EMAIL", "PHONE", "IBAN", "CREDIT_CARD", "EU_VAT", "NATIONAL_ID", "IP_ADDRESS"]
assert set(EntityType.__args__) == set(ENTITY_TYPES)

mcp = MCPServer(
    "eu-pii-redact",
    instructions=(
        "Redacts personal data (names, emails, phones, IBANs, cards, EU national ID numbers, VAT numbers, "
        "IPs) and replaces it with placeholders like [PERSON_1]. To keep personal data out of the "
        "conversation, prefer redact_file/restore_file for files: they never return the original values."
    ),
)
_redactor: Redactor | None = None


def _client() -> Redactor:
    global _redactor
    if _redactor is None:
        _redactor = Redactor()
    return _redactor


def _readable_errors(fn):
    """Only ToolError messages reach the model; others become a generic "Error executing tool".
    Pass ours through, since they say what to do ("subscribe to a plan", "file already exists")."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (RedactionError, ValueError, OSError) as e:
            raise ToolError(str(e)) from e
    return wrapper


def _counts(entities) -> dict[str, int]:
    return dict(Counter(e.type for e in entities))


def _check_output(path: Path, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise ValueError(f"{path} already exists; pass overwrite=true to replace it")


@mcp.tool(annotations=ToolAnnotations(title="Redact text", read_only_hint=True, open_world_hint=True))
@_readable_errors
def redact_text(
    text: Annotated[str, Field(description="Text to redact.")],
    types: Annotated[list[EntityType] | None, Field(description="Only these types; default all.")] = None,
    mode: Annotated[Literal["label", "mask"], Field(
        description='"label" replaces with [TYPE_n] placeholders, "mask" with asterisks.')] = "label",
) -> dict:
    """Redact personal data in a text and return the redacted text plus the detected entities
    (type, position, placeholder). Original values are not returned."""
    result = _client().redact(text, types, mode)
    return {
        "redacted": result.text,
        "counts": _counts(result.entities),
        "entities": [{k: v for k, v in vars(e).items() if v is not None} for e in result.entities],
    }


@mcp.tool(annotations=ToolAnnotations(title="Redact a file", read_only_hint=False, open_world_hint=True))
@_readable_errors
def redact_file(
    input_path: Annotated[str, Field(description="UTF-8 text file to redact (.txt, .md, .csv, .json, .log, .eml...).")],
    output_path: Annotated[str, Field(description="Where to write the redacted copy.")],
    types: Annotated[list[EntityType] | None, Field(description="Only these types; default all.")] = None,
    save_mapping: Annotated[bool, Field(
        description="Also write <output_path>.map.json (owner-only permissions) so restore_file can "
                    "put the original values back later.")] = True,
    overwrite: bool = False,
) -> dict:
    """Redact a text file into a new file without showing its contents. Returns only counts per type,
    so the personal data never enters the conversation."""
    src, dst = Path(input_path).expanduser(), Path(output_path).expanduser()
    if src.resolve() == dst.resolve():
        raise ValueError("output_path must differ from input_path")
    _check_output(dst, overwrite)
    result = _client().redact(src.read_text(encoding="utf-8"), types, "label")
    dst.write_text(result.text, encoding="utf-8")
    response = {"output_path": str(dst), "counts": _counts(result.entities)}
    if save_mapping:
        map_path = dst.with_name(dst.name + ".map.json")
        _check_output(map_path, overwrite)
        fd = os.open(map_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(result.originals, f, ensure_ascii=False, indent=1)
        response["mapping_path"] = str(map_path)
    return response


@mcp.tool(annotations=ToolAnnotations(title="Restore a file", read_only_hint=False, open_world_hint=False))
@_readable_errors
def restore_file(
    input_path: Annotated[str, Field(description="File containing placeholders, e.g. an edited redacted file "
                                                 "or an LLM answer saved to disk.")],
    mapping_path: Annotated[str, Field(description="The .map.json written by redact_file.")],
    output_path: Annotated[str, Field(description="Where to write the restored file.")],
    overwrite: bool = False,
) -> dict:
    """Put the original values back into a file, locally (no API call). Returns only how many
    placeholders were restored, not the values."""
    src, dst = Path(input_path).expanduser(), Path(output_path).expanduser()
    _check_output(dst, overwrite)
    originals = json.loads(Path(mapping_path).expanduser().read_text(encoding="utf-8"))
    text = src.read_text(encoding="utf-8")
    restored_count = sum(text.count(p) for p in originals)
    fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(restore(text, originals))
    return {"output_path": str(dst), "placeholders_restored": restored_count}


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
