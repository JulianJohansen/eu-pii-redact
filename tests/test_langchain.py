import pytest

pytest.importorskip("langchain_core")

from langchain_core.documents import Document  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.runnables import RunnableLambda  # noqa: E402

from eu_pii_redact.langchain import PIIRedactionTransformer, protect  # noqa: E402


def test_protect_hides_pii_from_the_model_and_restores_the_answer(redactor):
    seen = []

    def fake_llm(prompt: str) -> AIMessage:
        seen.append(prompt)
        return AIMessage(content="Hi [PERSON_1], refunded to [IBAN_1].")

    safe = protect(RunnableLambda(fake_llm), redactor=redactor)
    answer = safe.invoke("Reply to Karina Dahl about her refund to DK50 0040 0440 1162 43.")
    assert seen == ["Reply to [PERSON_1] about her refund to [IBAN_1]."]
    assert answer.content == "Hi Karina Dahl, refunded to DK50 0040 0440 1162 43."


def test_protect_restores_plain_string_output(redactor):
    safe = protect(RunnableLambda(lambda p: p.upper()), redactor=redactor)
    assert safe.invoke("Dear Mr Hansen,") == "DEAR MR Hansen,"


def test_transformer_redacts_documents(redactor):
    docs = [Document(page_content="Karina Dahl, karina@example.com", metadata={"source": "crm"}, id="1")]
    out = PIIRedactionTransformer(redactor=redactor).transform_documents(docs)
    assert out[0].page_content == "[PERSON_1], [EMAIL_1]"
    assert out[0].metadata == {"source": "crm", "pii_counts": {"PERSON": 1, "EMAIL": 1}}
    assert out[0].id == "1"


def test_transformer_can_keep_mapping(redactor):
    docs = [Document(page_content="Mail karina@example.com")]
    out = PIIRedactionTransformer(redactor=redactor, keep_mapping=True).transform_documents(docs)
    assert out[0].metadata["pii_originals"] == {"[EMAIL_1]": "karina@example.com"}
