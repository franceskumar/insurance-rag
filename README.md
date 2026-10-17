# PolicyLens · Insurance RAG

A runnable insurance document assistant with a FastAPI backend, local SQLite storage, BM25 retrieval, and a responsive browser interface. Upload your policies, ask a question, and inspect the cited passages behind the answer.

## Run

Requires Python 3.11 or newer.

```bash
cd insurance-rag
bash run.sh
```

Open **http://127.0.0.1:8011**. The launcher creates an isolated `.venv` and installs pinned dependencies. Set `PORT=8020 bash run.sh` to use another port.

Three fictional health, motor, and term life policies load on the first launch. The default **evidence mode** needs no API key or model download. It quotes complete matching passages with citations to preserve nearby exceptions and qualifications. This is extractive retrieval, not LLM-generated synthesis. Enable a model for the full retrieval-augmented generation pipeline.

## Features

- Upload text-based PDFs, DOCX (including table text), UTF-8 text, and Markdown; up to 15 MB per file.
- Section-aware, overlapping chunks with original PDF page numbers.
- BM25 passage ranking with basic insurance term normalization, explicit insurance-category filtering, and overlapping-result deduplication.
- Search all documents or scope a question to one policy.
- Clickable citations, source excerpts, full extracted-document previews, and insufficient-evidence responses.
- Durable document storage, file-content deduplication, recent questions, deletion, and Markdown conversation export.
- Explicit provider labels and an honest excerpt fallback if generation fails or citation IDs are invalid.
- Same-origin frontend and API, accessible controls, keyboard shortcuts, and responsive layouts.

## Enable generated answers

```bash
cp .env.example .env
```

Edit `.env` and restart the server. Environment variables take precedence over `.env`.

### Local model with Ollama

Install and run [Ollama](https://docs.ollama.com/quickstart), then download a model:

```bash
ollama pull llama3.2
```

Set:

```dotenv
ANSWER_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.2
```

Only the retrieved excerpts and question are sent to the configured Ollama server. Configure a server you control. Model downloads and inference require additional disk space and memory.

### OpenAI

Set your own key and an API model ID available to your account:

```dotenv
ANSWER_PROVIDER=openai
OPENAI_API_KEY=your-key
OPENAI_MODEL=your-model-id
```

This provider sends the question and selected policy excerpts to the [OpenAI Responses API](https://developers.openai.com/api/docs/guides/text), with `store: false`. API usage may incur charges. Keys stay in server-side configuration and are never returned to the browser. This project does not use your connected GitHub credentials or ChatGPT sign-in as an API key.

## Architecture

```text
Browser UI
   │ upload                       │ question + document scope
   ▼                              ▼
FastAPI → PDF / DOCX / text      BM25 retrieval
             │                       │
         section chunks          ranked source passages
             │                       │
             ▼                       ▼
           SQLite ←──────── evidence excerpts / optional LLM
                                     │
                            citation ID validation
                                     │
                          answer + source snapshots → UI
```

| File | Purpose |
| --- | --- |
| `app/main.py` | API routes, startup, local-host and origin checks, static frontend |
| `app/ingestion.py` | Bounded parsing, section extraction, overlapping chunks |
| `app/store.py` | Transactional SQLite persistence and deduplication |
| `app/rag.py` | Query normalization, BM25, prompt, providers, citation checks, fallback |
| `app/static/` | Buildless HTML/CSS/JavaScript interface with no remote assets |
| `sample_policies/` | Fictional demonstration documents |
| `tests/test_app.py` | Isolated integration tests with mock model responses |

All questions are independent retrieval requests. Recent answers are saved for reference; conversational pronoun resolution and implicit follow-up context are not implemented. Name the topic or policy explicitly in a follow-up question.

This project deliberately uses lexical BM25 retrieval. It does not claim semantic embeddings, a vector database, or a reranker. This keeps the default installation small and offline. For a larger corpus, add an embedding index and evaluation-driven reranking before scaling.

## API

Interactive API documentation: `http://127.0.0.1:8011/docs` (the JSON schema is at `/openapi.json`). The locally hosted UI is fully offline. Swagger UI loads third-party assets and may need internet access.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/status` | Counts and public provider configuration |
| GET / POST | `/api/documents` | List documents / upload one multipart `file` |
| GET / DELETE | `/api/documents/{id}` | Read extracted passages / delete document and index |
| POST | `/api/ask` | Answer `question` with optional `document_ids` and `top_k` |
| GET / DELETE | `/api/history` | List up to 50 recent answers / clear all stored history |

```bash
curl http://127.0.0.1:8011/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is the waiting period for pre-existing conditions?","top_k":5}'
```

## Verify

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Tests use temporary databases and mocked HTTP responses, with no paid API calls. They cover retrieval, policy scope, abstention, upload failures and deduplication, PDF errors, DOCX table text, chunk boundaries, persistent deletion, history, provider request shapes, citation validation, and origin checks.

## Data and limits

Runtime data is in `data/policylens.sqlite3`, including policy text and question/answer history. Original uploaded binaries are not retained; extracted text is retained. Deleting a policy removes its indexed text but **does not erase excerpts already saved in question history**. Clear recent questions to erase those snapshots. Uploaded files, database files, `.env`, and the virtual environment are Git-ignored.

PDFs must contain selectable text. OCR, image interpretation, DOCX physical pagination, embedded objects, and tracked-change interpretation are not supported. Extraction limits are 500 PDF pages and two million text characters. DOCX text is read in document order, including table cells; it does not reconstruct a table's visual relationships.

This is a **single-user local development app**, bound to `127.0.0.1`. It has no authentication, access controls between users, managed backups, malware scanner, or deployment service. Keep it local; add those capabilities before hosting it for other users. BM25 runs over the indexed corpus in memory on each question and is intended for a small library.

Generated answers can be wrong even when they cite valid sources. The application validates citation numbers, not full semantic support for every claim. The prompt treats document contents as untrusted evidence, but this is not a complete defense against prompt injection. No tools or business actions are exposed to the model. The default excerpt mode only quotes retrieved text. Low-relevance abstention is heuristic, so some partially related passages can still be returned.

The samples are invented solely for testing and are not insurance offers or financial advice. Use the actual policy schedule and wording to verify any coverage decision.

## GitHub

The application and launcher do not access GitHub or change Git credentials. Runtime data and server credentials are excluded by `.gitignore`.
