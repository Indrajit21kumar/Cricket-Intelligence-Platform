"""The Scoring Standard (Book 4 Ch. 8, Step 2, FR-M14-01).

Chapter 8 defines the score set and, for five of them, names the metrics they
derive from:

    Technique  - alignment of measured metrics to benchmark ranges
    Timing     - BM-17, BM-11, reaction metrics
    Power      - PH-01/02 (measured) + estimated energy (labelled)
    Balance    - BM-01, BM-14, centre-of-mass stability
    Footwork   - BM-07, BM-08, ground-contact timing
    Confidence - report-level confidence (Ch. 7)
    Improvement- change vs the player's own history (Cricket DNA, M04)

Chapter 8 does not enumerate every metric's category, does not fix the Overall
weighting, and Chapter 7 explicitly leaves "how to combine independent
confidences into a report-level confidence" as an open research question. This
module makes those choices explicitly and documents them so they are a
versioned, reviewable decision (per Ch. 8's own requirement that scoring be "a
defined, versioned method — not ad hoc per report"), not a hidden guess:

- **Category attribution**: a finding penalises every performance category one
  of its EVIDENCED metrics belongs to (Ch. 8's named anchors are authoritative;
  the remaining BM/PH ids are assigned by domain judgement to Technique, the
  catch-all "alignment to benchmark ranges" category. BM-17 sits in BOTH Timing
  and Footwork, per Ch. 8's own text ("ground-contact timing" appears in both).
- **Penalty model**: each finding whose evidence touches a category deducts
  ``PENALTY_PER_FINDING`` scaled by the finding's own confidence — a firm
  finding costs more than a shaky one, and a clean stroke (no findings) scores
  100 in every performance category.
- **Confidence score**: the mean confidence across the report's findings (or,
  when there are none, across the input facts) — a defensible v1 combination,
  explicitly not the final word Ch. 7 invites future refinement on.
- **Overall**: an equal-weighted mean of the five PERFORMANCE categories only.
  Confidence and Improvement are reported alongside, never blended in — folding
  a meta-uncertainty measure into the performance number would hide it inside a
  composite, contradicting Ch. 7's hard rule that "confidence is always shown,
  never hidden."
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

TECHNIQUE = "technique"
TIMING = "timing"
POWER = "power"
BALANCE = "balance"
FOOTWORK = "footwork"
PERFORMANCE_CATEGORIES = (TECHNIQUE, TIMING, POWER, BALANCE, FOOTWORK)

#: Metric -> categories it counts against. Ch. 8 anchors first; the rest of the
#: BM/PH catalogue assigned to Technique (the "alignment to benchmark ranges"
#: catch-all) by domain judgement, documented here rather than left implicit.
METRIC_CATEGORIES: dict[str, tuple[str, ...]] = {
    # --- Timing: BM-17, BM-11, reaction metrics (PH-05) ---
    "BM-17": (TIMING, FOOTWORK),  # ground-contact timing: named under both
    "BM-11": (TIMING,),
    "PH-05": (TIMING,),
    # --- Power: PH-01/02 measured + estimated energy ---
    "PH-01": (POWER,),
    "PH-02": (POWER,),
    "PH-06": (POWER,),  # momentum — energy-domain, estimated
    "PH-07": (POWER,),  # torque — energy-domain, estimated
    "PH-08": (POWER,),  # kinetic energy — the named "estimated energy"
    "PH-09": (POWER,),  # ground reaction force — energy-domain, estimated
    "PH-10": (POWER,),  # ball-exit velocity — energy-domain, estimated
    # --- Balance: BM-01, BM-14, centre-of-mass stability ---
    "BM-01": (BALANCE,),
    "BM-14": (BALANCE,),
    "BM-16": (BALANCE,),  # centre-of-mass path
    "PH-04": (BALANCE,),  # CoM & balance (physics)
    # --- Footwork: BM-07, BM-08, ground-contact timing (BM-17, above) ---
    "BM-07": (FOOTWORK,),
    "BM-08": (FOOTWORK,),
    "BM-06": (FOOTWORK,),  # front knee flexion — footwork-adjacent
    # --- Technique: the remaining catalogue (alignment to benchmark ranges) ---
    "BM-02": (TECHNIQUE,),
    "BM-03": (TECHNIQUE,),
    "BM-04": (TECHNIQUE,),
    "BM-05": (TECHNIQUE,),
    "BM-09": (TECHNIQUE,),
    "BM-10": (TECHNIQUE,),
    "BM-13": (TECHNIQUE,),
    "BM-15": (TECHNIQUE,),
    "PH-03": (TECHNIQUE,),
    "PH-11": (TECHNIQUE,),
}

#: Points deducted per finding touching a category, scaled by finding confidence.
PENALTY_PER_FINDING = 20.0
#: Overall = equal-weighted mean of the five performance categories (versioned).
SCORE_MODEL_VERSION = "score-std-1.0.0"


@dataclass(frozen=True, slots=True)
class ScoreEntry:
    """One score with the inputs it derived from (Ch. 8: "expose inputs on request")."""

    value: float | None
    confidence: float | None
    inputs: tuple[str, ...] = field(default_factory=tuple)
    unavailable_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "confidence": self.confidence,
            "inputs": list(self.inputs),
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass(frozen=True, slots=True)
class Scores:
    overall: ScoreEntry
    technique: ScoreEntry
    timing: ScoreEntry
    power: ScoreEntry
    balance: ScoreEntry
    footwork: ScoreEntry
    confidence: ScoreEntry
    improvement: ScoreEntry
    model_version: str = SCORE_MODEL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall.to_dict(),
            "technique": self.technique.to_dict(),
            "timing": self.timing.to_dict(),
            "power": self.power.to_dict(),
            "balance": self.balance.to_dict(),
            "footwork": self.footwork.to_dict(),
            "confidence": self.confidence.to_dict(),
            "improvement": self.improvement.to_dict(),
            "model_version": self.model_version,
        }


def _category_score(category: str, findings: Sequence[Mapping[str, Any]]) -> ScoreEntry:
    penalty = 0.0
    inputs: list[str] = []
    for finding in findings:
        evidence = finding.get("evidence", [])
        metric_ids = [e.get("metric_id") for e in evidence if isinstance(e, Mapping)]
        touches = any(category in METRIC_CATEGORIES.get(mid, ()) for mid in metric_ids if mid)
        if not touches:
            continue
        conf = finding.get("confidence")
        penalty += PENALTY_PER_FINDING * (conf if isinstance(conf, int | float) else 1.0)
        inputs.extend(
            mid for mid in metric_ids if mid and category in METRIC_CATEGORIES.get(mid, ())
        )

    value = round(max(0.0, min(100.0, 100.0 - penalty)), 1)
    return ScoreEntry(value=value, confidence=None, inputs=tuple(dict.fromkeys(inputs)))


def _confidence_score(
    findings: Sequence[Mapping[str, Any]], facts: Mapping[str, Any]
) -> ScoreEntry:
    """Ch. 7: combine independent confidences into one report-level number.

    Findings first (they are the rule-inference confidences Ch. 7 names
    directly); when a clean stroke produced no findings, fall back to the mean
    confidence of the input facts so a clean report is not scored as unknown.
    """
    finding_confs: list[float] = [
        float(f["confidence"]) for f in findings if isinstance(f.get("confidence"), int | float)
    ]
    if finding_confs:
        mean_conf = sum(finding_confs) / len(finding_confs)
        inputs = tuple(f.get("finding_id", "") for f in findings)
    else:
        fact_confs: list[float] = [
            float(v["confidence"])
            for v in facts.values()
            if isinstance(v, Mapping) and isinstance(v.get("confidence"), int | float)
        ]
        if not fact_confs:
            return ScoreEntry(value=None, confidence=None, unavailable_reason="no_facts")
        mean_conf = sum(fact_confs) / len(fact_confs)
        inputs = tuple(facts.keys())
    return ScoreEntry(
        value=round(mean_conf * 100.0, 1), confidence=round(mean_conf, 3), inputs=inputs
    )


def _overall_score(categories: Mapping[str, ScoreEntry]) -> ScoreEntry:
    values: list[float] = [
        v for c in PERFORMANCE_CATEGORIES if (v := categories[c].value) is not None
    ]
    if not values:
        return ScoreEntry(value=None, confidence=None, unavailable_reason="no_category_scores")
    overall = sum(values) / len(values)
    return ScoreEntry(value=round(overall, 1), confidence=None, inputs=PERFORMANCE_CATEGORIES)


#: Whether a HIGHER value is the improving direction for a metric. Only
#: metrics with well-established direction are listed; any metric absent here
#: is excluded from the Improvement score rather than guessed at.
HIGHER_IS_BETTER: dict[str, bool] = {
    "BM-01": False,  # head stability (cm) — less drift is better
    "BM-04": True,  # X-factor separation — more stretch is generally better
    "BM-12": True,  # hand speed — faster is generally better
    "BM-14": False,  # balance recovery (ms) — faster recovery is better
    "BM-16": False,  # centre-of-mass path (cm) — less drift is better
    "PH-01": True,  # bat/hand speed
    "PH-08": True,  # kinetic energy transferred
}


def compute_improvement(panels: Sequence[Mapping[str, Any]], history: Sequence[Any]) -> ScoreEntry:
    """Ch. 8 Improvement: change vs the player's own history (Cricket DNA).

    Only metrics with a documented improvement direction (:data:`HIGHER_IS_BETTER`)
    and a matching baseline are scored; everything else is left out rather than
    guessed. No history at all -> honestly unavailable, never a fabricated 0.
    """
    if not history:
        return ScoreEntry(value=None, confidence=None, unavailable_reason="no_history")

    baselines = {h.metric_key: h for h in history}
    panel_values = {
        p.get("metric_id"): p
        for p in panels
        if isinstance(p, Mapping) and p.get("value") is not None
    }

    deltas: list[float] = []
    confidences: list[float] = []
    inputs: list[str] = []
    for metric_id, higher_is_better in HIGHER_IS_BETTER.items():
        baseline = baselines.get(metric_id)
        panel = panel_values.get(metric_id)
        if baseline is None or panel is None or not baseline.baseline_value:
            continue
        current = panel["value"]
        raw_change = (current - baseline.baseline_value) / abs(baseline.baseline_value)
        signed_change = raw_change if higher_is_better else -raw_change
        deltas.append(signed_change)
        conf = panel.get("confidence")
        confidences.append(
            min(baseline.baseline_confidence, conf if isinstance(conf, int | float) else 1.0)
        )
        inputs.append(metric_id)

    if not deltas:
        return ScoreEntry(value=None, confidence=None, unavailable_reason="no_matching_baseline")

    # Centre a mean +-20% change on a 50-100 scale: unchanged -> 50, +20% -> 100.
    mean_delta = sum(deltas) / len(deltas)
    value = round(max(0.0, min(100.0, 50.0 + mean_delta * 250.0)), 1)
    confidence = round(sum(confidences) / len(confidences), 3)
    return ScoreEntry(value=value, confidence=confidence, inputs=tuple(inputs))


def compute_scores(
    findings: Sequence[Mapping[str, Any]],
    facts: Mapping[str, Any],
    *,
    improvement: ScoreEntry | None = None,
) -> Scores:
    """Compute the full Ch. 8 score set. ``improvement`` is supplied by the
    caller (built via :func:`compute_improvement` from the player-history seam)."""
    categories = {c: _category_score(c, findings) for c in PERFORMANCE_CATEGORIES}
    confidence = _confidence_score(findings, facts)
    overall = _overall_score(categories)
    return Scores(
        overall=overall,
        technique=categories[TECHNIQUE],
        timing=categories[TIMING],
        power=categories[POWER],
        balance=categories[BALANCE],
        footwork=categories[FOOTWORK],
        confidence=confidence,
        improvement=improvement
        or ScoreEntry(value=None, confidence=None, unavailable_reason="no_history"),
    )
