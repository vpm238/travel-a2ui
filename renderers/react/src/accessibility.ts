/**
 * The standard `accessibility` block, as ARIA attributes for a travel view.
 *
 * Read with the SDK's own `AccessibilityAttributesSchema`, and mapped by the
 * same rules `@a2ui/web_core`'s basic components apply to themselves: `label`
 * is `aria-label`, `description` is `aria-description`, `live` is `aria-live`
 * (left off when it is the schema's default, `off`, which is ARIA's default
 * too), and a boolean `hidden` is `aria-hidden`. The basic components are web
 * components and apply this to their own element; a React view applies it to
 * its root, which is what this is for.
 */

import { AccessibilityAttributesSchema } from '@a2ui/web_core/v1_0';

export interface AriaAttributes {
  'aria-label'?: string;
  'aria-description'?: string;
  'aria-live'?: 'polite' | 'assertive';
  'aria-hidden'?: boolean;
}

const present = (value: unknown): value is string | number =>
  value !== undefined && value !== null && value !== '' && typeof value !== 'object';

/**
 * The block as the binder hands it over: resolved values, plus a setter beside
 * each bindable one (`setLabel`, `setDescription`). The setters are not part of
 * the schema, so they come off before it is read.
 */
function valuesOf(accessibility: unknown): Record<string, unknown> {
  if (!accessibility || typeof accessibility !== 'object') return {};
  return Object.fromEntries(
    Object.entries(accessibility as Record<string, unknown>).filter(
      ([, value]) => typeof value !== 'function',
    ),
  );
}

export function ariaFrom(accessibility: unknown): AriaAttributes {
  const parsed = AccessibilityAttributesSchema.safeParse(valuesOf(accessibility));
  if (!parsed.success) return {};
  const a11y = parsed.data as Record<string, unknown>;
  const out: AriaAttributes = {};
  if (present(a11y['label'])) out['aria-label'] = String(a11y['label']);
  if (present(a11y['description'])) out['aria-description'] = String(a11y['description']);
  if (a11y['live'] === 'polite' || a11y['live'] === 'assertive') out['aria-live'] = a11y['live'];
  if (typeof a11y['hidden'] === 'boolean') out['aria-hidden'] = a11y['hidden'];
  return out;
}
