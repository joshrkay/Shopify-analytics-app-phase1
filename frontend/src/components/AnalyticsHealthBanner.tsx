/**
 * Analytics Health Banner
 *
 * Polaris Banner component displayed when analytics is temporarily unavailable.
 * Does NOT leak error details to users - only shows a generic message.
 * Emits audit events to backend for incident tracking (fire-and-forget).
 *
 * Phase 4 - Fallback UX
 */

import React, { useEffect, useRef } from 'react';
import { Banner, Button, Spinner, InlineStack } from '@shopify/polaris';
import { API_BASE_URL } from '../services/apiUtils';
import type { AccessSurface } from '../types/embed';

export interface AnalyticsHealthBannerProps {
  /** Retry callback */
  onRetry: () => void;
  /** Show spinner on retry button while retrying */
  isRetrying?: boolean;
  /** Error type for audit logging - NOT displayed to user */
  errorType?: string;
  /** Access surface for audit logging */
  accessSurface?: AccessSurface;
}

/**
 * Report a health incident to the backend.
 * Fire-and-forget: does not await response and does not throw on failure.
 */
function reportHealthIncident(errorType: string, accessSurface: string): void {
  try {
    fetch(`${API_BASE_URL}/embed/health/incident`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        error_type: errorType,
        access_surface: accessSurface,
      }),
    }).catch(() => {
      // Silently ignore - fire-and-forget
    });
  } catch {
    // Silently ignore - fire-and-forget
  }
}

/**
 * AnalyticsHealthBanner Component
 *
 * Displays a warning banner when analytics is temporarily unavailable.
 * Provides a retry button and reports incidents to backend audit log.
 */
export const AnalyticsHealthBanner: React.FC<AnalyticsHealthBannerProps> = ({
  onRetry,
  isRetrying = false,
  errorType = 'unknown',
  accessSurface = 'shopify_embed',
}) => {
  const incidentReportedRef = useRef(false);

  // Report health incident on mount (fire-and-forget, only once)
  useEffect(() => {
    if (!incidentReportedRef.current) {
      incidentReportedRef.current = true;
      reportHealthIncident(errorType, accessSurface);
    }
  }, [errorType, accessSurface]);

  return (
    <Banner
      title="Analytics temporarily unavailable"
      tone="warning"
    >
      <p>We're retrying. You can also try manually.</p>
      <div style={{ marginTop: '12px' }}>
        <InlineStack gap="200" blockAlign="center">
            {isRetrying && <Spinner size="small" />}
            <Button onClick={onRetry} disabled={isRetrying}>
              {isRetrying ? 'Retrying...' : 'Retry'}
            </Button>
          </InlineStack>
      </div>
    </Banner>
  );
};

export default AnalyticsHealthBanner;
