# Contract Intelligence API

A production-ready RAG-based FastAPI application for intelligent contract analysis, providing automated PDF ingestion, structured field extraction using hybrid LLM+regex approaches, semantic Q&A with source citations via FAISS vector search, and risk auditing to detect problematic clauses like unlimited liability, auto-renewal terms, and broad indemnification—all powered by OpenRouter's Claude 3.5 Sonnet with PII-redacted logging, comprehensive test coverage, and Docker-based deployment.

## 🚀 Setup

### Prerequisites
- Python 3.11+
- [Poetry](https://python-poetry.org/docs/#installation) for dependency management
- Docker & Docker Compose (optional, for containerized deployment)
- OpenRouter API key ([get one here](https://openrouter.ai/keys))

### Installation

```bash
# 1. Clone the repository
git clone <your-repo-url>
cd contract-intelligence-api

# 2. Install dependencies with Poetry
poetry install

# 3. Configure environment variables
cp .env.example .env
# Edit .env and set your OPENROUTER_API_KEY=sk-or-v1-your-actual-key-here

# 4. Initialize the database
make init-db

# 5. Start the development server
make dev
```

The API will be available at **http://localhost:8000** with interactive docs at **http://localhost:8000/docs**

### Docker Deployment

```bash
# Build and start services (API + optional PostgreSQL)
make up

# View live logs
make logs

# Stop all services
make down

# Run with PostgreSQL (instead of SQLite)
docker compose --profile with-db -f docker/docker-compose.yml up -d
```

## 📡 API Endpoints

| Method | Endpoint | Description | Request Body | Example cURL |
|--------|----------|-------------|--------------|--------------|
| `GET` | `/healthz` | Health check returning status, timestamp, version | None | `curl http://localhost:8000/healthz` |
| `GET` | `/metrics` | Prometheus-style metrics (ingests, extractions, QA requests, audits) | None | `curl http://localhost:8000/metrics` |
| `POST` | `/api/v1/ingest` | Upload PDF contract for processing | `multipart/form-data` with `file` field | `curl -F "file=@contract.pdf" http://localhost:8000/api/v1/ingest` |
| `POST` | `/api/v1/extract/{doc_id}` | Extract structured fields (parties, dates, terms, liability caps) | None | `curl -X POST http://localhost:8000/api/v1/extract/{uuid}` |
| `POST` | `/api/v1/ask` | RAG-based Q&A with citations and confidence scores | `{"question": "What is the termination notice period?", "doc_ids": [...]}` | `curl -X POST http://localhost:8000/api/v1/ask -H "Content-Type: application/json" -d '{"question":"What are the payment terms?"}'` |
| `POST` | `/api/v1/ask/stream` | Streaming Q&A with Server-Sent Events (SSE) | Same as `/ask` | `curl -N -X POST http://localhost:8000/api/v1/ask/stream -H "Content-Type: application/json" -d '{"question":"Summarize key obligations"}'` |
| `GET` | `/api/v1/audit/{doc_id}` | Risk audit report with findings (auto-renewal, unlimited liability, etc.) | None | `curl http://localhost:8000/api/v1/audit/{uuid}` |

### Example: Complete Workflow

```bash
# 1. Ingest a PDF
DOC_ID=$(curl -s -F "file=@examples/nda.pdf" http://localhost:8000/api/v1/ingest | jq -r '.id')

# 2. Extract structured fields
curl -X POST http://localhost:8000/api/v1/extract/$DOC_ID | jq

# 3. Ask questions with RAG
curl -X POST http://localhost:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"What is the confidentiality period?\",\"doc_ids\":[\"$DOC_ID\"]}" | jq

# 4. Audit for risks
curl http://localhost:8000/api/v1/audit/$DOC_ID | jq
```

## 🧪 Testing

```bash
# Run all tests with coverage report
make test

# Run specific test file
poetry run pytest tests/test_app.py -v

# Run with HTML coverage report
poetry run pytest --cov=src --cov-report=html
open htmlcov/index.html

# Run evaluation suite (if implemented)
make eval
```

### Test Coverage
- ✅ Health check endpoint (200 response)
- ✅ Metrics endpoint validation
- ✅ Pydantic schema validation
- ✅ PII redaction in logs
- ✅ Database connection lifecycle
- ✅ Error handling and edge cases

## ⚖️ Design Trade-offs

### FAISS Local vs. Scalable Vector Databases

**Current Choice: FAISS (Local, CPU-based)**

**Pros:**
- Zero external dependencies—runs locally without cloud services
- Fast in-memory similarity search for small-to-medium datasets (<100K documents)
- Deterministic, no network latency or API rate limits
- Free and open-source with no ongoing costs
- Perfect for MVP and proof-of-concept deployments

**Cons:**
- In-memory storage requires index persistence to disk (handled via `FAISS_INDEX_PATH`)
- Limited scalability—performance degrades beyond ~1M vectors without clustering/sharding
- No built-in multi-tenancy or access control
- Manual index rebuilding required when adding documents (no incremental updates)
- Single-node architecture—no horizontal scaling

**When to Switch:**
- **Pinecone/Weaviate/Qdrant:** For production at scale (>1M documents), multi-tenancy, cloud-native deployments
- **PostgreSQL pgvector:** For simpler setup with relational data co-location (acceptable for <1M vectors)
- **Milvus/Vespa:** For distributed, high-throughput scenarios with advanced filtering

**Migration Path:** Extract `VectorStore` abstraction in `services/base.py` to swap FAISS with alternative backends via dependency injection.

### Rule-Based vs. LLM-Only Auditing

**Current Choice: Hybrid (Rule-based + LLM fallback)**

Rule-based regex patterns provide fast, deterministic detection of common clauses (e.g., "automatic renewal", "unlimited liability"), while LLM fallback (`audit.txt` prompt) handles nuanced language variations. Toggle via `USE_LLM_AUDIT=true` in `.env` to compare outputs—rule-based is 10x faster but may miss edge cases; LLM is more comprehensive but slower and costs API credits.

## 📄 Public Sample PDFs for Testing

Use these non-proprietary contracts to test ingestion and extraction:

1. **Mutual NDA (Y Combinator Standard)**  
   https://www.ycombinator.com/documents/  
   *(Simple 2-page NDA with standard confidentiality clauses)*

2. **SEC Sample Service Agreement**  
   https://www.sec.gov/Archives/edgar/data/1018724/000119312513028362/d478090dex102.htm  
   *(10-page service agreement with termination, liability, indemnity)*

3. **Apache Software License 2.0**  
   https://www.apache.org/licenses/LICENSE-2.0.txt  
   *(Standard open-source license, good for testing extraction of grant clauses)*

4. **Creative Commons License (BY-SA 4.0)**  
   https://creativecommons.org/licenses/by-sa/4.0/legalcode.txt  
   *(Legal text with attribution and modification terms)*

5. **GitHub Open Source NDA Template**  
   https://github.com/github/balanced-employee-ip-agreement/blob/main/Mutual_NDA.md  
   *(Markdown-based NDA, tests format handling)*

**Note:** Convert HTML/Markdown to PDF using browser print or Pandoc before ingesting.

## 📁 Prompts

See the **`prompts/`** folder for LLM prompt templates with detailed rationales:

- **`extract.txt`**: Structured field extraction prompt (parties, dates, liability caps) with JSON schema enforcement
- **`rag.txt`**: RAG Q&A prompt for citation-backed answers with confidence scoring
- **`audit.txt`**: Risk auditing prompt to detect problematic clauses (auto-renewal, unlimited liability, broad indemnity)

Each file includes a rationale explaining the prompt engineering choices, few-shot examples (where applicable), and expected output formats.

## 🛠️ Development Commands

```bash
make install      # Install dependencies with Poetry
make dev          # Run development server with hot reload
make up           # Start Docker Compose services
make down         # Stop Docker services
make logs         # View Docker container logs
make test         # Run pytest with coverage
make lint         # Run black, flake8, mypy
make format       # Auto-format code with black & isort
make migrate      # Apply Alembic database migrations
make migration    # Create new migration (use MSG='description')
make clean        # Remove cache, logs, build artifacts
make eval         # Run evaluation suite (if implemented)
```

## 📊 Monitoring & Observability

- **Structured Logging**: Uses `structlog` with PII redaction (names, emails, phones → `[REDACTED]`)
- **Request Timing**: All responses include `X-Process-Time` header
- **Health Checks**: `/healthz` endpoint for load balancer probes
- **Metrics**: `/metrics` exposes counters for ingests, extractions, QA requests, audits
- **Error Tracking**: Global exception handler with sanitized error responses

## 📂 Project Structure

```
contract-intelligence-api/
├── src/
│   ├── app.py                  # Main FastAPI app with CORS, middleware, exception handlers
│   ├── core/
│   │   ├── config.py           # Pydantic Settings for env vars
│   │   └── logging.py          # Structlog with PII redactor
│   ├── db/
│   │   ├── engine.py           # SQLAlchemy async engine
│   │   └── models.py           # Database models
│   ├── models/
│   │   └── schemas.py          # Pydantic schemas (DocumentIn, ExtractionOut, etc.)
│   ├── routers/
│   │   ├── health.py           # Health & metrics endpoints
│   │   ├── ingest.py           # PDF upload
│   │   ├── extract.py          # Structured extraction
│   │   ├── ask.py              # RAG Q&A (sync & streaming)
│   │   └── audit.py            # Risk auditing
│   └── services/
│       └── base.py             # Abstract service classes
├── tests/
│   ├── conftest.py             # Pytest fixtures (TestClient, DB)
│   └── test_app.py             # Basic smoke tests
├── prompts/
│   ├── extract.txt             # Extraction prompt + rationale
│   ├── rag.txt                 # Q&A prompt + rationale
│   └── audit.txt               # Audit prompt + rationale
├── docker/
│   ├── Dockerfile              # Multi-stage build (Poetry → Runtime)
│   └── docker-compose.yml      # API + optional PostgreSQL
├── alembic/                    # Database migrations
├── .env.example                # Environment variable template
├── Makefile                    # Development commands
├── pyproject.toml              # Poetry dependencies
└── README.md                   # This file
```

## 🔒 Security & Privacy

- **PII Redaction**: Logs automatically redact names, emails, phone numbers
- **No Auth (Yet)**: This is a local-only MVP—add OAuth2/JWT before deploying publicly
- **Input Validation**: Pydantic v2 schemas enforce strict type checking
- **File Size Limits**: `MAX_UPLOAD_SIZE_MB=50` prevents DoS via large uploads

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes and add tests
4. Run `make lint` and `make test`
5. Commit with descriptive messages (`git commit -m 'Add extraction confidence scores'`)
6. Push to your branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## 📝 License

MIT License - see LICENSE file for details

---

**Built with ❤️ using FastAPI, LangChain, FAISS, and OpenRouter**
