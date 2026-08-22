---
parent: high-level-design
prefix: LAND
---

# Landing

## Context and Design Philosophy

Every other segment addresses a learner — someone who has an account, a course and a take in
progress. This one addresses a stranger. It is the public argument for the product: why
getting coached on an instrument is hard, why it is expensive, and what this system does about
it. It renders no learner state and owns no behaviour.

It is a segment rather than a page because **what it is allowed to claim is a design
constraint**, and a constraint with no owner is a constraint nobody keeps. A marketing surface
is the one place in a codebase where the cost of an unverified number is paid entirely by
someone who cannot check it. The HLD's tenet — *the public page claims only what the product
already does* — is enforced here or nowhere.

Three principles follow from that.

**Every figure on the page is traceable at the point of use.** A number carries the file,
symbol or source it came from, in the source and on the page. This is not a footnote habit; it
is what makes the tenet checkable by someone who was not there when the number was chosen.

**Evidence beats assertion.** "Coaching is expensive" is an assertion, and the reader has
heard it. What they have not heard is that three independent teams built an AI music coach and
none of them could hear a wrong note — one scored to the nearest semitone with no timing at
all, one drew its scores from a random number generator, and one fabricated metrics in its
fallback path and persisted them as real. That argument is specific, checkable, and makes the
difficulty concrete in a way no market figure does.

**The mascot carries the tone, never the argument.** Quartz is why the page is likeable; the
evidence is why it is believed. A reader who turns off animation loses charm and no substance.

## What the page argues

The narrative is the HLD's own Problem section, made concrete. A tutor supplies two things —
measurement in the moment and memory across months — and those two are most of what makes one
expensive. The page walks that in seven movements:

| # | Movement | What it does |
|---|---|---|
| I | **Hero** | The promise, with Quartz on stage. One sentence, one action. |
| II | **The two failures** | Unmeasured practice and silent decay, stated as the HLD states them. |
| III | **What a tutor actually costs** | The hour is not the product; the *attention* is. What a tutor does that a metronome and a video cannot. |
| IV | **Three teams tried** | The evidence section. Three named repositories, one verified finding each, each citing the file it can be checked in. |
| V | **What it takes to actually hear it** | The system's answer: alignment, cents, dynamics, posture — and the deterministic floor. |
| VI | **And then remembering** | Decay, SM-2, the quest that brings a faded skill back. |
| VII | **Enter** | The tech tree, and the way in. |

Movement IV is the load-bearing one and the reason the segment exists. Its three findings are
verified facts about code in sibling repositories, not characterisations:

- **music-maestro** scores a note by `Math.round(midiNum) == current_note.pitch`
  (`static/js/script.js`), incrementing a counter. There is no cents figure, no onset, and no
  duration — a note 49 cents flat scores identically to a perfect one, and a note played at
  the wrong moment scores identically to one in time.
- **MusicTeacher** returns `np.random.uniform(7.0, 9.5)` for pitch, and comparable draws for
  rhythm and dynamics (`backend/services/ai_services.py`). The feedback is a random number
  with a rubric written around it.
- **vocal-ai** carries genuine vocal science — jitter above 0.020 and shimmer above 0.025 read
  as strain, vibrato is optimal near 5.5–6 Hz (`backend/enhanced_letta_service.py`) — and its
  fallback analyzer invents metrics that are then persisted as though measured.

The point of the section is not that these teams failed. It is that hearing a performance well
enough to coach it is hard enough that three serious attempts each stopped short in a
different place, and that the honest thing to do about it is to say which measurements are
real and which are absent.

### The figures the page does not have

**No market statistic on this page is sourced, because none of the named repositories contains
one.** They are three hackathon projects: they hold problem statements and DSP thresholds, not
lesson prices, teacher supply or attrition rates. Rather than invent a plausible-looking
figure, the cost argument is made from what a tutor *does* — which is the argument the HLD
itself makes — and every quantity on the page is drawn from this repository.

`frontend/lib/landingEvidence.ts` is the single module those quantities live in, and it is the
place a sourced market figure would be added: each entry carries its own `source` string, and
a claim without one cannot be rendered because the type does not permit it.

## Structure

`frontend/app/page.tsx` is a server component holding the route and its metadata.
`LandingPage` renders the seven movements and imports the evidence directly — the figures are
a static module, so they are inlined into the markup at build rather than fetched, and the
page ships as a document.

One thing cannot be settled on the server: the session lives in a client store. That is
isolated in `LandingRoute`, which reads it and passes down a destination and a label, so
`LandingPage` itself knows nothing about authentication.

The route is the application root and is **public and ungated**. Being public and being
ungated are separate properties, and the second is the one that bites: the shell withholds
all rendering until the first session check resolves, which would leave a stranger watching a
spinner for as long as the API takes and indefinitely if it is down. The landing page is
excluded from that gate, not merely from the redirect that follows it.

Authenticated learners are not redirected away either — a learner who follows a link to the
argument should see the argument — but the primary action reads the session, so a signed-in
reader is offered their courses where a stranger is offered a sign-up. The learner HUD is
suppressed here, since it reports a progress a stranger does not have.

## Motion

The motion contract is inherited from the shell rather than invented here: **markup defaults
are the final state, and script animates from elsewhere.** A reader with no JavaScript, or
with `prefers-reduced-motion` set, gets the complete page — every figure, every section, in
order — and simply does not see it assemble. This is what keeps the page a document first.

Reveals are driven by `IntersectionObserver` rather than a scroll library. The page has no
pinning, no scrub and no horizontal scroll, so a scroll-timeline dependency would buy nothing
and cost the reader a bundle.

## Decisions & Alternatives

| Decision | Chosen | Alternatives | Rationale |
|---|---|---|---|
| Cost argument's evidence | Verified findings from three sibling repositories | Market statistics on lesson pricing and teacher supply | The named repositories contain no market data. A figure invented to fill the slot would be the exact failure the segment exists to prevent, and a reader who checks one claim and finds it fabricated discounts every other claim on the page. |
| Where figures live | One module, each entry carrying a `source` | Literals inline in the page markup | A claim's provenance has to travel with it or it is lost at the first edit. Making `source` non-optional means an unsourced figure fails to compile rather than fails to be noticed. |
| Scroll narrative mechanism | `IntersectionObserver` reveals | GSAP + ScrollTrigger + Lenis, as in the reference implementation | Those buy pinning, scrub and smoothed scroll; this page uses none of the three. The reference page's structure is worth copying, its dependency list is not. |
| Route | Application root, public, not redirected for learners | Root redirects signed-in users to `/courses` | The page is a document about the product, not an onboarding gate. A learner linking a friend to the argument should not have it swapped out from under them. |
| Session gating | The public page renders before the session check resolves | Wait for hydration everywhere, as every other route does | Waiting spends a round-trip to learn something the page does not use, and fails open to a spinner when the API is unavailable — on the one page whose whole job is to be readable by someone with no account. |
| Root's previous behaviour | Replaced | Landing moved to `/about` or `/welcome` | A product's root is its argument. `/courses` remains one redirect away and is where the primary action sends a signed-in reader. |
| Mascot's role on the page | Tone and punctuation between movements | Mascot narrates the argument in speech bubbles | A character asserting the evidence weakens it — the findings are checkable and should be read as such. Quartz reacts to the argument rather than making it. |

## Open Questions & Future Decisions

- **A sourced cost figure is still wanted.** The qualitative argument is honest but a reader
  responds to a number. The slot exists in `landingEvidence.ts` and needs a citable source —
  a published survey of lesson rates, not an estimate.
- **The page has no social preview.** No Open Graph image or card metadata is set, so a shared
  link renders as a bare URL.
- **Nothing measures whether the argument works.** There is no analytics on the page and no
  instrumentation of which movement a reader stops at.
