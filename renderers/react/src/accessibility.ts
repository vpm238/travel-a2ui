/**
 * The protocol's `accessibility` block, as DOM attributes.
 *
 * A2UI 1.0 lets every component carry `accessibility` — a short `label`, a
 * longer `description`, an ARIA `live` politeness, and `hidden` for decoration
 * — and it is the one part of the protocol an agent cannot route around. A
 * traveller using a screen reader hears whatever the renderer exposes, and
 * until this file existed the renderer exposed only what it had hard-coded
 * itself: good roles on the controls it knew about, and nothing the agent said.
 *
 * So: resolved like any other property (a label may be bound — `@path` to the
 * leg it describes — and the point of a `live` region is that its text
 * changes), and spread on the component's own root element rather than a
 * wrapper, because `aria-label` names the element it sits on and a wrapper
 * would name a box around it instead.
 */

import type { Json } from '@travel-a2ui/express';

import { resolveBoolean, resolveText, type ResolveScope } from './binding.js';

/** What `accessibility` becomes on an element. */
export interface AriaProps {
  role?: string;
  'aria-label'?: string;
  'aria-description'?: string;
  'aria-live'?: 'off' | 'polite' | 'assertive';
  'aria-hidden'?: true;
}

const POLITENESS = new Set(['off', 'polite', 'assertive']);

/**
 * The `accessibility` block on this node, ready to spread.
 *
 * `fallbackRole` is for the elements that have no role of their own. A name on
 * a bare `div` is not announced — every screen reader drops `aria-label` on a
 * generic container — so a labelled `Column` would look plumbed and be silent.
 * Containers pass `'group'`, which is the honest role for a box somebody named.
 * Anything that is already a control — a button, a text input, a slider —
 * passes nothing, because a role here would replace the one that makes it
 * operable.
 */
export function ariaOf(
  node: Record<string, Json> | undefined,
  scope: ResolveScope,
  fallbackRole?: string,
): AriaProps {
  const declared = node?.['accessibility'];
  if (!declared || typeof declared !== 'object' || Array.isArray(declared)) return {};
  const block = declared as Record<string, Json>;

  const out: AriaProps = {};
  const label = resolveText(block['label'], scope).trim();
  const description = resolveText(block['description'], scope).trim();

  if (label) out['aria-label'] = label;
  // `aria-description` is the attribute that matches this property exactly, and
  // the alternative — a visually hidden span plus `aria-describedby` — means
  // every component here learning to render a child it did not ask for. The
  // browsers that do not support it yet drop it silently, which costs a
  // description and breaks nothing.
  if (description) out['aria-description'] = description;

  if (fallbackRole && (label || description)) out.role = fallbackRole;

  const live = block['live'];
  if (typeof live === 'string' && POLITENESS.has(live) && live !== 'off') {
    out['aria-live'] = live as 'polite' | 'assertive';
  }

  // Only when true. `aria-hidden="false"` is not the opposite of hiding — it is
  // a value the spec leaves to the browser — so the absent case stays absent.
  if (resolveBoolean(block['hidden'], scope)) out['aria-hidden'] = true;

  return out;
}
