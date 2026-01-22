# AI Growth Analytics - Backend Makefile
# Provides common commands for development and testing

.PHONY: help install test test-unit test-regression test-billing test-platform lint format clean

# Default target
help:
	@echo "AI Growth Analytics - Backend Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install       Install dependencies"
	@echo ""
	@echo "Testing:"
	@echo "  make test          Run all tests"
	@echo "  make test-unit     Run unit tests only"
	@echo "  make test-regression  Run billing regression tests"
	@echo "  make test-billing  Run all billing-related tests"
	@echo "  make test-platform Run platform tests"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint          Run linter (ruff)"
	@echo "  make format        Auto-format code"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean         Remove cached files"

# =============================================================================
# Setup
# =============================================================================

install:
	pip install -r requirements.txt
	pip install pytest pytest-asyncio pytest-mock pytest-cov pytest-timeout ruff

# =============================================================================
# Testing
# =============================================================================

test:
	PYTHONPATH=. pytest src/tests/ -v --tb=short

test-unit:
	PYTHONPATH=. pytest src/tests/integration/ src/tests/platform/ -v --tb=short -m "not regression"

test-regression:
	@echo "Running Billing Regression Tests..."
	PYTHONPATH=. pytest src/tests/regression/test_billing_regression.py \
		-v \
		--tb=short \
		-m "regression" \
		--timeout=600

test-billing:
	@echo "Running All Billing Tests..."
	PYTHONPATH=. pytest \
		src/tests/integration/test_billing.py \
		src/tests/regression/test_billing_regression.py \
		-v \
		--tb=short \
		--cov=src/services/billing_service \
		--cov=src/api/routes/webhooks_shopify \
		--cov=src/integrations/shopify/billing_client \
		--cov-report=term-missing

test-platform:
	@echo "Running Platform Tests..."
	PYTHONPATH=. pytest src/tests/platform/ \
		-v \
		--tb=short \
		--cov=src/platform \
		--cov=src/repositories \
		--cov-report=term-missing

# =============================================================================
# Code Quality
# =============================================================================

lint:
	ruff check src/

format:
	ruff format src/

# =============================================================================
# Utilities
# =============================================================================

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".coverage" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "coverage.xml" -delete 2>/dev/null || true
	rm -rf htmlcov/ 2>/dev/null || true
