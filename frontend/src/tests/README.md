# Frontend Tests

This directory contains tests for the Shopify Analytics frontend application.

## Test Structure

```
tests/
├── setup.ts                    # Test environment configuration
├── integration/                # Integration tests
│   └── embeddedApp.test.tsx   # Full embedded app flow tests
└── README.md                  # This file

lib/__tests__/                 # Utility function tests
├── shopifyAppBridge.test.ts   # App Bridge utilities
└── redirects.test.ts          # Redirect utilities

hooks/__tests__/               # React hook tests
└── useShopifySession.test.tsx # Session token hook

components/__tests__/          # Component tests
├── ProtectedRoute.test.tsx    # Route protection
└── AppRouter.test.tsx         # App routing
```

## Running Tests

```bash
# Run all tests
npm test

# Run tests in watch mode
npm test -- --watch

# Run tests with UI
npm run test:ui

# Run tests with coverage
npm run test:coverage
```

## Test Coverage

### Unit Tests
- **shopifyAppBridge.test.ts**: Tests for embedded detection, host extraction, redirects, and config
- **redirects.test.ts**: Tests for OAuth redirects and navigation utilities
- **useShopifySession.test.tsx**: Tests for session token hook including caching, refresh, and error handling

### Component Tests
- **ProtectedRoute.test.tsx**: Tests for route protection, authentication checks, and redirects
- **AppRouter.test.tsx**: Tests for route matching, navigation, and default paths

### Integration Tests
- **embeddedApp.test.tsx**: Tests for complete embedded app flow including App Bridge initialization and session token handling

## Test Requirements

All tests must:
- Be deterministic (no flaky tests)
- Cover acceptance criteria from user stories
- Run in CI without manual intervention
- Have clear, descriptive names

## Mocking

Tests use Vitest mocking for:
- `@shopify/app-bridge-react` - App Bridge context
- `@shopify/app-bridge-utils` - Session token utilities
- `window.location` and `window.history` - Browser APIs
- Environment variables - Configuration

## Writing New Tests

When adding new features:

1. Add unit tests for utility functions
2. Add component tests for React components
3. Add integration tests for user flows
4. Ensure tests cover acceptance criteria
5. Keep tests isolated and independent

## CI Integration

Tests run automatically on:
- Every PR (must pass before merge)
- Every merge to main
- Before production deployments
