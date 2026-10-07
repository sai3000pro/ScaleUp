"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type {
  CurriculumCandidate,
  CurriculumProposal,
  CurriculumVersion,
} from "@/lib/types";
import {
  BUTTON_PRIMARY,
  BUTTON_SECONDARY,
  CARD,
  FOCUS_RING,
  INPUT,
  MUTED,
} from "@/lib/ui";

function safeUrl(value: string): string | null {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:"
      ? parsed.href
      : null;
  } catch {
    return null;
  }
}

interface CampaignPhase {
  label: string;
  description: string;
}

function campaignPhases(level: string, format: string): CampaignPhase[] {
  const practiceLabel =
    format === "papers"
      ? "Research synthesis"
      : format === "textbook"
        ? "Chapter mastery"
        : format === "course"
          ? "Lesson practice"
          : "Applied practice";
  const practiceDescription =
    format === "papers"
      ? "Compare evidence and explain the field's open questions."
      : format === "textbook"
        ? "Use worked examples to turn concepts into durable skills."
        : format === "course"
          ? "Apply each lesson through focused drills and checkpoints."
          : "Use examples and drills to transfer knowledge into action.";

  if (level === "advanced") {
    return [
      {
        label: "Theory & trade-offs",
        description:
          "Build the mental models needed to reason about difficult choices.",
      },
      {
        label: "Research methods",
        description:
          "Connect techniques to evidence, assumptions, and limitations.",
      },
      { label: practiceLabel, description: practiceDescription },
    ];
  }
  if (level === "intermediate") {
    return [
      {
        label: "Core models",
        description:
          "Consolidate the concepts that support the rest of the tree.",
      },
      {
        label: "Applied techniques",
        description: "Unlock methods by demonstrating their prerequisites.",
      },
      { label: practiceLabel, description: practiceDescription },
    ];
  }
  return [
    {
      label: "Foundations",
      description:
        "Learn the vocabulary and first principles that open the tree.",
    },
    {
      label: "Core skills",
      description: "Stack related skills and follow their prerequisite links.",
    },
    { label: practiceLabel, description: practiceDescription },
  ];
}

export function CurriculumPlanner({
  courseId,
  initialGoal = "",
  onComplete,
}: {
  courseId: string;
  initialGoal?: string;
  onComplete: () => void;
}) {
  const [goal, setGoal] = useState(initialGoal);
  const [targetOutcome, setTargetOutcome] = useState("");
  const [priorKnowledge, setPriorKnowledge] = useState("");
  const [applicationContext, setApplicationContext] = useState("");
  const [level, setLevel] = useState<"beginner" | "intermediate" | "advanced">(
    "beginner",
  );
  const [weeklyMinutes, setWeeklyMinutes] = useState(120);
  const [format, setFormat] = useState<
    "mixed" | "textbook" | "course" | "papers"
  >("mixed");
  const [proposal, setProposal] = useState<CurriculumProposal | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [policyAcknowledged, setPolicyAcknowledged] = useState(false);
  const [busy, setBusy] = useState<
    "search" | "approve" | "ingest" | "policy" | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [versions, setVersions] = useState<CurriculumVersion[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(
    null,
  );
  const [candidates, setCandidates] = useState<CurriculumCandidate[]>([]);
  const [reviewBusyId, setReviewBusyId] = useState<string | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [reviewNotice, setReviewNotice] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .listCurriculumVersions(courseId)
      .then((items) => {
        if (live) {
          setVersions(items);
          setSelectedVersionId((current) => current ?? items[0]?.id ?? null);
        }
      })
      .catch((caught: unknown) => {
        if (live)
          setReviewError(
            caught instanceof Error
              ? caught.message
              : "Could not load curriculum versions.",
          );
      });
    return () => {
      live = false;
    };
  }, [courseId]);

  useEffect(() => {
    if (!selectedVersionId) {
      setCandidates([]);
      return;
    }
    let live = true;
    api
      .listCurriculumCandidates(courseId, selectedVersionId)
      .then((items) => {
        if (live) setCandidates(items);
      })
      .catch((caught: unknown) => {
        if (live)
          setReviewError(
            caught instanceof Error
              ? caught.message
              : "Could not load curriculum candidates.",
          );
      });
    return () => {
      live = false;
    };
  }, [courseId, selectedVersionId]);

  useEffect(() => {
    let live = true;
    api
      .getLatestCurriculumProposal(courseId)
      .then((latest) => {
        if (live) {
          setGoal(latest.goal);
          setTargetOutcome(latest.target_outcome);
          setPriorKnowledge(latest.prior_knowledge);
          setApplicationContext(latest.application_context);
          setLevel(latest.learner_level as typeof level);
          setWeeklyMinutes(latest.weekly_minutes);
          setFormat(latest.format_preference as typeof format);
          setProposal(latest);
          const restoredIds =
            latest.status === "draft"
              ? latest.sources.map((source) => source.id)
              : latest.sources
                  .filter((source) => source.selected)
                  .map((source) => source.id);
          setSelectedIds(new Set(restoredIds));
          setPolicyAcknowledged(
            latest.sources.some(
              (source) => source.selected && source.policy_acknowledged,
            ),
          );
        }
      })
      .catch(() => {
        // A new course has no proposal yet; the empty planner is the expected state.
      });
    return () => {
      live = false;
    };
  }, [courseId]);

  async function search(event: React.FormEvent) {
    event.preventDefault();
    const wanted = goal.trim();
    if (!wanted || busy) return;

    setBusy("search");
    setError(null);
    setNotice(null);
    try {
      const next = await api.createCurriculumProposal(
        courseId,
        wanted,
        level,
        weeklyMinutes,
        format,
        8,
        targetOutcome.trim(),
        priorKnowledge.trim(),
        applicationContext.trim(),
      );
      setProposal(next);
      setSelectedIds(new Set(next.sources.map((source) => source.id)));
      setPolicyAcknowledged(false);
      setNotice(
        "Review these sources before approving them. Approved sources become the evidence for your RPG skill tree.",
      );
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(null);
    }
  }

  function toggleSource(sourceId: string): void {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(sourceId)) {
        next.delete(sourceId);
      } else {
        next.add(sourceId);
      }
      return next;
    });
  }

  async function checkPolicy(sourceId: string): Promise<void> {
    if (!proposal || busy) return;

    setBusy("policy");
    setError(null);
    setNotice(null);
    try {
      const next = await api.checkCurriculumSourcePolicy(
        courseId,
        proposal.id,
        sourceId,
      );
      setProposal(next);
      const checked = next.sources.find((source) => source.id === sourceId);
      if (checked?.policy_status === "blocked") {
        setSelectedIds((current) => {
          const updated = new Set(current);
          updated.delete(sourceId);
          return updated;
        });
      }
      setNotice(
        "Policy check complete. Robots status can block approval; a license declaration still requires your review.",
      );
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function approve(): Promise<void> {
    if (!proposal || selectedIds.size === 0 || busy) return;

    setBusy("approve");
    setError(null);
    setNotice(null);
    try {
      const next = await api.approveCurriculumSources(
        courseId,
        proposal.id,
        Array.from(selectedIds),
        policyAcknowledged,
      );
      setProposal(next);
      setNotice(
        `${selectedIds.size} source${selectedIds.size === 1 ? "" : "s"} approved. Start ingestion when ready.`,
      );
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function ingest(): Promise<void> {
    if (!proposal || proposal.status !== "approved" || busy) return;

    setBusy("ingest");
    setError(null);
    setNotice(null);
    try {
      const result = await api.ingestCurriculumSources(courseId, proposal.id);
      const failed = result.accepted.filter(
        (item) => item.status === "failed",
      ).length;
      setNotice(
        failed > 0
          ? `${result.accepted.length - failed} source${result.accepted.length - failed === 1 ? "" : "s"} queued; ${failed} could not be fetched.`
          : `${result.accepted.length} approved source${result.accepted.length === 1 ? "" : "s"} queued. Your skill tree will build as the campaign ingests them.`,
      );
      onComplete();
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const phases = proposal
    ? campaignPhases(proposal.learner_level, proposal.format_preference)
    : [];
  const selectedSourceCount =
    proposal?.sources.filter((source) => selectedIds.has(source.id)).length ??
    0;
  const selectedDomainCount = new Set(
    proposal?.sources
      .filter((source) => selectedIds.has(source.id))
      .map((source) => source.domain),
  ).size;

  async function reviewCandidate(
    candidateId: string,
    decision: "accepted" | "rejected" | "ambiguous",
  ): Promise<void> {
    if (!selectedVersionId || reviewBusyId) return;
    setReviewBusyId(candidateId);
    setReviewError(null);
    setReviewNotice(null);
    try {
      const updated = await api.reviewCurriculumCandidate(
        courseId,
        selectedVersionId,
        candidateId,
        decision,
      );
      setCandidates((current) =>
        current.map((candidate) =>
          candidate.id === candidateId ? updated : candidate,
        ),
      );
      setReviewNotice(`Candidate marked ${decision}.`);
    } catch (caught) {
      setReviewError(
        caught instanceof Error ? caught.message : "Could not save the review.",
      );
    } finally {
      setReviewBusyId(null);
    }
  }

  async function publishReviewedVersion(): Promise<void> {
    if (!selectedVersionId || reviewBusyId) return;
    setReviewBusyId("publish");
    setReviewError(null);
    setReviewNotice(null);
    try {
      await api.publishCurriculumVersion(courseId, selectedVersionId);
      const refreshed = await api.listCurriculumVersions(courseId);
      setVersions(refreshed);
      setReviewNotice(
        "Reviewed curriculum published. The learner skill graph has been updated.",
      );
      onComplete();
    } catch (caught) {
      setReviewError(
        caught instanceof Error
          ? caught.message
          : "Could not publish this curriculum.",
      );
    } finally {
      setReviewBusyId(null);
    }
  }

  const reviewPending = candidates.some(
    (candidate) =>
      candidate.status === "draft" || candidate.status === "ambiguous",
  );
  const selectedVersion =
    versions.find((version) => version.id === selectedVersionId) ?? null;

  return (
    <section className={CARD} aria-labelledby="curriculum-planner-heading">
      <h2
        id="curriculum-planner-heading"
        className="font-display text-sm font-semibold"
      >
        Plan from the web
      </h2>
      <p className={`mt-1 text-xs ${MUTED}`}>
        Describe what you want to master. Review and approve sources before they
        become evidence for this RPG skill tree.
      </p>

      <form onSubmit={search} className="mt-3 space-y-2">
        <div className="flex gap-2">
          <label htmlFor="curriculumGoal" className="sr-only">
            Learning goal
          </label>
          <input
            id="curriculumGoal"
            className={`${INPUT} min-w-0 flex-1`}
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
            placeholder="e.g. reinforcement learning for robotics"
            maxLength={500}
            disabled={busy !== null}
          />
          <button
            type="submit"
            disabled={busy !== null || !goal.trim()}
            className={`${BUTTON_PRIMARY} shrink-0 px-3`}
          >
            {busy === "search" ? "Searching…" : "Propose"}
          </button>
        </div>
        <label htmlFor="campaignOutcome" className={`block text-tiny ${MUTED}`}>
          Victory condition <span className="text-slate-500">(optional)</span>
          <input
            id="campaignOutcome"
            className={`${INPUT} mt-1`}
            value={targetOutcome}
            onChange={(event) => setTargetOutcome(event.target.value)}
            placeholder="e.g. build and evaluate a robot navigation policy"
            maxLength={300}
            disabled={busy !== null}
          />
        </label>
        <div className="grid gap-2 sm:grid-cols-2">
          <label className={`block text-tiny ${MUTED}`}>
            What do you already know?{" "}
            <span className="text-slate-500">(optional)</span>
            <textarea
              className={`${INPUT} mt-1 min-h-16 resize-y`}
              value={priorKnowledge}
              onChange={(event) => setPriorKnowledge(event.target.value)}
              placeholder="e.g. Python, basic algebra, and a first ML course"
              maxLength={300}
              disabled={busy !== null}
            />
          </label>
          <label className={`block text-tiny ${MUTED}`}>
            Where will you use it?{" "}
            <span className="text-slate-500">(optional)</span>
            <textarea
              className={`${INPUT} mt-1 min-h-16 resize-y`}
              value={applicationContext}
              onChange={(event) => setApplicationContext(event.target.value)}
              placeholder="e.g. a robot navigation project or research prototype"
              maxLength={300}
              disabled={busy !== null}
            />
          </label>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <label className={`text-tiny ${MUTED}`}>
            Level
            <select
              value={level}
              onChange={(event) => setLevel(event.target.value as typeof level)}
              disabled={busy !== null}
              className={`${INPUT} mt-1 px-2 py-1.5 text-xs`}
            >
              <option value="beginner">Beginner</option>
              <option value="intermediate">Intermediate</option>
              <option value="advanced">Advanced</option>
            </select>
          </label>
          <label className={`text-tiny ${MUTED}`}>
            Minutes / week
            <select
              value={weeklyMinutes}
              onChange={(event) => setWeeklyMinutes(Number(event.target.value))}
              disabled={busy !== null}
              className={`${INPUT} mt-1 px-2 py-1.5 text-xs`}
            >
              <option value={30}>30</option>
              <option value={120}>120</option>
              <option value={300}>300</option>
              <option value={600}>600</option>
            </select>
          </label>
          <label className={`text-tiny ${MUTED}`}>
            Format
            <select
              value={format}
              onChange={(event) =>
                setFormat(event.target.value as typeof format)
              }
              disabled={busy !== null}
              className={`${INPUT} mt-1 px-2 py-1.5 text-xs`}
            >
              <option value="mixed">Mixed</option>
              <option value="textbook">Textbook</option>
              <option value="course">Course</option>
              <option value="papers">Papers</option>
            </select>
          </label>
        </div>
      </form>

      {proposal && (
        <div className="mt-4 border-t border-slate-800 pt-3">
          <div className="flex items-baseline justify-between gap-2">
            <div>
              <p className="text-xs font-semibold text-slate-200">
                Sources for “{proposal.goal}”
              </p>
              <p className="mt-0.5 text-tiny text-slate-500">
                v{proposal.proposal_version} · {proposal.learner_level} ·{" "}
                {proposal.weekly_minutes} min/week ·{" "}
                {proposal.format_preference} · {proposal.provider}
              </p>
              {proposal.prior_knowledge && (
                <p className={`mt-1 text-tiny ${MUTED}`}>
                  Starting knowledge: {proposal.prior_knowledge}
                </p>
              )}
              {proposal.application_context && (
                <p className={`mt-1 text-tiny ${MUTED}`}>
                  Application: {proposal.application_context}
                </p>
              )}
              {proposal.target_outcome && (
                <p className="mt-1 text-tiny text-violet-300">
                  Victory condition: {proposal.target_outcome}
                </p>
              )}
            </div>
            <span className={`text-tiny ${MUTED}`}>
              {selectedIds.size} selected
            </span>
          </div>

          <ul className="mt-2 space-y-2" aria-label="Proposed web sources">
            {proposal.sources.map((source) => {
              const href = safeUrl(source.url);
              return (
                <li
                  key={source.id}
                  className="rounded-lg border border-slate-800 bg-slate-950/60 p-2.5"
                >
                  <label className="flex items-start gap-2">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(source.id)}
                      onChange={() => toggleSource(source.id)}
                      disabled={busy !== null || proposal.status !== "draft"}
                      className={`mt-1 accent-sky-400 ${FOCUS_RING}`}
                    />
                    <span className="min-w-0 flex-1">
                      {href ? (
                        <a
                          href={href}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={`font-display text-xs font-semibold text-sky-300 hover:text-sky-200 ${FOCUS_RING}`}
                        >
                          {source.title}
                        </a>
                      ) : (
                        <span className="font-display text-xs font-semibold text-slate-300">
                          {source.title}
                        </span>
                      )}
                      <span className="mt-0.5 block text-tiny text-slate-500">
                        {source.domain} ·{" "}
                        {Math.round(source.quality_score * 100)}% fit · found
                        via {source.discovery_angle}
                      </span>
                      {source.quality_reasons.length > 0 && (
                        <span className="mt-1 block text-tiny text-slate-500">
                          {source.quality_reasons.join(" · ")}
                        </span>
                      )}
                      <span
                        className={`mt-1 block text-tiny ${source.policy_status === "blocked" ? "text-rose-300" : "text-amber-300"}`}
                      >
                        {source.policy_status === "blocked"
                          ? "Policy blocked"
                          : "Policy review required"}
                        : {source.policy_reasons.join(" · ")}
                      </span>
                      <span className="mt-1 flex flex-wrap items-center gap-x-2 text-tiny">
                        <a
                          href={safeUrl(source.robots_url) ?? undefined}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={`text-amber-200 hover:text-amber-100 ${FOCUS_RING}`}
                        >
                          Inspect robots.txt
                        </a>
                        <a
                          href={href ?? undefined}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={`text-sky-300 hover:text-sky-200 ${FOCUS_RING}`}
                        >
                          Inspect source policy
                        </a>
                        <button
                          type="button"
                          onClick={() => void checkPolicy(source.id)}
                          disabled={busy !== null}
                          className={`text-emerald-300 hover:text-emerald-200 ${FOCUS_RING}`}
                        >
                          {busy === "policy" ? "Checking…" : "Check now"}
                        </button>
                      </span>
                      <span className="mt-1 block text-tiny text-slate-500">
                        Robots: {source.robots_status} · License:{" "}
                        {source.license_status}
                        {source.policy_checked_at
                          ? ` · checked ${new Date(source.policy_checked_at).toLocaleString()}`
                          : ""}
                      </span>
                      {source.snippet && (
                        <span
                          className={`mt-1 block text-mini leading-relaxed ${MUTED}`}
                        >
                          {source.snippet}
                        </span>
                      )}
                    </span>
                  </label>
                  {source.ingest_error && (
                    <p className="mt-1 text-tiny text-rose-400">
                      {source.ingest_error}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>

          <section
            className="mt-3 rounded-lg border border-violet-900/60 bg-violet-950/10 p-3"
            aria-labelledby="campaign-map-heading"
          >
            <div className="flex items-baseline justify-between gap-2">
              <h3
                id="campaign-map-heading"
                className="font-display text-xs font-semibold text-violet-100"
              >
                Campaign map preview
              </h3>
              <span className="text-tiny text-slate-500">
                planning beats, not generated nodes
              </span>
            </div>
            <p className={`mt-1 text-tiny leading-relaxed ${MUTED}`}>
              This is the adventure shape suggested by your context. The actual
              skills, branches, and prerequisite edges are extracted from the
              approved source text.
            </p>
            <ol className="mt-3 grid gap-2 sm:grid-cols-3">
              {phases.map((phase, index) => (
                <li
                  key={phase.label}
                  className="relative rounded-md border border-violet-900/50 bg-slate-950/40 p-2"
                >
                  <span className="text-tiny font-semibold text-violet-300">
                    Stage {index + 1}
                  </span>
                  <span className="mt-1 block text-mini font-semibold text-slate-200">
                    {phase.label}
                  </span>
                  <span className="mt-1 block text-tiny leading-relaxed text-slate-500">
                    {phase.description}
                  </span>
                </li>
              ))}
            </ol>
            <p className="mt-2 text-tiny text-slate-500">
              {selectedSourceCount} selected source
              {selectedSourceCount === 1 ? "" : "s"} across{" "}
              {selectedDomainCount} domain{selectedDomainCount === 1 ? "" : "s"}
              . More diverse approved evidence can produce a richer tree.
            </p>
            {proposal.target_outcome && (
              <p className="mt-1 text-tiny font-semibold text-violet-300">
                Final objective: {proposal.target_outcome}
              </p>
            )}
          </section>

          {proposal.status === "draft" && (
            <>
              <label className="mt-3 flex items-start gap-2 rounded-lg border border-amber-900/60 bg-amber-950/20 p-2 text-tiny text-amber-200">
                <input
                  type="checkbox"
                  checked={policyAcknowledged}
                  onChange={(event) =>
                    setPolicyAcknowledged(event.target.checked)
                  }
                  disabled={busy !== null || selectedIds.size === 0}
                  className={`mt-0.5 accent-amber-400 ${FOCUS_RING}`}
                />
                <span>
                  I reviewed the selected pages and their robots/license notes.
                  I understand policy status is not verified by ScaleUp and will
                  make sure I have permission to ingest them.
                </span>
              </label>
              <button
                type="button"
                onClick={() => void approve()}
                disabled={
                  busy !== null || selectedIds.size === 0 || !policyAcknowledged
                }
                className={`mt-3 w-full ${BUTTON_SECONDARY} text-xs`}
              >
                {busy === "approve"
                  ? "Approving…"
                  : `Approve ${selectedIds.size} source${selectedIds.size === 1 ? "" : "s"}`}
              </button>
            </>
          )}
          {proposal.status === "approved" && (
            <button
              type="button"
              onClick={() => void ingest()}
              disabled={busy !== null}
              className={`mt-3 w-full ${BUTTON_PRIMARY} text-xs`}
            >
              {busy === "ingest"
                ? "Starting ingestion…"
                : "Ingest approved sources"}
            </button>
          )}
        </div>
      )}

      {notice && <p className="mt-3 text-xs text-slate-300">{notice}</p>}
      {error && (
        <p role="alert" className="mt-3 text-xs text-rose-400">
          {error}
        </p>
      )}

      <section
        className="mt-5 border-t border-slate-800 pt-4"
        aria-labelledby="curriculum-review-heading"
      >
        <h3
          id="curriculum-review-heading"
          className="font-display text-xs font-semibold"
        >
          Review curriculum versions
        </h3>
        <p className={`mt-1 text-tiny leading-relaxed ${MUTED}`}>
          Candidate prerequisites stay inert until reviewed and published.
          Evidence counts show whether a source quote backs each proposed link.
        </p>
        {versions.length > 0 ? (
          <>
            <label
              htmlFor="curriculum-version"
              className={`mt-2 block text-tiny ${MUTED}`}
            >
              Version
            </label>
            <select
              id="curriculum-version"
              value={selectedVersionId ?? ""}
              onChange={(event) => setSelectedVersionId(event.target.value)}
              className={`${INPUT} mt-1 px-2 py-1.5 text-xs`}
            >
              {versions.map((version) => (
                <option key={version.id} value={version.id}>
                  {version.title} · v{version.version} · {version.status}
                </option>
              ))}
            </select>
            {selectedVersion && (
              <p className="mt-1 text-tiny text-slate-500">
                {selectedVersion.instrument} · {selectedVersion.node_count}{" "}
                skills · {selectedVersion.candidate_count} accepted ·{" "}
                {selectedVersion.rejected_count} rejected
              </p>
            )}
            {candidates.length > 0 ? (
              <ul
                className="mt-2 space-y-2"
                aria-label="Prerequisite candidates"
              >
                {candidates.map((candidate) => (
                  <li
                    key={candidate.id}
                    className="rounded-md border border-slate-800 bg-slate-950/60 p-2 text-tiny"
                  >
                    <p className="font-medium text-slate-200">
                      {candidate.prereq} → {candidate.target}
                    </p>
                    <p className={`mt-0.5 ${MUTED}`}>
                      {candidate.status} ·{" "}
                      {Math.round(candidate.confidence * 100)}% confidence ·{" "}
                      {candidate.support} support · {candidate.evidence_count}{" "}
                      evidence quote{candidate.evidence_count === 1 ? "" : "s"}
                    </p>
                    {candidate.rationale && (
                      <p className="mt-1 text-slate-500">
                        {candidate.rationale}
                      </p>
                    )}
                    {candidate.evidence.map((item) => (
                      <blockquote
                        key={item.chunk_id}
                        className="mt-1 border-l border-emerald-800 pl-2 text-emerald-200/80"
                      >
                        “{item.quote}”{" "}
                        <span className="text-slate-500">
                          · page {item.page_start + 1}
                          {item.section_path ? ` · ${item.section_path}` : ""}
                        </span>
                      </blockquote>
                    ))}
                    {candidate.cycle_path.length > 0 && (
                      <p className="mt-1 text-amber-300">
                        Cycle: {candidate.cycle_path.join(" → ")}
                      </p>
                    )}
                    {candidate.rejection_reason && (
                      <p className="mt-1 text-rose-300">
                        Compiler rejection: {candidate.rejection_reason}
                      </p>
                    )}
                    {(candidate.status === "draft" ||
                      candidate.status === "ambiguous") && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        <button
                          type="button"
                          onClick={() =>
                            void reviewCandidate(candidate.id, "accepted")
                          }
                          disabled={reviewBusyId !== null}
                          className={`${BUTTON_SECONDARY} px-2 py-1 text-tiny`}
                        >
                          Accept
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            void reviewCandidate(candidate.id, "rejected")
                          }
                          disabled={reviewBusyId !== null}
                          className={`${BUTTON_SECONDARY} px-2 py-1 text-tiny`}
                        >
                          Reject
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            void reviewCandidate(candidate.id, "ambiguous")
                          }
                          disabled={reviewBusyId !== null}
                          className={`${BUTTON_SECONDARY} px-2 py-1 text-tiny`}
                        >
                          Keep ambiguous
                        </button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-tiny text-slate-500">
                No prerequisite candidates in this version.
              </p>
            )}
            <button
              type="button"
              onClick={() => void publishReviewedVersion()}
              disabled={
                reviewBusyId !== null ||
                reviewPending ||
                selectedVersion?.status === "published" ||
                selectedVersion?.status === "retired"
              }
              className={`mt-3 w-full ${BUTTON_PRIMARY} text-xs`}
            >
              {reviewBusyId === "publish"
                ? "Publishing…"
                : reviewPending
                  ? "Review all candidates to publish"
                  : "Publish reviewed curriculum"}
            </button>
          </>
        ) : (
          <p className="mt-2 text-tiny text-slate-500">
            No curriculum versions yet.
          </p>
        )}
        {reviewNotice && (
          <p className="mt-2 text-xs text-slate-300">{reviewNotice}</p>
        )}
        {reviewError && (
          <p role="alert" className="mt-2 text-xs text-rose-400">
            {reviewError}
          </p>
        )}
      </section>
    </section>
  );
}
