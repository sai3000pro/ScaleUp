# Arrow: evaluation

Expected notation plus observations become a metric bundle. The segment that decides what a
performance was worth.

## Status

**AUDITED** — last audited 2026-08-21 (git SHA `2006ff8`). Six instruments score through five
evaluators — banjo routes to the guitar path — sharing an alignment approach, a registry, and
generated notation. The honesty rule now holds everywhere in the segment; what remains is
duplication that is correct by authorship rather than by construction.

## References

### HLD
- `docs/high-level-design.md`

### LLD
- `docs/intent/evaluation/evaluation-design.md`

### EARS
- `docs/intent/evaluation/evaluation-specs.md` (51 specs)

### Tests
- `backend/tests/unit/test_dtw.py`, `test_musicxml.py`, `test_score_generator.py`
- `backend/tests/unit/test_instrument_evaluators.py`, `test_evaluator_registry.py`
- `backend/tests/unit/test_unmeasured_dimensions.py` — the honesty rule at the wire/domain seam
- `backend/tests/unit/test_online_matcher.py`
- **No test covers `dynamics.py`.** `EVAL-DYN-001` – `004` are implemented and unverified.
- `backend/tests/integration/test_performance_flow.py`, `test_instrument_flows.py`

### Code
- `backend/app/evaluation/` — `musicxml.py`, `dtw.py`, `registry.py`, `dynamics.py`, `online.py`, `score_generator.py`
- `backend/app/evaluation/` — `piano.py`, `guitar.py`, `violin.py`, `trumpet.py`, `drums.py`
- `backend/app/services/performance_service.py`, `score_service.py`

## Architecture

**Purpose:** Align a performance to notation and report what was measured — and only what
was measured.

**Key Components:**
1. `musicxml.py` — strict parser for a constrained subset; expected notes, beats, dynamics.
2. `score_generator.py` — notation from parameters, self-validated through that parser.
3. `dtw.py` — the alignment core.
4. Five instrument modules — per-instrument dimensions over that core.
5. `registry.py` — instrument to evaluator and weights; renormalises over present dimensions.
6. `online.py` — the live monotone matcher, never authoritative.

## Spec Coverage

| Category | Spec IDs | Implemented | Deferred | Gaps |
|---|---|---|---|---|
| Notation | `EVAL-NOTE-001` – `008` | 8 | 0 | 0 |
| Generation | `EVAL-GEN-001` – `008` | 8 | 0 | 0 |
| Alignment | `EVAL-ALIGN-001` – `005` | 5 | 0 | 0 |
| Per-instrument | `EVAL-INST-001` – `011` | 9 | 2 | 0 |
| Dynamics | `EVAL-DYN-001` – `004` | 4 | 0 | 0 |
| Combination | `EVAL-WEIGHT-001` – `005` | 4 | 0 | 1 |
| Live matching | `EVAL-LIVE-001` – `006` | 5 | 1 | 0 |
| Versioning | `EVAL-VER-001` – `004` | 4 | 0 | 0 |

**Summary:** 47 of 51 implemented; 3 deliberate non-wants; 1 active gap.

## Key Findings

1. **The honesty rule is breakable at exactly one place: the type of an optional
   observation.** Both defects the segment carried were the same mistake at that seam — a
   wire field typed `float | None` reaching a domain field typed `float` with a sentinel
   default. The sentinel is wrong in both directions at once: `violin.py` raised on a payload
   that omitted cents (the ordinary case, since the shipped detector emits none), *and*
   excluded a note played exactly in tune from its own intonation average, so playing
   perfectly switched the weighting from 0.5/0.3/0.2 to 0.6/0.4. Optional observations are
   now optional all the way down, and the scorer branches on presence rather than on value
   (`EVAL-INST-009`, `EVAL-INST-010`).

2. **A downstream symptom confirmed the diagnosis.** `feedback.py` can say "Your intonation
   is impressively centred" above 0.9 accuracy — a sentence that could never fire, because
   intonation went `None` exactly when it was perfect. The examiner was silent about the one
   thing worth praising.

3. **The single honesty violation is closed, and its correct form was already in the file.**
   `guitar.py` folded an absent chord technique score in as `0.0`, capping a flawless strum
   at 0.8 for a fingering the notation never contained — while the single-note path two
   hundred lines above did the same thing correctly, with an explicit presence check and a
   0.6/0.4 fallback. The chord path now matches its sibling (`EVAL-INST-011`).

4. **The shared alignment core is not shared.** `_tempo_metrics`, the timing tolerance, the
   deletion and insertion costs, the pitch divisor, the pitch-quality divisor, the
   alignment-confidence formula and the extra-note penalty each exist in four independent
   copies across piano, guitar, violin and drums — identical today by authorship, not by
   construction. Finding 3 is what that costs: one copy drifted and nothing noticed.

5. **Duplicated constants meant to agree are unlinked.** `DYNAMIC_RANGE_DB = 24.0`
   (`dynamics.py:35`, self-labelled a guess) is re-hardcoded in `online.py:248` under a
   comment asserting they match. `MAX_FRET` is 24 in `guitar.py:24` and 12 in
   `score_generator.py:86`.

6. **The weight table carries no rationale.** `INSTRUMENT_WEIGHTS` decides what a performance
   is worth and no individual number is justified — only the renormalisation property is
   argued for (`EVAL-WEIGHT-005`).

7. **Notation and generation are the segment's strongest parts.** All 16 specs implemented,
   including the property that a generated score validates through the real parser before
   storage.

## Work Required

### Should Fix
1. Record a rationale for each instrument weight (`EVAL-WEIGHT-005`). These numbers decide
   what a performance is worth and none of them is defended.
2. Calibrate `DYNAMIC_RANGE_DB` and link the two copies.
3. Build the golden matrix — perfect, slow, fast, wrong-pitch, missed, extra, silence — per
   instrument. Both defects above were reachable by a perfect take, which is the cheapest row
   in that matrix.

### Consider
4. Unify the four alignment cores, or accept the duplication explicitly and test that they
   agree.
5. Read the live-versus-batch divergence telemetry already being recorded.
