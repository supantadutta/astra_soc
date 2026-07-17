# ASTRASOC — developer commands
.DEFAULT_GOAL := help
API := apps/api
WEB := apps/web

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Install API + web dependencies
	cd $(API) && pip install -r requirements-dev.txt
	cd $(WEB) && npm install

.PHONY: dev
dev: ## Run API (:8000) and web (:3000) locally
	cd $(API) && uvicorn astrasoc.main:app --reload --port 8000 & \
	cd $(WEB) && npm run dev

.PHONY: dev-api
dev-api: ## Run the API only
	cd $(API) && uvicorn astrasoc.main:app --reload --port 8000

.PHONY: dev-web
dev-web: ## Run the web app only
	cd $(WEB) && npm run dev

.PHONY: demo
demo: ## Start the full demo stack in Docker (SQLite, no creds)
	docker compose -f docker-compose.demo.yml up --build

.PHONY: test
test: test-api ## Run all tests (API unit/integration + web typecheck)
	cd $(WEB) && npm run typecheck

.PHONY: test-api
test-api: ## Run the backend test suite
	cd $(API) && python -m pytest -q

.PHONY: test-e2e
test-e2e: ## Run Playwright end-to-end tests (requires running servers)
	cd $(WEB) && npx playwright test

.PHONY: lint
lint: ## Lint API (ruff) and web (eslint)
	cd $(API) && ruff check astrasoc
	cd $(WEB) && npm run lint

.PHONY: typecheck
typecheck: ## Type-check API (mypy) and web (tsc)
	cd $(API) && mypy astrasoc || true
	cd $(WEB) && npm run typecheck

.PHONY: build
build: ## Production build validation (web build + API import check)
	cd $(WEB) && npm run build
	cd $(API) && python -c "import astrasoc.main; print('API imports OK')"

.PHONY: demo-seed
demo-seed: ## Seed demo data (idempotent; runs automatically on API startup)
	cd $(API) && python -m astrasoc.scripts.seed

.PHONY: demo-reset
demo-reset: ## Reset & reseed demo data (DEMO-scoped only)
	cd $(API) && python -m astrasoc.scripts.reset

.PHONY: clean
clean: ## Remove caches, build artifacts and local dbs
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(WEB)/.next $(WEB)/test-results $(WEB)/playwright-report $(API)/astrasoc.db
	rm -rf .ruff_cache .pytest_cache $(API)/.mypy_cache
