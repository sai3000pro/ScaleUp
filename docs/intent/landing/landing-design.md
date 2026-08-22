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

**Concreteness beats assertion, and it does not require a target.** "Coaching is expensive"
is an assertion the reader has heard. What lands instead is the specific shape of the
problem: that rounding a detected pitch to the nearest semitone passes a note a quarter-tone
flat, that comparing note-for-note makes playing slowly indistinguishable from playing wrong,
that absolute loudness measures the room. Each is checkable, each has an answer in this
codebase, and none of them needs anybody to have failed at it first.

**The page names nobody.** No other product, project or codebase appears on it. Arguing that
a problem is hard by pointing at somebody who did it badly is a cheap argument and a
discourtesy, and a reader who came to find out what this does did not come to read about
somebody else's repository. This is enforced rather than trusted — see `LAND-CLAIM-007` and
its test.

**The mascot carries the tone, never the argument.** Quartz is why the page is likeable; the
evidence is why it is believed. A reader who turns off animation loses charm and no substance.

## What the page argues

The narrative is the HLD's own Problem section, made concrete. A tutor supplies two things —
measurement in the moment and memory across months — and those two are most of what makes one
expensive. The page walks that in seven movements:

| # | Movement | What it does |
|---|---|---|
| I | **Hero** | What it does, in one sentence, with Quartz on stage. |
| II | **You can't hear yourself** | An error repeated until it is fluent, and technique lost without notice. |
| III | **What a teacher is for** | A second pair of ears with a long memory — and why that is the expensive part. |
| IV | **Why this is hard** | Four properties of the problem, each with what this system does about it. |
| V | **What it measures** | The figures, each rendering its own source. |
| VI | **And then it fades** | Decay, the review schedule, and the way in. |

Movement IV is the load-bearing one and the reason the segment exists as a segment. Its four
entries are properties of the problem rather than observations about anyone's work, and each
pairs the difficulty with the file here that answers it:

- **Cents, not semitones.** Rounding to the nearest semitone passes a note a quarter-tone
  flat, which is the whole of a string player's problem
  (`backend/app/evaluation/violin.py`).
- **Elastic alignment.** Compared position by position, time disappears; compared strictly by
  the clock, playing slowly to get it right becomes an error
  (`backend/app/evaluation/dtw.py`).
- **Relative dynamics.** Absolute level measures the microphone and the room, so levels are
  centred on the take and contrast is scored as rank agreement
  (`backend/app/evaluation/dynamics.py`).
- **Absent, not zero.** An unmeasured dimension is reported as missing and the rest
  renormalise around it (`backend/app/evaluation/registry.py`).

The fourth is the through-line: a plausible number is far cheaper to produce than a true one
and looks identical on a screen. Stating that as a property of the problem is honest;
attaching it to a named project would be an accusation, and would also invite the reader to
check the accusation rather than the product.

### The figures the page does not have

**No market statistic on this page is sourced, because no citable one was found.** Lesson
prices, teacher supply and attrition rates were looked for and are not available here at a
standard this page would meet. Rather than invent a plausible-looking figure, the cost
argument is made from what a teacher *does*, and every quantity on the page is drawn from this
repository.

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
| How difficulty is shown | Properties of the problem, each paired with the file that answers it | Named prior attempts with a specific finding for each; market statistics on lesson pricing | Naming other projects is a cheap argument and a discourtesy, and it redirects the reader to checking an accusation instead of the product. Market figures were looked for and none is citable, and a figure invented to fill the slot is the exact failure the segment exists to prevent. |
| Where figures live | One module, each entry carrying a `source` | Literals inline in the page markup | A claim's provenance has to travel with it or it is lost at the first edit. Making `source` non-optional means an unsourced figure fails to compile rather than fails to be noticed. |
| Scroll narrative mechanism | `IntersectionObserver` reveals | GSAP + ScrollTrigger + Lenis, as in the reference implementation | Those buy pinning, scrub and smoothed scroll; this page uses none of the three. The reference page's structure is worth copying, its dependency list is not. |
| Route | Application root, public, not redirected for learners | Root redirects signed-in users to `/courses` | The page is a document about the product, not an onboarding gate. A learner linking a friend to the argument should not have it swapped out from under them. |
| Session gating | The public page renders before the session check resolves | Wait for hydration everywhere, as every other route does | Waiting spends a round-trip to learn something the page does not use, and fails open to a spinner when the API is unavailable — on the one page whose whole job is to be readable by someone with no account. |
| Root's previous behaviour | Replaced | Landing moved to `/about` or `/welcome` | A product's root is its argument. `/courses` remains one redirect away and is where the primary action sends a signed-in reader. |
| Mascot's role on the page | Tone and punctuation between movements | Mascot narrates the argument in speech bubbles | A character asserting a technical claim weakens it — the claims are checkable and should read as such. Quartz reacts to the argument rather than making it. |

## Open Questions & Future Decisions

- **A sourced cost figure is still wanted.** The qualitative argument is honest but a reader
  responds to a number. The slot exists in `landingEvidence.ts` and needs a citable source — a
  published survey of lesson rates, not an estimate.
- **The page has no social preview.** No Open Graph image or card metadata is set, so a shared
  link renders as a bare URL.
- **Nothing measures whether the argument works.** There is no analytics on the page and no
  instrumentation of which movement a reader stops at.
