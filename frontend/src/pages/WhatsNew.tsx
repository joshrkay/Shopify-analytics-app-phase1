/**
 * WhatsNew Page
 *
 * Central page displaying all changelog entries with filtering.
 * Supports filtering by release type and marking entries as read.
 *
 * Story 9.7 - In-App Changelog & Release Notes
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Page,
  Layout,
  Card,
  BlockStack,
  InlineStack,
  Text,
  Select,
  Tabs,
  Banner,
  Spinner,
  EmptyState,
  Pagination,
} from '@shopify/polaris';
import { ChangelogEntry } from '../components/changelog/ChangelogEntry';
import type { ChangelogEntry as ChangelogEntryType, ReleaseType } from '../types/changelog';
import {
  listChangelog,
  markAsRead,
  markAllAsRead,
} from '../services/changelogApi';

const PAGE_SIZE = 10;

type TabId = 'all' | 'unread';

const releaseTypeOptions = [
  { label: 'All Types', value: '' },
  { label: 'New Features', value: 'feature' },
  { label: 'Improvements', value: 'improvement' },
  { label: 'Bug Fixes', value: 'fix' },
  { label: 'Deprecations', value: 'deprecation' },
  { label: 'Security', value: 'security' },
];

export function WhatsNew() {
  // State
  const [entries, setEntries] = useState<ChangelogEntryType[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTab, setSelectedTab] = useState<TabId>('all');
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);

  // Action loading states
  const [isMarkingAllRead, setIsMarkingAllRead] = useState(false);
  const [actionLoadingIds, setActionLoadingIds] = useState<Set<string>>(new Set());

  // Fetch entries
  const fetchEntries = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await listChangelog({
        release_type: typeFilter as ReleaseType | undefined,
        include_read: selectedTab === 'all',
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      });

      setEntries(response.entries);
      setTotal(response.total);
      setHasMore(response.has_more);
      setUnreadCount(response.unread_count);
    } catch (err) {
      console.error('Failed to fetch changelog entries:', err);
      setError('Failed to load changelog. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }, [typeFilter, selectedTab, page]);

  useEffect(() => {
    fetchEntries();
  }, [fetchEntries]);

  // Handle mark as read
  const handleMarkRead = async (entryId: string) => {
    setActionLoadingIds((prev) => new Set(prev).add(entryId));
    try {
      const response = await markAsRead(entryId);
      setEntries((prev) =>
        prev.map((e) =>
          e.id === entryId ? { ...e, is_read: true } : e
        )
      );
      setUnreadCount(response.unread_count);
    } catch (err) {
      console.error('Failed to mark entry as read:', err);
    } finally {
      setActionLoadingIds((prev) => {
        const next = new Set(prev);
        next.delete(entryId);
        return next;
      });
    }
  };

  // Handle mark all as read
  const handleMarkAllRead = async () => {
    setIsMarkingAllRead(true);
    try {
      await markAllAsRead();
      setEntries((prev) =>
        prev.map((e) => ({ ...e, is_read: true }))
      );
      setUnreadCount(0);
    } catch (err) {
      console.error('Failed to mark all as read:', err);
    } finally {
      setIsMarkingAllRead(false);
    }
  };

  // Tab change handler
  const handleTabChange = (selectedTabIndex: number) => {
    setSelectedTab(selectedTabIndex === 0 ? 'all' : 'unread');
    setPage(1);
  };

  // Pagination handlers
  const handleNextPage = () => {
    if (hasMore) {
      setPage((prev) => prev + 1);
    }
  };

  const handlePreviousPage = () => {
    if (page > 1) {
      setPage((prev) => prev - 1);
    }
  };

  const tabs = [
    {
      id: 'all',
      content: 'All Updates',
      accessibilityLabel: 'All updates',
      panelID: 'all-updates-panel',
    },
    {
      id: 'unread',
      content: `Unread (${unreadCount})`,
      accessibilityLabel: 'Unread updates',
      panelID: 'unread-updates-panel',
    },
  ];

  return (
    <Page
      title="What's New"
      subtitle="Recent updates and changes to the platform"
      primaryAction={
        unreadCount > 0
          ? {
              content: 'Mark all as read',
              onAction: handleMarkAllRead,
              loading: isMarkingAllRead,
            }
          : undefined
      }
    >
      <Layout>
        <Layout.Section>
          <Card>
            <Tabs
              tabs={tabs}
              selected={selectedTab === 'all' ? 0 : 1}
              onSelect={handleTabChange}
            >
              <BlockStack gap="400">
                {/* Filters */}
                <InlineStack gap="400" blockAlign="end">
                  <Select
                    label="Type"
                    labelInline
                    options={releaseTypeOptions}
                    value={typeFilter}
                    onChange={(value) => {
                      setTypeFilter(value);
                      setPage(1);
                    }}
                  />
                </InlineStack>

                {/* Error banner */}
                {error && (
                  <Banner tone="critical" onDismiss={() => setError(null)}>
                    {error}
                  </Banner>
                )}

                {/* Loading state */}
                {isLoading && (
                  <InlineStack align="center">
                    <Spinner size="large" />
                  </InlineStack>
                )}

                {/* Empty state */}
                {!isLoading && entries.length === 0 && (
                  <EmptyState
                    heading={
                      selectedTab === 'all'
                        ? 'No updates yet'
                        : 'All caught up!'
                    }
                    image=""
                  >
                    <Text as="p" variant="bodyMd" tone="subdued">
                      {selectedTab === 'all'
                        ? 'Check back later for platform updates and release notes.'
                        : 'You have read all the updates. Great job staying informed!'}
                    </Text>
                  </EmptyState>
                )}

                {/* Entries list */}
                {!isLoading && entries.length > 0 && (
                  <BlockStack gap="400">
                    {entries.map((entry) => (
                      <ChangelogEntry
                        key={entry.id}
                        entry={entry}
                        onMarkRead={handleMarkRead}
                        isLoading={actionLoadingIds.has(entry.id)}
                      />
                    ))}
                  </BlockStack>
                )}

                {/* Pagination */}
                {!isLoading && total > PAGE_SIZE && (
                  <InlineStack align="center">
                    <Pagination
                      hasPrevious={page > 1}
                      hasNext={hasMore}
                      onPrevious={handlePreviousPage}
                      onNext={handleNextPage}
                    />
                  </InlineStack>
                )}

                {/* Total count */}
                {!isLoading && entries.length > 0 && (
                  <Text as="p" variant="bodySm" tone="subdued" alignment="center">
                    Showing {entries.length} of {total} updates
                  </Text>
                )}
              </BlockStack>
            </Tabs>
          </Card>
        </Layout.Section>
      </Layout>
    </Page>
  );
}

export default WhatsNew;
