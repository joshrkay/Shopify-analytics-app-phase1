# E2E Testing Quick Start for Claude Cowork

## Your Task
Fix E2E tests that fail due to third-party service issues. When a test fails:

1. **Run the failing test** to see the error:
```bash
cd backend && PYTHONPATH=. pytest src/tests/e2e/<test_file>::<test_name> -v --tb=long
```

2. **Identify the service** from the error:
- "Connection refused" → Service not mocked
- "401 Unauthorized" → Auth token issue
- "404 Not Found" → Endpoint doesn't exist
- "Missing env var" → Configuration issue

3. **Look up documentation** for the failing service:

| Service | Docs | Required Env Vars |
|---------|------|-------------------|
| Frontegg | https://docs.frontegg.com/ | FRONTEGG_CLIENT_ID, FRONTEGG_CLIENT_SECRET |
| Airbyte | https://reference.airbyte.com/ | AIRBYTE_API_TOKEN, AIRBYTE_WORKSPACE_ID |
| Shopify | https://shopify.dev/docs/api | SHOPIFY_API_KEY, SHOPIFY_API_SECRET |
| OpenRouter | https://openrouter.ai/docs | OPENROUTER_API_KEY |

4. **Fix the issue**:
- For auth: Check `backend/src/tests/e2e/mocks/mock_frontegg.py` issuer matches `https://api.frontegg.com`
- For missing endpoints: Check `backend/src/tests/e2e/mocks/` for the relevant mock
- For env vars: Add to `backend/src/tests/e2e/conftest.py` using `os.environ.setdefault()`

5. **Verify the fix**:
```bash
pytest src/tests/e2e/<test_file>::<test_name> -v --tb=short
```

## Key Files
- `backend/src/tests/e2e/conftest.py` - Test fixtures and mocks
- `backend/src/tests/e2e/mocks/mock_frontegg.py` - Auth mocking
- `backend/src/tests/e2e/mocks/mock_airbyte.py` - Data sync mocking
- `backend/src/tests/e2e/mocks/mock_shopify.py` - Shopify API mocking

## Current Test Status
- 21 passing, 8 failing, 7 skipped
- Remaining failures need: Airbyte client injection, missing webhook endpoints

## Full Prompts
See `docs/E2E_IMPLEMENTATION_PROMPTS.md` for detailed implementation prompts.
