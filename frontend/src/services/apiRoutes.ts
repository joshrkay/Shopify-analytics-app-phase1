/**
 * Canonical frontend API route constants.
 *
 * Centralizes endpoint paths to prevent drift between services.
 */

export const API_ROUTES = {
  templates: '/api/v1/templates',
  datasets: '/api/datasets',
  datasetsPreview: '/api/datasets/preview',
} as const;
