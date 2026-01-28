/**
 * TypeScript types for AI Recommendations
 *
 * Story 9.3 - Insight & Recommendation UX
 */

export type RecommendationType =
  | 'pause_campaign'
  | 'increase_budget'
  | 'decrease_budget'
  | 'adjust_bid'
  | 'expand_targeting'
  | 'narrow_targeting'
  | 'creative_refresh'
  | 'schedule_adjustment';

export type RecommendationPriority = 'low' | 'medium' | 'high';

export type EstimatedImpact = 'minimal' | 'moderate' | 'significant';

export type RiskLevel = 'low' | 'medium' | 'high';

export interface Recommendation {
  recommendation_id: string;
  related_insight_id: string;
  recommendation_type: RecommendationType;
  priority: RecommendationPriority;
  recommendation_text: string;
  rationale: string | null;
  estimated_impact: EstimatedImpact;
  risk_level: RiskLevel;
  confidence_score: number;
  affected_entity: string | null;
  affected_entity_type: string | null;
  currency: string | null;
  generated_at: string;
  is_accepted: boolean;
  is_dismissed: boolean;
}

export interface RecommendationsListResponse {
  recommendations: Recommendation[];
  total: number;
  has_more: boolean;
}

export interface RecommendationActionResponse {
  status: string;
  recommendation_id: string;
}

export interface RecommendationsFilters {
  recommendation_type?: RecommendationType;
  priority?: RecommendationPriority;
  risk_level?: RiskLevel;
  related_insight_id?: string;
  include_dismissed?: boolean;
  include_accepted?: boolean;
  limit?: number;
  offset?: number;
}

/**
 * Get display label for recommendation type
 */
export function getRecommendationTypeLabel(type: RecommendationType): string {
  const labels: Record<RecommendationType, string> = {
    pause_campaign: 'Pause Campaign',
    increase_budget: 'Increase Budget',
    decrease_budget: 'Decrease Budget',
    adjust_bid: 'Adjust Bid',
    expand_targeting: 'Expand Targeting',
    narrow_targeting: 'Narrow Targeting',
    creative_refresh: 'Refresh Creative',
    schedule_adjustment: 'Adjust Schedule',
  };
  return labels[type] || type;
}

/**
 * Get priority badge tone
 */
export function getPriorityTone(priority: RecommendationPriority): 'info' | 'warning' | 'critical' {
  const tones: Record<RecommendationPriority, 'info' | 'warning' | 'critical'> = {
    low: 'info',
    medium: 'warning',
    high: 'critical',
  };
  return tones[priority];
}

/**
 * Get risk level badge tone
 */
export function getRiskTone(risk: RiskLevel): 'info' | 'warning' | 'critical' {
  const tones: Record<RiskLevel, 'info' | 'warning' | 'critical'> = {
    low: 'info',
    medium: 'warning',
    high: 'critical',
  };
  return tones[risk];
}
