import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../services/apiUtils', () => ({
  API_BASE_URL: '',
  createHeadersAsync: vi.fn(),
  handleResponse: vi.fn(async (res: Response) => res.json()),
}));

import { restoreFromBackup } from '../services/syncConfigApi';
import { createHeadersAsync } from '../services/apiUtils';

beforeEach(() => {
  vi.clearAllMocks();
  globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: vi.fn().mockResolvedValue({ success: true }) });
});

describe('syncConfigApi edge cases', () => {
  it('restoreFromBackup forwards lowercase authorization header from object headers', async () => {
    vi.mocked(createHeadersAsync).mockResolvedValue({ authorization: 'Bearer lower' } as unknown as HeadersInit);

    await restoreFromBackup(new File(['x'], 'backup.zip'));

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/sync/backup/restore',
      expect.objectContaining({ headers: { Authorization: 'Bearer lower' } }),
    );
  });

  it('restoreFromBackup omits auth header when none provided', async () => {
    vi.mocked(createHeadersAsync).mockResolvedValue({ 'Content-Type': 'application/json' });

    await restoreFromBackup(new File(['x'], 'backup.zip'));

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/sync/backup/restore',
      expect.objectContaining({ headers: {} }),
    );
  });
});
