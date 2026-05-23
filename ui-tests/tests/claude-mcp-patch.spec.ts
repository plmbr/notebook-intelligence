/**
 * End-to-end coverage for the Claude MCP workspace-disable endpoint.
 *
 * The plain Python unit test for ``ClaudeMCPManager.set_server_disabled``
 * pins the file-write logic, and ``TestPatchEndpointDispatches`` drives the
 * tornado handler under a stubbed APIHandler. This spec layers on a real
 * browser request so the JupyterLab server's actual routing tables, auth
 * middleware, and prepare() chain are all exercised. A missing import,
 * forgotten route registration, or auth regression would surface here even
 * if the Python-side tests still pass.
 *
 * Requires HOME to point at an isolated directory the test owns; otherwise
 * the PATCH would mutate the user's real ~/.claude.json. The runner sets
 * HOME=/tmp/... before invoking jlpm playwright, and the seed file is
 * placed by the test itself before each run.
 */
import { expect, test } from '@jupyterlab/galata';

const SERVER_NAME = 'voicemode-test';

test.describe('claude-mcp workspace disable PATCH endpoint', () => {
  test('toggle round-trips through the real lab server', async ({
    page,
    request
  }) => {
    // Wait for the extension to register itself before exercising the
    // endpoint. If extension activation hasn't completed, the route table
    // won't include /claude-mcp/<scope>/<name> yet.
    await page.evaluate(() => {
      const app = (window as any).jupyterapp;
      const ids: string[] = app?.listPlugins?.() ?? [];
      if (!ids.some(id => id.startsWith('@plmbr/'))) {
        throw new Error('notebook-intelligence plugin did not load');
      }
    });

    // PATCH to disable.
    const disableResp = await request.patch(
      `http://localhost:8888/notebook-intelligence/claude-mcp/user/${SERVER_NAME}`,
      {
        data: { disabled_for_workspace: true },
        headers: { 'Content-Type': 'application/json' }
      }
    );
    expect(disableResp.status()).toBe(200);
    const disableBody = await disableResp.json();
    expect(disableBody.server.name).toBe(SERVER_NAME);
    expect(disableBody.server.disabled_for_workspace).toBe(true);

    // PATCH to re-enable.
    const enableResp = await request.patch(
      `http://localhost:8888/notebook-intelligence/claude-mcp/user/${SERVER_NAME}`,
      {
        data: { disabled_for_workspace: false },
        headers: { 'Content-Type': 'application/json' }
      }
    );
    expect(enableResp.status()).toBe(200);
    const enableBody = await enableResp.json();
    expect(enableBody.server.disabled_for_workspace).toBe(false);
  });

  test('non-bool payload rejected with 400', async ({ request }) => {
    const resp = await request.patch(
      `http://localhost:8888/notebook-intelligence/claude-mcp/user/${SERVER_NAME}`,
      {
        data: { disabled_for_workspace: 'false' },
        headers: { 'Content-Type': 'application/json' }
      }
    );
    expect(resp.status()).toBe(400);
    const body = await resp.json();
    expect(body.error).toContain('JSON boolean');
  });

  test('missing field rejected with 400', async ({ request }) => {
    const resp = await request.patch(
      `http://localhost:8888/notebook-intelligence/claude-mcp/user/${SERVER_NAME}`,
      {
        data: {},
        headers: { 'Content-Type': 'application/json' }
      }
    );
    expect(resp.status()).toBe(400);
    const body = await resp.json();
    expect(body.error).toContain('Missing');
  });
});
