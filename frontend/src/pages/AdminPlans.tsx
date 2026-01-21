/**
 * Admin Plans Management Page
 *
 * Allows admins to:
 * - View all pricing plans
 * - Create new plans
 * - Edit existing plans (price, features)
 * - Toggle features on/off
 * - Validate Shopify plan sync
 *
 * Changes apply instantly without deployment.
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Page,
  Layout,
  Card,
  DataTable,
  Button,
  Modal,
  TextField,
  FormLayout,
  Checkbox,
  Banner,
  Badge,
  Spinner,
  Text,
  BlockStack,
  InlineStack,
  Divider,
  Select,
  Icon,
} from '@shopify/polaris';
import {
  PlusIcon,
  EditIcon,
  DeleteIcon,
  RefreshIcon,
  CheckIcon,
  XIcon,
} from '@shopify/polaris-icons';

import { plansApi, ApiError } from '../services/plansApi';
import type {
  Plan,
  PlanFeature,
  CreatePlanRequest,
  UpdatePlanRequest,
} from '../types/plans';

// Common feature definitions
const AVAILABLE_FEATURES = [
  { key: 'ai_insights', label: 'AI Insights' },
  { key: 'custom_reports', label: 'Custom Reports' },
  { key: 'export_data', label: 'Data Export' },
  { key: 'api_access', label: 'API Access' },
  { key: 'team_members', label: 'Team Members' },
  { key: 'priority_support', label: 'Priority Support' },
  { key: 'custom_branding', label: 'Custom Branding' },
  { key: 'advanced_analytics', label: 'Advanced Analytics' },
];

interface PlanFormData {
  name: string;
  display_name: string;
  description: string;
  price_monthly_cents: string;
  price_yearly_cents: string;
  shopify_plan_id: string;
  is_active: boolean;
  features: Record<string, { enabled: boolean; limit: string }>;
}

const initialFormData: PlanFormData = {
  name: '',
  display_name: '',
  description: '',
  price_monthly_cents: '',
  price_yearly_cents: '',
  shopify_plan_id: '',
  is_active: true,
  features: AVAILABLE_FEATURES.reduce(
    (acc, f) => ({ ...acc, [f.key]: { enabled: false, limit: '' } }),
    {}
  ),
};

export default function AdminPlans() {
  // State
  const [plans, setPlans] = useState<Plan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Modal state
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [selectedPlan, setSelectedPlan] = useState<Plan | null>(null);

  // Form state
  const [formData, setFormData] = useState<PlanFormData>(initialFormData);
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  // Include inactive plans toggle
  const [includeInactive, setIncludeInactive] = useState(false);

  // Load plans
  const loadPlans = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await plansApi.listPlans({
        include_inactive: includeInactive,
        limit: 100,
      });
      setPlans(response.plans);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.detail || err.message
          : 'Failed to load plans';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [includeInactive]);

  useEffect(() => {
    loadPlans();
  }, [loadPlans]);

  // Clear messages after 5 seconds
  useEffect(() => {
    if (successMessage) {
      const timer = setTimeout(() => setSuccessMessage(null), 5000);
      return () => clearTimeout(timer);
    }
  }, [successMessage]);

  // Format price for display
  const formatPrice = (cents: number | null | undefined): string => {
    if (cents === null || cents === undefined) return 'Free';
    return `$${(cents / 100).toFixed(2)}`;
  };

  // Convert plan to form data for editing
  const planToFormData = (plan: Plan): PlanFormData => {
    const features = AVAILABLE_FEATURES.reduce((acc, f) => {
      const planFeature = plan.features.find((pf) => pf.feature_key === f.key);
      return {
        ...acc,
        [f.key]: {
          enabled: planFeature?.is_enabled ?? false,
          limit: planFeature?.limit_value?.toString() ?? '',
        },
      };
    }, {} as Record<string, { enabled: boolean; limit: string }>);

    return {
      name: plan.name,
      display_name: plan.display_name,
      description: plan.description ?? '',
      price_monthly_cents: plan.price_monthly_cents?.toString() ?? '',
      price_yearly_cents: plan.price_yearly_cents?.toString() ?? '',
      shopify_plan_id: plan.shopify_plan_id ?? '',
      is_active: plan.is_active,
      features,
    };
  };

  // Convert form data to API request
  const formDataToRequest = (
    data: PlanFormData
  ): CreatePlanRequest | UpdatePlanRequest => {
    const features: PlanFeature[] = Object.entries(data.features)
      .filter(([, v]) => v.enabled)
      .map(([key, v]) => ({
        feature_key: key,
        is_enabled: v.enabled,
        limit_value: v.limit ? parseInt(v.limit, 10) : undefined,
      }));

    return {
      name: data.name.toLowerCase().replace(/\s+/g, '_'),
      display_name: data.display_name,
      description: data.description || undefined,
      price_monthly_cents: data.price_monthly_cents
        ? parseInt(data.price_monthly_cents, 10)
        : undefined,
      price_yearly_cents: data.price_yearly_cents
        ? parseInt(data.price_yearly_cents, 10)
        : undefined,
      shopify_plan_id: data.shopify_plan_id || undefined,
      is_active: data.is_active,
      features,
    };
  };

  // Validate form
  const validateForm = (): boolean => {
    const errors: Record<string, string> = {};

    if (!formData.name.trim()) {
      errors.name = 'Plan name is required';
    } else if (!/^[a-zA-Z0-9_-]+$/.test(formData.name)) {
      errors.name = 'Name must contain only letters, numbers, underscores, or hyphens';
    }

    if (!formData.display_name.trim()) {
      errors.display_name = 'Display name is required';
    }

    if (formData.price_monthly_cents && isNaN(parseInt(formData.price_monthly_cents, 10))) {
      errors.price_monthly_cents = 'Must be a valid number';
    }

    if (formData.price_yearly_cents && isNaN(parseInt(formData.price_yearly_cents, 10))) {
      errors.price_yearly_cents = 'Must be a valid number';
    }

    setFormErrors(errors);
    return Object.keys(errors).length === 0;
  };

  // Handle create
  const handleCreate = async () => {
    if (!validateForm()) return;

    setSaving(true);
    setError(null);

    try {
      const request = formDataToRequest(formData) as CreatePlanRequest;
      await plansApi.createPlan(request);
      setSuccessMessage('Plan created successfully');
      setShowCreateModal(false);
      setFormData(initialFormData);
      loadPlans();
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.detail || err.message
          : 'Failed to create plan';
      setError(message);
    } finally {
      setSaving(false);
    }
  };

  // Handle update
  const handleUpdate = async () => {
    if (!selectedPlan || !validateForm()) return;

    setSaving(true);
    setError(null);

    try {
      const request = formDataToRequest(formData) as UpdatePlanRequest;
      await plansApi.updatePlan(selectedPlan.id, request);
      setSuccessMessage('Plan updated successfully - changes are live');
      setShowEditModal(false);
      setSelectedPlan(null);
      setFormData(initialFormData);
      loadPlans();
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.detail || err.message
          : 'Failed to update plan';
      setError(message);
    } finally {
      setSaving(false);
    }
  };

  // Handle delete
  const handleDelete = async () => {
    if (!selectedPlan) return;

    setSaving(true);
    setError(null);

    try {
      await plansApi.deletePlan(selectedPlan.id);
      setSuccessMessage('Plan deleted successfully');
      setShowDeleteModal(false);
      setSelectedPlan(null);
      loadPlans();
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.detail || err.message
          : 'Failed to delete plan';
      setError(message);
    } finally {
      setSaving(false);
    }
  };

  // Handle quick feature toggle
  const handleFeatureToggle = async (plan: Plan, featureKey: string, enabled: boolean) => {
    try {
      await plansApi.toggleFeature(plan.id, {
        feature_key: featureKey,
        is_enabled: enabled,
      });
      setSuccessMessage(`Feature ${enabled ? 'enabled' : 'disabled'} - changes are live`);
      loadPlans();
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.detail || err.message
          : 'Failed to toggle feature';
      setError(message);
    }
  };

  // Open edit modal
  const openEditModal = (plan: Plan) => {
    setSelectedPlan(plan);
    setFormData(planToFormData(plan));
    setFormErrors({});
    setShowEditModal(true);
  };

  // Open delete modal
  const openDeleteModal = (plan: Plan) => {
    setSelectedPlan(plan);
    setShowDeleteModal(true);
  };

  // Open create modal
  const openCreateModal = () => {
    setFormData(initialFormData);
    setFormErrors({});
    setShowCreateModal(true);
  };

  // Table rows
  const tableRows = plans.map((plan) => [
    <BlockStack gap="100" key={`name-${plan.id}`}>
      <Text variant="bodyMd" fontWeight="semibold">
        {plan.display_name}
      </Text>
      <Text variant="bodySm" tone="subdued">
        {plan.name}
      </Text>
    </BlockStack>,
    formatPrice(plan.price_monthly_cents),
    formatPrice(plan.price_yearly_cents),
    <Badge
      key={`status-${plan.id}`}
      tone={plan.is_active ? 'success' : 'critical'}
    >
      {plan.is_active ? 'Active' : 'Inactive'}
    </Badge>,
    <InlineStack gap="100" wrap={false} key={`features-${plan.id}`}>
      {plan.features.filter((f) => f.is_enabled).length} enabled
    </InlineStack>,
    plan.shopify_plan_id ? (
      <Badge key={`shopify-${plan.id}`} tone="info">
        Synced
      </Badge>
    ) : (
      <Text key={`shopify-${plan.id}`} tone="subdued">
        Not synced
      </Text>
    ),
    <InlineStack gap="200" key={`actions-${plan.id}`}>
      <Button
        icon={EditIcon}
        onClick={() => openEditModal(plan)}
        accessibilityLabel={`Edit ${plan.display_name}`}
      />
      <Button
        icon={DeleteIcon}
        tone="critical"
        onClick={() => openDeleteModal(plan)}
        accessibilityLabel={`Delete ${plan.display_name}`}
      />
    </InlineStack>,
  ]);

  // Form modal content
  const renderFormModal = (isEdit: boolean) => (
    <Modal
      open={isEdit ? showEditModal : showCreateModal}
      onClose={() => {
        if (isEdit) {
          setShowEditModal(false);
          setSelectedPlan(null);
        } else {
          setShowCreateModal(false);
        }
        setFormData(initialFormData);
        setFormErrors({});
      }}
      title={isEdit ? `Edit Plan: ${selectedPlan?.display_name}` : 'Create New Plan'}
      primaryAction={{
        content: isEdit ? 'Save Changes' : 'Create Plan',
        onAction: isEdit ? handleUpdate : handleCreate,
        loading: saving,
      }}
      secondaryActions={[
        {
          content: 'Cancel',
          onAction: () => {
            if (isEdit) {
              setShowEditModal(false);
              setSelectedPlan(null);
            } else {
              setShowCreateModal(false);
            }
            setFormData(initialFormData);
          },
        },
      ]}
      large
    >
      <Modal.Section>
        <FormLayout>
          <FormLayout.Group>
            <TextField
              label="Plan Name"
              value={formData.name}
              onChange={(value) => setFormData({ ...formData, name: value })}
              error={formErrors.name}
              helpText="Unique identifier (e.g., 'growth', 'pro')"
              autoComplete="off"
              disabled={isEdit}
            />
            <TextField
              label="Display Name"
              value={formData.display_name}
              onChange={(value) => setFormData({ ...formData, display_name: value })}
              error={formErrors.display_name}
              helpText="Shown to customers (e.g., 'Growth', 'Professional')"
              autoComplete="off"
            />
          </FormLayout.Group>

          <TextField
            label="Description"
            value={formData.description}
            onChange={(value) => setFormData({ ...formData, description: value })}
            multiline={3}
            autoComplete="off"
          />

          <FormLayout.Group>
            <TextField
              label="Monthly Price (cents)"
              type="number"
              value={formData.price_monthly_cents}
              onChange={(value) =>
                setFormData({ ...formData, price_monthly_cents: value })
              }
              error={formErrors.price_monthly_cents}
              helpText="Leave empty for free plans"
              prefix="$"
              suffix="/ month"
              autoComplete="off"
            />
            <TextField
              label="Yearly Price (cents)"
              type="number"
              value={formData.price_yearly_cents}
              onChange={(value) =>
                setFormData({ ...formData, price_yearly_cents: value })
              }
              error={formErrors.price_yearly_cents}
              helpText="Optional annual pricing"
              prefix="$"
              suffix="/ year"
              autoComplete="off"
            />
          </FormLayout.Group>

          <TextField
            label="Shopify Plan ID"
            value={formData.shopify_plan_id}
            onChange={(value) =>
              setFormData({ ...formData, shopify_plan_id: value })
            }
            helpText="Shopify Billing API plan ID for sync"
            autoComplete="off"
          />

          <Checkbox
            label="Plan is active"
            checked={formData.is_active}
            onChange={(value) => setFormData({ ...formData, is_active: value })}
            helpText="Inactive plans cannot be selected for new subscriptions"
          />

          <Divider />

          <Text variant="headingMd" as="h3">
            Features
          </Text>

          <BlockStack gap="300">
            {AVAILABLE_FEATURES.map((feature) => (
              <InlineStack key={feature.key} gap="400" align="start" blockAlign="center">
                <div style={{ width: '200px' }}>
                  <Checkbox
                    label={feature.label}
                    checked={formData.features[feature.key]?.enabled ?? false}
                    onChange={(value) =>
                      setFormData({
                        ...formData,
                        features: {
                          ...formData.features,
                          [feature.key]: {
                            ...formData.features[feature.key],
                            enabled: value,
                          },
                        },
                      })
                    }
                  />
                </div>
                <div style={{ width: '150px' }}>
                  <TextField
                    label="Limit"
                    labelHidden
                    type="number"
                    value={formData.features[feature.key]?.limit ?? ''}
                    onChange={(value) =>
                      setFormData({
                        ...formData,
                        features: {
                          ...formData.features,
                          [feature.key]: {
                            ...formData.features[feature.key],
                            limit: value,
                          },
                        },
                      })
                    }
                    placeholder="No limit"
                    disabled={!formData.features[feature.key]?.enabled}
                    autoComplete="off"
                  />
                </div>
              </InlineStack>
            ))}
          </BlockStack>
        </FormLayout>
      </Modal.Section>
    </Modal>
  );

  // Delete confirmation modal
  const renderDeleteModal = () => (
    <Modal
      open={showDeleteModal}
      onClose={() => {
        setShowDeleteModal(false);
        setSelectedPlan(null);
      }}
      title="Delete Plan"
      primaryAction={{
        content: 'Delete',
        destructive: true,
        onAction: handleDelete,
        loading: saving,
      }}
      secondaryActions={[
        {
          content: 'Cancel',
          onAction: () => {
            setShowDeleteModal(false);
            setSelectedPlan(null);
          },
        },
      ]}
    >
      <Modal.Section>
        <BlockStack gap="400">
          <Banner tone="warning">
            <p>
              Are you sure you want to delete the plan "{selectedPlan?.display_name}"?
              This action cannot be undone.
            </p>
          </Banner>
          <Text variant="bodyMd">
            Consider deactivating the plan instead to preserve historical data.
          </Text>
        </BlockStack>
      </Modal.Section>
    </Modal>
  );

  return (
    <Page
      title="Plan Management"
      subtitle="Create and edit pricing plans. Changes apply instantly without deployment."
      primaryAction={{
        content: 'Create Plan',
        icon: PlusIcon,
        onAction: openCreateModal,
      }}
      secondaryActions={[
        {
          content: 'Refresh',
          icon: RefreshIcon,
          onAction: loadPlans,
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

        {successMessage && (
          <Layout.Section>
            <Banner tone="success" onDismiss={() => setSuccessMessage(null)}>
              <p>{successMessage}</p>
            </Banner>
          </Layout.Section>
        )}

        <Layout.Section>
          <Card>
            <BlockStack gap="400">
              <InlineStack align="space-between">
                <Text variant="headingMd" as="h2">
                  Pricing Plans
                </Text>
                <Checkbox
                  label="Show inactive plans"
                  checked={includeInactive}
                  onChange={setIncludeInactive}
                />
              </InlineStack>

              {loading ? (
                <div style={{ textAlign: 'center', padding: '40px' }}>
                  <Spinner size="large" />
                </div>
              ) : plans.length === 0 ? (
                <Banner>
                  <p>No plans found. Create your first plan to get started.</p>
                </Banner>
              ) : (
                <DataTable
                  columnContentTypes={[
                    'text',
                    'text',
                    'text',
                    'text',
                    'text',
                    'text',
                    'text',
                  ]}
                  headings={[
                    'Plan',
                    'Monthly',
                    'Yearly',
                    'Status',
                    'Features',
                    'Shopify',
                    'Actions',
                  ]}
                  rows={tableRows}
                />
              )}
            </BlockStack>
          </Card>
        </Layout.Section>

        <Layout.Section>
          <Card>
            <BlockStack gap="400">
              <Text variant="headingMd" as="h2">
                Quick Feature Toggle
              </Text>
              <Text variant="bodySm" tone="subdued">
                Quickly enable or disable features for plans. Changes apply instantly.
              </Text>

              {plans.length > 0 && (
                <DataTable
                  columnContentTypes={['text', ...plans.map(() => 'text' as const)]}
                  headings={['Feature', ...plans.map((p) => p.display_name)]}
                  rows={AVAILABLE_FEATURES.map((feature) => [
                    feature.label,
                    ...plans.map((plan) => {
                      const planFeature = plan.features.find(
                        (f) => f.feature_key === feature.key
                      );
                      const isEnabled = planFeature?.is_enabled ?? false;

                      return (
                        <Button
                          key={`${plan.id}-${feature.key}`}
                          size="slim"
                          tone={isEnabled ? 'success' : undefined}
                          onClick={() =>
                            handleFeatureToggle(plan, feature.key, !isEnabled)
                          }
                          icon={isEnabled ? CheckIcon : XIcon}
                        >
                          {isEnabled ? 'On' : 'Off'}
                        </Button>
                      );
                    }),
                  ])}
                />
              )}
            </BlockStack>
          </Card>
        </Layout.Section>
      </Layout>

      {renderFormModal(false)}
      {renderFormModal(true)}
      {renderDeleteModal()}
    </Page>
  );
}
