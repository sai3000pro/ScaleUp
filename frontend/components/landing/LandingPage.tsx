"use client";

/**
 * The public argument for the product, in seven movements.
 *
 * I    Hero — what it does, in one sentence, with Quartz on stage.
 * II   Two failures — practice nobody measures, and technique that fades. The
 *      HLD's own Problem section, stated to a stranger.
 * III  What a tutor costs — the hour is not the product; the attention is.
 * IV   Three teams tried — the evidence. Three named repositories, one verified
 *      finding each, each citing the file it can be checked in. This is the
 *      movement the segment exists for; everything else is scaffolding for it.
 * V    What it takes to hear it — the answer, as figures with sources.
 * VI   And then remembering — decay, and the quest that brings a skill back.
 * VII  Enter — the way in.
 *
 * Every number on this page comes from `lib/landingEvidence.ts` and renders its
 * own source beside it. Nothing here types a figure inline; the tenet is that
 * the public page claims only what the product already does, and a claim whose
 * provenance lives in someone's memory is not checkable.
 *
 * @spec LAND-STORY-001, LAND-STORY-002, LAND-STORY-003, LAND-STORY-004
 * @spec LAND-STORY-005, LAND-STORY-006, LAND-STORY-007, LAND-STORY-008
 * @spec LAND-STORY-009, LAND-CLAIM-004, LAND-CLAIM-005, LAND-ROUTE-003
 */
import Link from "next/link";

import { Quartz } from "@/components/mascot/Quartz";
import { Reveal } from "@/components/landing/Reveal";
import { PRIOR_ART, SYSTEM_FIGURES } from "@/lib/landingEvidence";

export interface LandingPageProps {
  /** Where the primary action goes. Signed-in readers get their courses. */
  primaryHref: string;
  primaryLabel: string;
  /** True when a session already exists, which changes only the wording. */
  signedIn: boolean;
}

export function LandingPage({ primaryHref, primaryLabel, signedIn }: LandingPageProps) {
  return (
    <main id="main-content" className="landing">
      {/* ── I. Hero ─────────────────────────────────────────────────────── */}
      <section className="landing-hero" aria-labelledby="hero-title">
        <div className="landing-shell landing-hero__grid">
          <div className="landing-hero__copy">
            <p className="landing-eyebrow">Learn Any Instrument</p>
            <h1 id="hero-title" className="landing-h1">
              Nobody can hear themselves play.
            </h1>
            <p className="landing-lede">
              Pick a skill off the tree, play the exercise behind it, and get scored on pitch,
              rhythm, dynamics and the way you are sitting — then coached about it in an
              examiner&rsquo;s voice. What you stop practising fades, and comes back as
              tomorrow&rsquo;s quest.
            </p>
            <div className="landing-actions">
              <Link href={primaryHref} className="landing-cta">
                {primaryLabel}
              </Link>
              <a href="#evidence" className="landing-cta landing-cta--quiet">
                Why this is hard
              </a>
            </div>
            <p className="landing-footnote">
              {signedIn
                ? "You are signed in — your courses are one click away."
                : "Free to try. Grading runs on your machine's microphone, with no API key."}
            </p>
          </div>

          <div className="landing-hero__stage">
            <div className="landing-stage-glow" aria-hidden />
            <Quartz
              size={190}
              rest="idle-front"
              greet="blink"
              react="belt"
              label="Quartz, the mascot. Give it a poke."
              className="landing-hero__quartz"
            />
            <p className="landing-stage-caption">Quartz. Poke it.</p>
          </div>
        </div>
      </section>

      {/* ── II. The two failures ────────────────────────────────────────── */}
      <section className="landing-band" aria-labelledby="failures-title">
        <div className="landing-shell">
          <Reveal>
            <p className="landing-eyebrow">The problem</p>
            <h2 id="failures-title" className="landing-h2">
              Practising alone fails twice, and each failure hides the other.
            </h2>
          </Reveal>
          <div className="landing-pair">
            <Reveal delay={80} className="landing-card">
              <h3 className="landing-h3">Practice nobody measures</h3>
              <p>
                You cannot hear your own intonation drift. You cannot tell rushing from
                unevenness. You certainly cannot see your own right shoulder. With no signal
                from outside, an hour of practice repeats an error until it is a habit — and
                the habit feels like progress, because it is getting more fluent.
              </p>
            </Reveal>
            <Reveal delay={160} className="landing-card">
              <h3 className="landing-h3">Technique that fades quietly</h3>
              <p>
                Nothing tells you which of the hundred things you could once do has stopped
                working. Decay is silent by construction: the skills you lose are the ones you
                stopped touching, so nothing you are currently doing will surface them. You
                find out in front of somebody.
              </p>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ── III. What a tutor costs ─────────────────────────────────────── */}
      <section className="landing-band landing-band--tint" aria-labelledby="cost-title">
        <div className="landing-shell landing-narrow">
          <Reveal>
            <p className="landing-eyebrow">The cost</p>
            <h2 id="cost-title" className="landing-h2">
              You are not paying for the hour.
            </h2>
            <p className="landing-body">
              A tutor supplies exactly the two things practising alone cannot: measurement in
              the moment, and memory across months. They hear the flat note as it happens, and
              they remember that your left hand collapsed the same way in March. The hour is
              only where those are delivered.
            </p>
            <p className="landing-body">
              That is most of what a tutor is <em>for</em>, and most of what makes one
              expensive — attention that has to be present, in real time, repeatedly, for
              years. It does not get cheaper with scale, because it is not reproducible: it is
              one person listening to one person.
            </p>
            <p className="landing-body landing-body--turn">
              Which invites an obvious question. The measuring half is a signal-processing
              problem, and signal processing is a solved field. How hard can it be?
            </p>
          </Reveal>
        </div>
      </section>

      {/* ── IV. Three teams tried ───────────────────────────────────────── */}
      <section className="landing-evidence" id="evidence" aria-labelledby="evidence-title">
        <div className="landing-shell">
          <Reveal>
            <p className="landing-eyebrow landing-eyebrow--invert">The evidence</p>
            <h2 id="evidence-title" className="landing-h2 landing-h2--invert">
              Hard enough that three teams shipped a music coach that could not hear a wrong
              note.
            </h2>
            <p className="landing-body landing-body--invert">
              These are real projects, and each finding below was read out of the file it
              cites — not inferred from a README. They are listed because what stopped each
              one is different, and the three failures together are a map of the problem.
            </p>
          </Reveal>

          <ol className="landing-evidence__list">
            {PRIOR_ART.map((attempt, i) => (
              <Reveal as="li" key={attempt.repo} delay={80 * (i + 1)} className="landing-evidence__item">
                <h3 className="landing-h3 landing-h3--invert">{attempt.repo}</h3>
                <p className="landing-evidence__premise">{attempt.premise}</p>
                <p className="landing-evidence__finding">{attempt.finding}</p>
                <p className="landing-evidence__missing">
                  <span className="landing-evidence__missing-label">What that misses</span>
                  {attempt.missing}
                </p>
                <p className="landing-source landing-source--invert">
                  Checkable in <code>{attempt.repo}/{attempt.file}</code>
                </p>
              </Reveal>
            ))}
          </ol>

          <Reveal delay={320}>
            <p className="landing-body landing-body--invert landing-evidence__coda">
              None of this is incompetence — two of the three are well-built, and the third
              knows more vocal science than this project does. It is what the problem does to
              you. The interesting part looks like the easy part, and a plausible number is
              enormously cheaper to produce than a true one. A grade nobody can check looks
              exactly like a grade.
            </p>
          </Reveal>
        </div>
      </section>

      {/* ── V. What it takes to hear it ─────────────────────────────────── */}
      <section className="landing-band" aria-labelledby="measure-title">
        <div className="landing-shell">
          <Reveal>
            <p className="landing-eyebrow">The answer, part one</p>
            <h2 id="measure-title" className="landing-h2">
              Measure what you can. Say so when you can&rsquo;t.
            </h2>
            <p className="landing-body landing-narrow">
              A take is aligned against a real score rather than compared note-for-note, so
              playing something slowly is not the same mistake as playing it wrong. Intonation
              is reported in cents, because &ldquo;nearest semitone&rdquo; cannot tell a
              violinist anything they need. Dynamics are measured relative to your own take,
              because absolute loudness is your microphone and your room, not your playing.
            </p>
            <p className="landing-body landing-narrow">
              And where a measurement is not available — silence, an unseen hand, an occluded
              hip — it is reported as absent and the remaining dimensions are renormalised. A
              drummer is not marked down for pitch. Nothing is ever scored as zero because it
              was not observed.
            </p>
          </Reveal>

          <dl className="landing-figures">
            {SYSTEM_FIGURES.map((figure, i) => (
              <Reveal key={figure.id} delay={60 * i} className="landing-figure">
                <dt className="landing-figure__value">{figure.value}</dt>
                <dd>
                  <span className="landing-figure__label">{figure.label}</span>
                  <span className="landing-source">
                    <code>{figure.source}</code>
                  </span>
                </dd>
              </Reveal>
            ))}
          </dl>
        </div>
      </section>

      {/* ── VI. And then remembering ────────────────────────────────────── */}
      <section className="landing-band landing-band--tint" aria-labelledby="memory-title">
        <div className="landing-shell landing-narrow">
          <Reveal>
            <p className="landing-eyebrow">The answer, part two</p>
            <h2 id="memory-title" className="landing-h2">
              The harder half is remembering.
            </h2>
            <p className="landing-body">
              Every skill sits on a prerequisite graph and carries a review schedule. Play it
              well and the interval stretches; leave it and it contracts. Nothing about that
              state is stored — mastery is computed from when you last played it and how it
              went, so a change to what &ldquo;mastered&rdquo; means applies to your whole
              history rather than to whatever a nightly job last wrote down.
            </p>
            <p className="landing-body">
              The practical effect is that the tree goes quietly dull in the places you have
              been avoiding, and the thing you were best at in March turns up as tomorrow&rsquo;s
              quest. That is the part a metronome and a video cannot do for you, and it is the
              half most practice tools skip.
            </p>
          </Reveal>
          <Reveal delay={140} className="landing-mascot-note">
            <Quartz size={92} rest="idle-l" greet="stumble" react="cheer" label="Quartz, reacting" />
            <p>
              Quartz has opinions about your semiquavers. It does not get a vote on your
              grade — nothing it does changes a number.
            </p>
          </Reveal>
        </div>
      </section>

      {/* ── VII. Enter ──────────────────────────────────────────────────── */}
      <section className="landing-close" aria-labelledby="close-title">
        <div className="landing-shell landing-narrow landing-close__inner">
          <Reveal>
            <Quartz size={116} rest="bow" greet="cheer" react="belt" label="Quartz, taking a bow" />
            <h2 id="close-title" className="landing-h2">
              Play something. Find out what it actually sounded like.
            </h2>
            <div className="landing-actions landing-actions--center">
              <Link href={primaryHref} className="landing-cta">
                {primaryLabel}
              </Link>
            </div>
          </Reveal>
        </div>
        <footer className="landing-footer">
          <p>
            Learn Any Instrument — a practice tutor that measures what it can and says so when
            it cannot.
          </p>
        </footer>
      </section>
    </main>
  );
}
