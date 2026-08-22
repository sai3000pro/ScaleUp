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

import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import * as THREE from "three";

import {
  CLOSE_FOV,
  cubicOut,
  DIVE_DISTANCE,
  TRANSIT_MS,
} from "@/components/skill-tree/SkillGraph3D";
import { GRAPH_ACCENTS, GRAPH_GROUND } from "@/lib/graphTheme";
import { canTraverseLesson } from "@/lib/lesson";
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

// The realm is the same world as the tree, drawn on the same warm light ground
// with the same site palette (lib/graphTheme.ts): warm neutral for lessons still
// ahead, violet for the one in hand, blue for cleared lessons, and green for the
// test at the end. A single palette makes the dive in and out read as one journey.
const LESSON_CLEARED = GRAPH_ACCENTS.mastered;
const LESSON_OPEN = GRAPH_ACCENTS.learning;
const LESSON_CLOSED = GRAPH_ACCENTS.locked;
const TEST_OPEN = GRAPH_ACCENTS.available;
const EDGE_LIT = GRAPH_ACCENTS.available;
const EDGE_LOCKED = GRAPH_ACCENTS.locked;

const LESSON_RADIUS = 9;
const LESSON_THICKNESS = 1.6;
const STEP_HEIGHT = 44;
/** Extra room under the test, so it reads as a destination rather than a fourth lesson. */
const TEST_GAP = 30;
const PICK_THRESHOLD = 20;

// The realm is walked the same way the tree is: the camera stands AT the
// current lesson -- half a lesson radius back, lens at eye height (one
// thickness plus two units above the plane), up along +Z so the chain's plane
// is the ground the learner is standing in -- and looks along the run toward
// the next lesson, or the test at its end. Clicking a lesson walks the camera
// to it; right-drag looks around. Same recipe as the tree's traversal, so the
// two sides of the dive read as one world.
const POV_STAND_BACK = LESSON_RADIUS * 0.5;
const POV_LOOK_AHEAD = 40;
const POV_EYE_OFFSET = LESSON_THICKNESS / 2 + 2;
const POV_FOV = 75;
const POV_UP = new THREE.Vector3(0, 0, 1);
const OVERVIEW_UP = new THREE.Vector3(0, 1, 0);

// Entering the realm is a turn-around, not a slide. The tree's dive ends
// looking at the skill from one side of it (its direction in the plane is +Y
// at the dive pose); the realm's walk-in swings the camera one hundred and
// eighty degrees about the skill (+Z is the plane's up) to stand on the far
// side looking up the chain, while closing from the dive distance to the
// standing point. The skill stays in frame for the whole turn because the
// camera aims at it until the swing is done.
const ENTRY_START_ANGLE = Math.PI / 2;
const ENTRY_END_ANGLE = -Math.PI / 2;
/** The fraction of the turn after which the aim leaves the skill for the chain. */
const ENTRY_LOOK_BLEND_AT = 0.6;
/** The fraction of the turn after which the up vector rolls into the plane. */
const ENTRY_UP_BLEND_AT = 0.3;

/**
 * One floating neighbour card in the realm, the way the tree's POV walks its
 * map: the lesson the line connects to the one being stood at -- the one
 * ahead and the one behind -- carries a card naming it and saying what it
 * asks for, and clicking it is a camera journey to that lesson.
 */
interface RealmCard {
  id: string;
  title: string;
  desc: string;
  /** The lesson's state, carried by the card: cleared with its best score, ready, or locked. */
  status: string;
  progress: string;
  badge: "previous" | "next" | "test";
  accent: string;
  x: number;
  y: number;
  visible: boolean;
}

// The cards float beside the neighbour's disc, like the tree's POV cards.
const REALM_CARD_WIDTH = 200;

interface RealmTraversalNotice {
  targetTitle: string;
  currentTitle: string | null;
  message: string;
}

// @spec PROG-REALM-004, UI-GRAPH3D-013, UI-GRAPH3D-017, UI-GRAPH3D-019, UI-GRAPH3D-023, UI-GRAPH3D-025, UI-GRAPH3D-026, UI-GRAPH3D-027, UI-GRAPH3D-028, UI-GRAPH3D-029, UI-GRAPH3D-030, UI-GRAPH3D-031
export function SkillRealm3D({
  realm,
  onExit,
  renderLesson,
  onOpenTest,
}: Props) {
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
  const [standingLessonIndex, setStandingLessonIndex] = useState(0);
  const standingLessonIndexRef = useRef(0);
  const mountRef = useRef<HTMLDivElement | null>(null);
  const prefersReducedMotion = usePrefersReducedMotion();
  const [realmCards, setRealmCards] = useState<RealmCard[]>([]);
  const [traversalNotice, setTraversalNotice] =
    useState<RealmTraversalNotice | null>(null);
  // The imperative handles the cards call into the canvas: a card click walks
  // to that lesson, and the test card opens the test.
  const realmActionsRef = useRef<{
    openLesson: (id: string) => void;
    walkTo: (id: string) => void;
    openTest: () => void;
  } | null>(null);

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
      [
        realm.node_id,
        realm.test_open,
        ...realm.lessons.map((l) => `${l.exercise_id}:${l.cleared}:${l.open}`),
      ].join("|"),
    [realm],
  );

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    const current = realmRef.current;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(GRAPH_GROUND);
    // The same rig as the tree, so the world does not visibly change between
    // the two sides of the dive.
    const keyLight = new THREE.DirectionalLight(0xffffff, 2);
    keyLight.position.set(20, 40, 60);
    scene.add(keyLight);
    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    // Opens at the field of view the dive ended on, and closes back down as it
    // pulls out -- so the first frame of the realm matches the last frame of
    // the tree in aim, distance AND lens.
    const camera = new THREE.PerspectiveCamera(
      prefersReducedMotion ? POV_FOV : CLOSE_FOV,
      1,
      0.1,
      4000,
    );

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
    const discGeometry = new THREE.CylinderGeometry(
      LESSON_RADIUS,
      LESSON_RADIUS,
      LESSON_THICKNESS,
      48,
    );
    const targets: { id: string; kind: "lesson" | "test"; mesh: THREE.Mesh }[] =
      [];

    current.lessons.forEach((lesson, index) => {
      const y = index * STEP_HEIGHT;
      const colour = lesson.cleared
        ? LESSON_CLEARED
        : lesson.open
          ? LESSON_OPEN
          : LESSON_CLOSED;
      const disc = new THREE.Mesh(
        discGeometry,
        new THREE.MeshStandardMaterial({
          color: new THREE.Color(colour),
          metalness: 0.3,
          roughness: 0.3,
          emissive: new THREE.Color(colour),
          emissiveIntensity: 0.22,
          transparent: true,
          opacity: lesson.open ? 1 : 0.5,
        }),
      );
      disc.position.set(0, y, 0);
      disc.rotation.x = Math.PI / 2;
      scene.add(disc);
      targets.push({
        id: lesson.exercise_id,
        kind: "lesson",
        mesh: disc,
      });

      if (index > 0) {
        const below = current.lessons[index - 1];
        const line = new THREE.Line(
          new THREE.BufferGeometry().setFromPoints([
            new THREE.Vector3(0, y - STEP_HEIGHT, 0),
            new THREE.Vector3(0, y, 0),
          ]),
          new THREE.LineBasicMaterial({
            color: new THREE.Color(below.cleared ? EDGE_LIT : EDGE_LOCKED),
            transparent: true,
            opacity: below.cleared ? 0.7 : 0.5,
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
        color: new THREE.Color(current.test_open ? TEST_OPEN : LESSON_CLOSED),
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
    });

    const tether = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(0, topY, 0),
        new THREE.Vector3(0, testY - 13, 0),
      ]),
      new THREE.LineBasicMaterial({
        color: new THREE.Color(current.test_open ? EDGE_LIT : EDGE_LOCKED),
        transparent: true,
        opacity: current.test_open ? 0.9 : 0.5,
      }),
    );
    scene.add(tether);

    // ── camera ────────────────────────────────────────────────────────────
    // The pose the dive ended on, so the realm opens there and hands the tree
    // the camera back from the same place when the learner leaves.
    const divePos = new THREE.Vector3(
      DIVE_DISTANCE * Math.sin(1.05) * Math.cos(Math.PI / 2),
      DIVE_DISTANCE * Math.cos(1.05),
      DIVE_DISTANCE * Math.sin(1.05) * Math.sin(Math.PI / 2),
    );

    // Which lesson the camera stands at, and the flight that walks it there.
    const initialLessonIndex = Math.min(
      standingLessonIndexRef.current,
      Math.max(0, current.lessons.length - 1),
    );
    let povIndex = initialLessonIndex;
    const povLook = new THREE.Vector3();
    let povFlight: {
      id: number;
      fromPos: THREE.Vector3;
      toPos: THREE.Vector3;
      fromLook: THREE.Vector3;
      toLook: THREE.Vector3;
      fromUp: THREE.Vector3;
      fromFov: number;
      startedAt: number;
    } | null = null;
    // The flight back out to the dive pose when the learner leaves.
    let povExit: {
      fromPos: THREE.Vector3;
      fromLook: THREE.Vector3;
      fromUp: THREE.Vector3;
      fromFov: number;
      startedAt: number;
    } | null = null;
    // The turn-around on entry: one flight, one 180-degree swing about the
    // skill while closing in. Kept apart from povFlight so a walk between
    // lessons stays the simple pose-to-pose flight it is.
    let entryFlight: {
      fromAngle: number;
      toAngle: number;
      fromRadius: number;
      toRadius: number;
      fromZ: number;
      toZ: number;
      at: THREE.Vector3;
      toLook: THREE.Vector3;
      fromFov: number;
      startedAt: number;
    } | null = null;
    let povLookDragging = false;
    let dragging = false;
    let dragged = false;
    let lastX = 0;
    let lastY = 0;

    /** The stance at a lesson: half a radius back, eye height, facing up the chain. */
    function povPoseFor(index: number) {
      const y = index * STEP_HEIGHT;
      return {
        pos: new THREE.Vector3(0, y - POV_STAND_BACK, POV_EYE_OFFSET),
        look: new THREE.Vector3(0, y + POV_LOOK_AHEAD, POV_EYE_OFFSET),
      };
    }

    /** Snap straight into the stance at a lesson (reduced motion). */
    function posePov(index: number) {
      const pose = povPoseFor(index);
      camera.up.copy(POV_UP);
      camera.position.copy(pose.pos);
      povLook.copy(pose.look);
      camera.lookAt(povLook);
      camera.fov = POV_FOV;
      camera.updateProjectionMatrix();
      povIndex = index;
      standingLessonIndexRef.current = index;
    }

    function canWalkTo(index: number) {
      const lesson = realmRef.current.lessons[index];
      return canTraverseLesson(lesson);
    }

    /** Fly the camera to an adjacent lesson whose prerequisite is complete. */
    function flyPovTo(index: number) {
      if (entryFlight || povFlight || povExit || index === povIndex) return;
      const lesson = realmRef.current.lessons[index];
      if (!lesson) return;
      const isAdjacent = Math.abs(index - povIndex) === 1;
      if (!isAdjacent || !canWalkTo(index)) {
        const currentLesson = realmRef.current.lessons[povIndex];
        setTraversalNotice({
          targetTitle: lesson.title,
          currentTitle: currentLesson?.title ?? null,
          message: currentLesson
            ? `You haven't unlocked ${lesson.title} yet. Please complete ${currentLesson.title} first.`
            : `You haven't unlocked ${lesson.title} yet. Complete the previous lesson first.`,
        });
        return;
      }
      setTraversalNotice(null);
      if (prefersReducedMotion) {
        posePov(index);
        setStandingLessonIndex(index);
        standingLessonIndexRef.current = index;
        return;
      }
      const pose = povPoseFor(index);
      povFlight = {
        id: index,
        fromPos: camera.position.clone(),
        toPos: pose.pos,
        fromLook: povLook.clone(),
        toLook: pose.look,
        fromUp: camera.up.clone(),
        fromFov: camera.fov,
        startedAt: performance.now(),
      };
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

    // Open where the tree's dive ended: DIVE_DISTANCE out, upright, lens
    // still open -- the realm's first frame is the tree's last, which is what
    // makes the swap read as travel rather than as a cut. Then turn around
    // into the chain: the camera swings one hundred and eighty degrees about
    // the skill while closing in to stand at the first lesson. Reduced motion
    // starts standing: it was a cut for them anyway, because the dive was
    // skipped.
    camera.up.copy(OVERVIEW_UP);
    camera.position.copy(divePos);
    povLook.set(0, 0, 0);
    camera.lookAt(povLook);
    camera.fov = CLOSE_FOV;
    camera.updateProjectionMatrix();
    if (prefersReducedMotion) {
      posePov(initialLessonIndex);
    } else {
      const first = povPoseFor(initialLessonIndex);
      entryFlight = {
        fromAngle: ENTRY_START_ANGLE,
        toAngle: ENTRY_END_ANGLE,
        fromRadius: Math.hypot(divePos.x, divePos.y),
        toRadius: Math.hypot(first.pos.x, first.pos.y),
        fromZ: divePos.z,
        toZ: first.pos.z,
        at: new THREE.Vector3(0, 0, 0),
        toLook: first.look.clone(),
        fromFov: camera.fov,
        startedAt: performance.now(),
      };
    }

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
      // The camera pose belongs to the standing point, so the left button
      // moves nothing -- but a left-drag must still not be read as a click on
      // release. The right button looks around from the standing point,
      // exactly as the tree's POV does.
      if (event.button === 2 && !povFlight && !povExit && !leavingRef.current) {
        povLookDragging = true;
        renderer.domElement.setPointerCapture(event.pointerId);
      }
    }

    function onPointerMove(event: PointerEvent) {
      // Right-drag in POV looks around: yaw about the world's up (+Z, the
      // chain's plane is the ground), pitch about the camera's right.
      if (povLookDragging && !povFlight && !povExit && !leavingRef.current) {
        const dx = event.clientX - lastX;
        const dy = event.clientY - lastY;
        lastX = event.clientX;
        lastY = event.clientY;
        const sensitivity = 0.003;
        const yaw = new THREE.Quaternion().setFromAxisAngle(
          POV_UP,
          -dx * sensitivity,
        );
        const right = new THREE.Vector3(1, 0, 0).applyQuaternion(
          camera.quaternion,
        );
        const pitch = new THREE.Quaternion().setFromAxisAngle(
          right,
          -dy * sensitivity,
        );
        camera.quaternion.premultiply(yaw);
        camera.quaternion.multiply(pitch);
        // Keep the leave departure where the learner is actually looking.
        povLook
          .copy(camera.position)
          .add(camera.getWorldDirection(new THREE.Vector3()));
        dragged = true;
        return;
      }
      if (!dragging) {
        renderer.domElement.style.cursor = pick(event.clientX, event.clientY)
          ? "pointer"
          : "grab";
        return;
      }
      const dx = event.clientX - lastX;
      const dy = event.clientY - lastY;
      // A left-drag in the realm moves nothing -- the camera belongs to the
      // standing point -- but it is still a drag, not a click.
      if (Math.abs(dx) + Math.abs(dy) > 3) dragged = true;
      lastX = event.clientX;
      lastY = event.clientY;
    }

    function onPointerUp(event: PointerEvent) {
      if (!dragging) return;
      dragging = false;
      povLookDragging = false;
      if (renderer.domElement.hasPointerCapture(event.pointerId)) {
        renderer.domElement.releasePointerCapture(event.pointerId);
      }
      // A drag that ends over something is a drag, not a click.
      if (dragged) return;
      const hit = pick(event.clientX, event.clientY);
      if (!hit) return;
      // One click opens a lesson's card, two clicks walk to it. Two clicks are
      // two pointer-ups, so the first one waits a beat to see whether the
      // second is coming -- a delayed card is a card a double-click can cancel.
      if (detailTimer !== null) window.clearTimeout(detailTimer);
      detailTimer = window.setTimeout(() => {
        detailTimer = null;
        const live = realmRef.current;
        if (hit.kind === "test") {
          if (live.test_open) {
            onOpenTestRef.current();
          } else {
            const currentLesson = live.lessons[live.lessons.length - 1];
            setTraversalNotice({
              targetTitle: `${live.node_title} test`,
              currentTitle: currentLesson?.title ?? null,
              message: currentLesson
                ? `You haven't unlocked the test yet. Please complete ${currentLesson.title} first.`
                : "You haven't unlocked the test yet. Complete the lessons first.",
            });
          }
        } else {
          const index = live.lessons.findIndex(
            (entry) => entry.exercise_id === hit.id,
          );
          const lesson = index >= 0 ? live.lessons[index] : undefined;
          if (lesson) {
            setPending(lesson);
          }
        }
      }, 220);
    }

    function onDoubleClick(event: MouseEvent) {
      // The two-click gesture asks to stand beside the lesson, not to read its
      // card -- cancel the card the first click scheduled.
      if (detailTimer !== null) {
        window.clearTimeout(detailTimer);
        detailTimer = null;
      }
      const hit = pick(event.clientX, event.clientY);
      if (!hit) return;
      const live = realmRef.current;
      if (hit.kind === "test") {
        if (live.test_open) {
          onOpenTestRef.current();
        } else {
          const currentLesson = live.lessons[povIndex];
          setTraversalNotice({
            targetTitle: `${live.node_title} test`,
            currentTitle: currentLesson?.title ?? null,
            message: currentLesson
              ? `You haven't unlocked the test yet. Please complete ${currentLesson.title} first.`
              : "You haven't unlocked the test yet. Complete the lessons first.",
          });
        }
        return;
      }
      const index = live.lessons.findIndex(
        (entry) => entry.exercise_id === hit.id,
      );
      if (index >= 0) flyPovTo(index);
    }

    realmActionsRef.current = {
      openLesson: (id: string) => {
        const lesson = realmRef.current.lessons.find(
          (entry) => entry.exercise_id === id,
        );
        if (lesson) setPending(lesson);
      },
      walkTo: (id: string) => {
        const index = realmRef.current.lessons.findIndex(
          (entry) => entry.exercise_id === id,
        );
        if (index >= 0) flyPovTo(index);
      },
      openTest: () => {
        if (realmRef.current.test_open) onOpenTestRef.current();
      },
    };

    const canvas = renderer.domElement;
    canvas.style.cursor = "grab";
    // The right button is the POV look-around, not the browser menu.
    canvas.addEventListener("contextmenu", (event) => event.preventDefault());
    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerup", onPointerUp);
    canvas.addEventListener("dblclick", onDoubleClick);

    // ── the loop ──────────────────────────────────────────────────────────
    let frame = 0;
    const started = performance.now();
    // The door timer. A single click opens a lesson's card; a double-click
    // walks to it. Two clicks are two pointer-ups, so the first one waits a
    // beat to see whether the second is coming.
    let detailTimer: number | null = null;

    function render() {
      const elapsed = (performance.now() - started) / 1000;

      // The turn-around on entry: one swing of one hundred and eighty degrees
      // about the skill while the camera closes in. Aimed at the skill for
      // the turn so it stays framed; once the swing is done the aim leaves
      // the skill for the chain and the up vector rolls into the plane,
      // landing in the standing pose.
      if (entryFlight) {
        const progress = Math.min(
          1,
          (performance.now() - entryFlight.startedAt) / TRANSIT_MS,
        );
        const eased = cubicOut(progress);
        const angle =
          entryFlight.fromAngle +
          (entryFlight.toAngle - entryFlight.fromAngle) * eased;
        const radius =
          entryFlight.fromRadius +
          (entryFlight.toRadius - entryFlight.fromRadius) * eased;
        const z =
          entryFlight.fromZ + (entryFlight.toZ - entryFlight.fromZ) * eased;
        camera.position.set(
          radius * Math.cos(angle),
          radius * Math.sin(angle),
          z,
        );
        const lookBlend = Math.max(
          0,
          (eased - ENTRY_LOOK_BLEND_AT) / (1 - ENTRY_LOOK_BLEND_AT),
        );
        povLook.lerpVectors(entryFlight.at, entryFlight.toLook, lookBlend);
        const upBlend = Math.max(
          0,
          (eased - ENTRY_UP_BLEND_AT) / (1 - ENTRY_UP_BLEND_AT),
        );
        camera.up.lerpVectors(OVERVIEW_UP, POV_UP, upBlend);
        camera.lookAt(povLook);
        camera.fov =
          entryFlight.fromFov + (POV_FOV - entryFlight.fromFov) * eased;
        camera.updateProjectionMatrix();
        if (progress >= 1) {
          povIndex = initialLessonIndex;
          standingLessonIndexRef.current = initialLessonIndex;
          entryFlight = null;
        }
      }

      // Walk to a lesson: position, aim and lens move together, landing with
      // the chain ahead. Same flight language as the tree's traversal.
      if (povFlight) {
        const progress = Math.min(
          1,
          (performance.now() - povFlight.startedAt) / TRANSIT_MS,
        );
        const eased = cubicOut(progress);
        camera.position.lerpVectors(povFlight.fromPos, povFlight.toPos, eased);
        povLook.lerpVectors(povFlight.fromLook, povFlight.toLook, eased);
        camera.up.lerpVectors(povFlight.fromUp, POV_UP, eased);
        camera.lookAt(povLook);
        camera.fov = povFlight.fromFov + (POV_FOV - povFlight.fromFov) * eased;
        camera.updateProjectionMatrix();
        if (progress >= 1) {
          povIndex = povFlight.id;
          setStandingLessonIndex(povFlight.id);
          standingLessonIndexRef.current = povFlight.id;
          povFlight = null;
        }
      }

      // The flight back out to the tree. Started by the back button (which
      // sets leavingRef); the exit ends exactly where the tree's dive ended,
      // so the tree can pick the camera up from the same pose.
      if (leavingRef.current && !povExit) {
        // A walk or the entry turn in progress is abandoned: the exit takes
        // the camera from wherever it is, and two flights over one camera
        // would fight.
        povFlight = null;
        entryFlight = null;
        povExit = {
          fromPos: camera.position.clone(),
          fromLook: povLook.clone(),
          fromUp: camera.up.clone(),
          fromFov: camera.fov,
          startedAt: performance.now(),
        };
      }
      if (povExit) {
        const progress = Math.min(
          1,
          (performance.now() - povExit.startedAt) / TRANSIT_MS,
        );
        const eased = cubicOut(progress);
        camera.position.lerpVectors(povExit.fromPos, divePos, eased);
        povLook.lerpVectors(
          povExit.fromLook,
          new THREE.Vector3(0, 0, 0),
          eased,
        );
        camera.up.lerpVectors(povExit.fromUp, OVERVIEW_UP, eased);
        camera.lookAt(povLook);
        camera.fov = povExit.fromFov + (CLOSE_FOV - povExit.fromFov) * eased;
        camera.updateProjectionMatrix();
        if (progress >= 1) {
          leavingRef.current = false;
          povExit = null;
          onExitRef.current();
        }
      }
      // An open test is the only thing that moves. It is the reward, and the
      // realm has nothing else competing for attention.
      if (realmRef.current.test_open && !prefersReducedMotion) {
        ring.scale.setScalar(1 + Math.sin(elapsed * 2.4) * 0.05);
        ring.rotation.z = elapsed * 0.35;
      }

      renderer.render(scene, camera);

      // POV neighbour cards, the way the tree walks its map: standing at a
      // lesson, the lesson the line connects it to -- the one ahead and the
      // one behind -- carries a floating card naming it, saying what it asks
      // for, and carrying its state. Projected and clamped to the panel so a
      // card at the edge is readable rather than half off it.
      const rect = renderer.domElement.getBoundingClientRect();
      if (povIndex >= 0 && povIndex < current.lessons.length) {
        const cards: RealmCard[] = [];
        const pushCard = (index: number, badge: RealmCard["badge"]) => {
          const entry = targets[index];
          if (!entry) return;
          projected
            .copy(entry.mesh.position)
            .setZ(entry.mesh.position.z + LESSON_THICKNESS + 6)
            .project(camera);
          if (projected.z > 1) return;
          const live = realmRef.current;
          const isTest = badge === "test";
          const lesson = isTest ? null : (live.lessons[index] ?? null);
          const walkable = isTest ? live.test_open : canWalkTo(index);
          const accent = isTest
            ? live.test_open
              ? TEST_OPEN
              : LESSON_CLOSED
            : lesson
              ? lesson.cleared
                ? LESSON_CLEARED
                : walkable
                  ? LESSON_OPEN
                  : LESSON_CLOSED
              : LESSON_CLOSED;
          const x = Math.min(
            Math.max(
              ((projected.x + 1) / 2) * rect.width,
              REALM_CARD_WIDTH / 2 + 4,
            ),
            rect.width - REALM_CARD_WIDTH / 2 - 4,
          );
          const y = Math.min(
            Math.max(((1 - projected.y) / 2) * rect.height - 8, 64),
            rect.height - 84,
          );
          cards.push({
            id: entry.id,
            title: isTest
              ? `${current.node_title} — test`
              : (lesson?.title ?? ""),
            desc: isTest
              ? live.test_open
                ? "Open. Pass it to master this skill."
                : "Clear every lesson to open"
              : (lesson?.instructions ?? ""),
            status: isTest
              ? live.test_open
                ? "Ready to pass"
                : "Locked"
              : lesson
                ? lesson.cleared
                  ? `Cleared · best ${Math.round((lesson.best_score ?? 0) * 100)}%`
                  : walkable
                    ? "Ready to play"
                    : "Locked · complete the previous lesson first"
                : "",
            progress: isTest
              ? `${live.lessons.filter((entry) => entry.cleared).length}/${live.lessons.length} lessons cleared`
              : lesson
                ? `Step ${lesson.step}/${live.lessons.length} · ${lesson.attempts} attempt${lesson.attempts === 1 ? "" : "s"}`
                : "",
            badge,
            accent,
            x,
            y,
            visible: true,
          });
        }; // The line connects a lesson to the ones it touches: behind and
        // ahead, and the test above the last lesson.
        if (povIndex > 0) pushCard(povIndex - 1, "previous");
        if (povIndex < current.lessons.length - 1) {
          pushCard(povIndex + 1, "next");
        } else {
          pushCard(current.lessons.length, "test");
        }
        setRealmCards(cards);
      } else {
        setRealmCards((previous) => (previous.length > 0 ? [] : previous));
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
      canvas.removeEventListener("dblclick", onDoubleClick);
      if (detailTimer !== null) window.clearTimeout(detailTimer);
      realmActionsRef.current = null;
      discGeometry.dispose();
      ringGeometry.dispose();
      for (const entry of targets)
        (entry.mesh.material as THREE.Material).dispose();
      renderer.dispose();
      if (canvas.parentNode === mount) mount.removeChild(canvas);
    };
  }, [shape, prefersReducedMotion]);

  const standingLesson =
    realm.lessons[standingLessonIndex] ?? realm.lessons[0] ?? null;
  const lessonIndex = (lesson: Lesson) =>
    realm.lessons.findIndex(
      (entry) => entry.exercise_id === lesson.exercise_id,
    );
  const canWalkToLesson = (lesson: Lesson) => canTraverseLesson(lesson);
  const pendingCanStart = pending?.open === true;

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent, action: () => void, enabled: boolean) => {
      if ((event.key === "Enter" || event.key === " ") && enabled) {
        event.preventDefault();
        action();
      }
    },
    [],
  );

  return (
    <div className="relative h-full overflow-hidden bg-graph-ground">
      <div ref={mountRef} className="absolute inset-0" aria-hidden="true" />

      {traversalNotice && (
        <div
          className="absolute inset-x-3 top-20 z-30 mx-auto max-w-md rounded-lg border border-graph-available/60 bg-graph-surface/95 p-3 shadow-lg"
          role="alert"
        >
          <p className="font-display text-sm font-semibold text-graph-ink">
            Not unlocked yet
          </p>
          <p className="mt-1 text-xs leading-relaxed text-graph-ink-quiet">
            {traversalNotice.message}
          </p>
          {traversalNotice.currentTitle && (
            <p className="mt-1 text-[10px] text-graph-learning">
              Current lesson: {traversalNotice.currentTitle}
            </p>
          )}
          <button
            type="button"
            onClick={() => setTraversalNotice(null)}
            className={`mt-2 rounded-md border border-graph-line bg-graph-raised px-2.5 py-1 text-[11px] font-semibold text-graph-ink ${FOCUS_RING}`}
          >
            Close
          </button>
        </div>
      )}

      {/* The chain's POV cards: standing at a lesson, the lesson the line
          connects it to -- the one ahead and the one behind -- floats beside
          its disc with its name, what it asks for, and current progress.
          Clicking a card opens its lesson details; double-clicking an unlocked
          neighbour walks to it, while a closed card explains the prerequisite. */}
      {realmCards.length > 0 && (
        <div className="pointer-events-none absolute inset-0 overflow-hidden">
          {realmCards.map((card) => (
            <button
              key={card.id}
              type="button"
              onClick={() => {
                if (card.badge === "test") {
                  realmActionsRef.current?.openTest();
                } else {
                  realmActionsRef.current?.openLesson(card.id);
                }
              }}
              onDoubleClick={(event) => {
                event.preventDefault();
                if (card.badge !== "test") {
                  realmActionsRef.current?.walkTo(card.id);
                }
              }}
              className={`pointer-events-auto absolute -translate-x-1/2 -translate-y-full rounded-lg border bg-graph-surface/95 p-2.5 text-left shadow-lg backdrop-blur-sm transition hover:bg-graph-raised ${FOCUS_RING}`}
              style={{
                left: card.x,
                top: card.y,
                width: REALM_CARD_WIDTH,
                borderColor: card.accent,
                opacity: card.visible ? 1 : 0,
              }}
              aria-label={`${card.badge === "previous" ? "Previous lesson" : card.badge === "next" ? "Next lesson" : "Test"} ${card.title}. ${card.desc} ${card.status}. ${card.progress}`}
            >
              <span className="block text-[9px] font-bold uppercase tracking-wider text-graph-ink-quiet">
                {card.badge === "previous"
                  ? "▲ Previous"
                  : card.badge === "next"
                    ? "▼ Next"
                    : "◆ Test"}
              </span>
              <span className="mt-0.5 block truncate font-display text-xs font-semibold text-graph-ink">
                {card.title}
              </span>{" "}
              <span className="mt-1 block line-clamp-2 text-[10px] leading-snug text-graph-ink-quiet">
                {card.desc}
              </span>
              <span
                className="mt-1.5 block text-[10px] font-semibold"
                style={{ color: card.accent }}
              >
                {card.status}
              </span>
              <span className="mt-1 block text-[10px] leading-snug text-graph-ink-quiet">
                {card.progress}
              </span>
            </button>
          ))}
        </div>
      )}

      <div className="absolute left-3 top-3 max-w-xs rounded-lg border border-graph-line bg-graph-surface p-3 shadow-lg">
        <p className="font-display text-sm font-semibold text-graph-ink">
          {realm.node_title}
        </p>
        <p className="mt-1 text-[11px] leading-snug text-graph-ink-quiet">
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

      <p className="pointer-events-none absolute bottom-3 left-3 text-[11px] text-graph-ink-quiet">
        Right-drag to look around · click a lesson for details · double-click to
        step to an unlocked neighbour
      </p>

      {/* What the lesson asks for, before committing to it. A click on a coin is
          one gesture away from an orbit, so playing takes a second press. */}
      {pending && !playing && (
        <div className="absolute inset-0 flex items-center justify-center bg-graph-ground/70 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="lesson-confirm-title"
            className="w-full max-w-sm rounded-xl border border-graph-line bg-graph-surface p-5 shadow-lg"
          >
            <p className="text-[10px] font-semibold uppercase tracking-wider text-graph-learning">
              Lesson {pending.step} of {realm.lessons.length}
            </p>
            <h3
              id="lesson-confirm-title"
              className="mt-1 font-display text-base font-semibold text-graph-ink"
            >
              {pending.title}
            </h3>
            <p className="mt-2 text-xs leading-relaxed text-graph-ink-quiet">
              {pending.instructions}
            </p>
            {pending.cleared && (
              <p className="mt-2 text-[11px] text-graph-ink-quiet">
                Already cleared at {Math.round((pending.best_score ?? 0) * 100)}
                %. Playing it again can only help.
              </p>
            )}
            {!pendingCanStart && (
              <p className="mt-2 text-[11px] text-graph-decaying">
                Complete the previous lesson before starting this lesson.
              </p>
            )}
            <div className="mt-5 flex gap-2">
              <button
                type="button"
                onClick={() => setPending(null)}
                className={`${BUTTON_SECONDARY} flex-1`}
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={!pendingCanStart}
                onClick={() => setPlaying(pending)}
                className={`${BUTTON_PRIMARY} flex-1`}
              >
                {pending.cleared ? "Redo lesson" : "Start lesson"}
              </button>
            </div>
          </div>
        </div>
      )}

      {standingLesson && !playing && (
        <div className="absolute bottom-12 left-1/2 z-10 -translate-x-1/2">
          <button
            type="button"
            disabled={!standingLesson.open}
            onClick={() => setPlaying(standingLesson)}
            className={`${BUTTON_PRIMARY} min-w-40 shadow-lg`}
          >
            {standingLesson.cleared ? "Redo lesson" : "Start lesson"}
          </button>
        </div>
      )}

      {/* The lesson itself, in the realm rather than in a panel beside the tree. */}
      {playing && (
        <div className="absolute inset-0 overflow-y-auto bg-graph-ground/85 p-4">
          <div className="mx-auto w-full max-w-md">
            <div className="mb-2 flex items-center justify-between gap-3">
              <p className="font-display text-sm font-semibold text-graph-ink">
                {playing.title}
              </p>
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
            aria-disabled={!canWalkToLesson(lesson)}
            aria-label={`${lesson.title}. ${lesson.cleared ? "Cleared and traversable." : lesson.open ? "Open for practice from its card." : "Locked until the previous lesson is cleared."}`}
            className={FOCUS_RING}
            onKeyDown={(event) =>
              onKeyDown(
                event,
                () => setPending(lesson),
                canWalkToLesson(lesson),
              )
            }
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
