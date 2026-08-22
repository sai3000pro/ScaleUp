# Arrow: landing

The public argument for the product — why coaching is hard, why it is expensive, and what
this system does about it. It owns no behaviour and renders no learner state.

## Status

**AUDITED** — last audited 2026-08-22 (git SHA `6346ba8`). Created with the segment: the
application had no public surface at all, and the root redirected straight to `/courses`.

The segment exists because *what the page may claim* is a design constraint with teeth, and
a constraint with no owner is a constraint nobody keeps. It is the one place in the codebase
where a wrong number is paid for entirely by a reader who cannot check it.

## References

### HLD
- `docs/high-level-design.md` — the tenet *the public page claims only what the product
  already does*, and the Problem section this page renders for a stranger

### LLD
- `docs/intent/landing/landing-design.md`

### EARS
- `docs/intent/landing/landing-specs.md` (27 specs)

### Tests
- `frontend/lib/landingEvidence.test.ts` — every figure carries a non-empty source; a claim
  about another codebase cites a file with an extension and says what was missing; no figure
  states a price while `LAND-CLAIM-006` stands

### Code
- `frontend/lib/landingEvidence.ts` — every stated quantity, each with its source
- `frontend/app/page.tsx` — the root route and its metadata
- `frontend/components/landing/LandingRoute.tsx` — reads the session, picks the destination
- `frontend/components/landing/LandingPage.tsx` — the seven movements
- `frontend/components/landing/Reveal.tsx` — the reveal, from displaced to the markup default
- `frontend/app/globals.css` — the `.landing-*` block
- `frontend/components/AuthGate.tsx` — public paths, and the gate a public page skips
- `frontend/components/ExpBar.tsx` — the HUD's suppression on the root

## Architecture

**Purpose:** Make the case for the product to someone who is not a learner, without making a
claim the product cannot support.

**Key Components:**
1. `landingEvidence.ts` — one module, one record type, `source` non-optional. A figure with
   no provenance does not compile.
2. Three verified findings about sibling repositories, each citing the file it was read from.
   The evidence movement is the segment's reason to exist; everything else frames it.
3. `Reveal` — `IntersectionObserver`, animating *from* a displaced state *to* the markup
   default, so the no-JS and reduced-motion renders are the complete page.
4. The root is public and is not exchanged for another destination when a session exists.

## Spec Coverage

| Category | Spec IDs | Implemented | Deferred | Gaps |
|---|---|---|---|---|
| Claims | `LAND-CLAIM-001` – `007` | 5 | 2 | 0 |
| Narrative | `LAND-STORY-001` – `010` | 9 | 0 | 1 |
| Motion | `LAND-MOTION-001` – `005` | 4 | 1 | 0 |
| Route | `LAND-ROUTE-001` – `005` | 4 | 0 | 1 |

**Summary:** 22 of 27 implemented; 3 deliberate non-wants; 2 active gaps.

## Key Findings

1. **The stat sources named for this work contain no statistics.** `music-maestro`,
   `MusicTeacher` and `vocal-ai` were read for figures on what coaching costs — lesson
   prices, teacher supply, attrition. They hold none; they are hackathon projects carrying
   problem statements and DSP thresholds. The cost argument is therefore made from what a
   tutor *does*, and every quantity on the page is drawn from this repository. This is
   recorded as an open question rather than closed, because a sourced figure is still wanted.

2. **What those repositories do contain is a better argument than a market figure.** Three
   independent teams built an AI music coach and none could hear a wrong note:
   `music-maestro` scores to the nearest semitone with no onset and no duration;
   `MusicTeacher` returns `np.random.uniform(7.0, 9.5)` as a pitch score; `vocal-ai` carries
   real vocal science and persists fabricated metrics from its fallback path. Each is checked
   against the file it cites, and each is a different failure — together they are a map of
   the problem rather than a list of competitors.

3. **A public page was blocked by the session gate, and the gate looked correct.**
   `AuthGate` withheld *all* rendering until the first `/me` call resolved. Adding `/` to the
   public-path set was not enough: a stranger still saw `Loading…` for as long as the API
   took, and indefinitely if the API was down. Being public and being ungated are two
   different properties, and only the first was expressed (`LAND-ROUTE-001`).

4. **The type refuses an unsourced claim, which is the only enforcement that survives.** A
   convention that figures should carry sources is a convention; a required field is a
   compile error. The test layer adds what a type cannot — that the source is a real path and
   that no price appears while `LAND-CLAIM-006` stands.

5. **Ornament that encodes nothing was removed rather than justified.** The evidence cards
   carried `01 / 02 / 03` markers. The three attempts are independent and nothing depends on
   which is read first, so the numbering claimed an order that does not exist.

## Work Required

### Should Fix
1. Derive the instrument count and names from the curricula rather than typing them
   (`LAND-STORY-010`). The figure is correct today and will drift the first time a curriculum
   is added.

### Consider
2. Declare social preview metadata, so a shared link renders as a card (`LAND-ROUTE-005`).
3. Find a citable source for a market figure and fill the open slot in `landingEvidence.ts`.
   Until then `LAND-CLAIM-006` stands and the page says nothing about price.
