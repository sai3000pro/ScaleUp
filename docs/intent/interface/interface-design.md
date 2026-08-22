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

## The skill graph

The tree is drawn in three dimensions on a ground of its own — near-black space
(`#0b0e14`), the one place the light page deliberately goes dark. The graph is a
window into the curriculum rather than page chrome, and a dark window is what
makes a lit orb glow: gold, slate, blue, purple and orange against space read the
way the reference this design follows intended, while the page around the card
stays warm and light. The canvas is where the learner stands in the curriculum;
chrome stays on the page.

**The palette is the reference scheme, mapped onto the app's states.** Gold for
what is ready, slate for what is locked, blue for what is in hand, purple for
what is done — and the one state the reference does not have, fading, takes
orange, the reference's own urgency hue from its branch palette. The mapping is
declared once and one-to-one:

| State | Graph colour | Meaning |
|---|---|---|
| Locked | `#334155` slate | ahead of you, recedes |
| Ready | `#facc15` gold | the way on |
| Learning | `#38bdf8` blue | in hand |
| Fading | `#f97316` orange | rescue now |
| Mastered | `#a78bfa` purple | done |
| Section | `#475569` slate-blue, hollow | scaffolding |

**The palette exists twice, and that is structural.** Every actionable graph
colour clears 3:1 against the graph's dark ground, exactly as the app's
node-state colours clear 3:1 against the light page — and no single colour can
clear 3:1 against both grounds (the reference's own gold against the warm page
measures about 1.6:1). So the graph declares its own palette, mirrored as
`--color-graph-*` tokens, mapped from the same five states by one function:
meaning never forks even though colour does. Locked and section sit below the
3:1 line by design — they are the "what is still ahead" part of the tree, and
their state is carried by the projected title, the hover card and the keyboard
list rather than by colour alone (`UI-GRAPH3D-017`).

**Lighting, not shading.** Discs are lit like the reference — a key light and an
ambient, with metalness and roughness — so they read as objects in space rather
than stickers, and the state hue is kept bright enough that five states stay five
colours under the rig (`UI-GRAPH3D-019`).

**Edges carry the route, in the same scheme.** Into a ready skill: gold, the way
on. Into what is in hand or done: gold, dimmed. Into a fading skill: orange.
Into the locked future: slate. One palette for nodes and routes, so a lit path
and its destination agree.

**The realm is the same world.** The chain inside a skill is drawn on the same
ground with the same palette — slate for the lessons still ahead, blue for the
one in hand, purple for the cleared, gold for the test at the end — so diving
into a skill and coming back out reads as one journey through one world rather
than two canvases that happen to sit near each other. It is walked the same
way the tree is: the camera stands at the current lesson — half a lesson
radius back, lens at eye height (one thickness plus two units above the
plane), up along +Z so the chain's plane is the ground the learner is standing
in — and looks along the run toward the next lesson, or the test at its end.
Clicking an open lesson walks the camera to it, right-drag looks around, and a
closed lesson remains worth viewing because its progress card explains the
blocker; clicking it does not move the camera.

Entering the realm is a turn-around, not a slide. The tree's dive ends looking
at the skill from one side of it; the realm's walk-in swings the camera one
hundred and eighty degrees around the skill — the route the tree drew behind
the learner becomes the chain ahead — while closing from the dive distance to
the standing point. The skill stays in frame for the whole turn, the lens
widens on the way, and the flight lands in the standing pose described above.
A learner who has asked for less motion is handed the standing pose directly.

A lesson's state is carried by its card, not painted under its disc. The
lesson the learner stands beside — and the one ahead — carries a floating card
naming it and saying what it asks for; the same card carries the state (ready,
cleared, or locked, with a best score where one exists) and the test card
carries the test's state. Nothing floats beneath the discs: the chain is read
by walking it, one standing point at a time.

## Traversal: walking the tree in place

The tree is walked the way the reference this design follows walks its maps:
not by zooming the whole graph, but by standing at a skill and looking at its
neighbours. Double-clicking a skill flies the camera down to stand beside it —
field of view opens, the orbit controls let go — and the skills it touches
appear as floating cards in the world: a parent card above it, a child card for
each thing it unlocks. Each card carries the neighbour's name and state, and
clicking one is a camera journey to that skill, which becomes the new centre and
spawns its own cards. The learner walks the tree node to node instead of
zooming a diagram.

A card is the neighbour's route, and the route is gated by the learner's
current progress. A locked neighbour's card remains visible — its name is
dimmed, its state line says what stands in the way, and its progress remains
readable — but clicking it does not move the camera. Instead a notice says,
"You haven't unlocked [skill] yet. Please complete [current skill] first."
The learner may inspect the locked future without walking into it. The skill
the learner is standing on is the current completed point in the route, and the
cards ahead show the next skill's level, mastery and current proficiency. A
structural heading is visible but is never a traversable skill.

The same rule applies inside a realm. A closed lesson remains on the chain and
its card shows its current progress, but single-click and double-click both
refuse to walk there and explain that the current lesson must be completed
first. Traversal is navigation; only the next unlocked point can become the
standing point.

The camera stands AT the skill, the way the reference's own camera does: half
a node radius back from its centre, its lens at eye height — one disc thickness
plus two units above the plane — and its up vector along +Z, so the tree's
plane is the ground the learner is standing in and the route the skill opens
(its children) runs away up the screen at eye level. The skill itself is at the
learner's feet, filling the bottom of the frame; the path ahead is the view.
Right-drag looks around from the standing point, exactly as the reference's POV
does: yaw about the world's up, pitch about the camera's right.

From a skill's own card the learner enters its world — the realm dive this
design already had — and one deliberate action (a back button, or Escape)
returns to the overview. Realm entry first fades the graph to black, swaps the
world beneath that black frame, and then fades the realm back in; reduced-motion
viewers receive the swap without the decorative fade. Every camera journey is
over a fixed duration with the pose and lens on each side matching, and a
viewer who has asked for less motion is handed the destination instead of the
travel.

**The click and the double-click say different things.** In the overview, one
click on a skill opens a door — a modal naming the skill, describing it, and
offering to enter its world — and two clicks ask to stand beside it. The two
are disambiguated by a short delay, so a double-click never flashes the modal
it was never meant to summon. Inside a realm the same two gestures mean the
same two things: one click on a lesson opens its card, two clicks walk the
camera to stand at it.

**A realm is walked the same way the tree is.** Standing at a lesson, the
lesson the line connects it to — the one ahead, and the one behind — carries a
floating card naming it, saying what it asks for, and carrying its state, so a
cleared lesson's best score, an open lesson's readiness, and a locked lesson's
blocker all live in the hovering text rather than under the discs. Clicking a
card is a camera journey to that lesson, which becomes the new standing point
and spawns its own cards; the test hangs above the last lesson as its own
card. The realm is not a ladder to be climbed by dragging — it is a chain to
be walked, neighbour to neighbour, the same traversal the tree uses.

## The mascot

Quartz is a quarter note with a microphone, and the segment holds it for the same reason it
holds the palette: it appears on every surface, so it is something every surface *draws with*
rather than something any one surface owns. It carries no state of its own and reports no
progress — a mark that reacted to a learner's EXP would be progression's, drawn here.

**The character is a registered sprite library, not an image.** `design/sprite_sheet.jpg` is
one 2048x2048 sheet of twenty labelled poses on flat grey, and
`frontend/scripts/build-sprites.ts` cuts it into `frontend/public/sprites/quartz/` plus a
generated manifest at `frontend/lib/quartzSprites.ts`. The script is not part of the framework
build graph: nothing under `app/` or `lib/` imports `scripts/`, every output is committed, and
the imaging dependency stays a devDependency. A contributor who never touches the artwork
never runs it.

Three properties of the cut are what make the library usable rather than merely present, and
each is a decision the pipeline had to make rather than a detail of it.

**Frames are found by projecting ink onto each axis, not by dividing the sheet into
twentieths.** The grid looks regular and is not — poses differ in width, and the two singing
poses throw quaver glyphs clear of the body with a gap between. Projection finds the true
bands; merging column runs closer than any real inter-frame gap re-attaches those quavers.
Both counts are gated, so an art revision that breaks the assumption fails at build rather
than shipping a sheared drawing. The captions lettered under each pose are dropped by height:
the drawing bands measure 305-318px and the caption bands 49-55, a factor of six.

**The ground is flood-filled inward from the cell border rather than thresholded in place.**
The gloves and shoes are painted a near-white about twenty levels off the grey ground — close
enough that any threshold loose enough to absorb the sheet's JPEG noise also punches holes
through both. Filling inward keeps an enclosed region *because* it is enclosed, whatever
colour it is, and absorbs the ground's corner-to-corner drift in the same pass. The
character's colour is then grown a few pixels past the cut before the alpha is feathered,
because a feathered edge over a colourless pixel blends the silhouette toward black and rims
the character.

**Every frame is registered onto one ground line and one horizontal anchor**, so swapping one
for another moves nothing the artist did not draw as moving. The anchor is the centroid of the
frame's own purple, which is what makes the run cycle work: the two gait frames sit within a
pixel of each other by centroid where their bounding-box centres differ by nine. The ground
line is measured per row of drawings as the lowest ink in it, so a pose drawn in the air keeps
its lift — it survives into the cell as transparent padding, and nothing offsets it at
runtime.

**No frame is ever mirrored.** The sheet draws its own left- and right-facing variants, so a
flop would be a worse copy of a drawing that already exists, and the microphone and the
quavers read as reversed when flipped.

The manifest is the contract: draw a cell at its declared aspect, put `footY` of its height on
the ground, size it so `bodyH` of its height is the character. Every frame agrees about all
three. `QUARTZ_CLIPS` names sequences, and its `fps`, `loop` and `rest` are *declared* rather
than measured — frame timing is not in the artwork, and pretending otherwise would give a
generated file the authority of a measurement.

**The mascot is interactive, and its interactivity is decoration.** It reacts to the pointer
and to being clicked; nothing it does changes anything. That is deliberate: a character that
gated a real action would make charm load-bearing, and a reader with reduced motion would lose
function rather than delight. Under `prefers-reduced-motion` the mascot holds a pose — which
pose it holds is information and stays; the motion between poses is animation and goes.

The sheet's resolution is the ceiling on where it can be used. The character is drawn about
265px tall, so it ships at 240 and goes soft much above that. That is a property of the
artwork, not of the pipeline, and it is why the wordmark beside it stays text (`UI-SHELL-004`)
rather than becoming part of the image.

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
| Graph ground | Dark space, one declared ground | Keep the light canvas | A lit orb needs a dark ground to glow, and the reference this design follows is a space scene; the page around the card stays light. |
| Graph palette | The reference scheme, declared once, mapped from node states | Reuse the app's node-state palette on the graph | The app palette is tuned against the light page and cannot clear 3:1 on dark; the reference gold/slate/blue/purple (plus orange for fading) is the look the learner asked for. |
| Orb lighting | Lit discs (key + ambient, metalness and roughness) | Unlit flat discs | The reference look is lit and dimensional; the state hues are kept identifiable under the rig. |
| Fading colour | Orange, the reference's own urgency hue | A gold or slate variant | The reference has no decay state; orange keeps "rescue now" unmistakable and comes from the reference's own branch palette. |
| Traversal | POV walking: fly to a skill, floating neighbour cards, enter the realm from there | Zoom the whole graph; keep double-click diving straight into the realm | The reference walks maps node to node, and this design follows it; the dive still exists, it is just reached from the skill rather than from the canvas. |
| Locked neighbours in POV | Visible, progress shown, traversal blocked with a completion notice | Visible and traversable behind a locked-traversal toggle | The learner can inspect the future without skipping the prerequisite route; a toggle is unnecessary when the curriculum already owns the gate. |
| Realm entry transition | Fade fully to black before swapping the world, then fade the realm in | Swap immediately; fade only the canvas | The black hold hides the component handoff and makes entering the lesson world read as one deliberate transition; reduced motion skips it. |

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
