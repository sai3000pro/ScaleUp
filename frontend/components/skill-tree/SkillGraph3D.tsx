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
 * The application is light — a warm near-white page — so the canvas is too. A
 * dark viewport dropped into it reads as a hole cut in the page rather than as
 * part of it, whatever is drawn inside.
 *
 * Skills are flat discs facing the camera, not shaded spheres. A lit sphere
 * turns every accent into a gradient running from a washed-out highlight to a
 * brown terminator, which destroys the one job those five colours have: five
 * distinguishable states, each holding contrast against the page. Unlit discs
 * render the palette exactly as `nodeState.ts` declares it.
 *
 * Titles are HTML positioned over the canvas rather than drawn in the scene.
 * Text in WebGL means either a texture atlas that goes soft under the camera or
 * geometry that costs more than the tree does; projecting a DOM label costs a
 * matrix multiply per skill and gets the application's own typeface, kerning and
 * subpixel rendering for nothing.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

import { graphShapeKey } from "@/lib/layout";
import { framingCentre, framingDistance, layoutGraph3D } from "@/lib/layout3d";
import { canOpenLesson } from "@/lib/lesson";
import { nodeAriaLabel, nodeStyle } from "@/lib/nodeState";
import type { GraphNode, GraphSnapshot } from "@/lib/types";
import { FOCUS_RING } from "@/lib/ui";
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

/** From the `@theme` block in app/globals.css. Change one, change both. */
const PAGE = 0xfdfbfb;
const EDGE = 0xb3a5a9;
/** A prerequisite the learner has already worked: the path behind them. */
const EDGE_WALKED = 0x1f7a54;
/** The edge into a skill they could start right now. */
const EDGE_NEXT = 0xb8496f;

const DISC_RADIUS = 8.5;
const DISC_THICKNESS = 1.4;
const UNMATCHED_OPACITY = 0.14;
const PICK_THRESHOLD = 16;

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

// @spec UI-GRAPH3D-001, UI-GRAPH3D-004, UI-GRAPH3D-005, UI-GRAPH3D-006, UI-GRAPH3D-007, UI-GRAPH3D-008
// @spec UI-GRAPH3D-013, UI-GRAPH3D-014, UI-GRAPH3D-015, UI-GRAPH3D-016
export function SkillGraph3D({ snapshot, selectedNodeId, onSelect, onOpenLesson, matchedNodeIds, arriveFrom }: Props) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const prefersReducedMotion = usePrefersReducedMotion();
  const [hovered, setHovered] = useState<GraphNode | null>(null);
  const [labels, setLabels] = useState<Label[]>([]);
  const hoveredIdRef = useRef<string | null>(null);

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
    scene.background = new THREE.Color(PAGE);

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
    const discGeometry = new THREE.CylinderGeometry(DISC_RADIUS, DISC_RADIUS, DISC_THICKNESS, 48);
    const ringGeometry = new THREE.TorusGeometry(DISC_RADIUS + 2.2, 0.8, 8, 48);
    const discs = new Map<string, THREE.Mesh>();
    const rings = new Map<string, THREE.Mesh>();

    for (const node of nodes) {
      const point = positions[node.id];
      if (point) {
        const accent = new THREE.Color(nodeStyle(node).accent);
        // Basic, not standard: unlit, so the accent lands exactly as declared.
        const material = new THREE.MeshBasicMaterial({ color: accent, transparent: true });
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
          new THREE.MeshBasicMaterial({ color: new THREE.Color(EDGE_NEXT), transparent: true }),
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
      const prereq = lookup.get(edge.source);
      const target = lookup.get(edge.target);
      if (from && to && prereq && target) {
        // Three weights, because an edge means three different things. Behind
        // the learner: ground they have covered. Immediately ahead: the way on.
        // Beyond that: structure they cannot use yet.
        const walked = prereq.progress.state === "mastered" || prereq.progress.state === "learning";
        const next = walked && target.progress.state === "available";
        const geometry = new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(from.x, from.y, from.z),
          new THREE.Vector3(to.x, to.y, to.z),
        ]);
        const material = new THREE.LineBasicMaterial({
          color: new THREE.Color(next ? EDGE_NEXT : walked ? EDGE_WALKED : EDGE),
          transparent: true,
          opacity: next ? 1 : walked ? 0.85 : 0.75,
        });
        scene.add(new THREE.Line(geometry, material));
      }
    }

    // ── orbit ─────────────────────────────────────────────────────────────
    // Starts nearly face-on, so the first thing the learner sees is the tree
    // rather than a perspective puzzle.
    let theta = Math.PI / 2;
    let phi = 1.42;
    const returning = !prefersReducedMotion && arriveFromRef.current ? positions[arriveFromRef.current] : undefined;
    let radius = returning ? DIVE_DISTANCE : distance;
    let returnProgress = returning ? 0 : 1;
    let dragging = false;
    let dragged = false;
    let lastX = 0;
    let lastY = 0;

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
      renderer.domElement.setPointerCapture(event.pointerId);
    }

    function onPointerMove(event: PointerEvent) {
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
      dragging = false;
      renderer.domElement.releasePointerCapture(event.pointerId);
      // A drag that ends over a skill is a drag, not a click. Without this,
      // orbiting the tree selects whatever you happen to release over.
      if (dragged) return;
      onSelectRef.current(pick(event.clientX, event.clientY));
    }

    function onDoubleClick(event: MouseEvent) {
      const hit = pick(event.clientX, event.clientY);
      if (!hit) return;
      const node = lookup.get(hit);
      // A locked skill or a heading has no realm to dive into. Select it instead
      // and let the inspector say why -- flying at something and then bouncing
      // off it is worse than never having moved.
      if (!canOpenLesson(node)) {
        onSelectRef.current(hit);
        return;
      }
      if (prefersReducedMotion) {
        onOpenRef.current(hit);
        return;
      }
      const point = positions[hit];
      if (!point) return;
      const at = new THREE.Vector3(point.x, point.y, point.z);
      // Straight down the line the camera is already on, so the skill does not
      // slide sideways on the way in.
      const approach = camera.position.clone().sub(at).normalize().multiplyScalar(DIVE_DISTANCE).add(at);
      diveTo = {
        id: hit,
        at,
        fromPos: camera.position.clone(),
        toPos: approach,
        fromLook: target.clone(),
        fromFov: camera.fov,
        startedAt: performance.now(),
      };
    }

    function onWheel(event: WheelEvent) {
      event.preventDefault();
      radius = Math.min(distance * 2.5, Math.max(60, radius + event.deltaY * 0.3));
      place();
    }

    const canvas = renderer.domElement;
    canvas.style.cursor = "grab";
    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerup", onPointerUp);
    canvas.addEventListener("dblclick", onDoubleClick);
    canvas.addEventListener("wheel", onWheel, { passive: false });

    // ── the loop ──────────────────────────────────────────────────────────
    let frame = 0;
    const started = performance.now();
    let diveTo: {
      id: string;
      at: THREE.Vector3;
      fromPos: THREE.Vector3;
      toPos: THREE.Vector3;
      fromLook: THREE.Vector3;
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
        const progress = Math.min(1, (performance.now() - started) / TRANSIT_MS);
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
      // request, and all three mean "show me this skill".
      const request = focusRef.current;
      if (request && request.nonce !== handledNonce) {
        handledNonce = request.nonce;
        const point = positions[request.nodeId];
        if (point) {
          flyFrom = target.clone();
          flyingTo = new THREE.Vector3(point.x, point.y, point.z);
          // Reduced motion still moves the camera -- refusing to would leave the
          // learner looking at the wrong part of the tree -- it just arrives.
          flyProgress = prefersReducedMotion ? 1 : 0;
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
        const progress = Math.min(1, (performance.now() - diveTo.startedAt) / TRANSIT_MS);
        const eased = cubicOut(progress);
        camera.position.lerpVectors(diveTo.fromPos, diveTo.toPos, eased);
        lookAt.lerpVectors(diveTo.fromLook, diveTo.at, eased);
        camera.lookAt(lookAt);
        camera.fov = diveTo.fromFov + (CLOSE_FOV - diveTo.fromFov) * eased;
        camera.updateProjectionMatrix();
        if (progress >= 1) {
          const arrived = diveTo.id;
          diveTo = null;
          onOpenRef.current(arrived);
        }
      }

      for (const [id, disc] of discs) {
        const material = disc.material as THREE.MeshBasicMaterial;
        material.opacity = !matched || matched.has(id) ? 1 : UNMATCHED_OPACITY;

        const isSelected = id === selected;
        const pulse = isSelected && !prefersReducedMotion ? 1.22 + Math.sin(elapsed * 3) * 0.06 : isSelected ? 1.25 : 1;
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
          projected.copy(disc.position).setY(disc.position.y - DISC_RADIUS * 2.1).project(camera);
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
              (box) => Math.abs(box.y - label.y) < label.size * 1.3 && Math.abs(box.x - label.x) < box.half + half,
            );
            if (clash) {
              label.visible = false;
            } else {
              taken.push({ x: label.x, y: label.y, half });
            }
          }
        }
        setLabels(candidates.map(({ depth: _depth, ...label }) => label));
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
      discGeometry.dispose();
      ringGeometry.dispose();
      for (const disc of discs.values()) (disc.material as THREE.Material).dispose();
      for (const ring of rings.values()) (ring.material as THREE.Material).dispose();
      renderer.dispose();
      if (canvas.parentNode === mount) mount.removeChild(canvas);
    };
  }, [shapeKey, positions, prefersReducedMotion]);

  // ── the keyboard path ───────────────────────────────────────────────────
  // A WebGL canvas is one focusable element with no children, so a list beside
  // it is what makes the tree reachable without a mouse.
  const ordered = useMemo(
    () => [...snapshot.nodes].sort((a, b) => a.depth - b.depth || a.title.localeCompare(b.title)),
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

  // Fills the frame the page draws rather than drawing a second one: the
  // container owns the chrome and the size, and this fills it.
  //
  // @spec UI-PAGE-006
  return (
    <div className="relative h-full w-full overflow-hidden">
      <div ref={mountRef} className="absolute inset-0" aria-hidden="true" />

      {/* Titles, projected. Pointer-events off so they never eat a click meant
          for the skill underneath them. */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
        {labels.map((label) => (
          <span
            key={label.id}
            className={`absolute -translate-x-1/2 whitespace-nowrap font-display font-semibold tracking-tight ${
              label.id === selectedNodeId ? "text-slate-50" : "text-slate-300"
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

      {hovered && (
        <div className="pointer-events-none absolute left-3 top-3 max-w-xs rounded-lg border border-slate-700 bg-slate-900/95 p-3 shadow-sm">
          <p className="font-display text-sm font-semibold text-slate-100">{hovered.title}</p>
          <p className="mt-0.5 text-[11px] text-slate-400">{nodeStyle(hovered).label}</p>
          {hovered.summary && <p className="mt-1.5 text-[11px] leading-snug text-slate-400">{hovered.summary}</p>}
        </div>
      )}

      <p className="pointer-events-none absolute bottom-3 left-3 text-[11px] text-slate-400">
        Drag to orbit · scroll to zoom · double-click a skill to start it
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
