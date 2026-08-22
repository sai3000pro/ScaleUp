"use client";

/**
 * One skill's realm: the run of lessons inside it, and the test at the end.
 *
 * A skill is not one thing you either can or cannot do. Basic Strumming is a
 * slow four-bar pattern before it is a fast eight-bar one, and the realm is
 * where that middle ground lives — a chain climbing away from the skill, with
 * the test hanging above the last lesson.
 *
 * The chain is vertical and nothing else, deliberately. The overworld is where
 * structure is worth exploring; a run of three has exactly one shape, and
 * spreading it out would imply choices the learner does not have.
 *
 * ## What it does not decide
 *
 * Cleared, open and test-open all arrive from the server, computed in
 * `app/domain/realm.py` against the same pass boundary the rest of the system
 * uses. The realm draws them. A canvas keeping its own record of what a learner
 * had finished would disagree with the EXP they were awarded for the very same
 * take, and the learner would have two answers about one lesson.
 */

import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

import { CLOSE_FOV, cubicOut, DIVE_DISTANCE, TRANSIT_MS, WIDE_FOV } from "@/components/skill-tree/SkillGraph3D";
import type { Lesson, SkillRealm } from "@/lib/types";
import { BUTTON_PRIMARY, BUTTON_SECONDARY, FOCUS_RING } from "@/lib/ui";
import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";

interface Props {
  realm: SkillRealm;
  /** Leave the realm and go back to the tree. */
  onExit: () => void;
  /**
   * Render the thing that actually plays a lesson, over the realm.
   *
   * Passed in rather than built here: a take is recorded in exactly one place,
   * and a realm that grew its own recorder would be a second one. `close`
   * returns to the chain, for a caller that wants to leave on its own terms;
   * the learner always has the back button.
   */
  renderLesson: (lesson: Lesson, close: () => void) => ReactNode;
  /** Sit the skill's test — the drill that decides whether it is mastered. */
  onOpenTest: () => void;
}

/** From the `@theme` block in app/globals.css. Change one, change both. */
const PAGE = 0xfdfbfb;
const CLEARED = 0x2b6f9e;
const OPEN = 0x1f7a54;
const CLOSED = 0x96859d;
const LOCKED_EDGE = 0xcabfc2;
/** The accent. Reserved here for the one thing that is a reward. */
const TEST = 0xb8496f;

const LESSON_RADIUS = 9;
const LESSON_THICKNESS = 1.6;
const STEP_HEIGHT = 44;
/** Extra room under the test, so it reads as a destination rather than a fourth lesson. */
const TEST_GAP = 30;
const PICK_THRESHOLD = 20;

interface Marker {
  key: string;
  label: string;
  sub: string;
  x: number;
  y: number;
  visible: boolean;
  emphasis: boolean;
}

// @spec PROG-REALM-004
export function SkillRealm3D({ realm, onExit, renderLesson, onOpenTest }: Props) {
  /**
   * The lesson the learner clicked, before they have committed to playing it.
   *
   * A click on a coin opens a card describing what the lesson asks for; playing
   * starts on a second, deliberate press. Dropping straight into a recorder
   * would put a microphone prompt behind an orbit gesture.
   */
  const [pending, setPending] = useState<Lesson | null>(null);
  // Set by the back button, read by the render loop, which dives out before
  // handing back to the tree.
  const leavingRef = useRef(false);
  const [playing, setPlaying] = useState<Lesson | null>(null);
  const mountRef = useRef<HTMLDivElement | null>(null);
  const prefersReducedMotion = usePrefersReducedMotion();
  const [markers, setMarkers] = useState<Marker[]>([]);

  const onOpenTestRef = useRef(onOpenTest);
  const onExitRef = useRef(onExit);
  const realmRef = useRef(realm);
  onOpenTestRef.current = onOpenTest;
  onExitRef.current = onExit;
  realmRef.current = realm;

  // The realm is rebuilt when its progress changes, which is rare and cheap --
  // four objects — so this keys on the whole shape rather than on an id.
  const shape = useMemo(
    () =>
      [realm.node_id, realm.test_open, ...realm.lessons.map((l) => `${l.exercise_id}:${l.cleared}:${l.open}`)].join("|"),
    [realm],
  );

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    const current = realmRef.current;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(PAGE);
    // Opens at the field of view the dive ended on, and closes back down as it
    // pulls out -- so the first frame of the realm matches the last frame of
    // the tree in aim, distance AND lens.
    const camera = new THREE.PerspectiveCamera(prefersReducedMotion ? WIDE_FOV : CLOSE_FOV, 1, 0.1, 4000);

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch {
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.domElement.style.display = "block";
    mount.appendChild(renderer.domElement);

    // ── the chain ─────────────────────────────────────────────────────────
    const discGeometry = new THREE.CylinderGeometry(LESSON_RADIUS, LESSON_RADIUS, LESSON_THICKNESS, 48);
    const targets: { id: string; kind: "lesson" | "test"; mesh: THREE.Mesh; label: string; sub: string }[] = [];

    current.lessons.forEach((lesson, index) => {
      const y = index * STEP_HEIGHT;
      const colour = lesson.cleared ? CLEARED : lesson.open ? OPEN : CLOSED;
      const disc = new THREE.Mesh(
        discGeometry,
        new THREE.MeshBasicMaterial({ color: new THREE.Color(colour), transparent: true, opacity: lesson.open ? 1 : 0.5 }),
      );
      disc.position.set(0, y, 0);
      disc.rotation.x = Math.PI / 2;
      scene.add(disc);
      targets.push({
        id: lesson.exercise_id,
        kind: "lesson",
        mesh: disc,
        label: lesson.title,
        sub: lesson.cleared
          ? `Cleared · best ${Math.round((lesson.best_score ?? 0) * 100)}%`
          : lesson.open
            ? "Ready to play"
            : "Clear the one before it",
      });

      if (index > 0) {
        const below = current.lessons[index - 1];
        const line = new THREE.Line(
          new THREE.BufferGeometry().setFromPoints([
            new THREE.Vector3(0, y - STEP_HEIGHT, 0),
            new THREE.Vector3(0, y, 0),
          ]),
          new THREE.LineBasicMaterial({
            color: new THREE.Color(below.cleared ? OPEN : LOCKED_EDGE),
            transparent: true,
            opacity: below.cleared ? 0.9 : 0.6,
          }),
        );
        scene.add(line);
      }
    });

    // ── the test ──────────────────────────────────────────────────────────
    // A ring rather than a disc: it is a way through, not another thing to
    // stand on, and it should not read as a fourth lesson.
    const topY = (current.lessons.length - 1) * STEP_HEIGHT;
    const testY = topY + STEP_HEIGHT + TEST_GAP;
    const ringGeometry = new THREE.TorusGeometry(13, 2.2, 16, 64);
    const ring = new THREE.Mesh(
      ringGeometry,
      new THREE.MeshBasicMaterial({
        color: new THREE.Color(current.test_open ? TEST : CLOSED),
        transparent: true,
        opacity: current.test_open ? 1 : 0.45,
      }),
    );
    ring.position.set(0, testY, 0);
    scene.add(ring);
    targets.push({
      id: "test",
      kind: "test",
      mesh: ring,
      label: `${current.node_title} — test`,
      sub: current.test_open ? "Open. Pass it to master this skill." : "Clear every lesson to open",
    });

    const tether = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(0, topY, 0),
        new THREE.Vector3(0, testY - 13, 0),
      ]),
      new THREE.LineBasicMaterial({
        color: new THREE.Color(current.test_open ? TEST : LOCKED_EDGE),
        transparent: true,
        opacity: current.test_open ? 0.9 : 0.5,
      }),
    );
    scene.add(tether);

    // ── camera ────────────────────────────────────────────────────────────
    // Centred a little below the midpoint, and framed wider than the chain,
    // because the captions hang under each disc -- framing to the discs alone
    // crops the first lesson's caption off the bottom, which is the one the
    // learner is being sent to.
    const centreY = testY / 2 - LESSON_RADIUS * 2;
    const span = testY + LESSON_RADIUS * 8;
    let theta = Math.PI / 2;
    let phi = 1.45;
    const settled = Math.max(210, span * 1.45);
    // Arrive where the dive ended -- close in on the first lesson -- and pull
    // back from there. The tree and the realm are different scenes, so this
    // matched pose is the only thing that makes the swap read as travel rather
    // than as a cut. Reduced motion starts settled: it was a cut for them
    // anyway, because the dive was skipped.
    let radius = prefersReducedMotion ? settled : DIVE_DISTANCE;
    let arriving = prefersReducedMotion ? 1 : 0;
    let dragging = false;
    let dragged = false;
    let lastX = 0;
    let lastY = 0;
    const target = new THREE.Vector3(0, prefersReducedMotion ? centreY : 0, 0);

    function place() {
      camera.position.set(
        radius * Math.sin(phi) * Math.cos(theta),
        target.y + radius * Math.cos(phi),
        radius * Math.sin(phi) * Math.sin(theta),
      );
      camera.lookAt(target);
    }

    function resize() {
      const { clientWidth, clientHeight } = mount!;
      if (clientWidth === 0 || clientHeight === 0) return;
      renderer.setSize(clientWidth, clientHeight);
      camera.aspect = clientWidth / clientHeight;
      camera.updateProjectionMatrix();
    }

    const observer = new ResizeObserver(resize);
    observer.observe(mount);
    resize();
    place();

    // ── picking ───────────────────────────────────────────────────────────
    const projected = new THREE.Vector3();

    function pick(clientX: number, clientY: number) {
      const rect = renderer.domElement.getBoundingClientRect();
      const px = clientX - rect.left;
      const py = clientY - rect.top;
      let best: (typeof targets)[number] | null = null;
      let bestDistance = PICK_THRESHOLD;
      for (const entry of targets) {
        projected.copy(entry.mesh.position).project(camera);
        if (projected.z <= 1) {
          const sx = ((projected.x + 1) / 2) * rect.width;
          const sy = ((1 - projected.y) / 2) * rect.height;
          const away = Math.hypot(sx - px, sy - py);
          if (away < bestDistance) {
            bestDistance = away;
            best = entry;
          }
        }
      }
      return best;
    }

    function onPointerDown(event: PointerEvent) {
      dragging = true;
      dragged = false;
      lastX = event.clientX;
      lastY = event.clientY;
      renderer.domElement.setPointerCapture(event.pointerId);
    }

    function onPointerMove(event: PointerEvent) {
      if (!dragging) {
        renderer.domElement.style.cursor = pick(event.clientX, event.clientY) ? "pointer" : "grab";
        return;
      }
      const dx = event.clientX - lastX;
      const dy = event.clientY - lastY;
      if (Math.abs(dx) + Math.abs(dy) > 3) dragged = true;
      // Taking hold of the camera ends the arrival: nothing should move the
      // view while the learner is moving it themselves.
      arriving = 1;
      lastX = event.clientX;
      lastY = event.clientY;
      theta -= dx * 0.005;
      phi = Math.min(Math.PI - 0.25, Math.max(0.25, phi - dy * 0.005));
      place();
    }

    function onPointerUp(event: PointerEvent) {
      dragging = false;
      renderer.domElement.releasePointerCapture(event.pointerId);
      // A drag that ends over something is a drag, not a click.
      if (dragged) return;
      const hit = pick(event.clientX, event.clientY);
      if (!hit) return;
      const live = realmRef.current;
      if (hit.kind === "test") {
        // A closed test is not a thing to nudge. The learner is told why by the
        // caption under it, so a click that silently did nothing would be worse.
        if (live.test_open) onOpenTestRef.current();
      } else {
        const lesson = live.lessons.find((entry) => entry.exercise_id === hit.id);
        if (lesson?.open) setPending(lesson);
      }
    }

    function onWheel(event: WheelEvent) {
      event.preventDefault();
      radius = Math.min(span * 2.5, Math.max(90, radius + event.deltaY * 0.3));
      place();
    }

    const canvas = renderer.domElement;
    canvas.style.cursor = "grab";
    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerup", onPointerUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });

    // ── the loop ──────────────────────────────────────────────────────────
    let frame = 0;
    const started = performance.now();
    let sinceMarkers = 0;
    let leftAt = 0;

    function render() {
      const elapsed = (performance.now() - started) / 1000;

      // Pull back to frame the chain. Eased out, so it decelerates into place
      // and the learner's eye has somewhere to rest at the end of the movement.
      if (leavingRef.current) {
        // Back down to exactly where the tree's dive ended, so the tree can pick
        // the camera up from the same pose.
        if (leftAt === 0) leftAt = performance.now();
        const progress = Math.min(1, (performance.now() - leftAt) / TRANSIT_MS);
        const eased = 1 - cubicOut(progress);
        radius = DIVE_DISTANCE + (settled - DIVE_DISTANCE) * eased;
        target.y = centreY * eased;
        camera.fov = CLOSE_FOV + (WIDE_FOV - CLOSE_FOV) * eased;
        camera.updateProjectionMatrix();
        place();
        if (progress >= 1) {
          leavingRef.current = false;
          onExitRef.current();
        }
      } else if (arriving < 1) {
        arriving = Math.min(1, (performance.now() - started) / TRANSIT_MS);
        const eased = cubicOut(arriving);
        radius = DIVE_DISTANCE + (settled - DIVE_DISTANCE) * eased;
        target.y = centreY * eased;
        camera.fov = CLOSE_FOV + (WIDE_FOV - CLOSE_FOV) * eased;
        camera.updateProjectionMatrix();
        place();
      }
      // An open test is the only thing that moves. It is the reward, and the
      // realm has nothing else competing for attention.
      if (realmRef.current.test_open && !prefersReducedMotion) {
        ring.scale.setScalar(1 + Math.sin(elapsed * 2.4) * 0.05);
        ring.rotation.z = elapsed * 0.35;
      }

      renderer.render(scene, camera);

      sinceMarkers += 1;
      if (sinceMarkers >= 3) {
        sinceMarkers = 0;
        const rect = renderer.domElement.getBoundingClientRect();
        setMarkers(
          targets.map((entry) => {
            projected
              .copy(entry.mesh.position)
              .setY(entry.mesh.position.y - LESSON_RADIUS * 2.2)
              .project(camera);
            return {
              key: entry.id,
              label: entry.label,
              sub: entry.sub,
              x: ((projected.x + 1) / 2) * rect.width,
              y: ((1 - projected.y) / 2) * rect.height,
              visible: projected.z <= 1,
              emphasis: entry.kind === "test",
            };
          }),
        );
      }
      frame = requestAnimationFrame(render);
    }
    render();

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      canvas.removeEventListener("pointerdown", onPointerDown);
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerup", onPointerUp);
      canvas.removeEventListener("wheel", onWheel);
      discGeometry.dispose();
      ringGeometry.dispose();
      for (const entry of targets) (entry.mesh.material as THREE.Material).dispose();
      renderer.dispose();
      if (canvas.parentNode === mount) mount.removeChild(canvas);
    };
  }, [shape, prefersReducedMotion]);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent, action: () => void, enabled: boolean) => {
      if ((event.key === "Enter" || event.key === " ") && enabled) {
        event.preventDefault();
        action();
      }
    },
    [],
  );

  // Fills the frame the page draws rather than drawing a second one: the
  // container owns the chrome and the size, and this fills it.
  //
  // @spec UI-PAGE-006
  return (
    <div className="relative h-full w-full overflow-hidden">
      <div ref={mountRef} className="absolute inset-0" aria-hidden="true" />

      <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
        {markers.map((marker) => (
          <span
            key={marker.key}
            className="absolute -translate-x-1/2 whitespace-nowrap text-center"
            style={{ left: marker.x, top: marker.y, opacity: marker.visible ? 1 : 0 }}
          >
            <span
              className={`block font-display font-semibold tracking-tight ${
                marker.emphasis ? "text-[13px] text-slate-50" : "text-[12px] text-slate-100"
              }`}
            >
              {marker.label}
            </span>
            <span className="mt-0.5 block text-[10px] text-slate-400">{marker.sub}</span>
          </span>
        ))}
      </div>

      <div className="absolute left-3 top-3 max-w-xs rounded-lg border border-slate-700 bg-slate-900/95 p-3 shadow-sm">
        <p className="font-display text-sm font-semibold text-slate-100">{realm.node_title}</p>
        <p className="mt-1 text-[11px] leading-snug text-slate-400">
          {realm.test_open
            ? "Every lesson cleared. Pass the test to master this skill."
            : `Lesson ${realm.open_step ?? 1} of ${realm.lessons.length}. Clear them all to open the test.`}
        </p>
        <button
          type="button"
          onClick={() => {
            if (prefersReducedMotion) {
              onExit();
            } else {
              leavingRef.current = true;
            }
          }}
          className={`${BUTTON_SECONDARY} mt-3 w-full`}
        >
          ← Back to the tree
        </button>
      </div>

      <p className="pointer-events-none absolute bottom-3 left-3 text-[11px] text-slate-400">
        Drag to orbit · click a lesson to play it
      </p>

      {/* What the lesson asks for, before committing to it. A click on a coin is
          one gesture away from an orbit, so playing takes a second press. */}
      {pending && !playing && (
        <div className="absolute inset-0 flex items-center justify-center bg-slate-950/70 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="lesson-confirm-title"
            className="w-full max-w-sm rounded-xl border border-slate-700 bg-slate-900 p-5 shadow-lg"
          >
            <p className="text-[10px] font-semibold uppercase tracking-wider text-sky-400">
              Lesson {pending.step} of {realm.lessons.length}
            </p>
            <h3 id="lesson-confirm-title" className="mt-1 font-display text-base font-semibold text-slate-50">
              {pending.title}
            </h3>
            <p className="mt-2 text-xs leading-relaxed text-slate-400">{pending.instructions}</p>
            {pending.cleared && (
              <p className="mt-2 text-[11px] text-slate-400">
                Already cleared at {Math.round((pending.best_score ?? 0) * 100)}%. Playing it again can only help.
              </p>
            )}
            <div className="mt-5 flex gap-2">
              <button type="button" onClick={() => setPending(null)} className={`${BUTTON_SECONDARY} flex-1`}>
                Cancel
              </button>
              <button type="button" onClick={() => setPlaying(pending)} className={`${BUTTON_PRIMARY} flex-1`}>
                Play this lesson
              </button>
            </div>
          </div>
        </div>
      )}

      {/* The lesson itself, in the realm rather than in a panel beside the tree. */}
      {playing && (
        <div className="absolute inset-0 overflow-y-auto bg-slate-950/85 p-4">
          <div className="mx-auto w-full max-w-md">
            <div className="mb-2 flex items-center justify-between gap-3">
              <p className="font-display text-sm font-semibold text-slate-100">{playing.title}</p>
              <button
                type="button"
                onClick={() => {
                  setPlaying(null);
                  setPending(null);
                }}
                className={BUTTON_SECONDARY}
              >
                ← Back to the realm
              </button>
            </div>
            {renderLesson(playing, () => {
              setPlaying(null);
              setPending(null);
            })}
          </div>
        </div>
      )}

      {/* A canvas is one focusable element, so the run is also a list. */}
      <ul className="sr-only">
        {realm.lessons.map((lesson) => (
          <li
            key={lesson.exercise_id}
            tabIndex={0}
            aria-disabled={!lesson.open}
            aria-label={`${lesson.title}. ${lesson.cleared ? "Cleared." : lesson.open ? "Ready to play." : "Locked until the previous lesson is cleared."}`}
            className={FOCUS_RING}
            onKeyDown={(event) => onKeyDown(event, () => setPending(lesson), lesson.open)}
          >
            {lesson.title}
          </li>
        ))}
        <li
          tabIndex={0}
          aria-disabled={!realm.test_open}
          aria-label={`${realm.node_title} test. ${realm.test_open ? "Open." : "Clear every lesson to open it."}`}
          className={FOCUS_RING}
          onKeyDown={(event) => onKeyDown(event, onOpenTest, realm.test_open)}
        >
          Test
        </li>
      </ul>
    </div>
  );
}
