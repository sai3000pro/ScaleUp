"use client";

/**
 * The public argument for the product, in six movements.
 *
 * I    Hero — what it does, in one sentence, with Quartz on stage.
 * II   You can't hear yourself — the thing everyone who practises alone knows.
 * III  What a teacher is actually for — and why that is the expensive part.
 * IV   Why this is hard — four properties of the problem, each with what this
 *      system does about it. Names nobody. See `lib/landingEvidence.ts`.
 * V    What it measures — the figures, each rendering its own source.
 * VI   Enter — decay, and the way in.
 *
 * Every claim comes from `lib/landingEvidence.ts` and renders its source beside
 * it. Nothing here types a figure inline: the tenet is that the public page
 * claims only what the product already does, and a claim whose provenance lives
 * in somebody's memory is not checkable.
 *
 * @spec LAND-STORY-001, LAND-STORY-002, LAND-STORY-003, LAND-STORY-004
 * @spec LAND-STORY-005, LAND-STORY-006, LAND-STORY-007, LAND-STORY-008
 * @spec LAND-STORY-009, LAND-CLAIM-004, LAND-CLAIM-005, LAND-ROUTE-003
 */
import Link from "next/link";

import { Quartz } from "@/components/mascot/Quartz";
import { Reveal } from "@/components/landing/Reveal";
import { HARD_PARTS, SYSTEM_FIGURES } from "@/lib/landingEvidence";

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
              Pick a skill off the tree, play it, and find out what you actually did — pitch,
              timing, dynamics, and how you were sitting. The things you stop practising fade,
              and come back as tomorrow&rsquo;s quest.
            </p>
            <div className="landing-actions">
              <Link href={primaryHref} className="landing-cta">
                {primaryLabel}
              </Link>
              <a href="#hard" className="landing-cta landing-cta--quiet">
                Why this is hard
              </a>
            </div>
            <p className="landing-footnote">
              {signedIn
                ? "You're signed in — your courses are one click away."
                : "Free to try. No model decides your grade — the numbers come from the recording."}
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

      {/* ── II. You can't hear yourself ─────────────────────────────────── */}
      <section className="landing-band" aria-labelledby="alone-title">
        <div className="landing-shell">
          <Reveal>
            <p className="landing-eyebrow">The problem</p>
            <h2 id="alone-title" className="landing-h2">
              An hour of practice can make you worse.
            </h2>
          </Reveal>
          <div className="landing-pair">
            <Reveal delay={80} className="landing-card">
              <h3 className="landing-h3">You can&rsquo;t hear it while you do it</h3>
              <p>
                Your ear is busy playing. You can&rsquo;t tell a flat third from a nervous one,
                or rushing from unevenness, and you certainly can&rsquo;t see your own right
                shoulder. So the mistake gets repeated until it&rsquo;s fluent — and fluent
                feels like progress.
              </p>
            </Reveal>
            <Reveal delay={160} className="landing-card">
              <h3 className="landing-h3">And you won&rsquo;t notice it going</h3>
              <p>
                The things you lose are the things you stopped touching, so nothing you&rsquo;re
                currently playing will surface them. Scales you had cold in March are gone by
                June and there&rsquo;s no moment where you find out. Until there is.
              </p>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ── III. What a teacher is for ──────────────────────────────────── */}
      <section className="landing-band landing-band--tint" aria-labelledby="teacher-title">
        <div className="landing-shell landing-narrow">
          <Reveal>
            <p className="landing-eyebrow">Why lessons cost what they cost</p>
            <h2 id="teacher-title" className="landing-h2">
              A teacher is a second pair of ears with a long memory.
            </h2>
            <p className="landing-body">
              They hear the flat note while it&rsquo;s still in the air, and they remember your
              left hand collapsing the same way two months ago. That&rsquo;s the job. The
              scales and the repertoire you could get from a book.
            </p>
            <p className="landing-body">
              It&rsquo;s also why an hour costs what it does. Someone has to be in the room,
              paying attention, every week, for years — and it doesn&rsquo;t get cheaper the
              more people want it, because it isn&rsquo;t one thing being copied. It&rsquo;s
              one person listening to one person.
            </p>
            <p className="landing-body landing-body--turn">
              The listening half sounds like a signal-processing problem, and signal processing
              is a solved field. It isn&rsquo;t that simple.
            </p>
          </Reveal>
        </div>
      </section>

      {/* ── IV. Why this is hard ────────────────────────────────────────── */}
      <section className="landing-evidence" id="hard" aria-labelledby="hard-title">
        <div className="landing-shell">
          <Reveal>
            <p className="landing-eyebrow landing-eyebrow--invert">Why this is hard</p>
            <h2 id="hard-title" className="landing-h2 landing-h2--invert">
              Every obvious way to grade a performance is wrong in a way you can&rsquo;t see.
            </h2>
            <p className="landing-body landing-body--invert">
              Not hard to build — hard to build so the number means something. Each of these is
              a version that runs, returns a score, and would quietly teach you the wrong
              lesson.
            </p>
          </Reveal>

          <ol className="landing-evidence__list">
            {HARD_PARTS.map((part, i) => (
              <Reveal as="li" key={part.id} delay={70 * (i + 1)} className="landing-evidence__item">
                <h3 className="landing-h3 landing-h3--invert">{part.title}</h3>
                <p className="landing-evidence__finding">{part.problem}</p>
                <p className="landing-evidence__missing">
                  <span className="landing-evidence__missing-label">What we do instead</span>
                  {part.answer}
                </p>
                <p className="landing-source landing-source--invert">
                  <code>{part.source}</code>
                </p>
              </Reveal>
            ))}
          </ol>

          <Reveal delay={340}>
            <p className="landing-body landing-body--invert landing-evidence__coda">
              The through-line is the last one. A plausible number is far cheaper to produce
              than a true one, and on a screen they look identical. So the rule here is that a
              dimension nothing measured is reported as missing, never as zero — and the score
              you get is the one the recording can actually support.
            </p>
          </Reveal>
        </div>
      </section>

      {/* ── V. What it measures ─────────────────────────────────────────── */}
      <section className="landing-band" aria-labelledby="measure-title">
        <div className="landing-shell">
          <Reveal>
            <p className="landing-eyebrow">What you get</p>
            <h2 id="measure-title" className="landing-h2">
              A grade you can argue with.
            </h2>
            <p className="landing-body landing-narrow">
              Every take comes back with the dimensions it could measure, the ones it
              couldn&rsquo;t, and an examiner&rsquo;s read on what to fix first. The numbers are
              measured off the recording; a model may improve the wording and never touches
              them.
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

      {/* ── VI. Enter ───────────────────────────────────────────────────── */}
      <section className="landing-band landing-band--tint" aria-labelledby="decay-title">
        <div className="landing-shell landing-narrow">
          <Reveal>
            <p className="landing-eyebrow">And then it fades</p>
            <h2 id="decay-title" className="landing-h2">
              The tree goes dull where you stop going.
            </h2>
            <p className="landing-body">
              Every skill carries a review schedule. Play it well and the gap before it comes
              back gets longer; leave it and the gap closes. None of that is stored as a
              number — it&rsquo;s worked out from when you last played it and how it went, so
              changing what &ldquo;solid&rdquo; means changes your whole history rather than
              whatever a nightly job last wrote down.
            </p>
            <p className="landing-body">
              What it feels like: the thing you were best at in March turns up as
              tomorrow&rsquo;s quest, and you find out you&rsquo;d lost it before anyone else
              does.
            </p>
          </Reveal>
          <Reveal delay={140} className="landing-mascot-note">
            <Quartz size={92} rest="idle-l" greet="stumble" react="cheer" label="Quartz, reacting" />
            <p>
              Quartz has opinions about your semiquavers. It doesn&rsquo;t get a vote on your
              grade — nothing it does changes a number.
            </p>
          </Reveal>
        </div>
      </section>

      <section className="landing-close" aria-labelledby="close-title">
        <div className="landing-shell landing-narrow landing-close__inner">
          <Reveal>
            <Quartz size={116} rest="bow" greet="cheer" react="belt" label="Quartz, taking a bow" />
            <h2 id="close-title" className="landing-h2">
              Play something. Find out what it sounded like.
            </h2>
            <div className="landing-actions landing-actions--center">
              <Link href={primaryHref} className="landing-cta">
                {primaryLabel}
              </Link>
            </div>
          </Reveal>
        </div>
        <footer className="landing-footer">
          <p>Learn Any Instrument — practice that measures itself, and says so when it can&rsquo;t.</p>
        </footer>
      </section>
    </main>
  );
}
