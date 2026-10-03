# eu-pii-redact

Keep European personal data out of LLM prompts and logs, and put it back in the answer.
Python client, LangChain integration and MCP server for the
[EU PII Redaction API](https://rapidapi.com/JulianJohansen/api/eu-pii-redaction).
**[Try it live without signing up](https://eu-id-check.julvankran.workers.dev/try)** ·
[Quickstart](https://eu-id-check.julvankran.workers.dev/quickstart) ·
[Privacy and data processing](https://eu-id-check.julvankran.workers.dev/privacy)

<!-- mcp-name: io.github.JulianJohansen/eu-pii-redact -->

```text
Hi, my name is Karina Dahl. I was charged twice for order 88412.
Please refund to DK50 0040 0440 1162 43 or call me on +45 32 12 34 56.
Karina
```
becomes
```text
Hi, my name is [PERSON_1]. I was charged twice for order 88412.
Please refund to [IBAN_1] or call me on [PHONE_1].
[PERSON_1]
```

- **Names** from evidence, not capital letters: titles, greetings, roles, `Name:` labels, sign-offs, or a
  first name from 140,000 European names. "Best Practices" and "Court of Justice" stay as they are.
- **National ID numbers from 21 EU/EEA countries**, checked by check digit and birth date
  (personnummer, HETU, DNI/NIE, codice fiscale, NIR, PESEL, BSN, CPR, ...).
- **IBANs** (mod-97), **cards** (Luhn), **EU VAT numbers**, **emails**, **phones** (with + prefix), **IPs**.
- Every mention of a person shares one placeholder; order and invoice numbers stay untouched.

You need a RapidAPI key with a plan for the API. The
[free plan](https://rapidapi.com/JulianJohansen/api/eu-pii-redaction/pricing) gives 500 requests a month.
Set it as `RAPIDAPI_KEY`.

## Python

```bash
pip install eu-pii-redact
```

```python
from eu_pii_redact import Redactor

with Redactor() as r:                       # reads RAPIDAPI_KEY
    redaction = r.redact(ticket)
    reply = ask_llm(redaction.text)         # the model only sees placeholders
    print(redaction.restore(reply))         # real values back in the answer
```

`redaction.entities` lists each finding with its type, offsets in the original text and placeholder
(national IDs also carry `country` and `scheme`). Texts longer than 50,000 characters are sent in pieces
with consistent placeholders. `r.redact(text, types=["EMAIL", "IBAN"], mode="mask")` masks with asterisks.

## LangChain

```bash
pip install "eu-pii-redact[langchain]"
```

```python
from eu_pii_redact.langchain import protect, PIIRedactionTransformer

safe_llm = protect(llm)   # any model or chain that takes a string
safe_llm.invoke("Draft a reply to Karina Dahl about her refund to DK50 0040 0440 1162 43")
# the model sees [PERSON_1] and [IBAN_1]; the returned message has the real values again

docs = PIIRedactionTransformer().transform_documents(docs)   # e.g. before indexing for RAG
```

## MCP server

Lets an AI assistant redact text and, more importantly, **files without reading them**:
`redact_file` reads and writes the file itself and only reports counts, so the personal data
never enters the conversation. `restore_file` puts the values back locally.

| Tool | What it does |
|---|---|
| `redact_text` | Redact a text; returns the redacted text and entities (no original values) |
| `redact_file` | Redact a UTF-8 file into a new file; writes a restore mapping (owner-only permissions) |
| `restore_file` | Put the original values back into a file using that mapping, offline |

**Claude Desktop (one click):** download `eu-pii-redact-0.1.0.mcpb` from the
[latest release](https://github.com/JulianJohansen/eu-pii-redact/releases/latest), open it, and paste
your RapidAPI key when asked. The bundle sources are in `mcpb/`.

**Claude Code**
```bash
claude mcp add eu-pii-redact -e RAPIDAPI_KEY=your-key -- uvx eu-pii-redact
```

**Claude Desktop / Cursor / other hosts** (`mcpServers` config)
```json
{
  "mcpServers": {
    "eu-pii-redact": {
      "command": "uvx",
      "args": ["eu-pii-redact"],
      "env": { "RAPIDAPI_KEY": "your-key" }
    }
  }
}
```

## Postman

Fork the public collection from the
[EU PII Redaction workspace](https://www.postman.com/jejvks-team/eu-pii-redaction/overview) (or import
`postman/eu-pii-redaction.postman_collection.json`), set the collection variable `rapidapi_key`, and send:
four requests with example responses and built-in tests.

## Limits

Rule-based, which keeps it fast (about 0.1 s for 50,000 characters) and predictable:
no street addresses yet, phone numbers need an international prefix, and a name without
any cue whose surname is an English word ("Will Smith") is missed on purpose. Use it as a
strong first layer, not as a compliance guarantee.

## License

MIT for this client package. The API itself is a hosted service.
