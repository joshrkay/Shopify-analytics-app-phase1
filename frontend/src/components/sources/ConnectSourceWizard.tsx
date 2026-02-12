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

import { useEffect, useCallback } from 'react';
import { Modal, BlockStack, Banner } from '@shopify/polaris';
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
import { useSyncProgress } from '../../hooks/useDataSources';

interface ConnectSourceWizardProps {
  open: boolean;
  platform: DataSourceDefinition | null;
  onClose: () => void;
  onSuccess?: (connectionId: string) => void;
}

export function ConnectSourceWizard({
  open,
  platform,
  onClose,
  onSuccess,
}: ConnectSourceWizardProps) {
  const navigate = useNavigate();
  const wizard = useConnectSourceWizard();
  const { state } = wizard;

  // Use sync progress hook for the syncing step
  const { progress: syncProgress } = useSyncProgress(
    state.connectionId ?? '',
    state.step === 'syncing' && !!state.connectionId,
  );

  // Initialize wizard when modal opens with a platform
  useEffect(() => {
    if (open && platform) {
      wizard.initWithPlatform(platform);
    }
  }, [open, platform]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleClose = useCallback(() => {
    wizard.reset();
    onClose();
  }, [wizard, onClose]);

  const handleDone = useCallback(() => {
    if (state.connectionId && onSuccess) {
      onSuccess(state.connectionId);
    }
    handleClose();
  }, [state.connectionId, onSuccess, handleClose]);

  const handleViewDashboard = useCallback(() => {
    if (state.connectionId && onSuccess) {
      onSuccess(state.connectionId);
    }
    wizard.reset();
    onClose();
    navigate('/');
  }, [state.connectionId, onSuccess, wizard, onClose, navigate]);

  if (!platform && !state.platform) return null;

  const activePlatform = state.platform ?? platform!;
  const title = `Connect ${activePlatform.displayName}`;

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={title}
      large
      primaryAction={undefined}
    >
      <Modal.Section>
        <BlockStack gap="400">
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
              progress={syncProgress}
              error={state.error}
            />
          )}

          {state.step === 'success' && state.connectionId && (
            <SuccessStep
              platform={activePlatform}
              connectionId={state.connectionId}
              onDone={handleDone}
              onViewDashboard={handleViewDashboard}
            />
          )}
        </BlockStack>
      </Modal.Section>
    </Modal>
  );
}
