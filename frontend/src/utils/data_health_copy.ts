/**
 * data_health_copy.ts
 *
 * Merchant-safe messaging for data health states.
 * All merchant-visible text for the unified trust layer lives here.
 *
 * Health states:
 * - 'healthy': All data current, all features enabled
 * - 'delayed': Some data delayed, AI insights paused
 * - 'unavailable': Data temporarily unavailable, dashboards blocked
 *
 * CRITICAL: No internal system names (dbt, Airbyte, RLS, SLA, etc.)
 * may appear in any copy string. No speculation or root cause guesses.
 *
 * Story 4.3 - Merchant Data Health Trust Layer
 */

/**
 * Merchant-facing data health states.
 */
export type MerchantHealthState = 'healthy' | 'delayed' | 'unavailable';

/**
 * Returns a short label for the merchant health state.
 * Suitable for badges and compact indicators.
 */
export function getMerchantHealthLabel(state: MerchantHealthState): string {
  switch (state) {
    case 'healthy':
      return 'Up to date';
    case 'delayed':
      return 'Data delayed';
    case 'unavailable':
      return 'Unavailable';
  }
}

/**
 * Returns the primary merchant-facing message for the health state.
 * This is the main copy shown in banners and the API response.
 */
export function getMerchantHealthMessage(state: MerchantHealthState): string {
  switch (state) {
    case 'healthy':
      return 'Your data is up to date.';
    case 'delayed':
      return 'Some data is delayed. Reports may be incomplete.';
    case 'unavailable':
      return 'Your data is temporarily unavailable.';
  }
}

/**
 * Returns a banner title for the given health state.
 * Empty string for 'healthy' since no banner is shown.
 */
export function getMerchantHealthBannerTitle(
  state: MerchantHealthState,
): string {
  switch (state) {
    case 'healthy':
      return '';
    case 'delayed':
      return 'Data Update in Progress';
    case 'unavailable':
      return 'Data Temporarily Unavailable';
  }
}

/**
 * Returns a longer banner body message explaining the impact.
 * Written in plain English, action-oriented, no blame.
 */
export function getMerchantHealthBannerMessage(
  state: MerchantHealthState,
): string {
  switch (state) {
    case 'healthy':
      return '';
    case 'delayed':
      return (
        'Some of your data is being refreshed. You can still view reports, ' +
        'but some numbers may not be fully current. AI insights are paused ' +
        'until the update completes.'
      );
    case 'unavailable':
      return (
        'We are unable to display your data right now. ' +
        'This usually resolves on its own. If it persists, please contact support.'
      );
  }
}

/**
 * Returns tooltip text explaining the impact of the health state.
 * Focuses on what the merchant can or cannot do, not the cause.
 */
export function getMerchantHealthTooltip(state: MerchantHealthState): string {
  switch (state) {
    case 'healthy':
      return 'All your data is current and all features are available.';
    case 'delayed':
      return (
        'Data is being updated. Reports are available but may be slightly ' +
        'behind. AI insights will resume once the update finishes.'
      );
    case 'unavailable':
      return (
        'Data is temporarily unavailable. Reports and exports are paused. ' +
        'This usually resolves automatically.'
      );
  }
}

/**
 * Returns the Polaris Badge tone for the given health state.
 */
export function getMerchantHealthBadgeTone(
  state: MerchantHealthState,
): 'success' | 'attention' | 'critical' {
  switch (state) {
    case 'healthy':
      return 'success';
    case 'delayed':
      return 'attention';
    case 'unavailable':
      return 'critical';
  }
}

/**
 * Returns the Polaris Banner tone for the given health state.
 */
export function getMerchantHealthBannerTone(
  state: MerchantHealthState,
): 'info' | 'warning' | 'critical' {
  switch (state) {
    case 'healthy':
      return 'info';
    case 'delayed':
      return 'warning';
    case 'unavailable':
      return 'critical';
  }
}

/**
 * Returns feature availability flags for the given health state.
 */
export function getMerchantHealthFeatures(state: MerchantHealthState): {
  aiInsightsEnabled: boolean;
  dashboardsEnabled: boolean;
  exportsEnabled: boolean;
} {
  switch (state) {
    case 'healthy':
      return {
        aiInsightsEnabled: true,
        dashboardsEnabled: true,
        exportsEnabled: true,
      };
    case 'delayed':
      return {
        aiInsightsEnabled: false,
        dashboardsEnabled: true,
        exportsEnabled: false,
      };
    case 'unavailable':
      return {
        aiInsightsEnabled: false,
        dashboardsEnabled: false,
        exportsEnabled: false,
      };
  }
}
