/**
 * FeatureUpdateBanner Component
 *
 * Contextual banner that appears near changed features.
 * Shows recent unread changelog entries for a specific feature area.
 *
 * Story 9.7 - In-App Changelog & Release Notes
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Banner,
  BlockStack,
  InlineStack,
  Text,
  Button,
} from '@shopify/polaris';
import { getEntriesForFeature, markAsRead } from '../../services/changelogApi';
import { ChangelogEntry } from './ChangelogEntry';
import type {
  ChangelogEntry as ChangelogEntryType,
  FeatureArea,
} from '../../types/changelog';
import { getFeatureAreaLabel } from '../../types/changelog';

interface FeatureUpdateBannerProps {
  featureArea: FeatureArea;
  maxItems?: number;
  onDismiss?: () => void;
  onViewAll?: () => void;
}

export function FeatureUpdateBanner({
  featureArea,
  maxItems = 3,
  onDismiss,
  onViewAll,
}: FeatureUpdateBannerProps) {
  const [entries, setEntries] = useState<ChangelogEntryType[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isDismissed, setIsDismissed] = useState(false);

  const fetchEntries = useCallback(async () => {
    try {
      const response = await getEntriesForFeature(featureArea, maxItems);
      setEntries(response.entries);
    } catch (err) {
      console.error('Failed to fetch feature updates:', err);
    } finally {
      setIsLoading(false);
    }
  }, [featureArea, maxItems]);

  useEffect(() => {
    fetchEntries();
  }, [fetchEntries]);

  const handleMarkRead = async (entryId: string) => {
    try {
      await markAsRead(entryId);
      setEntries((prev) =>
        prev.map((e) =>
          e.id === entryId ? { ...e, is_read: true } : e
        )
      );
    } catch (err) {
      console.error('Failed to mark as read:', err);
    }
  };

  const handleDismiss = () => {
    setIsDismissed(true);
    // Mark all as read
    entries.forEach((e) => {
      if (!e.is_read) {
        markAsRead(e.id).catch(console.error);
      }
    });
    onDismiss?.();
  };

  // Don't render if loading, dismissed, or no entries
  if (isLoading || isDismissed || entries.length === 0) {
    return null;
  }

  const areaLabel = getFeatureAreaLabel(featureArea);

  return (
    <Banner
      title={`New updates to ${areaLabel}`}
      tone="info"
      onDismiss={handleDismiss}
    >
      <BlockStack gap="300">
        <Text as="p" variant="bodyMd">
          {entries.length === 1
            ? 'There is 1 new update that may affect this feature.'
            : `There are ${entries.length} new updates that may affect this feature.`}
        </Text>

        <BlockStack gap="200">
          {entries.map((entry) => (
            <ChangelogEntry
              key={entry.id}
              entry={entry}
              onMarkRead={handleMarkRead}
              isCompact
            />
          ))}
        </BlockStack>

        {onViewAll && (
          <InlineStack>
            <Button variant="plain" onClick={onViewAll}>
              View all updates
            </Button>
          </InlineStack>
        )}
      </BlockStack>
    </Banner>
  );
}

export default FeatureUpdateBanner;
