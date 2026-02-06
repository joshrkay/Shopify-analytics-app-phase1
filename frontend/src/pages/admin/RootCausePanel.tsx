/**
 * Root Cause Diagnostics Panel (Operator Only)
 *
 * Renders root cause diagnostics for operators:
 * - Timeline of events
 * - Ranked hypothesis list with confidence visualization
 * - Evidence details and links to logs, dbt runs, sync history
 * - Suggested investigation steps
 *
 * Story 4.2 - Data Quality Root Cause Signals (Prompt 4.2.7)
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Page,
  Layout,
  Card,
  Banner,
  Badge,
  Spinner,
  Text,
  BlockStack,
  InlineStack,
  ProgressBar,
  Divider,
  Button,
  Select,
  Box,
  Link,
} from '@shopify/polaris';
import { RefreshIcon } from '@shopify/polaris-icons';

import {
  getDiagnostics,
  runDiagnostics,
  getCauseTypeLabel,
  getConfidenceTone,
  formatConfidence,
} from '../../services/diagnosticsApi';
import type {
  DiagnosticsSignal,
  RankedCause,
  EvidenceLink,
} from '../../services/diagnosticsApi';

// =============================================================================
// Sub-components
// =============================================================================

function ConfidenceBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const tone = getConfidenceTone(score);

  const toneColor: Record<string, string> = {
    critical: 'critical',
    warning: 'highlight',
    attention: 'primary',
    success: 'success',
  };

  return (
    <InlineStack gap="200" align="center" blockAlign="center">
      <div style={{ width: 120 }}>
        <ProgressBar
          progress={pct}
          tone={toneColor[tone] as 'primary' | 'success' | 'critical' | 'highlight'}
          size="small"
        />
      </div>
      <Badge tone={tone}>{formatConfidence(score)}</Badge>
    </InlineStack>
  );
}

function EvidenceLinkList({ links }: { links: EvidenceLink[] }) {
  if (!links.length) return null;

  return (
    <BlockStack gap="100">
      <Text variant="bodySm" fontWeight="semibold" as="p">
        Evidence
      </Text>
      {links.map((link, idx) => (
        <InlineStack gap="100" key={idx}>
          <Badge tone="info">{link.link_type}</Badge>
          <Text variant="bodySm" as="span">
            {link.label}
            {link.resource_id && (
              <Text variant="bodySm" tone="subdued" as="span">
                {' '}({link.resource_id})
              </Text>
            )}
          </Text>
        </InlineStack>
      ))}
    </BlockStack>
  );
}

function EvidenceDetails({ evidence }: { evidence: Record<string, unknown> }) {
  const entries = Object.entries(evidence).filter(
    ([key]) => key !== 'signal'
  );
  if (!entries.length) return null;

  return (
    <BlockStack gap="100">
      <Text variant="bodySm" fontWeight="semibold" as="p">
        Details
      </Text>
      <Box padding="200" background="bg-surface-secondary" borderRadius="200">
        <BlockStack gap="050">
          {entries.map(([key, value]) => (
            <InlineStack gap="200" key={key}>
              <Text variant="bodySm" tone="subdued" as="span">
                {key}:
              </Text>
              <Text variant="bodySm" as="span">
                {typeof value === 'object'
                  ? JSON.stringify(value)
                  : String(value)}
              </Text>
            </InlineStack>
          ))}
        </BlockStack>
      </Box>
    </BlockStack>
  );
}

function HypothesisCard({ cause }: { cause: RankedCause }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <Card>
      <BlockStack gap="300">
        <InlineStack align="space-between" blockAlign="center">
          <InlineStack gap="200" blockAlign="center">
            <Badge>{`#${cause.rank}`}</Badge>
            <Text variant="headingSm" as="h3">
              {getCauseTypeLabel(cause.cause_type)}
            </Text>
            {cause.evidence.signal && (
              <Badge tone="info">{String(cause.evidence.signal)}</Badge>
            )}
          </InlineStack>
          <ConfidenceBar score={cause.confidence_score} />
        </InlineStack>

        <Text variant="bodyMd" as="p">
          {cause.suggested_next_step}
        </Text>

        {cause.first_seen_at && (
          <Text variant="bodySm" tone="subdued" as="p">
            First seen: {new Date(cause.first_seen_at).toLocaleString()}
          </Text>
        )}

        <Button
          variant="plain"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? 'Hide details' : 'Show details'}
        </Button>

        {expanded && (
          <BlockStack gap="300">
            <Divider />
            <EvidenceDetails evidence={cause.evidence} />
            <EvidenceLinkList links={cause.evidence_links} />
          </BlockStack>
        )}
      </BlockStack>
    </Card>
  );
}

function TimelineEvent({ signal }: { signal: DiagnosticsSignal }) {
  const detected = new Date(signal.anomaly_summary.detected_at);
  const topCause = signal.ranked_causes[0];

  return (
    <Box padding="300" background="bg-surface-secondary" borderRadius="200">
      <InlineStack align="space-between" blockAlign="center">
        <InlineStack gap="200" blockAlign="center">
          <Badge tone={signal.is_active ? 'attention' : 'success'}>
            {signal.is_active ? 'Active' : 'Resolved'}
          </Badge>
          <Text variant="bodySm" fontWeight="semibold" as="span">
            {signal.anomaly_summary.anomaly_type}
          </Text>
          {topCause && (
            <Text variant="bodySm" tone="subdued" as="span">
              Top cause: {getCauseTypeLabel(topCause.cause_type)} (
              {formatConfidence(topCause.confidence_score)})
            </Text>
          )}
        </InlineStack>
        <Text variant="bodySm" tone="subdued" as="span">
          {detected.toLocaleString()}
        </Text>
      </InlineStack>
    </Box>
  );
}

// =============================================================================
// Main Component
// =============================================================================

const DATASET_OPTIONS = [
  { label: 'shopify_orders', value: 'shopify_orders' },
  { label: 'shopify_refunds', value: 'shopify_refunds' },
  { label: 'meta_ads', value: 'meta_ads' },
  { label: 'google_ads', value: 'google_ads' },
  { label: 'tiktok_ads', value: 'tiktok_ads' },
  { label: 'klaviyo', value: 'klaviyo' },
];

export default function RootCausePanel() {
  const [dataset, setDataset] = useState('shopify_orders');
  const [signals, setSignals] = useState<DiagnosticsSignal[]>([]);
  const [selectedSignal, setSelectedSignal] = useState<DiagnosticsSignal | null>(
    null
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);

  const loadSignals = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const result = await getDiagnostics(dataset, {
        activeOnly: false,
        limit: 20,
      });
      setSignals(result.signals);
      if (result.signals.length > 0 && !selectedSignal) {
        setSelectedSignal(result.signals[0]);
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to load diagnostics'
      );
    } finally {
      setLoading(false);
    }
  }, [dataset]);

  useEffect(() => {
    setSelectedSignal(null);
    loadSignals();
  }, [loadSignals]);

  const handleAnalyze = async () => {
    setAnalyzing(true);
    setError(null);

    try {
      const result = await runDiagnostics(dataset, 'manual_analysis');
      setSelectedSignal(result);
      await loadSignals();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to run analysis'
      );
    } finally {
      setAnalyzing(false);
    }
  };

  return (
    <Page
      title="Root Cause Diagnostics"
      subtitle="Operator-grade root cause analysis for data quality anomalies"
      secondaryActions={[
        {
          content: 'Refresh',
          icon: RefreshIcon,
          onAction: loadSignals,
        },
      ]}
    >
      <Layout>
        {error && (
          <Layout.Section>
            <Banner tone="critical" onDismiss={() => setError(null)}>
              <p>{error}</p>
            </Banner>
          </Layout.Section>
        )}

        {/* Controls */}
        <Layout.Section>
          <Card>
            <InlineStack gap="400" align="start" blockAlign="end">
              <div style={{ width: 250 }}>
                <Select
                  label="Dataset"
                  options={DATASET_OPTIONS}
                  value={dataset}
                  onChange={setDataset}
                />
              </div>
              <Button
                onClick={handleAnalyze}
                loading={analyzing}
                variant="primary"
              >
                Run Analysis
              </Button>
            </InlineStack>
          </Card>
        </Layout.Section>

        {loading ? (
          <Layout.Section>
            <div style={{ textAlign: 'center', padding: '40px' }}>
              <Spinner size="large" />
            </div>
          </Layout.Section>
        ) : (
          <>
            {/* Timeline */}
            <Layout.Section>
              <Card>
                <BlockStack gap="300">
                  <Text variant="headingMd" as="h2">
                    Event Timeline
                  </Text>
                  {signals.length === 0 ? (
                    <Banner>
                      <p>
                        No root cause signals for {dataset}. Run an analysis or
                        wait for automated detection.
                      </p>
                    </Banner>
                  ) : (
                    <BlockStack gap="200">
                      {signals.map((sig) => (
                        <div
                          key={sig.signal_id}
                          onClick={() => setSelectedSignal(sig)}
                          style={{
                            cursor: 'pointer',
                            borderLeft:
                              selectedSignal?.signal_id === sig.signal_id
                                ? '3px solid var(--p-color-border-interactive)'
                                : '3px solid transparent',
                            paddingLeft: '8px',
                          }}
                          role="button"
                          tabIndex={0}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') setSelectedSignal(sig);
                          }}
                        >
                          <TimelineEvent signal={sig} />
                        </div>
                      ))}
                    </BlockStack>
                  )}
                </BlockStack>
              </Card>
            </Layout.Section>

            {/* Selected Signal Detail */}
            {selectedSignal && (
              <>
                {/* Ranked Hypotheses */}
                <Layout.Section>
                  <BlockStack gap="400">
                    <Text variant="headingMd" as="h2">
                      Ranked Hypotheses
                    </Text>
                    <Text variant="bodySm" tone="subdued" as="p">
                      Signal: {selectedSignal.signal_id} | Hypotheses:{' '}
                      {selectedSignal.total_hypotheses} | Confidence sum:{' '}
                      {formatConfidence(selectedSignal.confidence_sum)}
                    </Text>
                    {selectedSignal.ranked_causes.length === 0 ? (
                      <Banner>
                        <p>
                          No root causes detected. This anomaly may require
                          manual investigation.
                        </p>
                      </Banner>
                    ) : (
                      selectedSignal.ranked_causes.map((cause) => (
                        <HypothesisCard key={cause.rank} cause={cause} />
                      ))
                    )}
                  </BlockStack>
                </Layout.Section>

                {/* Investigation Steps */}
                <Layout.Section>
                  <Card>
                    <BlockStack gap="300">
                      <Text variant="headingMd" as="h2">
                        Investigation Steps
                      </Text>
                      <BlockStack gap="200">
                        {selectedSignal.investigation_steps.map(
                          (step, idx) => (
                            <InlineStack gap="200" key={idx} blockAlign="start">
                              <Badge>{String(idx + 1)}</Badge>
                              <Text variant="bodyMd" as="p">
                                {step}
                              </Text>
                            </InlineStack>
                          )
                        )}
                      </BlockStack>
                    </BlockStack>
                  </Card>
                </Layout.Section>
              </>
            )}
          </>
        )}
      </Layout>
    </Page>
  );
}
