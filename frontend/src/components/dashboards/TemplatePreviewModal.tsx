/**
 * TemplatePreviewModal Component
 *
 * Modal for previewing a template before instantiation.
 * Features:
 * - Template name, description, category, and required datasets display
 * - Dashboard name input field
 * - "Create Dashboard" button that instantiates the template
 * - Navigates to the dashboard edit page upon success
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Modal,
  FormLayout,
  TextField,
  BlockStack,
  InlineStack,
  Button,
  Banner,
  Badge,
  Text,
  Divider,
} from '@shopify/polaris';
import { instantiateTemplate } from '../../services/templatesApi';
import type { ReportTemplate } from '../../types/customDashboards';
import { getTemplateCategoryLabel } from '../../types/customDashboards';

interface TemplatePreviewModalProps {
  template: ReportTemplate;
  open: boolean;
  onClose: () => void;
}

export function TemplatePreviewModal({
  template,
  open,
  onClose,
}: TemplatePreviewModalProps) {
  const navigate = useNavigate();

  const [dashboardName, setDashboardName] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Initialize dashboard name with template name
  useEffect(() => {
    if (open) {
      setDashboardName(template.name);
      setError(null);
    }
  }, [open, template.name]);

  const handleCreate = useCallback(async () => {
    const trimmedName = dashboardName.trim();

    if (!trimmedName) {
      setError('Dashboard name is required.');
      return;
    }

    setCreating(true);
    setError(null);

    try {
      const dashboard = await instantiateTemplate(template.id, trimmedName);
      onClose();
      navigate(`/dashboards/${dashboard.id}/edit`);
    } catch (err) {
      console.error('Failed to instantiate template:', err);
      setError(
        err instanceof Error ? err.message : 'Failed to create dashboard from template.',
      );
    } finally {
      setCreating(false);
    }
  }, [template.id, dashboardName, onClose, navigate]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Create dashboard from template"
    >
      <Modal.Section>
        <BlockStack gap="400">
          {error && (
            <Banner tone="critical" onDismiss={() => setError(null)}>
              {error}
            </Banner>
          )}

          {/* Template info */}
          <BlockStack gap="200">
            <InlineStack gap="200" blockAlign="center">
              <Text as="h3" variant="headingMd">
                {template.name}
              </Text>
              <Badge>{getTemplateCategoryLabel(template.category)}</Badge>
            </InlineStack>

            <Text as="p" variant="bodyMd" tone="subdued">
              {template.description}
            </Text>
          </BlockStack>

          {/* Template details */}
          <BlockStack gap="100">
            <Text as="p" variant="bodySm">
              {template.reports_json.length} report{template.reports_json.length !== 1 ? 's' : ''} included
            </Text>
            {template.required_datasets.length > 0 && (
              <Text as="p" variant="bodySm" tone="subdued">
                Required datasets: {template.required_datasets.join(', ')}
              </Text>
            )}
          </BlockStack>

          <Divider />

          {/* Dashboard name input */}
          <FormLayout>
            <TextField
              label="Dashboard name"
              value={dashboardName}
              onChange={setDashboardName}
              placeholder="My dashboard"
              autoComplete="off"
              requiredIndicator
              helpText="You can rename it later in dashboard settings."
            />
          </FormLayout>
        </BlockStack>
      </Modal.Section>

      <Modal.Section>
        <InlineStack align="end" gap="200">
          <Button onClick={onClose} disabled={creating}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleCreate}
            loading={creating}
            disabled={creating || !dashboardName.trim()}
          >
            Create dashboard
          </Button>
        </InlineStack>
      </Modal.Section>
    </Modal>
  );
}
