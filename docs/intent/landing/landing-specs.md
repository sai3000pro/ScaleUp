# Landing — EARS Specs

Prefix: `LAND`. Facets: `CLAIM` (what the page may assert, and how a figure is sourced),
`STORY` (the narrative structure and its movements), `MOTION` (reveal behaviour and reduced
motion), `ROUTE` (where the page lives and where it sends a reader).

Status: `[x]` observed working in current code · `[ ]` specified but broken or partial ·
`[D]` deliberate non-want.

**This segment owns the public argument, not any learner behaviour.** It reads no learner
state and renders no scored take. A surface that shows a learner their own progress belongs to
the segment that owns that progress.

---

## What the page may claim

- [x] **LAND-CLAIM-001**: Every quantity rendered on the landing page shall be declared in one evidence module rather than written inline in markup.
- [x] **LAND-CLAIM-002**: Every declared figure shall carry the source it came from, and the type shall not permit a figure without one.
- [x] **LAND-CLAIM-003**: Where a figure describes code in another repository, its source shall name the repository and the file the claim can be checked in.
- [x] **LAND-CLAIM-004**: The page shall render a figure's source alongside the figure, so a reader can check a claim without reading the source code.
- [x] **LAND-CLAIM-005**: A capability shall be described in the present tense only where it is implemented; anything not yet shipped shall be absent rather than described as forthcoming.
- [D] **LAND-CLAIM-006**: The page shall not state a market statistic — a lesson price, a teacher supply figure, an attrition rate — until one is available with a citable outside source.
- [D] **LAND-CLAIM-007**: The page shall not name a competitor product as inferior; a finding about another codebase shall be stated as what that code does, not as a verdict on its authors.

## The narrative

- [x] **LAND-STORY-001**: The page shall open with a single statement of what the product does and one primary action.
- [x] **LAND-STORY-002**: The page shall state both failure modes of practising alone — practice that is never measured, and technique that decays unnoticed — before it describes any remedy.
- [x] **LAND-STORY-003**: The page shall argue the cost of coaching from what a tutor supplies rather than from a price.
- [x] **LAND-STORY-004**: The page shall present evidence that automating a music tutor is hard, drawn from named prior attempts, with one specific finding for each.
- [x] **LAND-STORY-005**: Each evidence finding shall state what the prior attempt could not measure, not merely that it was limited.
- [x] **LAND-STORY-006**: The page shall describe what this system measures in a take, naming the dimensions rather than claiming accuracy in general.
- [x] **LAND-STORY-007**: The page shall state that grading runs with no credentials and no network, since a reader's first question about an AI product is what happens when the model is unavailable.
- [x] **LAND-STORY-008**: The page shall describe decay and return — that unpractised technique fades and is scheduled back — as a distinct movement from measurement.
- [x] **LAND-STORY-009**: The page shall close with the way into the product.
- [ ] **LAND-STORY-010**: The page shall name the instruments that ship with a published curriculum, and the count shall be derived from the curricula rather than typed.

## Motion

- [x] **LAND-MOTION-001**: The page's markup shall render complete and in order with no script, so every figure and every movement is readable without JavaScript.
- [x] **LAND-MOTION-002**: Reveal animations shall move an element from a displaced state to the state the markup already declares, never to a state only script knows.
- [x] **LAND-MOTION-003**: Where the reader has asked for reduced motion, reveals shall be skipped rather than shortened, and the page shall render at rest.
- [x] **LAND-MOTION-004**: A reveal shall fire once, and an element already revealed shall not re-animate when scrolled past a second time.
- [D] **LAND-MOTION-005**: The page shall not pin, scrub or hijack scrolling, and shall take no smooth-scroll dependency.

## Route

- [x] **LAND-ROUTE-001**: The landing page shall be the application root and shall render without a session.
- [x] **LAND-ROUTE-002**: The page shall not be exchanged for another destination on the basis of a reader's session; a signed-in reader who navigates to it shall see it.
- [x] **LAND-ROUTE-003**: The primary action shall send a signed-in reader to their courses and a stranger to sign-up.
- [x] **LAND-ROUTE-004**: The persistent learner HUD shall not render over the landing page, since it reports a progress a stranger does not have.
- [ ] **LAND-ROUTE-005**: The page shall declare social preview metadata, so a shared link renders as a card rather than a bare URL.
