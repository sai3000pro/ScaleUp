# Arrow: interface

The visual language every other segment's surfaces are drawn in — colour, type, focus,
contrast, and the persistent shell.

## Status

**AUDITED** — last audited 2026-08-21 (git SHA `f3a4706`). Created to close a hole the
signal-path mapping itself left: the lens dissolved the frontend across the behavioural
segments, which is right for behaviour and leaves visual design with no owner. The theme
layer, the shared class system and the shell were governed by no spec in any segment.

## References

### HLD
- `docs/high-level-design.md`

### LLD
- `docs/intent/interface/interface-design.md`

### EARS
- `docs/intent/interface/interface-specs.md` (49 specs)

### Tests
- `frontend/lib/layout3d.test.ts` — depth ordering, ring spacing, stability, framing
- `frontend/lib/theme.test.ts` — computes contrast ratios and ramp order from the shipped
  token block, checks the `nodeState.ts` mirror, and rejects colours from a superseded
  palette

### Code
- `frontend/app/globals.css` — the `@theme` token block, shell styles, ambient decoration
- `frontend/lib/ui.ts` — `FOCUS_RING`, `BUTTON_PRIMARY`, `BUTTON_SECONDARY`, `INPUT`, `CARD`, `NAV_LINK`, `MUTED`
- `frontend/lib/nodeState.ts` — node-state literals mirroring the theme block
- `frontend/app/layout.tsx` — font binding, skip link, document language
- `frontend/components/ExpBar.tsx` — the HUD composition
- `frontend/lib/layout3d.ts` — where each skill sits in space
- `frontend/components/skill-tree/SkillGraph3D.tsx` — the WebGL canvas and its interactions
- `frontend/lib/usePrefersReducedMotion.ts` — the shared motion preference

## Architecture

**Purpose:** Hold every visual decision in one place, so a palette revision is a token edit
rather than a sweep, and so presentation invariants that break silently can be stated as
checkable claims.

**Key Components:**
1. A single `@theme` token block; the neutral and accent ramps are inverted in place, which
   repaints the whole application without touching a component.
2. `lib/ui.ts` — one definition each for the recurring interactive surfaces.
3. `lib/nodeState.ts` — the one declared exception, for colours the canvas takes as values.
4. `lib/theme.test.ts` — the ratios, the ramp order and the mirror, asserted from source.
5. The shell — HUD, wordmark, navigation, and an explicit narrow-breakpoint reflow order.

## Spec Coverage

| Category | Spec IDs | Implemented | Deferred | Gaps |
|---|---|---|---|---|
| Token layer | `UI-THEME-001` – `008` | 7 | 1 | 0 |
| Shared classes | `UI-SYS-001` – `005` | 3 | 0 | 2 |
| Typography | `UI-TYPE-001` – `004` | 3 | 0 | 1 |
| Accessibility | `UI-A11Y-001` – `009` | 9 | 0 | 0 |
| Skill graph | `UI-GRAPH3D-001` – `016` | 14 | 0 | 2 |
| Shell | `UI-SHELL-001` – `007` | 6 | 0 | 1 |

**Summary:** 42 of 49 implemented; 1 deliberate non-want; 6 active gaps.

## Key Findings

1. **Presentation invariants break silently, and this segment exists because of it.** Every
   defect found here survived a full palette rewrite and a browser walkthrough, because none
   of them look like bugs: text at 4.37:1 looks like text, and a gradient into the previous
   palette's navy looks like a gradient. All of them are computable from source, which is why
   the segment's specs are stated as ratios rather than as adjectives.

2. **A token-layer repaint does not reach raw colour literals.** The ramp inversion repainted
   every component that names a class, and left untouched every rule written with `rgb()` —
   so the character hall kept two gradients blending into the superseded dark palette and two
   badges setting `color: white` on what had become a pale tint, rendering their own labels
   invisible. This is the cost of the inversion technique, and it is now a test rather than a
   caveat (`UI-THEME-007`).

3. **The colour that fails is the one on the surface nobody measures against.** Muted text
   was tuned against the page and lands on a raised card, one step lighter, where it fell
   short. The fix is at the token layer, so it reaches all 58 use sites without touching a
   component — which is the inversion technique paying for itself in the same segment where
   it cost something (`UI-A11Y-007`).

4. **The one constant nobody adopted is the one that would have prevented finding 3.**
   `MUTED` exists precisely to stop sub-AA muted text and is used in **0** components, while
   `text-slate-500`, the class it replaces, appears 58 times. `FOCUS_RING` and `CARD` sit at
   18 components each and `BUTTON_PRIMARY` at 12, so the system is adopted in general — this
   is a single-constant failure, not a cultural one (`UI-SYS-004`, `UI-SYS-005`).

5. **Focus indication is genuinely solved.** Every `focus-visible` occurrence in the
   application arrives through `FOCUS_RING`; there are zero ad-hoc ones. This is the
   strongest evidence for the one-definition principle working.

6. **The declared duplicate held.** Both the theme block and `nodeState.ts` name each other,
   and their five node-state values agree. A declared duplicate that stays in sync is a
   different thing from an undeclared one — and it is now asserted rather than trusted.

## Work Required

### Should Fix
1. Adopt `MUTED` at the 58 raw sites, or delete it (`UI-SYS-004`, `UI-SYS-005`). Best done
   per component as each is touched: a single sweep would recolour text where the raw class
   was deliberate.

### Consider
2. Declare a type scale and move the shell's eight ad-hoc sizes onto it (`UI-TYPE-004`).
3. Audit wide content for its own scroll container (`UI-SHELL-007`).
