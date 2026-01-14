Horizon JS architecture context (assets folder)
1) Don’t write inline JS for features

Inline <script> in Liquid should be limited to:

global bootstrapping (import maps, module loads, tiny config objects)

very small “data handoff” one-liners that call an existing module

Any real feature logic (DOM querying, event handlers, state, async flows, UI updates) belongs in assets/*.js as an ES module and should integrate with the theme’s Component + ThemeEvents + section rendering patterns.

2) Component base class: web components + refs + declarative event binding

Horizon’s interactivity is built around custom elements extending Component (assets/component.js), which itself extends a DeclarativeShadowElement:

Declarative shadow DOM support

DeclarativeShadowElement hydrates declarative shadow DOM templates if the element is connected after initial page render (it looks for template[shadowrootmode="open"] and attaches it).

Automatic refs system

Component maintains this.refs by scanning descendants for [ref] attributes across both light DOM and shadow DOM roots:

get roots() returns [this, this.shadowRoot] if a shadow root exists, otherwise [this]

a MutationObserver keeps refs in sync when DOM changes

optional requiredRefs = [...] throws if a required ref is missing (via MissingRefError)

LLM rule: when you add markup a component depends on, wire it with ref="..." and use this.refs instead of repeated querySelector.

Declarative event listeners via on:* attributes

Horizon registers global delegated listeners once (on first component connection). Supported events include:

Common: click, change, select, focus, blur, submit, input, keydown, keyup, toggle

“Expensive” events handled specially: pointerenter, pointerleave

Instead of ad-hoc addEventListener everywhere, you put attributes like:

on:click="methodName"

on:click="selector/methodName"

Optional data can be appended as the final segment prefixed with ? (parsed as URLSearchParams)

Example pattern: on:click="my-component/doThing?variantId=123&qty=2"

At runtime, Horizon:

finds the element with on:${event.type}

finds the target Component instance (closest component, or a selector like #id / closest(selector))

calls the method on that component

passes parsed data when provided

proxies event.target to the element holding the on:* attribute to make handlers more predictable

LLM rule: prefer on:click etc + component methods. Avoid scattering direct DOM listeners unless there’s a strong reason.

3) Theme-wide events: ThemeEvents + typed Event classes (assets/events.js)

Horizon centralizes cross-feature coordination using custom DOM events that bubble.

Canonical event names

ThemeEvents defines string constants like:

variant:selected

variant:update

cart:update

cart:error

media:started-playing

quantity-selector:update

megaMenu:hover

zoom-media:selected

discount:update

filter:update

Use the provided Event classes (don’t invent your own shape)

Horizon ships event classes that set bubbles: true and standardize .detail payloads, e.g.:

VariantSelectedEvent

VariantUpdateEvent (detail includes { resource, sourceId, data: { html, productId, newProduct? } })

CartAddEvent

CartUpdateEvent

CartErrorEvent

QuantitySelectorUpdateEvent

DiscountUpdateEvent

MediaStartedPlayingEvent

SlideshowSelectEvent

ZoomMediaSelectedEvent

MegaMenuHoverEvent

FilterUpdateEvent

LLM rule: if your feature needs to notify other parts of the theme, dispatch one of these events (or add a new ThemeEvents constant + event class in the same style). Don’t directly reach into other components and mutate them.

4) Section Rendering + Morphing: section-renderer.js

Horizon re-renders sections using Shopify’s Section Rendering API style URL:

It builds URLs by setting ?section_id=<normalized> on the current URL and sorting search params.

A section’s DOM id is expected to be shopify-section-<id>.

Key helpers

normalizeSectionId(sectionId) strips the shopify-section- prefix if present

buildSectionSelector(sectionId) adds shopify-section- prefix

sectionRenderer behavior

sectionRenderer is a singleton instance of SectionRenderer that:

Caches section HTML by section-render URL (enabled by default when not in Shopify.designMode)

Dedupes in-flight fetches per section-render URL (#pendingPromises)

Aborts pending morphs per section using AbortController keyed by section ID (so rapid updates don’t apply stale results)

When renderSection(sectionId, options) runs:

it fetches the latest section HTML (cached unless cache: false)

then calls morphSection(sectionId, html) to morph the existing section element into the new element using morph() (assets/morph.js)

throws if it can’t find the existing section element or the replacement element in the response

LLM rule: if you need to update UI that is section-based (cart drawer, product info, etc.), use sectionRenderer.renderSection(...) (or call the underlying patterns) rather than manual DOM patching.

5) Lazy hydration: section-hydration.js

This module provides hydrate(sectionId, url?) which:

waits for DOM ready

uses requestIdleCallback

calls sectionRenderer.renderSection(normalizedId, { cache: false, url })

then sets section.dataset.hydrated = 'true' to avoid re-hydrating

LLM rule: if a section is meant to be hydrated later (performance), use this API instead of inventing a new “lazy init” system.

“LLM guardrails” summary (copy/paste)

No feature-sized inline JS in Liquid. Put logic in assets/*.js.

Prefer custom elements extending Component.

Use ref="..." + this.refs for DOM references.

Use on:* declarative handlers (e.g. on:click="method"), not random listeners.

Use ThemeEvents + provided Event classes for cross-component coordination.

For UI refreshes, use sectionRenderer.renderSection (morphing) and hydrate() for lazy hydration.

Normalize section IDs with normalizeSectionId() and expect DOM ids like shopify-section-<id>.

Theme blocks in Horizon (critical conventions)
Why theme blocks matter here

Horizon is built to encourage reusable, composable content building blocks that are defined at the theme level and then used across sections/templates. The goal is to avoid duplicating “the same block concept” inside many different section schemas.

LLM rule: default to theme blocks for reusable UI patterns. Only use section-local blocks when the block truly only makes sense within one specific section.

Theme blocks vs “classic section blocks”
Classic section blocks (old default)

Blocks are declared inside a section’s schema

The block types exist only within that section

Reuse across sections means copying schema + Liquid patterns

This is what LLMs tend to do by habit.

Theme blocks (Horizon convention)

Blocks are defined in the /blocks directory (theme-level)

They’re intended to be reused across many sections

They are designed to be nestable/composable, so merchants can build richer layouts without you creating a bespoke “mega section” for every layout

LLM rule: if you’re adding something like a CTA, badge, promo tile, icon+text row, accordion item, media-with-text unit, trust markers, etc., it should usually be a theme block.

Practical conventions to follow when implementing a theme block
1) Put the implementation in /blocks/

A theme block’s Liquid should live in blocks/<name>.liquid (or whatever the repo’s naming pattern is).

The block should be self-contained:

semantic markup

settings-driven rendering

minimal assumptions about its parent container

2) Keep a clean “data contract”

Theme blocks should rely on:

settings provided by the block schema

the block object/context passed by Shopify

Avoid tightly coupling a block to one specific section’s DOM structure.

3) Make blocks “composition-friendly”

Blocks should be safe in different contexts:

inside different sections

inside different layouts (grid, stack, carousel)

Don’t hardcode outer layout constraints that belong to the parent section (like grid columns, page-width wrappers, etc.) unless the block is explicitly a layout block.

4) Styling: avoid section-specific assumptions

Use theme utility classes / tokens consistently (whatever Horizon’s CSS architecture is in your repo).

Don’t write CSS that assumes a single section wrapper. Prefer block-level classes and inherited layout.

5) JS: blocks shouldn’t invent their own initialization model

If a theme block needs interactivity:

Prefer implementing the interactivity as a Component custom element in assets/ (Horizon pattern)

Use ref="..." and on:* declarative handlers

Communicate via ThemeEvents if coordination is needed

If the block affects section HTML, use sectionRenderer (don’t patch DOM manually)

When NOT to use theme blocks

Use section-local blocks when:

the block only exists to support one section’s internal layout

it depends heavily on that section’s markup structure

it would be confusing or unsafe if reused elsewhere

Even then, keep the block logic minimal and still follow Horizon’s JS conventions.

Anti-patterns LLMs should avoid in Horizon

Creating a new “mega section” just to get a certain layout, instead of composing with theme blocks

Copy/pasting the same block schema into multiple sections (classic OS2 style)

Building UI variations as separate sections when they should be theme blocks with settings

Adding block-specific inline scripts rather than using Component + ThemeEvents

Add this to your LLM guardrails

Prefer theme blocks (/blocks) for reusable patterns; reserve section blocks for truly section-specific internals.

Make blocks self-contained and layout-agnostic; parent sections own layout and spacing.

Interactive blocks must use Horizon’s Component/event architecture, not inline JS.

**Important** - For design/style changes, always first see if it's possible to simply update the configuration in json files. If it seems like it's not possible to achieve the desired style by updating json files, then we can move on to editing / creating liquid files. The goal should always be to keep the theme as native as possible. (we will certainly
have to write plenty of custom code, so don't be afraid to write custom code after confirming it's necessary to do so).
Make sure to fill in content via json files even for custom built components too. For example, if you build a new section
for the product page, add it and some content to product.json and use Shopify MCP/CLI to ensure there are no JSON errors.