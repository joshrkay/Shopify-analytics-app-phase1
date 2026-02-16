/**
 * Shared API Utilities
 *
 * Common functions for API service modules:
 * - Authentication token handling (supports Clerk)
 * - HTTP headers creation
 * - Response handling with error extraction
 * - Query string building
 *
 * Token Management:
 * - Uses Clerk's getToken() when available
 * - Falls back to localStorage for backwards compatibility
 */

export const API_BASE_URL = import.meta.env.VITE_API_URL || '';

const RETRYABLE_STATUS_CODES = new Set([429, 502, 503, 504]);

interface FetchRetryOptions {
  maxRetries?: number;
  baseDelayMs?: number;
  maxDelayMs?: number;
}

/**
 * API error with status and detail information.
 */
export interface ApiError extends Error {
  status: number;
  detail: string;
}

/**
 * Type guard to check if an error is an ApiError.
 * Use this instead of `instanceof ApiError` since ApiError is an interface.
 */
export function isApiError(err: unknown): err is ApiError {
  return err instanceof Error && 'status' in err && 'detail' in err;
}

/**
 * Token provider function type.
 * Can be async (for Clerk's getToken) or sync (for localStorage).
 */
type TokenProvider = () => Promise<string | null> | string | null;

/**
 * Global token provider.
 * Set this to Clerk's getToken function from a React component.
 */
let tokenProvider: TokenProvider | null = null;

/**
 * Set the token provider function.
 * Call this from a React component with Clerk's getToken.
 *
 * @example
 * // In a component:
 * const { getToken } = useAuth();
 * useEffect(() => {
 *   setTokenProvider(() => getToken());
 * }, [getToken]);
 */
export function setTokenProvider(provider: TokenProvider | null): void {
  tokenProvider = provider;
}

/**
 * Get the current JWT token.
 * Uses the token provider if set, otherwise falls back to localStorage.
 */
export async function getAuthTokenAsync(): Promise<string | null> {
  if (tokenProvider) {
    const token = await tokenProvider();
    if (token) return token;
  }
  // Fallback to localStorage
  return localStorage.getItem('jwt_token') || localStorage.getItem('auth_token');
}

/**
 * Get the current JWT token synchronously.
 * Only checks localStorage - use getAuthTokenAsync for Clerk tokens.
 * @deprecated Use getAuthTokenAsync for Clerk support
 */
export function getAuthToken(): string | null {
  return localStorage.getItem('jwt_token') || localStorage.getItem('auth_token');
}

/**
 * Set the JWT token in localStorage.
 * Used for backwards compatibility and token caching.
 */
export function setAuthToken(token: string): void {
  localStorage.setItem('jwt_token', token);
}

/**
 * Clear the JWT token from localStorage.
 */
export function clearAuthToken(): void {
  localStorage.removeItem('jwt_token');
  localStorage.removeItem('auth_token');
}

/**
 * Create headers with authentication (async version for Clerk).
 */
export async function createHeadersAsync(): Promise<HeadersInit> {
  const token = await getAuthTokenAsync();
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

/**
 * Create headers with authentication (sync version).
 * Uses localStorage token - for backwards compatibility.
 */
export function createHeaders(): HeadersInit {
  const token = getAuthToken();
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

// =============================================================================
// Fetch Retry Helper
// =============================================================================

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function getRetryDelayMs(
  response: Response | null,
  attempt: number,
  baseDelayMs: number,
  maxDelayMs: number,
): number {
  const retryAfter = response?.headers.get('retry-after');
  if (retryAfter) {
    const parsedSeconds = Number.parseInt(retryAfter, 10);
    if (!Number.isNaN(parsedSeconds) && parsedSeconds >= 0) {
      return Math.min(parsedSeconds * 1000, maxDelayMs);
    }

    const parsedDate = Date.parse(retryAfter);
    if (!Number.isNaN(parsedDate)) {
      const msUntilRetry = parsedDate - Date.now();
      if (msUntilRetry > 0) {
        return Math.min(msUntilRetry, maxDelayMs);
      }
    }
  }

  return Math.min(baseDelayMs * 2 ** attempt, maxDelayMs);
}

function isRetryableNetworkError(error: unknown): boolean {
  if (error instanceof DOMException && error.name === 'AbortError') {
    return false;
  }
  return error instanceof TypeError;
}

/**
 * Fetch wrapper with retry support for transient gateway/availability failures.
 *
 * Retries are intentionally limited to idempotent GET requests.
 */
export async function fetchWithRetry(
  input: RequestInfo | URL,
  init: RequestInit = {},
  options: FetchRetryOptions = {},
): Promise<Response> {
  const method = (init.method || 'GET').toUpperCase();
  if (method !== 'GET') {
    return fetch(input, init);
  }

  const maxRetries = options.maxRetries ?? 2;
  const baseDelayMs = options.baseDelayMs ?? 300;
  const maxDelayMs = options.maxDelayMs ?? 5000;

  for (let attempt = 0; attempt <= maxRetries; attempt += 1) {
    try {
      const response = await fetch(input, init);
      if (!RETRYABLE_STATUS_CODES.has(response.status) || attempt === maxRetries) {
        return response;
      }

      await sleep(getRetryDelayMs(response, attempt, baseDelayMs, maxDelayMs));
    } catch (error) {
      if (!isRetryableNetworkError(error) || attempt === maxRetries) {
        throw error;
      }
      await sleep(Math.min(baseDelayMs * 2 ** attempt, maxDelayMs));
    }
  }

  throw new Error('fetchWithRetry exhausted retries without returning a response.');
}

// =============================================================================
// API Circuit Breaker
// =============================================================================
// Tracks consecutive 5xx errors across ALL API calls. When the backend is down,
// this prevents every context/hook from independently flooding it with requests.

let _consecutiveServerErrors = 0;
let _lastServerErrorTs = 0;

/** Number of consecutive 5xx responses before the circuit opens. */
const CIRCUIT_OPEN_THRESHOLD = 3;
/** How long (ms) the circuit stays open before allowing a probe request. */
const CIRCUIT_OPEN_DURATION_MS = 30_000; // 30 seconds

function _recordServerError(): void {
  _consecutiveServerErrors++;
  _lastServerErrorTs = Date.now();
}

function _recordSuccess(): void {
  _consecutiveServerErrors = 0;
}

/**
 * Returns true when the backend appears down (too many consecutive 5xx errors).
 * After CIRCUIT_OPEN_DURATION_MS, the circuit enters half-open state to allow
 * a single probe request through.
 */
export function isBackendDown(): boolean {
  if (_consecutiveServerErrors < CIRCUIT_OPEN_THRESHOLD) return false;
  const elapsed = Date.now() - _lastServerErrorTs;
  if (elapsed > CIRCUIT_OPEN_DURATION_MS) {
    // Half-open: allow one request through to probe backend health
    _consecutiveServerErrors = CIRCUIT_OPEN_THRESHOLD - 1;
    return false;
  }
  return true;
}

/** Reset circuit breaker (e.g., after manual refresh action). */
export function resetCircuitBreaker(): void {
  _consecutiveServerErrors = 0;
}

/**
 * Handle API response and throw on error.
 * Extracts error details from the response body.
 */
export async function handleResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get('content-type') || '';
  const isJson = contentType.includes('application/json');

  if (!response.ok) {
    // Track server errors for circuit breaker
    if (response.status >= 500) {
      _recordServerError();
    }

    let errorDetail = `API error: ${response.status}`;

    if (isJson) {
      const errorData = await response.json().catch(() => ({}));
      errorDetail = errorData.detail || errorDetail;
      // For 503s, include the backend error type for diagnostics
      if (response.status === 503 && errorData.error_type) {
        errorDetail += ` (${errorData.error_type})`;
      }
    } else {
      const raw = await response.text().catch(() => '');
      if (raw.includes('<!DOCTYPE') || raw.includes('<html')) {
        errorDetail = 'Received HTML instead of API JSON. Check API base URL and backend deployment.';
      }
    }

    const error = new Error(errorDetail) as ApiError;
    error.status = response.status;
    error.detail = errorDetail;
    throw error;
  }

  // Successful response — reset circuit breaker
  _recordSuccess();

  if (!isJson) {
    const raw = await response.text().catch(() => '');
    const error = new Error(
      raw.includes('<!DOCTYPE') || raw.includes('<html')
        ? 'Received HTML instead of API JSON. Check API base URL and backend deployment.'
        : 'Unexpected non-JSON response from API.',
    ) as ApiError;
    error.status = response.status;
    error.detail = error.message;
    throw error;
  }

  return response.json();
}

/**
 * Build query string from a filters object.
 * Handles undefined values and converts booleans/numbers to strings.
 */
export function buildQueryString<T extends object>(filters: T): string {
  const params = new URLSearchParams();

  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null) {
      params.append(key, String(value));
    }
  }

  const queryString = params.toString();
  return queryString ? `?${queryString}` : '';
}

/**
 * Get the HTTP status code from an error, or null if not an API error.
 */
export function getErrorStatus(err: unknown): number | null {
  return isApiError(err) ? err.status : null;
}

/**
 * Map API error to a user-friendly message with status-specific defaults.
 *
 * Provides distinct messages for:
 * - 402: Plan limit / upgrade required
 * - 403: Permission denied
 * - 404: Resource not found
 * - 409: Concurrent edit conflict
 * - 422: Validation error
 *
 * The backend's `detail` field always takes priority when present.
 */
export function getErrorMessage(err: unknown, fallback: string): string {
  if (!isApiError(err)) {
    return err instanceof Error ? err.message : fallback;
  }

  switch (err.status) {
    case 402:
      return err.detail || 'You\'ve reached your plan limit. Upgrade to continue.';
    case 403:
      return err.detail || 'You don\'t have permission to perform this action.';
    case 404:
      return err.detail || 'The requested resource was not found.';
    case 409:
      return err.detail || 'This resource was modified by another user. Please reload and try again.';
    case 422:
      return err.detail || 'Invalid input. Please check your data and try again.';
    default:
      return err.detail || err.message || fallback;
  }
}
