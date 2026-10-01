"""LangChain integration: `pip install "eu-pii-redact[langchain]"`.

    from eu_pii_redact.langchain import protect, PIIRedactionTransformer

    safe_llm = protect(llm)                 # the model sees [PERSON_1]; the answer comes back restored
    safe_llm.invoke("Draft a reply to Karina Dahl about her refund to DK50 0040 0440 1162 43")

    docs = PIIRedactionTransformer().transform_documents(docs)   # e.g. before indexing for RAG
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Sequence

from langchain_core.documents import BaseDocumentTransformer, Document
from langchain_core.runnables import Runnable, RunnableConfig, RunnableLambda

from .client import Mode, Redactor


def protect(runnable: Runnable, *, redactor: Redactor | None = None,
            types: Iterable[str] | None = None) -> Runnable:
    """Wrap a model or chain that takes a string: personal data is replaced by placeholders before
    it is invoked, and the placeholders in its output (a string or a message) are restored."""
    types = list(types) if types is not None else None

    def _invoke(text: str, config: RunnableConfig | None = None) -> Any:
        if not isinstance(text, str):
            raise TypeError("protect() expects a string input; redact structured inputs before templating")
        red = redactor or Redactor()
        redaction = red.redact(text, types)
        result = runnable.invoke(redaction.text, config)
        if isinstance(result, str):
            return redaction.restore(result)
        content = getattr(result, "content", None)
        if isinstance(content, str) and hasattr(result, "model_copy"):
            return result.model_copy(update={"content": redaction.restore(content)})
        return result

    return RunnableLambda(_invoke, name="pii_protected")


class PIIRedactionTransformer(BaseDocumentTransformer):
    """Redact `page_content` of documents. Adds `pii_counts` to metadata; with
    `keep_mapping=True` also `pii_originals` (placeholder -> value), which then holds personal data."""

    def __init__(self, *, redactor: Redactor | None = None, types: Iterable[str] | None = None,
                 mode: Mode = "label", keep_mapping: bool = False):
        self._redactor = redactor
        self.types = list(types) if types is not None else None
        self.mode = mode
        self.keep_mapping = keep_mapping

    def transform_documents(self, documents: Sequence[Document], **kwargs: Any) -> Sequence[Document]:
        red = self._redactor or Redactor()
        out = []
        for doc in documents:
            r = red.redact(doc.page_content, self.types, self.mode)
            metadata = {**doc.metadata, "pii_counts": dict(Counter(e.type for e in r.entities))}
            if self.keep_mapping:
                metadata["pii_originals"] = r.originals
            out.append(Document(page_content=r.text, metadata=metadata, id=doc.id))
        return out
