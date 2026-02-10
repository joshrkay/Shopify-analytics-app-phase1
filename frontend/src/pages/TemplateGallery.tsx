/**
 * TemplateGallery Page
 *
 * Displays available report templates in a filterable grid.
 * Features:
 * - Category filter dropdown (sales, marketing, customer, product, operations)
 * - Grid of TemplateCards showing name, description, and category
 * - Template preview modal for instantiation
 * - Loading and error states
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Page,
  Layout,
  BlockStack,
  InlineStack,
  Select,
  Spinner,
  Banner,
  Text,
  InlineGrid,
} from '@shopify/polaris';
import { listTemplates } from '../services/templatesApi';
import { TemplateCard } from '../components/dashboards/TemplateCard';
import { TemplatePreviewModal } from '../components/dashboards/TemplatePreviewModal';
import type {
  ReportTemplate,
  TemplateCategory,
} from '../types/customDashboards';

const CATEGORY_OPTIONS: { label: string; value: string }[] = [
  { label: 'All categories', value: '' },
  { label: 'Sales', value: 'sales' },
  { label: 'Marketing', value: 'marketing' },
  { label: 'Customer', value: 'customer' },
  { label: 'Product', value: 'product' },
  { label: 'Operations', value: 'operations' },
];

export function TemplateGallery() {
  const [templates, setTemplates] = useState<ReportTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState('');
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);

  // Fetch templates
  useEffect(() => {
    let cancelled = false;

    async function fetchTemplates() {
      setLoading(true);
      setError(null);

      try {
        const filters = categoryFilter
          ? { category: categoryFilter as TemplateCategory }
          : {};
        const response = await listTemplates(filters);
        if (!cancelled) {
          setTemplates(response.templates);
        }
      } catch (err) {
        if (!cancelled) {
          console.error('Failed to fetch templates:', err);
          setError(
            err instanceof Error ? err.message : 'Failed to load templates',
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchTemplates();

    return () => {
      cancelled = true;
    };
  }, [categoryFilter]);

  const handleUseTemplate = useCallback((templateId: string) => {
    setSelectedTemplateId(templateId);
  }, []);

  const handleClosePreview = useCallback(() => {
    setSelectedTemplateId(null);
  }, []);

  const selectedTemplate = selectedTemplateId
    ? templates.find((t) => t.id === selectedTemplateId) ?? null
    : null;

  return (
    <Page
      title="Template Gallery"
      subtitle="Start with a pre-built template to quickly create your dashboard"
      breadcrumbs={[{ content: 'Dashboards', url: '/dashboards' }]}
    >
      <Layout>
        <Layout.Section>
          <BlockStack gap="400">
            {/* Category filter */}
            <InlineStack align="start">
              <div style={{ width: '250px' }}>
                <Select
                  label="Category"
                  labelHidden
                  options={CATEGORY_OPTIONS}
                  value={categoryFilter}
                  onChange={setCategoryFilter}
                />
              </div>
            </InlineStack>

            {/* Error */}
            {error && (
              <Banner tone="critical" onDismiss={() => setError(null)}>
                {error}
              </Banner>
            )}

            {/* Loading */}
            {loading && (
              <InlineStack gap="200" blockAlign="center" align="center">
                <Spinner size="large" />
                <Text as="p" variant="bodyMd" tone="subdued">
                  Loading templates...
                </Text>
              </InlineStack>
            )}

            {/* Empty state */}
            {!loading && !error && templates.length === 0 && (
              <BlockStack gap="200" inlineAlign="center">
                <Text as="p" variant="bodyMd" tone="subdued">
                  No templates found
                  {categoryFilter ? ' for this category' : ''}.
                </Text>
              </BlockStack>
            )}

            {/* Template grid */}
            {!loading && templates.length > 0 && (
              <InlineGrid columns={{ xs: 1, sm: 2, md: 3 }} gap="400">
                {templates.map((template) => (
                  <TemplateCard
                    key={template.id}
                    template={template}
                    onUse={handleUseTemplate}
                  />
                ))}
              </InlineGrid>
            )}
          </BlockStack>
        </Layout.Section>
      </Layout>

      {/* Preview modal */}
      {selectedTemplate && (
        <TemplatePreviewModal
          template={selectedTemplate}
          open={selectedTemplateId !== null}
          onClose={handleClosePreview}
        />
      )}
    </Page>
  );
}
