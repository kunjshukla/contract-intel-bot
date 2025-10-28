# Contract Intelligence API - Setup Guide

## Quick Start

Follow these steps to get the Contract Intelligence API up and running.

### 1. Install Dependencies

```bash
# Install Poetry (if not installed)
curl -sSL https://install.python-poetry.org | python3 -

# Install project dependencies
poetry install
```

### 2. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env and add your OpenRouter API key
# OPENROUTER_API_KEY=sk-or-v1-your-actual-key-here
```

### 3. Initialize Database

```bash
# Create initial migration
poetry run alembic revision --autogenerate -m "Initial schema"

# Apply migrations
make migrate
```

### 4. Run Development Server

```bash
# Start the server
make dev

# Server will start at http://localhost:8000
```

### 5. Verify Installation

```bash
# Test health endpoint
curl http://localhost:8000/healthz

# Expected response:
# {"status":"ok","timestamp":"2025-10-28T...","version":"0.1.0"}

# View API documentation
open http://localhost:8000/docs
```

## Docker Deployment

```bash
# Build and start services
make up

# View logs
make logs

# Stop services
make down

# Run with PostgreSQL
docker compose --profile with-db -f docker/docker-compose.yml up -d
```

## Development Workflow

```bash
# Format code
make format

# Run linters
make lint

# Run tests
make test

# Create new migration
make migration MSG="add new table"

# Apply migrations
make migrate
```

## Project Structure

```
contract-intelligence-api/
├── src/
│   ├── app.py                  # FastAPI application
│   ├── core/
│   │   ├── config.py          # Configuration management
│   │   └── logging.py         # Structured logging with PII redaction
│   ├── db/
│   │   ├── engine.py          # Database engine and session
│   │   └── models.py          # SQLAlchemy ORM models
│   ├── models/
│   │   └── schemas.py         # Pydantic validation schemas
│   ├── routers/
│   │   ├── health.py          # Health check and metrics
│   │   ├── ingest.py          # Document ingestion (TODO)
│   │   ├── extract.py         # Field extraction (TODO)
│   │   ├── ask.py             # RAG Q&A (TODO)
│   │   └── audit.py           # Risk auditing (TODO)
│   └── services/
│       └── base.py            # Abstract service class
├── tests/
│   ├── conftest.py            # Pytest fixtures
│   └── test_app.py            # Basic API tests
├── alembic/                    # Database migrations
├── docker/                     # Docker configuration
├── pyproject.toml             # Poetry dependencies
├── Makefile                   # Development commands
└── README.md                  # Project documentation
```

## Next Steps

### Implement Core Features

1. **Document Ingestion Service**
   - PDF parsing with PyMuPDF
   - Text chunking (semantic + fixed-size)
   - OpenAI embeddings via OpenRouter
   - FAISS index creation

2. **Extraction Service**
   - LLM prompts for structured fields
   - Regex fallbacks for dates/parties
   - Hybrid confidence scoring

3. **RAG Q&A Service**
   - FAISS similarity search
   - LLM reranking
   - Citation extraction

4. **Risk Audit Service**
   - Rule-based clause detection
   - LLM-enhanced severity scoring

### Production Hardening

- Add authentication (API keys, JWT)
- Implement rate limiting
- Add Prometheus metrics integration
- Set up structured logging to files/ELK
- Add error monitoring (Sentry)
- Configure HTTPS/TLS

## Testing

```bash
# Run all tests with coverage
make test

# Run specific test file
poetry run pytest tests/test_app.py -v

# View coverage report
open htmlcov/index.html
```

## Troubleshooting

### Database Issues

```bash
# Reset database
rm -f app.db
make init-db
```

### Dependency Issues

```bash
# Clear cache and reinstall
poetry cache clear pypi --all
poetry install
```

### Port Already in Use

```bash
# Find and kill process on port 8000
lsof -ti:8000 | xargs kill -9

# Or use different port
poetry run uvicorn src.app:app --port 8001
```

## Support

For issues and questions:
- Check the README.md for API documentation
- Review the DESIGN.md for architecture details
- Open an issue on GitHub

---

**Built with ❤️ using FastAPI, OpenRouter, and FAISS**
