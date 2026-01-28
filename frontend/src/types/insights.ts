/**
 * TypeScript types for AI Insights
 *
 * Story 9.3 - Insight & Recommendation UX
 */

export type InsightType =
  | 'spend_anomaly'
  | 'roas_change'
  | 'ctr_change'
  | 'cpc_change'
  | 'conversion_change'
  | 'budget_pacing'
  | 'performance_trend';

export type InsightSeverity = 'info' | 'warning' | 'critical';

export interface SupportingMetric {
  metric: string;
  previous: number | null;
  current: number | null;
  change: number | null;
  change_pct: number | null;
}

export interface Insight {
  insight_id: string;
  insight_type: InsightType;
  severity: InsightSeverity;
  summary: string;
  why_it_matters: string | null;
  supporting_metrics: SupportingMetric[];
  timeframe: string;
  confidence_score: number;
  platform: string | null;
  campaign_id: string | null;
  currency: string | null;
  generated_at: string;
  is_read: boolean;
  is_dismissed: boolean;
}

export interface InsightsListResponse {
  insights: Insight[];
  total: number;
  has_more: boolean;
}

export interface InsightActionResponse {
  status: string;
  insight_id: string;
}

export interface InsightsFilters {
  insight_type?: InsightType;
  severity?: InsightSeverity;
  include_dismissed?: boolean;
  include_read?: boolean;
  limit?: number;
  offset?: number;
}

/**
 * Get display label for insight type
 */
export function getInsightTypeLabel(type: InsightType): string {
  const labels: Record<InsightType, string> = {
    spend_anomaly: 'Spend Anomaly',
    roas_change: 'ROAS Change',
    ctr_change: 'CTR Change',
    cpc_change: 'CPC Change',
    conversion_change: 'Conversion Change',
    budget_pacing: 'Budget Pacing',
    performance_trend: 'Performance Trend',
  };
  return labels[type] || type;
}

/**
 * Get severity color tone for Polaris components
 */
export function getSeverityTone(severity: InsightSeverity): 'info' | 'warning' | 'critical' {
  return severity;
}
