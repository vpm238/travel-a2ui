/**
 * Which Chromium every tool here drives, decided once.
 *
 * This was copied into five scripts and missing from three of them, which is
 * how it usually goes: the two that had it worked, and `catalog.mjs` failed
 * with "Executable doesn't exist at .../chromium_headless_shell-1234/..." — a
 * message about a build number nobody chose, on a machine with a perfectly good
 * browser at a different one.
 *
 * `CHROMIUM_PATH` wins, so a machine with its own browser can say so. Otherwise
 * a preinstalled one is used if it is actually on disk, and failing that
 * Playwright resolves its own, which is the case on CI after `playwright
 * install`. Naming a path that does not exist is worse than naming none, so the
 * check is for the file rather than for the environment.
 */

import { existsSync } from 'node:fs';

import { chromium } from 'playwright';

/** Where the sandbox image keeps its browser. */
const PREINSTALLED = [
  '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  '/opt/pw-browsers/chromium/chrome-linux/chrome',
];

export const executablePath =
  process.env['CHROMIUM_PATH'] || PREINSTALLED.find((path) => existsSync(path)) || undefined;

/** A browser, with the executable resolved. Options pass straight through. */
export const launchBrowser = (options = {}) =>
  chromium.launch({ ...(executablePath ? { executablePath } : {}), ...options });
