import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

describe('/builder route contract', () => {
  it('mounts wizard flow via DashboardBuilderProvider', () => {
    const appPath = path.resolve(__dirname, '../App.tsx');
    const content = fs.readFileSync(appPath, 'utf8');

    expect(content).toContain('path="/builder"');
    expect(content).toContain('<DashboardBuilderProvider>');
    expect(content).toContain('<WizardFlow />');
  });
});
