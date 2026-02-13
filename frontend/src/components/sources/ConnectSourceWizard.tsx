/**
 * Connect Source Wizard Component
 *
 * 6-step modal wizard for connecting new data sources.
 * Uses separate step components and the useConnectSourceWizard hook.
 *
 * Steps:
 * 1. Intro — Source info, features, permissions
 * 2. OAuth — Authorization redirect/popup
 * 3. Accounts — Select ad accounts (ads platforms only)
 * 4. SyncConfig — Historical range, frequency
 * 5. Syncing — Real-time sync progress
 * 6. Success — Confirmation + next steps
 *
 * Phase 3 — Subphase 3.4/3.5: Connection Wizard
 */

import { useState, useEffect, useCallback } from 'react';
import { Modal, BlockStack, Banner, Text, InlineStack, Button } from '@shopify/polaris';
import { useNavigate } from 'react-router-dom';
import type { DataSourceDefinition } from '../../types/sourceConnection';
import { useConnectSourceWizard } from '../../hooks/useConnectSourceWizard';
import { WizardSteps } from './WizardSteps';
import {
  IntroStep,
  OAuthStep,
  AccountSelectStep,
  SyncConfigStep,
  SyncProgressStep,
  SuccessStep,
} from './steps';

interface ConnectSourceWizardProps {
  open: boolean;
  platform: DataSourceDefinition | null;
  onClose: () => void;
  onSuccess?: (connectionId: string) => void;
}

/** Steps where closing should prompt for confirmation */
const MID_FLOW_STEPS = new Set(['oauth', 'accounts', 'syncConfig', 'syncing']);

export function ConnectSourceWizard({
  open,
  platform,
  onClose,
  onSuccess,
}: ConnectSourceWizardProps) {
  const navigate = useNavigate();
  const wizard = useConnectSourceWizard();
  const { state } = wizard;
  const [showCloseConfirm, setShowCloseConfirm] = useState(false);

  // Initialize wizard when modal opens with a platform
  useEffect(() => {
    if (open && platform) {
      wizard.initWithPlatform(platform);
    }
  }, [open, platform, wizard.initWithPlatform]);

  // Reset confirmation state when modal closes
  useEffect(() => {
    if (!open) {
      setShowCloseConfirm(false);
    }
  }, [open]);

  const doClose = useCallback(() => {
    setShowCloseConfirm(false);
    wizard.reset();
    onClose();
  }, [wizard, onClose]);

  const handleClose = useCallback(() => {
    if (MID_FLOW_STEPS.has(state.step)) {
      setShowCloseConfirm(true);
    } else {
      doClose();
    }
  }, [state.step, doClose]);

  const handleViewDashboard = useCallback(() => {
    if (state.connectionId && onSuccess) {
      onSuccess(state.connectionId);
    }
    doClose();
    navigate('/');
  }, [state.connectionId, onSuccess, doClose, navigate]);

  const handleConnectAnother = useCallback(() => {
    if (state.connectionId && onSuccess) {
      onSuccess(state.connectionId);
    }
    doClose();
    navigate('/sources');
  }, [state.connectionId, onSuccess, doClose, navigate]);

  const activePlatform = state.platform ?? platform;
  if (!activePlatform) return null;

  const title = `Connect ${activePlatform.displayName}`;

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={title}
      size="large"
    >
      <Modal.Section>
        <BlockStack gap="400">
          {showCloseConfirm && (
            <Banner tone="warning" title="Leave connection wizard?">
              <BlockStack gap="200">
                <Text as="p" variant="bodyMd">
                  Your progress will be lost if you close now.
                </Text>
                <InlineStack gap="200">
                  <Button onClick={() => setShowCloseConfirm(false)}>
                    Continue Setup
                  </Button>
                  <Button variant="primary" tone="critical" onClick={doClose}>
                    Leave Wizard
                  </Button>
                </InlineStack>
              </BlockStack>
            </Banner>
          )}

          <WizardSteps currentStep={state.step} />

          {state.error && state.step !== 'syncing' && (
            <Banner tone="critical" onDismiss={() => wizard.setError(null)}>
              <p>{state.error}</p>
            </Banner>
          )}

          {state.step === 'intro' && (
            <IntroStep
              platform={activePlatform}
              onContinue={wizard.proceedFromIntro}
              onCancel={handleClose}
            />
          )}

          {state.step === 'oauth' && (
            <OAuthStep
              platform={activePlatform}
              loading={state.loading}
              error={state.error}
              onStartOAuth={wizard.startOAuth}
              onCancel={handleClose}
            />
          )}

          {state.step === 'accounts' && (
            <AccountSelectStep
              accounts={state.accounts}
              selectedAccountIds={state.selectedAccountIds}
              loading={state.loading}
              error={state.error}
              onToggleAccount={wizard.toggleAccount}
              onSelectAll={wizard.selectAllAccounts}
              onDeselectAll={wizard.deselectAllAccounts}
              onConfirm={wizard.confirmAccounts}
              onBack={wizard.goBack}
            />
          )}

          {state.step === 'syncConfig' && (
            <SyncConfigStep
              platform={activePlatform}
              syncConfig={state.syncConfig}
              onUpdateConfig={wizard.updateWizardSyncConfig}
              onConfirm={wizard.confirmSyncConfig}
              onBack={wizard.goBack}
              loading={state.loading}
            />
          )}

          {state.step === 'syncing' && (
            <SyncProgressStep
              platform={activePlatform}
              progress={state.syncProgress}
              error={state.error}
              onNavigateDashboard={handleViewDashboard}
            />
          )}

          {state.step === 'success' && state.connectionId && (
            <SuccessStep
              platform={activePlatform}
              onConnectAnother={handleConnectAnother}
              onViewDashboard={handleViewDashboard}
            />
          )}
        </BlockStack>
      </Modal.Section>
    </Modal>
  );
}
