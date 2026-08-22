"use client";

/**
 * The skill tree, in space.
 *
 * Takes exactly the props the flat canvas took, and means the same thing by all
 * of them: click selects, double-click asks to work on a skill, a search dims
 * what it did not match. Everything downstream — the inspector, the drill panel,
 * the lesson gate — reads the store, not this component, so the view is a view.
 *
 * What it does NOT do is decide anything about progress. Locked, ready, fading
 * and mastered are derived server-side from review history and arrive on the
 * snapshot; this paints them. A canvas that computed its own idea of mastered
 * would disagree with the scheduler the first time a skill decayed, and the
 * learner would have two answers about the same skill.
 *
 * ## Why it looks the way it does
 *
 * The graph is a window into the curriculum, and it is the one place the light
 * page deliberately goes dark — near-black space, so a lit orb glows. Chrome
 * stays on the page; the canvas is where the learner stands in the curriculum.
 *
 * Skills are lit discs, not shaded spheres: a key light and an ambient with
 * metalness and roughness make them read as objects in space rather than
 * stickers, while the state hue stays bright enough that five states read as
 * five colours under the rig. The palette is the reference scheme this design
 * follows — gold ready, slate locked, blue in hand, purple done, orange fading
 * — mapped once from the node states in `lib/graphTheme.ts`, because the
 * app's page palette is tuned against the light page and cannot clear 3:1 on
 * dark.
 *
 * Titles are HTML positioned over the canvas rather than drawn in the scene.
 * Text in WebGL means either a texture atlas that goes soft under the camera or
 * geometry that costs more than the tree does; projecting a DOM label costs a
 * matrix multiply per skill and gets the application's own typeface, kerning and
 * subpixel rendering for nothing.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

import {
  GRAPH_GROUND,
  GRAPH_SELECTED,
  graphEdgeStyle,
  graphNodeStyle,
} from "@/lib/graphTheme";
import { neighboursOf } from "@/lib/graphNeighbours";
import { graphShapeKey } from "@/lib/layout";
import { framingCentre, framingDistance, layoutGraph3D } from "@/lib/layout3d";
import { canOpenLesson } from "@/lib/lesson";
import { nodeAriaLabel } from "@/lib/nodeState";
import type { GraphNode, GraphSnapshot } from "@/lib/types";
import { BUTTON_SECONDARY, FOCUS_RING } from "@/lib/ui";
import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";
import { useGraphStore } from "@/stores/useGraphStore";

interface Props {
  snapshot: GraphSnapshot;
  selectedNodeId: string | null;
  onSelect: (nodeId: string | null) => void;
  /** The learner asked to work on this skill, not merely to read about it. */
  onOpenLesson: (nodeId: string) => void;
  /** Node ids matching the active search, or null when none is running. */
  matchedNodeIds?: ReadonlySet<string> | null;
  /**
   * The learner just came back out of a realm, so the camera starts where the
   * realm left it and pulls back. Without this the return is a cut, and only
   * one direction of the journey reads as travel.
   */
  arriveFrom?: string | null;
}

const DISC_RADIUS = 8.5;
const DISC_THICKNESS = 1.4;
const UNMATCHED_OPACITY = 0.14;
const PICK_THRESHOLD = 16;

// POV traversal (the reference this design follows walks maps node to node).
// The camera stands AT the skill, exactly as the reference's own POV camera
// does: half a node radius back from its centre, the lens at eye height -- one
// disc thickness plus two units above the plane -- and the up vector along +Z,
// so the tree's plane is the ground the learner is standing in and the route
// the skill opens (its children) runs away up the screen at eye level. The
// skill itself is at the learner's feet; the path ahead is the view. The up
// vector is never parallel to the view direction (the route runs in the plane,
// the up leaves it), so no route can degenerate into an arbitrary roll.
const POV_STAND_BACK = DISC_RADIUS * 0.5;
const POV_LOOK_AHEAD = 40;
const POV_EYE_OFFSET = DISC_THICKNESS / 2 + 2;
const POV_FOV = 75;
const POV_CARD_WIDTH = 180;
const POV_UP = new THREE.Vector3(0, 0, 1);
const OVERVIEW_UP = new THREE.Vector3(0, 1, 0);

/**
 * The camera pose the tree hands the realm.
 *
 * Exported because the realm starts here and pulls back out of it. The two
 * canvases are separate scenes, so a matched pose on each side is the only
 * thing making the swap read as travel rather than as a cut.
 *
 * The field of view widens on the way in. That is what makes a dive feel like
 * a dive: moving the camera closer alone reads as a zoom, while opening the
 * lens as you approach reads as arriving somewhere. Coming back out, it closes
 * again.
 */
export const DIVE_DISTANCE = 34;
export const WIDE_FOV = 45;
export const CLOSE_FOV = 72;
export const TRANSIT_MS = 900;

/** Decelerating. The end of a journey is where the eye needs time to settle. */
export function cubicOut(progress: number): number {
  return 1 - Math.pow(1 - progress, 3);
}

interface Label {
  id: string;
  title: string;
  x: number;
  y: number;
  size: number;
  visible: boolean;
}

/** One floating neighbour card in POV traversal. */
interface PovCard {
  id: string;
  title: string;
  badge: "parent" | "child";
  accent: string;
  label: string;
  progress: string;
  locked: boolean;
  structural: boolean;
  needs: string;
  x: number;
  y: number;
  visible: boolean;
}

interface TraversalNotice {
  targetTitle: string;
  currentTitle: string | null;
  message: string;
}

// @spec UI-GRAPH3D-001, UI-GRAPH3D-004, UI-GRAPH3D-005, UI-GRAPH3D-006, UI-GRAPH3D-007, UI-GRAPH3D-008
// @spec UI-GRAPH3D-013, UI-GRAPH3D-014, UI-GRAPH3D-015, UI-GRAPH3D-016, UI-GRAPH3D-017, UI-GRAPH3D-019
// @spec UI-GRAPH3D-020, UI-GRAPH3D-021, UI-GRAPH3D-022, UI-GRAPH3D-028
export function SkillGraph3D({
  snapshot,
  selectedNodeId,
  onSelect,
  onOpenLesson,
  matchedNodeIds,
  arriveFrom,
}: Props) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const prefersReducedMotion = usePrefersReducedMotion();
  const [hovered, setHovered] = useState<GraphNode | null>(null);
  const [labels, setLabels] = useState<Label[]>([]);
  // The skill the learner is standing beside in POV traversal, and its floating
  // neighbour cards. Both live in React state because they are DOM; the camera
  // pose itself is world state inside the effect.
  const [povNodeId, setPovNodeId] = useState<string | null>(null);
  const [povCards, setPovCards] = useState<PovCard[]>([]);
  const [traversalNotice, setTraversalNotice] =
    useState<TraversalNotice | null>(null);
  // The skill whose door is open -- the modal naming it, describing it, and
  // offering its world. Lives here (React) because it is DOM; the click that
  // opens it lives in the effect, so the timer and the double-click that
  // cancels it share a home.
  const [detailNodeId, setDetailNodeId] = useState<string | null>(null);
  const detailNodeIdRef = useRef<string | null>(null);
  detailNodeIdRef.current = detailNodeId;
  const hoveredIdRef = useRef<string | null>(null);
  // The imperative handles the DOM (cards, toolbar) calls into the canvas.
  const povActionsRef = useRef<{
    flyTo: (id: string) => void;
    exit: () => void;
    enter: () => void;
  } | null>(null);

  const focusRequest = useGraphStore((state) => state.focusRequest);
  const focusRef = useRef(focusRequest);
  focusRef.current = focusRequest;

  /**
   * The shape of the tree, as a string.
   *
   * Everything below keys off this rather than off `snapshot.nodes`. A refetch
   * after a grade hands back a new array for the same tree, and array identity
   * as an effect dependency means tearing down the WebGL context and building a
   * new one every time a learner answers a question.
   */
  const shapeKey = useMemo(
    () => graphShapeKey(snapshot.nodes, snapshot.edges),
    [snapshot.nodes, snapshot.edges],
  );

  const positions = useMemo(
    () => layoutGraph3D(snapshot.nodes, snapshot.edges),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- shapeKey IS the identity of these arrays
    [shapeKey],
  );

  const selectedRef = useRef(selectedNodeId);
  const matchedRef = useRef(matchedNodeIds);
  const onSelectRef = useRef(onSelect);
  const onOpenRef = useRef(onOpenLesson);
  const snapshotRef = useRef(snapshot);
  selectedRef.current = selectedNodeId;
  matchedRef.current = matchedNodeIds;
  onSelectRef.current = onSelect;
  onOpenRef.current = onOpenLesson;
  snapshotRef.current = snapshot;

  const nodeById = useMemo(() => {
    const map = new Map<string, GraphNode>();
    for (const node of snapshot.nodes) map.set(node.id, node);
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- shapeKey IS the identity of this array
  }, [shapeKey]);
  const nodeByIdRef = useRef(nodeById);
  nodeByIdRef.current = nodeById;
  // Read once at mount: this is where the camera STARTS, not something that
  // should move the view if it changes later.
  const arriveFromRef = useRef(arriveFrom);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount || snapshotRef.current.nodes.length === 0) return;
    const { nodes, edges } = snapshotRef.current;
    const lookup = nodeByIdRef.current;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(GRAPH_GROUND);

    // The same rig as the reference this look follows: a key light and an
    // ambient, so a disc reads as an object in space rather than a sticker.
    const keyLight = new THREE.DirectionalLight(0xffffff, 2);
    keyLight.position.set(20, 40, 60);
    scene.add(keyLight);
    scene.add(new THREE.AmbientLight(0xffffff, 0.6));

    const camera = new THREE.PerspectiveCamera(WIDE_FOV, 1, 0.1, 6000);
    const distance = framingDistance(positions);
    const centre = framingCentre(positions);

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch {
      // No WebGL. The page keeps the outline, which is the honest fallback.
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.domElement.style.display = "block";
    mount.appendChild(renderer.domElement);

    // ── skills ────────────────────────────────────────────────────────────
    // A flat coin standing in the plane of the tree, not a billboard that turns
    // to face you. A billboard is always a perfect circle, so orbiting tells you
    // nothing; a fixed disc foreshortens into an ellipse and shows its edge,
    // which is what makes the rotation legible as rotation.
    const discGeometry = new THREE.CylinderGeometry(
      DISC_RADIUS,
      DISC_RADIUS,
      DISC_THICKNESS,
      48,
    );
    const ringGeometry = new THREE.TorusGeometry(DISC_RADIUS + 2.2, 0.8, 8, 48);
    const discs = new Map<string, THREE.Mesh>();
    const rings = new Map<string, THREE.Mesh>();

    for (const node of nodes) {
      const point = positions[node.id];
      if (point) {
        const style = graphNodeStyle(node);
        const accent = new THREE.Color(style.accent);
        // Standard, lit like the reference -- metalness and roughness put the
        // disc in the space -- with a low emissive of the state hue so a state
        // still reads as its colour where the key light falls off it.
        const material = new THREE.MeshStandardMaterial({
          color: accent,
          metalness: 0.3,
          roughness: 0.3,
          emissive: accent,
          emissiveIntensity: 0.22,
          transparent: true,
        });
        const disc = new THREE.Mesh(discGeometry, material);
        disc.position.set(point.x, point.y, point.z);
        // Lay the coin into the plane the tree occupies: a cylinder's axis is Y,
        // so a quarter turn about X points its face down +Z, at the camera.
        disc.rotation.x = Math.PI / 2;
        scene.add(disc);
        discs.set(node.id, disc);

        // Drawn only for the selected skill, so selection reads without
        // recolouring the skill and losing its state.
        const ring = new THREE.Mesh(
          ringGeometry,
          new THREE.MeshBasicMaterial({
            color: new THREE.Color(GRAPH_SELECTED),
            transparent: true,
          }),
        );
        ring.position.copy(disc.position);
        // A torus already lies in the XY plane, so it shares the disc's facing
        // without a rotation and foreshortens with it.
        ring.visible = false;
        scene.add(ring);
        rings.set(node.id, ring);
      }
    }

    // ── prerequisites ─────────────────────────────────────────────────────
    for (const edge of edges) {
      const from = positions[edge.source];
      const to = positions[edge.target];
      const target = lookup.get(edge.target);
      if (from && to && target) {
        // One palette for nodes and routes, coloured by what the edge leads TO
        // (see lib/graphTheme.ts): gold into a ready skill, dimmed gold into
        // what is in hand or done, orange into a fading skill, slate into the
        // locked future. An available skill's prerequisites are mastered by
        // definition, so target state fully determines the route.
        const edgeStyle = graphEdgeStyle(target);
        const geometry = new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(from.x, from.y, from.z),
          new THREE.Vector3(to.x, to.y, to.z),
        ]);
        const material = new THREE.LineBasicMaterial({
          color: new THREE.Color(edgeStyle.accent),
          transparent: true,
          opacity: edgeStyle.opacity,
        });
        scene.add(new THREE.Line(geometry, material));
      }
    }

    // ── orbit ─────────────────────────────────────────────────────────────
    // Starts at a three-quarter tilt -- cos(phi) puts the camera about a third
    // of the way above the plane -- so the tree reads as space rather than as a
    // flat diagram, which is the difference the reference look is built on.
    let theta = Math.PI / 2;
    let phi = 1.08;
    const returning =
      !prefersReducedMotion && arriveFromRef.current
        ? positions[arriveFromRef.current]
        : undefined;
    let radius = returning ? DIVE_DISTANCE : distance;
    let returnProgress = returning ? 0 : 1;
    let dragging = false;
    let dragged = false;
    let povLookDragging = false;
    let lastX = 0;
    let lastY = 0;
    // The door timer. A single click opens the skill's modal; a double-click
    // enters POV. Two clicks are two pointer-ups, so the first one waits a
    // beat to see whether the second is coming -- a delayed modal is a modal
    // a double-click can still cancel.
    let detailTimer: number | null = null;

    const target = returning
      ? new THREE.Vector3(returning.x, returning.y, returning.z)
      : new THREE.Vector3(centre.x, centre.y, centre.z);

    function place() {
      camera.position.set(
        target.x + radius * Math.sin(phi) * Math.cos(theta),
        target.y + radius * Math.cos(phi),
        target.z + radius * Math.sin(phi) * Math.sin(theta),
      );
      camera.lookAt(target);
    }

    // ── POV traversal ─────────────────────────────────────────────────────
    // The overview pose, frozen when the learner steps into POV and restored
    // (or flown back to) when they leave. The orbit state -- theta, phi,
    // radius, target -- is untouched while POV holds the camera, so the way
    // back is exactly the way the learner was looking.
    const overviewPos = new THREE.Vector3();
    const overviewLook = new THREE.Vector3();
    const povLook = new THREE.Vector3();

    function captureOverviewPose() {
      overviewPos.set(
        target.x + radius * Math.sin(phi) * Math.cos(theta),
        target.y + radius * Math.cos(phi),
        target.z + radius * Math.sin(phi) * Math.sin(theta),
      );
      overviewLook.copy(target);
    }

    /**
     * The pose the camera takes standing AT a skill: half a radius back, eye
     * level in the plane, looking along the route it opens -- toward its
     * children when it has any, back the way it was reached otherwise. The
     * skill itself is where the learner stands; the path ahead is the view.
     */
    function povPoseFor(id: string) {
      const point = positions[id];
      if (!point) return null;
      const { parents, children } = neighboursOf(nodes, edges, id);
      const parentIds = parents.map((entry) => entry.id);
      const childIds = children.map((entry) => entry.id);

      let fx = 0;
      let fy = -1;
      const childPts = childIds
        .map((cid) => positions[cid])
        .filter((entry) => entry !== undefined);
      if (childPts.length > 0) {
        const avgX =
          childPts.reduce((sum, entry) => sum + entry.x, 0) / childPts.length;
        const avgY =
          childPts.reduce((sum, entry) => sum + entry.y, 0) / childPts.length;
        const dx = avgX - point.x;
        const dy = avgY - point.y;
        if (Math.hypot(dx, dy) > 0.001) {
          fx = dx;
          fy = dy;
        }
      } else if (parentIds.length > 0) {
        const back = positions[parentIds[0]];
        if (back) {
          const dx = point.x - back.x;
          const dy = point.y - back.y;
          if (Math.hypot(dx, dy) > 0.001) {
            fx = dx;
            fy = dy;
          }
        }
      }
      const length = Math.hypot(fx, fy) || 1;
      return {
        id,
        at: new THREE.Vector3(point.x, point.y, point.z),
        forward: new THREE.Vector2(fx / length, fy / length),
        parentIds,
        childIds,
      };
    }

    let povState: ReturnType<typeof povPoseFor> = null;
    let povFlight: {
      id: string;
      at: THREE.Vector3;
      forward: THREE.Vector2;
      parentIds: string[];
      childIds: string[];
      fromPos: THREE.Vector3;
      toPos: THREE.Vector3;
      fromLook: THREE.Vector3;
      toLook: THREE.Vector3;
      fromUp: THREE.Vector3;
      fromFov: number;
      startedAt: number;
    } | null = null;
    let povExit: {
      fromPos: THREE.Vector3;
      fromLook: THREE.Vector3;
      fromFov: number;
      startedAt: number;
    } | null = null;
    let pendingFocus: { nodeId: string; point: THREE.Vector3 } | null = null;

    /** Snap straight into POV at a skill (reduced motion, or arrival). */
    function posePov(pov: NonNullable<ReturnType<typeof povPoseFor>>) {
      camera.up.copy(POV_UP);
      const eye = pov.at.z + POV_EYE_OFFSET;
      camera.position.set(
        pov.at.x - pov.forward.x * POV_STAND_BACK,
        pov.at.y - pov.forward.y * POV_STAND_BACK,
        eye,
      );
      povLook.set(
        pov.at.x + pov.forward.x * POV_LOOK_AHEAD,
        pov.at.y + pov.forward.y * POV_LOOK_AHEAD,
        eye,
      );
      camera.lookAt(povLook);
      camera.fov = POV_FOV;
      camera.updateProjectionMatrix();
      povState = pov;
      setPovNodeId(pov.id);
    }

    /** Fly the camera to stand beside an unlocked skill. */
    function flyPovTo(id: string) {
      if (povFlight || povExit || diveTo) return;
      const node = lookup.get(id);
      const pov = povPoseFor(id);
      if (!node || !pov) return;
      if (!node.assessable) {
        setTraversalNotice({
          targetTitle: node.title,
          currentTitle: povState
            ? (lookup.get(povState.id)?.title ?? null)
            : null,
          message: `${node.title} is a section heading, not a playable skill.`,
        });
        return;
      }
      if (node.progress.state === "locked") {
        const currentTitle = povState
          ? (lookup.get(povState.id)?.title ?? null)
          : null;
        setTraversalNotice({
          targetTitle: node.title,
          currentTitle,
          message: currentTitle
            ? `You haven't unlocked ${node.title} yet. Please complete ${currentTitle} first.`
            : `You haven't unlocked ${node.title} yet. Complete its prerequisites first.`,
        });
        return;
      }
      setTraversalNotice(null);
      if (prefersReducedMotion) {
        captureOverviewPose();
        posePov(pov);
        return;
      }
      captureOverviewPose();
      const eye = pov.at.z + POV_EYE_OFFSET;
      const toPos = new THREE.Vector3(
        pov.at.x - pov.forward.x * POV_STAND_BACK,
        pov.at.y - pov.forward.y * POV_STAND_BACK,
        eye,
      );
      const toLook = new THREE.Vector3(
        pov.at.x + pov.forward.x * POV_LOOK_AHEAD,
        pov.at.y + pov.forward.y * POV_LOOK_AHEAD,
        eye,
      );
      povFlight = {
        ...pov,
        fromPos: camera.position.clone(),
        toPos,
        fromLook: povState ? povLook.clone() : target.clone(),
        toLook,
        fromUp: povState ? POV_UP.clone() : OVERVIEW_UP.clone(),
        fromFov: camera.fov,
        startedAt: performance.now(),
      };
    }

    /** Leave POV, flying back to the overview pose. */
    function exitPov() {
      if (!povState) return;
      if (prefersReducedMotion) {
        camera.up.copy(OVERVIEW_UP);
        camera.position.copy(overviewPos);
        camera.lookAt(overviewLook);
        camera.fov = WIDE_FOV;
        camera.updateProjectionMatrix();
        povState = null;
        setPovNodeId(null);
        return;
      }
      povExit = {
        fromPos: camera.position.clone(),
        fromLook: povLook.clone(),
        fromFov: camera.fov,
        startedAt: performance.now(),
      };
    }

    /** Dive from wherever the camera is into the skill's realm. */
    function startDive(id: string) {
      const node = lookup.get(id);
      const point = positions[id];
      if (!canOpenLesson(node) || !point) return;
      if (prefersReducedMotion) {
        onOpenRef.current(id);
        return;
      }
      const at = new THREE.Vector3(point.x, point.y, point.z);
      // Straight down the line the camera is already on, so the skill does not
      // slide sideways on the way in.
      const approach = camera.position
        .clone()
        .sub(at)
        .normalize()
        .multiplyScalar(DIVE_DISTANCE)
        .add(at);
      diveTo = {
        id,
        at,
        fromPos: camera.position.clone(),
        toPos: approach,
        fromLook: povState ? povLook.clone() : target.clone(),
        fromUp: povState ? POV_UP.clone() : OVERVIEW_UP.clone(),
        fromFov: camera.fov,
        startedAt: performance.now(),
      };
    }

    povActionsRef.current = {
      flyTo: flyPovTo,
      exit: exitPov,
      enter: () => startDive(povState?.id ?? ""),
    };

    function resize() {
      const { clientWidth, clientHeight } = mount!;
      // A zero-sized mount happens on the first observation, before layout.
      // Dividing by it gives the camera an aspect of NaN, after which nothing
      // draws and nothing says why.
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

    function pick(clientX: number, clientY: number): string | null {
      const rect = renderer.domElement.getBoundingClientRect();
      const px = clientX - rect.left;
      const py = clientY - rect.top;

      let best: string | null = null;
      let bestDistance = PICK_THRESHOLD;
      for (const [id, disc] of discs) {
        projected.copy(disc.position).project(camera);
        // Behind the camera. Projected coordinates are still finite there, so
        // without this a skill behind you competes for the click.
        if (projected.z <= 1) {
          const sx = ((projected.x + 1) / 2) * rect.width;
          const sy = ((1 - projected.y) / 2) * rect.height;
          const away = Math.hypot(sx - px, sy - py);
          if (away < bestDistance) {
            bestDistance = away;
            best = id;
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
      // In POV the camera pose is owned by the traversal, not the pointer --
      // the right button is the one exception: it looks around from the
      // standing point, exactly as the reference's POV rotation does.
      if (event.button === 2 && povState && !povFlight && !povExit) {
        povLookDragging = true;
      }
      if (!(povState || povFlight || povExit) || povLookDragging) {
        renderer.domElement.setPointerCapture(event.pointerId);
      }
    }

    function onPointerMove(event: PointerEvent) {
      // Right-drag in POV looks around: yaw about the world's up (in POV the
      // tree plane is the ground, so +Z is up) and pitch about the camera's
      // right, exactly as the reference's POV rotation does.
      if (povLookDragging && povState && !povFlight && !povExit) {
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
        // Keep the dive/exit departure point where the learner is actually
        // looking, so leaving POV continues from the turned head.
        povLook
          .copy(camera.position)
          .add(camera.getWorldDirection(new THREE.Vector3()));
        // A look-around is a drag, not a click -- releasing must not select.
        dragged = true;
        return;
      }
      if (!dragging) {
        // Only when the skill under the cursor actually changes. Setting state
        // on every pointermove re-renders at the pointer's sample rate.
        const id = pick(event.clientX, event.clientY);
        if (id !== hoveredIdRef.current) {
          hoveredIdRef.current = id;
          setHovered(id ? (nodeByIdRef.current.get(id) ?? null) : null);
          renderer.domElement.style.cursor = id ? "pointer" : "grab";
        }
        return;
      }
      if (povState || povFlight || povExit) return;
      const dx = event.clientX - lastX;
      const dy = event.clientY - lastY;
      if (Math.abs(dx) + Math.abs(dy) > 3) dragged = true;
      lastX = event.clientX;
      lastY = event.clientY;
      returnProgress = 1;
      theta -= dx * 0.005;
      // Clamped short of the poles: at exactly vertical the up-vector flips and
      // the whole tree mirrors itself in one frame.
      phi = Math.min(Math.PI - 0.2, Math.max(0.2, phi - dy * 0.005));
      place();
    }

    function onPointerUp(event: PointerEvent) {
      if (!dragging) return;
      dragging = false;
      povLookDragging = false;
      if (renderer.domElement.hasPointerCapture(event.pointerId)) {
        renderer.domElement.releasePointerCapture(event.pointerId);
      }
      // A drag that ends over a skill is a drag, not a click. Without this,
      // orbiting the tree selects whatever you happen to release over.
      if (dragged) return;
      const hit = pick(event.clientX, event.clientY);
      onSelectRef.current(hit);
      // In the overview, a click on a skill opens its door: a modal naming
      // it, describing it, and offering its world. POV is not the overview,
      // so the traversal's own interactions are left alone.
      if (hit && !(povState || povFlight || povExit)) {
        if (detailTimer !== null) window.clearTimeout(detailTimer);
        detailTimer = window.setTimeout(() => {
          detailTimer = null;
          setDetailNodeId(hit);
        }, 220);
      } else if (!hit) {
        // Clicking empty space closes an open door.
        setDetailNodeId(null);
      }
    }

    function onDoubleClick(event: MouseEvent) {
      // A double-click is two pointer-ups: the first one scheduled the modal,
      // and this cancels it -- the learner asked to stand beside the skill,
      // not to read its card.
      if (detailTimer !== null) {
        window.clearTimeout(detailTimer);
        detailTimer = null;
      }
      setDetailNodeId(null);
      const hit = pick(event.clientX, event.clientY);
      if (!hit) return;
      // Double-clicking the skill the learner is already standing beside asks to
      // begin it; anywhere else asks to stand there -- POV traversal, the way
      // this design's reference walks its maps. A locked skill or a heading is
      // still worth standing beside: the view is never refused, only the realm.
      if (povState?.id === hit) {
        startDive(hit);
        return;
      }
      flyPovTo(hit);
    }

    function onWheel(event: WheelEvent) {
      event.preventDefault();
      if (povState || povFlight || povExit) return;
      radius = Math.min(
        distance * 2.5,
        Math.max(60, radius + event.deltaY * 0.3),
      );
      place();
    }

    function onWindowKeyDown(event: KeyboardEvent) {
      // Escape closes the open door first; if no door is open, it leaves POV.
      if (event.key === "Escape") {
        if (detailNodeIdRef.current) {
          setDetailNodeId(null);
        } else if (povState || povFlight || povExit) {
          exitPov();
        }
      }
    }

    const canvas = renderer.domElement;
    canvas.style.cursor = "grab";
    // The right button is the POV look-around, not the browser menu.
    canvas.addEventListener("contextmenu", (event) => event.preventDefault());
    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerup", onPointerUp);
    canvas.addEventListener("dblclick", onDoubleClick);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    window.addEventListener("keydown", onWindowKeyDown);

    // ── the loop ──────────────────────────────────────────────────────────
    let frame = 0;
    const started = performance.now();
    let diveTo: {
      id: string;
      at: THREE.Vector3;
      fromPos: THREE.Vector3;
      toPos: THREE.Vector3;
      fromLook: THREE.Vector3;
      fromUp: THREE.Vector3;
      fromFov: number;
      startedAt: number;
    } | null = null;
    const lookAt = new THREE.Vector3();
    let flyingTo: THREE.Vector3 | null = null;
    let flyFrom = new THREE.Vector3();
    let flyProgress = 1;
    let handledNonce = 0;
    let sinceLabels = 0;

    function render() {
      const elapsed = (performance.now() - started) / 1000;
      const matched = matchedRef.current;
      const selected = selectedRef.current;

      // Pulling back out of the skill the learner just left, so the tree opens
      // up around it rather than replacing it.
      if (returnProgress < 1 && returning) {
        const progress = Math.min(
          1,
          (performance.now() - started) / TRANSIT_MS,
        );
        returnProgress = progress;
        const eased = cubicOut(progress);
        radius = DIVE_DISTANCE + (distance - DIVE_DISTANCE) * eased;
        target.set(
          returning.x + (centre.x - returning.x) * eased,
          returning.y + (centre.y - returning.y) * eased,
          returning.z + (centre.z - returning.z) * eased,
        );
        camera.fov = CLOSE_FOV + (WIDE_FOV - CLOSE_FOV) * eased;
        camera.updateProjectionMatrix();
        place();
      }

      // A quest deep-link, a search result and a citation all arrive as a focus
      // request, and all three mean "show me this skill". In POV the request
      // first leaves the traversal, then lands -- a camera that tried to move
      // while standing beside a skill would do neither properly.
      const request = focusRef.current;
      if (request && request.nonce !== handledNonce) {
        handledNonce = request.nonce;
        const point = positions[request.nodeId];
        if (point) {
          if (povState || povExit) {
            pendingFocus = {
              nodeId: request.nodeId,
              point: new THREE.Vector3(point.x, point.y, point.z),
            };
            exitPov();
          } else {
            flyFrom = target.clone();
            flyingTo = new THREE.Vector3(point.x, point.y, point.z);
            // Reduced motion still moves the camera -- refusing to would leave
            // the learner looking at the wrong part of the tree -- it just
            // arrives.
            flyProgress = prefersReducedMotion ? 1 : 0;
          }
        }
      }

      if (flyingTo) {
        flyProgress = Math.min(1, flyProgress + 0.05);
        // Ease out: the end of the flight is where the learner reads the label.
        const eased = 1 - Math.pow(1 - flyProgress, 3);
        target.copy(flyFrom).lerp(flyingTo, eased);
        place();
        if (flyProgress >= 1) flyingTo = null;
      }

      // The dive into a skill's realm. Position, aim and field of view move
      // together over a fixed duration -- a distance-per-frame step would take
      // twice as long from the far side of a deep tree as from the near side,
      // and the hand-off has to land at a predictable moment.
      if (diveTo) {
        const progress = Math.min(
          1,
          (performance.now() - diveTo.startedAt) / TRANSIT_MS,
        );
        const eased = cubicOut(progress);
        camera.position.lerpVectors(diveTo.fromPos, diveTo.toPos, eased);
        lookAt.lerpVectors(diveTo.fromLook, diveTo.at, eased);
        // The realm opens upright, so a dive launched from POV rolls back to
        // the overview's up on the way in.
        camera.up.lerpVectors(diveTo.fromUp, OVERVIEW_UP, eased);
        camera.lookAt(lookAt);
        camera.fov = diveTo.fromFov + (CLOSE_FOV - diveTo.fromFov) * eased;
        camera.updateProjectionMatrix();
        if (progress >= 1) {
          const arrived = diveTo.id;
          diveTo = null;
          onOpenRef.current(arrived);
        }
      }

      // The flight down to stand beside a skill in POV: position, aim and lens
      // move together, landing with the skill's face ahead and the route it
      // opens in view.
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
          const arrived = povFlight;
          povFlight = null;
          povState = {
            id: arrived.id,
            at: arrived.at,
            forward: arrived.forward,
            parentIds: arrived.parentIds,
            childIds: arrived.childIds,
          };
          setPovNodeId(arrived.id);
        }
      }

      // The flight back out of POV to the pose the learner left. The overview
      // orbit state was untouched while they walked, so the way back is exactly
      // the way they were looking.
      if (povExit) {
        const progress = Math.min(
          1,
          (performance.now() - povExit.startedAt) / TRANSIT_MS,
        );
        const eased = cubicOut(progress);
        camera.position.lerpVectors(povExit.fromPos, overviewPos, eased);
        povLook.lerpVectors(povExit.fromLook, overviewLook, eased);
        camera.up.lerpVectors(POV_UP, OVERVIEW_UP, eased);
        camera.lookAt(povLook);
        camera.fov = povExit.fromFov + (WIDE_FOV - povExit.fromFov) * eased;
        camera.updateProjectionMatrix();
        if (progress >= 1) {
          povState = null;
          setPovNodeId(null);
          povExit = null;
          // A focus request that arrived mid-walk lands now that the camera is
          // back on the overview.
          if (pendingFocus) {
            flyFrom = target.clone();
            flyingTo = pendingFocus.point;
            flyProgress = prefersReducedMotion ? 1 : 0;
            pendingFocus = null;
          }
        }
      }

      for (const [id, disc] of discs) {
        const material = disc.material as THREE.MeshBasicMaterial;
        material.opacity = !matched || matched.has(id) ? 1 : UNMATCHED_OPACITY;

        const isSelected = id === selected;
        const pulse =
          isSelected && !prefersReducedMotion
            ? 1.22 + Math.sin(elapsed * 3) * 0.06
            : isSelected
              ? 1.25
              : 1;
        disc.scale.setScalar(pulse);

        const ring = rings.get(id)!;
        ring.visible = isSelected;
        if (isSelected) {
          ring.scale.setScalar(pulse);
        }
      }

      renderer.render(scene, camera);

      // Labels are DOM, so they update on a slower clock than the scene --
      // sixty React renders a second would cost more than the tree does.
      sinceLabels += 1;
      if (sinceLabels >= 3) {
        sinceLabels = 0;
        const rect = renderer.domElement.getBoundingClientRect();
        const candidates: (Label & { depth: number })[] = [];
        for (const [id, disc] of discs) {
          // Projected from a point below the coin rather than from its centre,
          // so the gap between disc and title is a fixed distance in the SCENE.
          // A fixed pixel offset would sit clear at one zoom and print across
          // the coin at another.
          projected
            .copy(disc.position)
            .setY(disc.position.y - DISC_RADIUS * 2.1)
            .project(camera);
          candidates.push({
            id,
            title: lookup.get(id)?.title ?? "",
            x: ((projected.x + 1) / 2) * rect.width,
            y: ((1 - projected.y) / 2) * rect.height,
            // Nearer skills carry slightly larger type, which is most of what
            // makes a flat tree read as having depth at all.
            size: Math.max(9.5, Math.min(13, 15 - projected.z * 6)),
            depth: projected.z,
            visible: projected.z <= 1 && (!matched || matched.has(id)),
          });
        }

        // Two titles printed over each other are worse than one title: the
        // overlap is unreadable AND it hides which skill each belongs to.
        // Nearest wins, which is also the one the learner is looking at.
        candidates.sort((a, b) => a.depth - b.depth);
        const taken: { x: number; y: number; half: number }[] = [];
        for (const label of candidates) {
          if (label.visible) {
            const half = (label.title.length * label.size * 0.5) / 2;
            const clash = taken.some(
              (box) =>
                Math.abs(box.y - label.y) < label.size * 1.3 &&
                Math.abs(box.x - label.x) < box.half + half,
            );
            if (clash) {
              label.visible = false;
            } else {
              taken.push({ x: label.x, y: label.y, half });
            }
          }
        }
        setLabels(candidates.map(({ depth: _depth, ...label }) => label));

        // POV neighbour cards: projected the same way as the titles, sitting
        // just in front of each neighbour's disc. Clamped to the panel so a
        // card at the edge is readable rather than half off it.
        if (povState) {
          const cards: PovCard[] = [];
          const pushCard = (neighbourId: string, badge: "parent" | "child") => {
            const neighbour = lookup.get(neighbourId);
            const point = positions[neighbourId];
            if (!neighbour || !point) return;
            projected
              .copy(point)
              .setZ(point.z + DISC_THICKNESS + 6)
              .project(camera);
            if (projected.z > 1) return;
            const style = graphNodeStyle(neighbour);
            const locked =
              neighbour.assessable && neighbour.progress.state === "locked";
            const x = Math.min(
              Math.max(
                ((projected.x + 1) / 2) * rect.width,
                POV_CARD_WIDTH / 2 + 4,
              ),
              rect.width - POV_CARD_WIDTH / 2 - 4,
            );
            const y = Math.min(
              Math.max(((1 - projected.y) / 2) * rect.height - 8, 64),
              rect.height - 84,
            );
            const progress = neighbour.assessable
              ? `Level ${neighbour.progress.level}/5 · Mastery ${Math.round(neighbour.progress.mastery * 100)}% · Proficiency ${Math.round(neighbour.progress.proficiency * 100)}%`
              : "Section heading";
            cards.push({
              id: neighbour.id,
              title: neighbour.title,
              badge,
              accent: style.accent,
              label: style.label,
              progress,
              locked,
              structural: !neighbour.assessable,
              needs: locked
                ? neighbour.blocked_by
                    .map((blocker) => blocker.title)
                    .slice(0, 2)
                    .join(", ")
                : "",
              x,
              y,
              visible: true,
            });
          };
          for (const parentId of povState.parentIds)
            pushCard(parentId, "parent");
          for (const childId of povState.childIds) pushCard(childId, "child");
          setPovCards(cards);
        } else {
          setPovCards((previous) => (previous.length > 0 ? [] : previous));
        }
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
      canvas.removeEventListener("wheel", onWheel);
      window.removeEventListener("keydown", onWindowKeyDown);
      povActionsRef.current = null;
      if (detailTimer !== null) window.clearTimeout(detailTimer);
      discGeometry.dispose();
      ringGeometry.dispose();
      for (const disc of discs.values())
        (disc.material as THREE.Material).dispose();
      for (const ring of rings.values())
        (ring.material as THREE.Material).dispose();
      renderer.dispose();
      if (canvas.parentNode === mount) mount.removeChild(canvas);
    };
  }, [shapeKey, positions, prefersReducedMotion]);

  // ── the keyboard path ───────────────────────────────────────────────────
  // A WebGL canvas is one focusable element with no children, so a list beside
  // it is what makes the tree reachable without a mouse.
  const ordered = useMemo(
    () =>
      [...snapshot.nodes].sort(
        (a, b) => a.depth - b.depth || a.title.localeCompare(b.title),
      ),
    [snapshot.nodes],
  );

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLLIElement>, node: GraphNode) => {
      if (event.key === "Enter" && selectedNodeId === node.id) {
        event.preventDefault();
        onOpenLesson(node.id);
      } else if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onSelect(node.id);
      }
    },
    [onOpenLesson, onSelect, selectedNodeId],
  );

  // The skill being stood beside in POV, for the toolbar's enter affordance.
  const povNode = useMemo(
    () =>
      povNodeId
        ? (snapshot.nodes.find((entry) => entry.id === povNodeId) ?? null)
        : null,
    [povNodeId, snapshot.nodes],
  );
  const povEnterable = povNode ? canOpenLesson(povNode) : false;

  // The skill whose door is open. Keyed off the id rather than the node so a
  // refresh that swaps node objects does not drop an open modal.
  const detailNode = useMemo(
    () =>
      detailNodeId
        ? (snapshot.nodes.find((entry) => entry.id === detailNodeId) ?? null)
        : null,
    [detailNodeId, snapshot.nodes],
  );
  const detailEnterable = detailNode ? canOpenLesson(detailNode) : false;

  return (
    <div className="relative h-full overflow-hidden bg-graph-ground">
      <div ref={mountRef} className="absolute inset-0" aria-hidden="true" />

      {/* Titles, projected. Pointer-events off so they never eat a click meant
          for the skill underneath them. */}
      <div
        className="pointer-events-none absolute inset-0 overflow-hidden"
        aria-hidden="true"
      >
        {labels.map((label) => (
          <span
            key={label.id}
            className={`absolute -translate-x-1/2 whitespace-nowrap font-display font-semibold tracking-tight ${
              label.id === selectedNodeId
                ? "text-graph-ink"
                : "text-graph-ink-quiet"
            }`}
            style={{
              left: label.x,
              top: label.y,
              fontSize: `${label.size}px`,
              opacity: label.visible ? 1 : 0,
            }}
          >
            {label.title}
          </span>
        ))}
      </div>

      {/* POV traversal: the neighbours of the skill being stood beside, as
          floating cards in the world. Clicking an unlocked card walks to it.
          A locked neighbour remains visible with its progress and blocker, but
          the camera stays put and the notice explains what must be completed. */}
      {povNodeId && (
        <div className="pointer-events-none absolute inset-0 overflow-hidden">
          {povCards.map((card) => (
            <button
              key={card.id}
              type="button"
              onClick={() => {
                // flyPovTo itself refuses to re-target mid-flight; the centre
                // card is the skill being stood beside, whose action is Enter.
                if (card.id !== povNodeId)
                  povActionsRef.current?.flyTo(card.id);
              }}
              className={`pointer-events-auto absolute -translate-x-1/2 -translate-y-full rounded-lg border bg-graph-surface/95 p-2.5 text-left shadow-lg backdrop-blur-sm transition hover:bg-graph-raised ${FOCUS_RING}`}
              style={{
                left: card.x,
                top: card.y,
                width: POV_CARD_WIDTH,
                borderColor: card.accent,
                opacity: card.visible ? 1 : 0,
              }}
              aria-label={`${card.badge === "parent" ? "Prerequisite" : "Unlocks"} ${card.title}. ${card.locked ? "Locked" : card.structural ? "Section heading" : card.label}.`}
            >
              <span className="block text-[9px] font-bold uppercase tracking-wider text-graph-ink-quiet">
                {card.badge === "parent" ? "▲ Prerequisite" : "▼ Unlocks"}
              </span>
              <span className="mt-0.5 block truncate font-display text-xs font-semibold text-graph-ink">
                {card.locked ? `\u{1F512} ${card.title}` : card.title}
              </span>
              <span className="mt-1 block truncate text-[10px] text-graph-ink-quiet">
                {card.structural
                  ? "Section heading"
                  : card.locked
                    ? `Locked — needs ${card.needs || "prerequisites"}`
                    : card.label}
              </span>
              <span className="mt-1 block text-[10px] leading-snug text-graph-ink-quiet">
                {card.progress}
              </span>
            </button>
          ))}
        </div>
      )}

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
          {traversalNotice.targetTitle && traversalNotice.currentTitle && (
            <p className="mt-1 text-[10px] text-graph-learning">
              Current skill: {traversalNotice.currentTitle}
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

      {hovered && (
        <div className="pointer-events-none absolute left-3 top-3 max-w-xs rounded-lg border border-graph-line bg-graph-surface p-3 shadow-lg">
          <p className="font-display text-sm font-semibold text-graph-ink">
            {hovered.title}
          </p>
          <p className="mt-0.5 text-[11px] text-graph-ink-quiet">
            {graphNodeStyle(hovered).label}
          </p>
          {hovered.summary && (
            <p className="mt-1.5 text-[11px] leading-snug text-graph-ink-quiet">
              {hovered.summary}
            </p>
          )}
        </div>
      )}

      {/* The door: what a single click on a skill opens. One click names the
          skill and offers its world; two clicks stand beside it instead, so
          the modal is summoned by a timer the double-click cancels. A locked
          skill or a heading still gets its card -- refusing to enter is not
          refusing to explain -- but the door stays shut. */}
      {detailNode && (
        <div
          className="absolute inset-0 z-20 flex items-center justify-center bg-graph-ground/70 p-4"
          onClick={() => setDetailNodeId(null)}
          role="presentation"
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="skill-detail-title"
            className="w-full max-w-sm rounded-xl border border-graph-line bg-graph-surface p-5 shadow-lg"
            onClick={(event) => event.stopPropagation()}
          >
            <p className="text-[10px] font-semibold uppercase tracking-wider text-graph-learning">
              {graphNodeStyle(detailNode).label}
            </p>
            <h3
              id="skill-detail-title"
              className="mt-1 font-display text-base font-semibold text-graph-ink"
            >
              {detailNode.title}
            </h3>
            <p className="mt-2 text-xs leading-relaxed text-graph-ink-quiet">
              {detailNode.summary}
            </p>
            {detailNode.assessable &&
              detailNode.progress.state === "locked" && (
                <p className="mt-2 text-[11px] text-graph-ink-quiet">
                  Blocked by{" "}
                  {detailNode.blocked_by
                    .map((blocker) => blocker.title)
                    .join(", ")}
                </p>
              )}
            <div className="mt-5 flex gap-2">
              <button
                type="button"
                onClick={() => setDetailNodeId(null)}
                className={BUTTON_SECONDARY}
              >
                Close
              </button>
              <button
                type="button"
                disabled={!detailEnterable}
                title={
                  detailNode && !detailEnterable
                    ? detailNode.assessable
                      ? `Blocked by ${detailNode.blocked_by.map((blocker) => blocker.title).join(", ")}`
                      : "A section heading owns no skill to drill"
                    : undefined
                }
                onClick={() => {
                  setDetailNodeId(null);
                  onOpenLesson(detailNode.id);
                }}
                className="flex-1 rounded-md bg-graph-available px-3 py-1.5 text-xs font-bold text-graph-ground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-35"
              >
                Enter World
              </button>
            </div>
          </div>
        </div>
      )}

      {/* The POV toolbar: the two deliberate actions of walking -- leave, and
          enter the skill being stood beside. Gold for the enter, the one thing
          that is a reward. */}
      {povNodeId && (
        <div className="absolute bottom-4 left-1/2 z-10 flex -translate-x-1/2 items-center gap-2 rounded-lg border border-graph-line bg-graph-surface/90 p-1.5 shadow-lg backdrop-blur-sm">
          <button
            type="button"
            onClick={() => povActionsRef.current?.exit()}
            className="rounded-md border border-graph-line bg-graph-raised px-3 py-1.5 text-xs font-semibold text-graph-ink transition hover:bg-graph-surface"
          >
            ← Back to the tree
          </button>
          <button
            type="button"
            disabled={!povEnterable}
            title={
              povNode && !povEnterable
                ? povNode.assessable
                  ? `Blocked by ${povNode.blocked_by.map((blocker) => blocker.title).join(", ")}`
                  : "A section heading owns no skill to drill"
                : undefined
            }
            onClick={() => povActionsRef.current?.enter()}
            className="rounded-md bg-graph-available px-3 py-1.5 text-xs font-bold text-graph-ground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-35"
          >
            Enter this skill
          </button>
        </div>
      )}

      <p className="pointer-events-none absolute bottom-3 left-3 text-[11px] text-graph-ink-quiet">
        {povNodeId
          ? "Click a card to walk the tree · Enter to open its world · Esc to return"
          : "Drag to orbit · scroll to zoom · double-click a skill to stand beside it"}
      </p>

      <ul className="sr-only">
        {ordered.map((node) => (
          <li
            key={node.id}
            tabIndex={0}
            aria-label={nodeAriaLabel(node)}
            aria-current={selectedNodeId === node.id}
            className={FOCUS_RING}
            onKeyDown={(event) => onKeyDown(event, node)}
            onFocus={() => onSelect(node.id)}
          >
            {node.title}
          </li>
        ))}
      </ul>
    </div>
  );
}
