---
parent: high-level-design
prefix: UI
---

# Interface

## Context and Design Philosophy

Every other segment in this project owns a behaviour — a note is segmented, a take is
scored, a skill decays. This one owns the visual language all of those behaviours are drawn
in: colour, type, spacing, focus, contrast, and the persistent shell they sit inside. It
exists because presentation is a real design surface with its own invariants, and because
those invariants are the kind that break silently — nothing throws when text falls to 3:1,
or when a superseded colour survives a repaint.

The boundary is content, not file location. `PracticePanel` renders a take, so it belongs to
evaluation; `SkillNodeCard` renders a node's state, so it belongs to progression. What
belongs here is what those components *draw with*.

Three principles govern the segment.

**One definition per visual decision.** A colour, a button, a focus ring, a card — each is
declared once and referenced by name. The alternative is not "slightly inconsistent"; it is
a change that has to be made in forty places and gets made in thirty-seven.

**Contrast is a measurement, not a judgement.** Text either clears 4.5:1 against the surface
behind it or it does not, and the surface behind it is often a raised card rather than the
page. A palette is not finished when it looks right; it is finished when the ratios have
been computed.

**The theme is a token layer, not a set of component edits.** The whole interface is
repainted by redefining tokens. That is what makes a palette revision a bounded change
rather than a sweep across every component in the application, and it is why the one
unavoidable exception — colours that must be passed as values rather than class names — is
confined to a single mirrored module that names what it mirrors.

## The token layer

`frontend/app/globals.css` declares the palette in a single `@theme` block. Two ramps
matter: a warm, rose-biased neutral ramp used for surfaces and ink, and a set of accent
ramps used for emphasis and state.

The neutral ramp is **inverted relative to its conventional direction**: `slate-950` is the
page white and `slate-50` is the strongest ink. The application is written against a dark
palette, consistently using the dark end of each ramp for surfaces and the light end for
text, so inverting each ramp repaints the entire interface coherently. The alternative —
rewriting components — measures at 643 individual class changes with a long tail of ones
that would be missed. The inversion is a property of the token layer alone; no component
knows it happened.

The neutrals carry a faint warm/rose bias rather than being neutral grey, so they sit
underneath the blossom accent instead of fighting it.

**One exception is structural.** React Flow edge strokes and the SVG proficiency ring take
colour *values*, not class names, so the node-state palette exists twice: as tokens in the
theme block and as literals in `frontend/lib/nodeState.ts`. The mirror is declared in both
files. It cannot be removed without either giving up the canvas or computing styles at
runtime, so it is managed rather than eliminated.

## The shared class system

`frontend/lib/ui.ts` holds the recurring surfaces: `BUTTON_PRIMARY`, `BUTTON_SECONDARY`,
`INPUT`, `CARD`, `NAV_LINK`, `FOCUS_RING`, `MUTED`. Each is a literal string, never
interpolated — the compiler scans source text for class names, so a class assembled from a
variable is never generated at all.

`FOCUS_RING` is the load-bearing one. Without it no control in the application has a focus
style, so keyboard users get the browser default on some elements and nothing
distinguishable on others. It is `focus-visible` rather than `focus`, so a mouse click does
not leave a ring behind.

Adoption is uneven, and the unevenness is measurable: `CARD` and `FOCUS_RING` are used in 18
components each and `BUTTON_PRIMARY` in 12 — while `MUTED` is used in none, and the
low-contrast class it exists to replace appears 58 times. A constant nobody uses is not a
design system; it is a comment (`UI-SYS-004`, `UI-SYS-005`).

## Typography

Sora for display, Space Grotesk for body, both loaded through the framework's font pipeline
and bound to `--font-display` / `--font-body` with a system fallback stack. Headings are set
light (300) and tightly tracked; uppercase micro-labels take positive letter-spacing so they
stay readable at the sizes the HUD uses them at.

There is no declared type scale. Sizes are chosen per component, largely as fractional `rem`
values in the shell stylesheet, which is why the HUD carries eight distinct font sizes
between 0.48rem and 0.95rem (`UI-TYPE-004`).

## The shell

The persistent HUD — wordmark, level pill, experience track, streak, navigation — is a game
header rather than application chrome, and it is styled in the stylesheet rather than in
shared classes because it is one composition rather than a reusable pattern.

Its responsive behaviour is explicit: below 768px the header reflows to a stack with a
declared `order` for each element, rather than scrolling sideways or wrapping arbitrarily.
This is stated as intent because reflow ordering that emerges from source order is the kind
of thing that silently changes when a component is moved.

Ambient decoration — the plus-mark grid and the blossom wash — is painted in CSS gradients on
a fixed pseudo-element, masked to fade out down the page. It loads no asset, sits at
`z-index: -1`, and is `pointer-events: none`.

## Current state versus intent

The gap between the two is adoption, not correctness. The token layer is complete, its ramps
are ordered, its contrast ratios are computed rather than judged, and the one declared
duplicate is asserted to stay in sync — all of it in `frontend/lib/theme.test.ts`, which
reads the shipped stylesheet rather than a copy of it.

What remains is the class system's uneven uptake. `MUTED` exists to keep muted text above
4.5:1 and is used in no component, while the class it replaces appears directly in 58
places. Those sites are currently correct — the token beneath them was moved — but they are
correct by accident, and the next palette change will not know they exist (`UI-SYS-004`,
`UI-SYS-005`). Type sizes have the same shape of problem without the same stakes: chosen per
component rather than drawn from a declared scale (`UI-TYPE-004`).

**The technique has a known cost.** Inverting ramps in the token layer repaints every
component that names a class, and reaches nothing written as a raw `rgb()` literal. That is
the whole reason `UI-THEME-007` is a spec with a test behind it rather than a note: the
failure mode is a rule that keeps a colour from a palette that no longer exists, and it is
invisible until someone looks at that one component.

## Decisions & Alternatives

| Decision | Chosen | Alternatives | Rationale |
|---|---|---|---|
| Repainting the interface | Invert the ramps in the token layer | Rewrite component classes; add a parallel light ramp | Inversion is one file and repaints everything coherently; the rewrite measures at 643 changes with a long tail of misses. A parallel ramp means every component must be taught which of the two to read. |
| Node-state colour | Declared twice, with the mirror documented in both files | Resolve canvas colours from CSS custom properties at runtime | The canvas takes values, not classes. Runtime resolution puts a `getComputedStyle` call in a path that runs per edge, per frame. |
| Theme switching | A single committed light theme | Follow `prefers-color-scheme`; offer a toggle | The inverted-ramp technique produces exactly one palette. Supporting two requires the parallel-ramp approach the inversion was chosen over. |
| Shell styling | Stylesheet rules rather than shared classes | Inline utility classes like the rest of the app | The HUD is one composition used once, not a pattern used many times. A shared constant for a single use site is indirection without reuse. |
| Focus indication | `focus-visible`, one shared constant | `focus`; per-component styles | `focus` rings on mouse clicks, which reads as a bug and gets deleted by the next person. One constant is what makes "every control has a focus style" checkable at all. |
| Ambient decoration | CSS gradients | An image asset | No request, no cache concern, and no asset to keep in sync with the palette — it repaints when the tokens do. |

## Open Questions & Future Decisions

### Deferred

- **A declared type scale** (`UI-TYPE-004`). The HUD's eight ad-hoc sizes are the evidence
  that one is wanted; imposing it is a sweep across the shell stylesheet, and is not urgent
  while the shell is still moving.
- **`MUTED` adoption** (`UI-SYS-004`). The 58 raw uses are the work. Doing it as one sweep
  risks changing text colour where the raw class was deliberate; doing it per component as
  each is touched is slower but keeps every change reviewable.

### Open

- **Where does the boundary sit for a component that is mostly presentation?** The character
  hall is roughly two-thirds visual composition and one-third progression state. It is
  assigned to progression under the content rule, but its stylesheet lives here — so a change
  to it can straddle two segments.
- **Should `nodeState.ts` be generated from the theme block?** A build step would remove the
  mirror entirely, at the cost of a build step nothing else in the frontend needs.

## References

- `frontend/app/globals.css` — the token layer, shell styles, ambient decoration
- `frontend/lib/ui.ts` — shared class constants
- `frontend/lib/nodeState.ts` — the mirrored node-state literals
- `frontend/app/layout.tsx` — fonts, skip link, document language
- `frontend/components/ExpBar.tsx` — the HUD composition
- `docs/high-level-design.md` — project-level architecture and tenets
