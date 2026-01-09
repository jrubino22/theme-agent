Task: Mark “gift” products in cart requests via line-item properties
Goal

When a customer adds a product to cart, if the product has the gift tag, the add-to-cart request must include a line item property:

gift = true

This should apply anywhere in the theme that adds items to cart (PDP, quick add, featured product sections, product cards, etc.).

Requirements

Do not change styling/CSS.

Do not add new content/assets.

Keep changes minimal and follow Horizon JS architecture rules (use assets modules + components/events, no feature-sized inline JS).

The property must be included in the cart/add request as a Shopify line item property.

Format should be a standard cart line item property (e.g. properties[gift]=true or JSON { properties: { gift: "true" } } depending on the existing add-to-cart implementation.

Only set the property when the product is tagged gift. Otherwise do not include it.

Tag signal (how to detect)

Use the existing data already available in the theme (preferred):

If the product JSON / product object already includes tags in the JS layer, use that.

If not, add a minimal “data handoff” in Liquid (allowed) to expose whether the current product is a gift:

e.g. add a boolean data-is-gift="true" on the relevant product form / component root (or similar)

Avoid adding inline JS; use attributes and component refs.

Verification

Add a quick, reproducible verification step:

Add a “debug artifact” file under the run artifacts directory describing where the logic lives and what payload shape you changed.

If Playwright smoke tests exist, add/extend a simple route test that adds a gift-tagged product and confirms the request includes the gift property (if feasible with existing test harness). If not feasible, clearly state why in admin_steps or edits.

Acceptance criteria

Adding a gift-tagged product results in cart line item properties including gift: "true" (or true if your codebase standard is boolean).

Adding a non-gift product does not include the property.

No style changes.
