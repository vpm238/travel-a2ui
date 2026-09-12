/**
 * The Claude plugin, checked against the shapes Claude Code actually requires.
 *
 * A plugin fails quietly: a marketplace in the wrong directory, a `source` that
 * points at nothing, an MCP entry with a `url` and no `type` — each of these
 * ends with the plugin simply not being there, and none of them is visible from
 * inside this repository. So the manifests are asserted here rather than
 * discovered by whoever tries to install it.
 */

import { readFileSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

/** The repository root — which is the marketplace root once extracted. */
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');

const read = (...parts: string[]) => JSON.parse(readFileSync(join(ROOT, ...parts), 'utf-8'));

describe('the marketplace', () => {
  const marketplace = () => read('.claude-plugin', 'marketplace.json');

  /**
   * `/plugin marketplace add owner/repo` looks here and nowhere else.
   */
  it('sits at .claude-plugin/marketplace.json in the repository root', () => {
    expect(existsSync(join(ROOT, '.claude-plugin', 'marketplace.json'))).toBe(true);
  });

  it('names itself and lists at least one plugin', () => {
    const entry = marketplace();
    expect(entry.name).toBe('travel-a2ui');
    expect(Array.isArray(entry.plugins)).toBe(true);
    expect(entry.plugins.length).toBeGreaterThan(0);
  });

  it('gives every plugin the two fields an entry cannot be read without', () => {
    for (const plugin of marketplace().plugins) {
      expect(plugin.name, JSON.stringify(plugin)).toBeTruthy();
      expect(plugin.source, JSON.stringify(plugin)).toBeTruthy();
    }
  });

  /**
   * Relative sources resolve against the marketplace root — the directory
   * holding `.claude-plugin/`, not `.claude-plugin/` itself.
   */
  it('points each source at a directory that is really there', () => {
    for (const plugin of marketplace().plugins) {
      expect(typeof plugin.source).toBe('string');
      expect(plugin.source.startsWith('./')).toBe(true);
      expect(existsSync(join(ROOT, plugin.source)), plugin.source).toBe(true);
      expect(
        existsSync(join(ROOT, plugin.source, '.claude-plugin', 'plugin.json')),
        `${plugin.source} has no manifest`,
      ).toBe(true);
    }
  });
});

describe('the plugin manifest', () => {
  const manifest = () => read('plugins', 'travel-a2ui', '.claude-plugin', 'plugin.json');

  it('has the one field a manifest requires', () => {
    expect(manifest().name).toBe('travel-a2ui');
  });

  it('uses kebab-case, because the name namespaces every component it ships', () => {
    expect(manifest().name).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/);
  });

  /** Paths in a manifest must be relative to the plugin root and start with `./`. */
  it('points at an MCP config that exists', () => {
    const path = manifest().mcpServers as string;
    expect(path.startsWith('./')).toBe(true);
    expect(existsSync(join(ROOT, 'plugins', 'travel-a2ui', path))).toBe(true);
  });
});

describe('the MCP server the plugin installs', () => {
  const mcp = () => read('plugins', 'travel-a2ui', '.mcp.json');

  /**
   * The failure this exists for: an entry with a `url` and no `type` is read as
   * a stdio server, skipped, and reported as a configuration error. The plugin
   * installs, and simply has no tools.
   */
  it('declares a type, because a url without one is skipped', () => {
    for (const [name, server] of Object.entries<any>(mcp().mcpServers)) {
      if (server.url) expect(server.type, `${name} has a url and no type`).toBeTruthy();
      expect(['http', 'streamable-http', 'sse', 'ws']).toContain(server.type);
    }
  });

  it('points at an absolute https endpoint', () => {
    const url = new URL(mcp().mcpServers['travel-a2ui'].url);
    expect(url.protocol).toBe('https:');
    expect(url.pathname).toBe('/mcp');
  });

  /**
   * No credential, deliberately. Every tool answers from data the deployment
   * already has, so installing this asks nobody for a key.
   */
  it('asks for no credential', () => {
    expect(JSON.stringify(mcp())).not.toMatch(/authorization|api[-_]?key|token|secret/i);
  });
});

describe('the skill the plugin ships', () => {
  const path = join(ROOT, 'plugins', 'travel-a2ui', 'skills', 'travel-a2ui', 'SKILL.md');

  it('is a directory with a SKILL.md, which is how skills are discovered', () => {
    expect(existsSync(path)).toBe(true);
  });

  it('carries the frontmatter a skill is matched on', () => {
    const body = readFileSync(path, 'utf-8');
    expect(body.startsWith('---\n')).toBe(true);
    const frontmatter = body.slice(4, body.indexOf('\n---', 4));
    expect(frontmatter).toMatch(/^name: travel-a2ui$/m);
    expect(frontmatter).toMatch(/^description: .{40,}/m);
  });

  /**
   * The component contract is fetched, not shipped. A copy in the plugin goes
   * stale the moment the deployment adds a component; this keeps the skill
   * pointing at the tool that always has the current one.
   */
  it('sends the model to the server for the component contract', () => {
    const body = readFileSync(path, 'utf-8');
    expect(body).toContain('get_a2ui_component_reference');
  });

  it('tells the model the two things the server will refuse it for', () => {
    const body = readFileSync(path, 'utf-8');
    expect(body).toMatch(/never invent a date/i);
    expect(body).toContain('provenance');
  });
});
