# Interface — EARS Specs

Prefix: `UI`. Facets: `THEME` (the token layer and palette), `SYS` (shared class
constants), `TYPE` (typography), `A11Y` (contrast, focus, motion, landmarks),
`PAGE` (how a working surface is composed — what is on screen at once, and what is one
control away), `SHELL` (the persistent chrome — HUD, brand, navigation, responsive behaviour), `SPRITE`
(the mascot's art pipeline and the registration contract it emits), `MASCOT` (the character's
presence and behaviour across the application).

Status: `[x]` observed working in current code · `[ ]` specified but broken or partial ·
`[D]` deliberate non-want.

**This segment owns presentation, not behaviour.** Every surface that renders a score, a
node, a quest or a take belongs to the segment that owns that behaviour; what belongs here
is the visual language those surfaces are drawn in — colour, type, spacing, focus, contrast
and the shell they sit inside. A component appears here only when its content is the design
system itself.

---

## The token layer

- [x] **UI-THEME-001**: The interface shall define every colour it uses as a token in one theme layer, and components shall reference tokens rather than literal colour values.
- [x] **UI-THEME-002**: Where a colour must be passed as a value rather than a class — a canvas stroke, an SVG fill — its literal shall be declared in one module and that module shall name the token it mirrors.
- [x] **UI-THEME-003**: The neutral ramp shall carry a bias toward the accent hue rather than being a pure grey.
- [x] **UI-THEME-004**: The ramp shall be ordered by ink strength, so a component written against any point on it renders coherently without being rewritten.
- [x] **UI-THEME-005**: The interface shall declare its colour scheme to the browser, so form controls and scrollbars match the page.
- [x] **UI-THEME-006**: Page background and body ink shall be painted explicitly rather than inherited from the user agent.
- [x] **UI-THEME-007**: No rule shall retain a literal colour from a superseded palette; a colour that is not a token shall be traceable to one.
- [D] **UI-THEME-008**: The interface shall not offer a runtime theme switch.

## The shared class system

- [x] **UI-SYS-001**: Recurring interactive surfaces — primary action, secondary action, text input, card, navigation link, focus ring — shall each be defined once and referenced by name.
- [x] **UI-SYS-002**: Every shared class constant shall be a literal string, never assembled from a variable, so the compiler's source scan can see it.
- [x] **UI-SYS-003**: A shared class constant shall carry the reason it exists, so a later reader can tell a considered value from an arbitrary one.
- [ ] **UI-SYS-004**: Where a shared constant exists for a purpose, components shall use it rather than restating its classes inline.
- [ ] **UI-SYS-005**: A shared constant that no component uses shall be adopted or deleted.

## Typography

- [x] **UI-TYPE-001**: The interface shall pair a display face with a body face, each bound to a token and loaded with a system fallback stack.
- [x] **UI-TYPE-002**: Display headings shall be set lighter and more tightly tracked than body copy.
- [x] **UI-TYPE-003**: Uppercase micro-labels shall carry positive letter-spacing.
- [ ] **UI-TYPE-004**: Type sizes shall be drawn from a declared scale rather than chosen per component.

## Accessibility

- [x] **UI-A11Y-001**: Every interactive control shall have a visible keyboard focus indicator.
- [x] **UI-A11Y-002**: The focus indicator shall appear for keyboard interaction and not for pointer interaction.
- [x] **UI-A11Y-003**: The page shall offer a skip link to the main content as the first focusable element.
- [x] **UI-A11Y-004**: The document shall declare its language.
- [x] **UI-A11Y-005**: Where a viewer has asked for reduced motion, decorative animation and transition shall be suppressed.
- [x] **UI-A11Y-006**: A state shall never be signalled by colour alone; a glyph, a label or a shape shall carry it too.
- [x] **UI-A11Y-007**: Body and secondary text shall meet a contrast ratio of at least 4.5:1 against every surface it is placed on, including raised cards, not only against the page.
- [x] **UI-A11Y-008**: A control's label shall meet 4.5:1 against that control's own fill.
- [x] **UI-A11Y-009**: A colour carrying state on a non-text element shall meet at least 3:1 against the surface behind it.

## The skill graph

- [x] **UI-GRAPH3D-001**: The skill graph shall be rendered in three dimensions, and shall present the same selection, lesson-opening and search behaviour the surrounding page already depends on.
- [x] **UI-GRAPH3D-002**: A skill shall be drawn above every skill that depends on it, at a height determined by its prerequisite depth rather than by the arrangement.
- [x] **UI-GRAPH3D-003**: No two skills shall occupy the same point, and a skill alone at its depth shall sit on the axis rather than off to one side.
- [x] **UI-GRAPH3D-004**: The initial camera shall frame the whole tree, however deep or wide it is.
- [x] **UI-GRAPH3D-005**: A focus request raised elsewhere in the application shall move the camera to that skill.
- [x] **UI-GRAPH3D-006**: Orbiting the graph shall not select a skill, and releasing a drag over a skill shall not be read as a click on it.
- [x] **UI-GRAPH3D-007**: Every skill shall be reachable and openable by keyboard, without a pointer.
- [x] **UI-GRAPH3D-008**: The graph shall derive no progression of its own; locked, ready, fading and mastered shall come from the snapshot.
- [ ] **UI-GRAPH3D-009**: Where the browser cannot provide a WebGL context, the learner shall be offered the skill outline in place of the graph rather than an empty panel.
- [ ] **UI-GRAPH3D-010**: The graph shall remain usable at the node counts a compiled textbook produces, not only at the size a curriculum produces.
- [x] **UI-GRAPH3D-011**: A tree small enough to read shall be laid out on one plane, and only a tier too wide to read on one row shall use depth to wrap.
- [x] **UI-GRAPH3D-012**: A skill shall be drawn centred over the prerequisites that converge on it.
- [x] **UI-GRAPH3D-013**: The graph shall be drawn on the application's own ground, and each skill shall carry its state's declared colour unaltered by lighting.
- [x] **UI-GRAPH3D-014**: Every skill shall be titled on the canvas without the learner having to point at it.
- [x] **UI-GRAPH3D-015**: Entering and leaving a skill's realm shall be a camera journey rather than a cut, with the pose and field of view on each side of the change matching.
- [x] **UI-GRAPH3D-016**: Where the viewer has asked for less motion, the journey shall be skipped rather than shortened.

## The mascot's sprite library

- [x] **UI-SPRITE-001**: The mascot's frames shall be produced from the art sheet by a committed script, and both the frames and the manifest it emits shall be committed rather than generated at build time.
- [x] **UI-SPRITE-002**: The sprite script shall sit outside the framework build graph, and its imaging dependency shall not be required to build or run the application.
- [x] **UI-SPRITE-003**: Frames shall be located by projecting ink onto each axis rather than by dividing the sheet into equal cells.
- [x] **UI-SPRITE-004**: Parts of one pose separated by a gap shall be re-attached to that pose rather than cut as separate frames.
- [x] **UI-SPRITE-005**: The script shall fail rather than emit output where the sheet yields a different number of rows or frames per row than declared.
- [x] **UI-SPRITE-006**: Lettering on the sheet shall be excluded from every frame, and no frame shall contain any part of a caption.
- [x] **UI-SPRITE-007**: The background shall be removed by filling inward from each cell's border, so a region enclosed by the artwork is kept whatever its colour.
- [x] **UI-SPRITE-008**: The character's colour shall be grown past the cut before the alpha is feathered, so no frame ships with a dark rim.
- [x] **UI-SPRITE-009**: Every frame shall be registered onto one ground line and one horizontal anchor, so substituting one frame for another moves nothing.
- [x] **UI-SPRITE-010**: A pose the artist drew off the ground shall keep its lift in the shipped frame, without the consumer offsetting it.
- [x] **UI-SPRITE-011**: The scale shall be taken once for the sheet rather than per frame, so a pose drawn deliberately squashed is not stretched back out.
- [x] **UI-SPRITE-012**: No frame shall be mirrored; each facing the sheet draws shall ship as its own frame, and the manifest shall record which way each looks.
- [x] **UI-SPRITE-013**: The manifest shall declare the cell geometry every frame shares — aspect, ground line and character height — as the contract for drawing one.
- [x] **UI-SPRITE-014**: Frame timing in the manifest shall be marked as declared rather than measured, since it is not present in the artwork.
- [x] **UI-SPRITE-015**: The script shall verify that each encoded frame carries transparency and the intended dimensions before writing it.
- [x] **UI-SPRITE-016**: A clip naming a frame the sheet does not contain shall fail the build.

## The mascot

- [x] **UI-MASCOT-001**: The mascot shall appear beside the wordmark on every view that renders the persistent shell.
- [x] **UI-MASCOT-002**: The mascot shall face the wordmark it sits beside.
- [x] **UI-MASCOT-003**: The mascot shall respond to the pointer and to being activated, and nothing it does shall change application state.
- [x] **UI-MASCOT-004**: The mascot shall be reachable and activatable by keyboard wherever it is interactive.
- [x] **UI-MASCOT-005**: The mascot shall carry no accessible name where it sits beside a wordmark that already names the product, so a screen reader hears the destination once.
- [x] **UI-MASCOT-006**: Where the reader has asked for reduced motion, the mascot shall hold a pose rather than animate between poses.
- [x] **UI-MASCOT-007**: The pose the mascot holds shall be chosen for what it conveys and shall not depend on whether motion is allowed.
- [x] **UI-MASCOT-008**: The first frame the mascot renders shall be the frame the server rendered, so no substitution occurs at hydration.
- [x] **UI-MASCOT-009**: A clip that does not loop shall settle on a resting pose rather than holding its final frame indefinitely.
- [x] **UI-MASCOT-010**: The mascot shall preload the frames a reaction needs before that reaction can be triggered, so a first interaction does not show a gap.
- [x] **UI-MASCOT-011**: The mascot shall derive no learner state, and shall report no progress, score or streak.
- [D] **UI-MASCOT-012**: The mascot shall not speak, and shall not present copy in a bubble attached to itself.

## Page composition

- [x] **UI-PAGE-001**: A working surface built around one primary object shall occupy exactly one viewport on a wide screen, and no secondary column shall be able to extend the document.
- [x] **UI-PAGE-002**: The height of the persistent chrome shall be declared once as a token and enforced on the chrome itself, so a surface that fills the remaining viewport subtracts a known value rather than a guessed one.
- [x] **UI-PAGE-003**: Panels that are alternative views of one activity shall be presented as alternatives rather than stacked, and only the selected one shall be mounted where a hidden one would hold a camera, a microphone or a socket open.
- [x] **UI-PAGE-004**: A surface shall show only the panels that answer a question its reader has while using it; panels used at setup or occasionally shall be one control away rather than below.
- [x] **UI-PAGE-005**: A panel moved out of a surface shall remain reachable from it, and the control that reveals it shall name what it holds.
- [x] **UI-PAGE-006**: A container and the component it frames shall not both declare the frame; the container shall own chrome and size, and the component shall fill it.
- [ ] **UI-PAGE-007**: No two panels visible at once shall report the same figure.

## The shell

- [x] **UI-SHELL-001**: A persistent header shall show identity, level, experience and streak on every authenticated view.
- [x] **UI-SHELL-002**: The header shall mark the current destination distinctly from the others.
- [x] **UI-SHELL-003**: Below the narrow breakpoint the header shall reflow to stack rather than scroll horizontally, and its ordering shall be declared rather than incidental.
- [x] **UI-SHELL-004**: The wordmark shall render as text, so it needs no asset and scales with type.
- [x] **UI-SHELL-005**: Ambient page decoration shall be painted in CSS rather than loaded as an image.
- [x] **UI-SHELL-006**: Ambient decoration shall be non-interactive and shall sit behind all content.
- [ ] **UI-SHELL-007**: Wide content shall scroll within its own container, so the page body never scrolls sideways.
