/**
 * Wizard Flow Component
 *
 * Main orchestrator for the 3-step dashboard creation wizard:
 * 1. Select Widgets - Browse and select from widget catalog
 * 2. Customize Layout - Edit name, description, and arrange widgets
 * 3. Preview & Save - Review and save the dashboard
 *
 * Phase 3 - Dashboard Builder Wizard UI
 */

import { useState, useMemo, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Page,
  BlockStack,
  InlineStack,
  Box,
  TextField,
  Text,
} from '@shopify/polaris';
import type { ChartType, WidgetCatalogItem } from '../../../types/customDashboards';
import { useDashboardBuilder } from '../../../contexts/DashboardBuilderContext';
import { useWidgetCatalog } from '../../../hooks/useWidgetCatalog';
import { BuilderStepNav } from './BuilderStepNav';
import { BuilderToolbar } from './BuilderToolbar';
import { CategorySidebar } from './CategorySidebar';
import { WidgetGallery } from './WidgetGallery';
import { WizardGrid } from './WizardGrid';
import { LayoutControls } from './LayoutControls';
import { PreviewGrid } from './PreviewGrid';
import { PreviewControls } from './PreviewControls';

export function WizardFlow() {
  const navigate = useNavigate();

  // Context state
  const {
    wizardState,
    isSaving,
    setBuilderStep,
    setSelectedCategory,
    addCatalogWidget,
    setWizardDashboardName,
    setWizardDashboardDescription,
    saveDashboard,
    exitWizardMode,
    enterWizardMode,
    canProceedToCustomize,
    canProceedToPreview,
    canSaveDashboard,
  } = useDashboardBuilder();

  // Widget catalog
  const { items, loading, error } = useWidgetCatalog();

  // Track completed steps
  const [completedSteps, setCompletedSteps] = useState<Set<'select' | 'customize' | 'preview'>>(
    new Set()
  );

  // Enter wizard mode on mount
  useEffect(() => {
    enterWizardMode();
  }, [enterWizardMode]);

  // Filter items by selected category
  const filteredItems = useMemo(() => {
    if (!wizardState.selectedCategory) return items;
    return items.filter((item) => item.category === wizardState.selectedCategory);
  }, [items, wizardState.selectedCategory]);

  // Calculate widget counts per category
  const widgetCounts = useMemo(() => {
    const counts: Record<ChartType | 'all', number> = {
      all: items.length,
      line: 0,
      bar: 0,
      area: 0,
      pie: 0,
      kpi: 0,
      table: 0,
    };

    items.forEach((item) => {
      counts[item.chart_type] = (counts[item.chart_type] || 0) + 1;
    });

    return counts;
  }, [items]);

  // Selected widget IDs for gallery
  const selectedWidgetIds = useMemo(() => {
    return new Set(wizardState.selectedWidgets.map((w) => w.id.split('::')[0]));
  }, [wizardState.selectedWidgets]);

  // Navigation handlers
  const handleNext = useCallback(() => {
    if (wizardState.currentStep === 'select' && canProceedToCustomize) {
      setCompletedSteps((prev) => new Set([...prev, 'select']));
      setBuilderStep('customize');
    } else if (wizardState.currentStep === 'customize' && canProceedToPreview) {
      setCompletedSteps((prev) => new Set([...prev, 'customize']));
      setBuilderStep('preview');
    }
  }, [wizardState.currentStep, canProceedToCustomize, canProceedToPreview, setBuilderStep]);

  const handleBack = useCallback(() => {
    if (wizardState.currentStep === 'preview') {
      setBuilderStep('customize');
    } else if (wizardState.currentStep === 'customize') {
      setBuilderStep('select');
    }
  }, [wizardState.currentStep, setBuilderStep]);

  const handleSave = useCallback(async () => {
    try {
      await saveDashboard();
      // Navigate to dashboards list on success
      navigate('/dashboards');
    } catch (err) {
      console.error('Failed to save dashboard:', err);
      // Error is handled by context
    }
  }, [saveDashboard, navigate]);

  const handleCancel = useCallback(() => {
    exitWizardMode();
    navigate('/dashboards');
  }, [exitWizardMode, navigate]);

  const handleAddWidget = useCallback(
    (item: WidgetCatalogItem) => {
      addCatalogWidget(item);
    },
    [addCatalogWidget]
  );

  // Render step content
  const renderStepContent = () => {
    switch (wizardState.currentStep) {
      case 'select':
        return (
          <InlineStack gap="400" align="start">
            {/* Category Sidebar */}
            <Box minWidth="220px">
              <CategorySidebar
                selectedCategory={wizardState.selectedCategory}
                onSelectCategory={setSelectedCategory}
                widgetCounts={widgetCounts}
              />
            </Box>

            {/* Widget Gallery */}
            <div style={{ flex: 1 }}>
              <WidgetGallery
                items={filteredItems}
                selectedIds={selectedWidgetIds}
                onAddWidget={handleAddWidget}
                loading={loading}
                error={error}
              />
            </div>
          </InlineStack>
        );

      case 'customize':
        return (
          <BlockStack gap="400">
            {/* Dashboard Name */}
            <TextField
              label="Dashboard name"
              value={wizardState.dashboardName}
              onChange={setWizardDashboardName}
              placeholder="e.g., Sales Performance Dashboard"
              autoComplete="off"
              requiredIndicator
            />

            {/* Dashboard Description */}
            <TextField
              label="Description (optional)"
              value={wizardState.dashboardDescription}
              onChange={setWizardDashboardDescription}
              placeholder="Add a description for your dashboard"
              autoComplete="off"
              multiline={3}
            />

            {/* Layout Controls */}
            <LayoutControls />

            {/* Visual Grid with Drag & Drop */}
            <WizardGrid />
          </BlockStack>
        );

      case 'preview':
        return (
          <BlockStack gap="400">
            {/* Dashboard Info */}
            <BlockStack gap="200">
              <Text as="h2" variant="headingLg">
                {wizardState.dashboardName || 'Untitled Dashboard'}
              </Text>
              <Text as="p" variant="bodySm" tone="subdued">
                {wizardState.dashboardDescription || 'No description'}
              </Text>
            </BlockStack>

            {/* Widget Summary */}
            <Text as="p" variant="bodyMd">
              {wizardState.selectedWidgets.length} widget{wizardState.selectedWidgets.length !== 1 ? 's' : ''} selected
            </Text>

            {/* Preview Controls (date range, filters, save as template) */}
            <PreviewControls />

            {/* Visual Grid Preview with Sample Data */}
            <PreviewGrid />
          </BlockStack>
        );

      default:
        return null;
    }
  };

  return (
    <Page
      title="Create Dashboard"
      backAction={{ content: 'Back to Dashboards', onAction: handleCancel }}
    >
      <BlockStack gap="600">
        {/* Step Navigator */}
        <BuilderStepNav
          currentStep={wizardState.currentStep}
          completedSteps={completedSteps}
          onChangeStep={setBuilderStep}
          canProceedToCustomize={canProceedToCustomize}
          canProceedToPreview={canProceedToPreview}
        />

        {/* Step Content */}
        {renderStepContent()}

        {/* Navigation Toolbar */}
        <BuilderToolbar
          currentStep={wizardState.currentStep}
          onBack={handleBack}
          onNext={handleNext}
          onSave={handleSave}
          onCancel={handleCancel}
          canGoBack={wizardState.currentStep !== 'select'}
          canProceed={
            wizardState.currentStep === 'select'
              ? canProceedToCustomize
              : canProceedToPreview
          }
          canSave={canSaveDashboard}
          isSaving={isSaving}
        />
      </BlockStack>
    </Page>
  );
}
