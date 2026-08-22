# Interface — EARS Specs

Prefix: `UI`. Facets: `THEME` (the token layer and palette), `SYS` (shared class
constants), `TYPE` (typography), `A11Y` (contrast, focus, motion, landmarks),
`SHELL` (the persistent chrome — HUD, brand, navigation, responsive behaviour).

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

## The shell

- [x] **UI-SHELL-001**: A persistent header shall show identity, level, experience and streak on every authenticated view.
- [x] **UI-SHELL-002**: The header shall mark the current destination distinctly from the others.
- [x] **UI-SHELL-003**: Below the narrow breakpoint the header shall reflow to stack rather than scroll horizontally, and its ordering shall be declared rather than incidental.
- [x] **UI-SHELL-004**: The wordmark shall render as text, so it needs no asset and scales with type.
- [x] **UI-SHELL-005**: Ambient page decoration shall be painted in CSS rather than loaded as an image.
- [x] **UI-SHELL-006**: Ambient decoration shall be non-interactive and shall sit behind all content.
- [ ] **UI-SHELL-007**: Wide content shall scroll within its own container, so the page body never scrolls sideways.
