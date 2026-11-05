/**
 * The travel catalog for the A2UI SDK renderers.
 *
 * Render with `@a2ui/web_core`'s `MessageProcessor` and `@a2ui/react`'s
 * `A2uiSurface`; this package supplies only what is travel: the catalog
 * (`createTravelCatalog`), its client-side functions, Markdown for `Text`, and
 * the stylesheet that themes the SDK's basic components and draws ours.
 */

export { createTravelCatalog, travelComponentNames, type CatalogDocument } from './catalog.js';
export { calcNights, equals } from './functions.js';
export { renderMarkdown } from './markdown.js';
export { Icon, hasIcon, type IconName, type IconProps } from './components/icons.js';
