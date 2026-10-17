"""Integration tests use temporary databases; external models are never called."""

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app import rag
from app.ingestion import DocumentError, extract
from app.main import create_app
from app.rag import Settings, retrieve
from app.store import Store


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "test.sqlite3", Settings())) as session:
        yield session


def question(client, text, **kwargs):
    response = client.post("/api/ask", json={"question": text, **kwargs})
    assert response.status_code == 200, response.text
    return response.json()


def test_demo_policies_are_seeded_once_and_deletion_survives_restart(tmp_path):
    path = tmp_path / "persistent.sqlite3"
    with TestClient(create_app(path, Settings())) as first:
        docs = first.get("/api/documents").json()
        assert len(docs) == 3
        assert all(doc["is_demo"] and doc["chunk_count"] > 4 for doc in docs)
        assert first.delete(f"/api/documents/{docs[0]['id']}").status_code == 204
    with TestClient(create_app(path, Settings())) as second:
        assert len(second.get("/api/documents").json()) == 2


@pytest.mark.parametrize(("prompt", "expected", "title"), [
    ("What is the waiting period for pre-existing conditions?", "36", "Meridian Health Plus"),
    ("What are the motor compulsory deductibles?", "1,000", "Horizon Comprehensive Motor"),
    ("What is the term life death benefit?", "10,000,000", "Evergreen Term Life"),
    ("What is excluded from maternity coverage?", "excluded", "Meridian Health Plus"),
    ("Does the car policy cover flood and engine damage?", "water ingress", "Horizon Comprehensive Motor"),
])
def test_retrieval_finds_the_answer_and_citable_source(client, prompt, expected, title):
    answer = question(client, prompt)
    assert answer["mode"] == "extractive"
    assert expected.lower() in answer["answer"].lower()
    assert title in {source["title"] for source in answer["sources"]}
    assert "[1]" in answer["answer"]
    assert all(source["text"] and source["section"] and source["page"] >= 1 for source in answer["sources"])


def test_scope_prevents_cross_policy_retrieval(client):
    life = next(doc for doc in client.get("/api/documents").json() if doc["category"] == "Life")
    answer = question(client, "What are the health policy hospitalization limits?", document_ids=[life["id"]])
    assert answer["mode"] == "no_evidence"
    assert not answer["sources"]
    answer = question(client, "What is the death benefit?", document_ids=[life["id"]])
    assert {source["document_id"] for source in answer["sources"]} == {life["id"]}


def test_named_insurance_category_is_respected_with_all_documents(client):
    answer = question(client, "What are the waiting periods in the health policy?")
    assert answer["sources"]
    assert {source["category"] for source in answer["sources"]} == {"Health"}
    comparison = question(client, "Compare health and life exclusions")
    assert {source["category"] for source in comparison["sources"]} == {"Health", "Life"}


def test_category_filter_keeps_uncategorized_uploaded_policies(client):
    result = client.post("/api/documents", files={"file": (
        "document.txt", b"Health policy endorsement: The oncology waiting period is 91 days.")})
    assert result.json()["document"]["category"] == "General"
    answer = question(client, "What is the health oncology waiting period?")
    assert "91" in answer["answer"]


def test_unknown_topic_abstains_instead_of_using_category_match(client):
    answer = question(client, "Does the motor policy cover teleportation?")
    assert answer["mode"] == "no_evidence"
    assert not answer["sources"]
    assert "couldn't find" in answer["answer"]


def test_upload_deduplicates_and_keeps_text_out_of_html(client):
    text = b"# Custom Home Policy\n\n## Glass replacement\nWindow glass replacement is covered up to INR 9,500 per incident. <script>alert('x')</script>"
    first = client.post("/api/documents", files={"file": ("../../home.md", text, "text/markdown")})
    assert first.status_code == 201
    doc = first.json()["document"]
    assert doc["filename"] == "home.md"
    assert not doc["is_demo"]
    second = client.post("/api/documents", files={"file": ("renamed.md", text)})
    assert second.json()["duplicate"] is True
    assert second.json()["document"]["id"] == doc["id"]
    answer = question(client, "What is the glass replacement limit?", document_ids=[doc["id"]])
    assert "9,500" in answer["answer"]
    assert len(client.get("/api/documents").json()) == 4


@pytest.mark.parametrize(("filename", "content"), [
    ("program.exe", b"MZ" * 100), ("blank.txt", b""),
    ("corrupt.pdf", b"not a pdf"), ("binary.txt", b"\x00" * 100),
    ("broken.docx", b"not a zip"), ("latin.txt", b"\xff" * 100),
])
def test_unreadable_uploads_fail_without_mutating_library(client, filename, content):
    result = client.post("/api/documents", files={"file": (filename, content)})
    assert result.status_code == 422
    assert len(client.get("/api/documents").json()) == 3


def test_oversize_upload_is_rejected(client):
    result = client.post("/api/documents", files={"file": ("large.txt", b"x" * (15 * 1024 * 1024 + 1))})
    assert result.status_code == 413


def test_docx_table_text_and_headings_are_extracted():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as docx:
        docx.writestr("word/document.xml", '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Equipment cover</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Equipment theft is covered up to INR 30,000 for each incident.</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>''')
    _, passages, _ = extract("equipment.docx", stream.getvalue())
    assert passages[0].section == "Equipment cover"
    assert "30,000" in passages[0].text


def test_scanned_and_password_protected_pdfs_have_actionable_errors():
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    stream = io.BytesIO()
    writer.write(stream)
    with pytest.raises(DocumentError, match="OCR"):
        extract("scan.pdf", stream.getvalue())
    writer.encrypt("secret")
    stream = io.BytesIO()
    writer.write(stream)
    with pytest.raises(DocumentError, match="password"):
        extract("locked.pdf", stream.getvalue())


def test_text_pdf_preserves_original_page_numbers(client):
    writer = PdfWriter()
    for text in ["Fictional equipment policy. The annual policy period is twelve months.",
                 "Portable scanner theft is covered up to INR 42,000 per incident."]:
        page = writer.add_blank_page(width=500, height=500)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 40 400 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    content = io.BytesIO()
    writer.write(content)
    uploaded = client.post("/api/documents", files={"file": ("equipment.pdf", content.getvalue())})
    assert uploaded.status_code == 201
    document_id = uploaded.json()["document"]["id"]
    answer = question(client, "What is the scanner theft limit?", document_ids=[document_id])
    assert "42,000" in answer["answer"]
    assert answer["sources"][0]["page"] == 2


def test_long_text_chunks_overlap_without_losing_end():
    text = "## Coverage\n" + ("The insured may submit supporting receipts. " * 100) + "The final special limit is INR 71,234."
    _, passages, _ = extract("long.md", text.encode())
    assert len(passages) > 3
    assert all(len(p.text) <= 1050 for p in passages)
    assert "71,234" in passages[-1].text


def test_history_persistence_and_clear_do_not_delete_documents(client):
    answer = question(client, "What are the pre-existing condition waiting periods?")
    history = client.get("/api/history").json()
    assert history[0]["id"] == answer["id"]
    assert history[0]["sources"] == answer["sources"]
    assert client.delete("/api/history").status_code == 204
    assert client.get("/api/history").json() == []
    assert len(client.get("/api/documents").json()) == 3


def test_deleted_document_passages_are_not_retrieved(client):
    health = next(doc for doc in client.get("/api/documents").json() if doc["category"] == "Health")
    assert client.delete(f"/api/documents/{health['id']}").status_code == 204
    assert client.get(f"/api/documents/{health['id']}").status_code == 404
    answer = question(client, "What is the co-payment for hospitalization?")
    assert not any(source["document_id"] == health["id"] for source in answer["sources"])
    assert client.post("/api/ask", json={"question": "What is the limit?", "document_ids": [health["id"]]}).status_code == 404


def test_invalid_question_limits_and_cross_origin_writes(client):
    assert client.post("/api/ask", json={"question": "   "}).status_code == 422
    assert client.post("/api/ask", json={"question": "What's covered?", "top_k": 100}).status_code == 422
    assert client.post("/api/ask", json={"question": "What's covered?"}, headers={"Origin": "https://example.com"}).status_code == 403
    assert client.get("/api/status", headers={"Host": "malicious.example"}).status_code == 400


def test_no_api_key_falls_back_honestly_without_network(tmp_path):
    with TestClient(create_app(tmp_path / "fallback.sqlite3", Settings(provider="openai"))) as client:
        answer = question(client, "What is the waiting period for pre-existing conditions?")
        assert answer["mode"] == "extractive"
        assert "OPENAI_API_KEY" in answer["notice"]
        assert "36" in answer["answer"]
        assert client.get("/api/status").json()["configured"] is False


@pytest.mark.parametrize(("output", "mode", "notice"), [
    ("The fictional policy has a 36-month waiting period. [1]", "openai", False),
    ("The limit is one million. [999]", "extractive", True),
    ("Coverage is unlimited with no exclusions.", "extractive", True),
])
def test_openai_wire_format_and_citation_validation(tmp_path, monkeypatch, output, mode, notice):
    real_client = httpx.AsyncClient

    def handler(request):
        assert str(request.url) == "https://api.openai.com/v1/responses"
        body = json.loads(request.content)
        assert body["store"] is False
        assert body["model"] == "test-model"
        assert "untrusted" in body["instructions"]
        assert "36" in body["input"]
        return httpx.Response(200, json={"status": "completed", "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": output}]},
        ]})

    monkeypatch.setattr(rag.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    with TestClient(create_app(tmp_path / "model.sqlite3", Settings(provider="openai", openai_key="test-placeholder", openai_model="test-model"))) as client:
        answer = question(client, "What is the waiting period for pre-existing conditions?")
        assert answer["mode"] == mode
        assert bool(answer["notice"]) is notice


def test_ollama_wire_format(tmp_path, monkeypatch):
    real_client = httpx.AsyncClient

    def handler(request):
        body = json.loads(request.content)
        assert str(request.url) == "http://127.0.0.1:11434/api/chat"
        assert body["stream"] is False
        assert body["messages"][0]["role"] == "system"
        return httpx.Response(200, json={"message": {"content": "The fictional waiting period is 36 months. [1]"}})

    monkeypatch.setattr(rag.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    with TestClient(create_app(tmp_path / "ollama.sqlite3", Settings(provider="ollama"))) as client:
        assert question(client, "What is the pre-existing condition waiting period?")["mode"] == "ollama"


def test_empty_library_and_api_status(tmp_path):
    with TestClient(create_app(tmp_path / "empty.sqlite3", Settings(), seed_demo=False)) as client:
        assert client.get("/api/status").json()["documents"] == 0
        assert question(client, "What is the coverage?")["mode"] == "no_evidence"
        assert client.get("/").status_code == 200
        assert "PolicyLens" in client.get("/").text
        assert "no-store" in client.get("/api/status").headers["cache-control"]
