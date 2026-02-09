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

/**
 * Handle API response and throw on error.
 * Extracts error details from the response body.
 */
export async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    const error = new Error(errorData.detail || `API error: ${response.status}`) as ApiError;
    error.status = response.status;
    error.detail = errorData.detail;
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
