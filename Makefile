.PHONY: help install up down logs lint format test migrate clean

help:
	@echo "Contract Intelligence API - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  install     Install dependencies with Poetry"
	@echo "  init-db     Initialize database with Alembic"
	@echo ""
	@echo "Development:"
	@echo "  dev         Run local development server"
	@echo "  up          Start Docker Compose services"
	@echo "  down        Stop Docker Compose services"
	@echo "  logs        Show Docker logs"
	@echo ""
	@echo "Code Quality:"
	@echo "  lint        Run black, flake8, and mypy"
	@echo "  format      Format code with black and isort"
	@echo "  test        Run pytest with coverage"
	@echo ""
	@echo "Database:"
	@echo "  migrate     Run Alembic migrations"
	@echo "  migration   Create new migration (use MSG='description')"
	@echo ""
	@echo "Cleanup:"
	@echo "  clean       Remove cache, logs, and build artifacts"

install:
	poetry install

dev:
	poetry run uvicorn src.app:app --reload --host 0.0.0.0 --port 8000

up:
	docker compose -f docker/docker-compose.yml up -d
	@echo "API running at http://localhost:8000"
	@echo "Docs at http://localhost:8000/docs"

down:
	docker compose -f docker/docker-compose.yml down

logs:
	docker compose -f docker/docker-compose.yml logs -f

lint:
	poetry run black --check src/ tests/
	poetry run isort --check-only src/ tests/
	poetry run flake8 src/ tests/
	poetry run mypy src/

format:
	poetry run black src/ tests/
	poetry run isort src/ tests/

test:
	poetry run pytest tests/ -v --cov=src --cov-report=term-missing

migrate:
	poetry run alembic upgrade head

migration:
	@if [ -z "$(MSG)" ]; then echo "Usage: make migration MSG='description'"; exit 1; fi
	poetry run alembic revision --autogenerate -m "$(MSG)"

init-db:
	poetry run alembic upgrade head

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.log" -delete
	rm -rf .pytest_cache/ .coverage htmlcov/ .mypy_cache/
	rm -f app.db
