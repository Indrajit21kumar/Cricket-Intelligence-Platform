CRICKET INTELLIGENCE PLATFORM
CIP BLUEPRINT
BOOK 4
Cricket Intelligence Standards
CIP-STD — the canonical metrics, ontology, conventions, and benchmark methodology
Document ID: CIP-B4-STD
Version: 1.0   ·   Status: Draft
Owner: CIP Labs  ·  Prepared for: Indrajit  ·  July 2026
CONFIDENTIAL — Founding Documentation

# Document Control
Field
Value
Document ID
CIP-B4-STD
Version
1.0 (Living Standard)
Status
Draft v1.0
Owner
CIP Labs — Research & Architecture
Author
Prepared for Indrajit (Founder)
Classification
Confidential
Date
July 2026

## Version History
Version
Date
Author
Summary of Change
0.1
Jul 2026
CIP Labs
Initial outline drafted in working sessions
1.0
Jul 2026
CIP Labs
First complete professional draft of this volume

## Revision & Approval Log
Role
Name
Status
Date
Author / Chief Architect
CIP Labs
Drafted
Jul 2026
Founder / Domain Authority
Indrajit
Pending review
—
Engineering Lead
TBD
Pending
—

## Dependencies (Inputs)
- Book 0 — Manifesto (Trust Doctrine)
- Book 1 — GCIR (science + requirements)
- Book 2 — Reference Architecture (engines as services)
- Book 3 — Engineering Standards (provenance, validation)

## Feeds Into (Downstream)
- Book 5 — Cricket Intelligence Benchmark Library (CIBL)
- Module 10 — Biomechanics Engine
- Module 11 — Physics Engine
- Module 12 — Cricket Knowledge Graph
- Module 15 — Benchmark Intelligence

# Contents
- Chapter 1 — Purpose & Status of This Standard
- Chapter 2 — Coordinate System & Measurement Conventions
- Chapter 3 — Canonical Metric Catalogue
- Chapter 4 — Physics Quantities & Provenance
- Chapter 5 — The Cricket Ontology
- Chapter 6 — Knowledge Rule Format (Fault → Cause → Risk → Drill)
- Chapter 7 — Confidence & Uncertainty Standard
- Chapter 8 — Scoring Standard
- Chapter 9 — Benchmark Methodology
- Appendix A — Metric Identifier Registry
- Appendix B — Traceability
- Appendix C — Glossary & Acronyms

# Chapter 1 — Purpose & Status of This Standard
Document ID: STD4-CH-001
CIP-STD is the single, authoritative definition of every metric, term, convention, and scoring rule used across the platform. It exists so that the Biomechanics Engine, Physics Engine, Knowledge Graph, Benchmark Intelligence, and Report Generator all speak the same language. If any module defines a metric differently from CIP-STD, the module is wrong.
This is a living standard: it is versioned and expected to grow as new metrics and rules are validated. Changes follow the governance in Chapter 9 and the versioning rules of Book 3. Every metric added here MUST carry a stable identifier (Appendix A), a unit, a valid range, and a provenance class (measured / estimated / modelled).
### Research Findings
- A shared standard is the prerequisite for services to interoperate and for benchmarks to be comparable.
### Business Implications
- Standardisation is CIP's wedge into academies and governing bodies (Book 1).
### Engineering Implications
- Every metric has a stable ID, unit, range, and provenance class.
- Modules import definitions from CIP-STD; they never redefine them.
### AI Implications
- Consistent metric identifiers are what make longitudinal learning and benchmarking possible.
### Future Research Questions
- What is the change-review quorum for adding a validated metric?
### Traceability
- Governs Modules M10, M11, M12, M15; feeds Book 5.

# Chapter 2 — Coordinate System & Measurement Conventions
Document ID: STD4-CH-002
## 2.1 Reference frame
All positional metrics are defined in a normalised, handedness-invariant batting reference frame, not raw pixels. Left-handed batters are mirrored so downstream logic is identical for both.
Axis
Direction
Positive toward
Origin
Ground point beneath mid-stance (ankle midpoint, first stance frame)
—
X
Along the batting crease
Off-side (for the normalised right-hand frame)
Y
Vertical
Up
Z
Down the pitch
The bowler
## 2.2 Units & sign conventions
- Angles in degrees; angular velocity in deg/s; linear distance in centimetres; linear velocity in m/s; time in milliseconds relative to a named event (e.g. bowler release).
- Flexion/extension, rotation direction, and tilt signs are fixed per metric in the catalogue (Chapter 3).
## 2.3 Scale & calibration
Pixel-to-metric scale is derived from a known reference (stump height 71.1cm when visible, else player height). Every positional metric carries spatial_confidence (high/medium/low). Depth (Z) from monocular video is estimated and carries depth_estimated = true, widening tolerance per Book 3, Chapter 6.
### Research Findings
- A single normalised, mirrored reference frame removes handedness special-casing everywhere downstream.
### Business Implications
- Consistent conventions make cross-player and cross-academy comparison valid.
### Engineering Implications
- All modules consume the same frame, units, and sign conventions.
- spatial_confidence and depth_estimated travel with every positional metric.
### AI Implications
- Normalised frames improve model transfer across camera setups.
### Future Research Questions
- Standard fallback when neither stumps nor reliable height is available?
### Traceability
- Feeds M10, M11; consistent with the earlier Biomechanics Engine chapter.

# Chapter 3 — Canonical Metric Catalogue
Document ID: STD4-CH-003
The authoritative biomechanical metric set. Each row is the definition modules MUST implement. Provenance is MEASURED for all of these (directly computed from observed pose/bat).
ID
Metric
Unit
Typical range
BM-01
Head stability (X-Z displacement, stance→impact)
cm
0–25 (elite <8)
BM-02
Shoulder rotation
deg
30–90
BM-03
Hip rotation
deg
25–80
BM-04
X-Factor (shoulder–hip separation)
deg
15–40
BM-05
Pelvic tilt
deg
-10 to +15
BM-06
Front knee flexion at impact
deg
140–170
BM-07
Foot alignment vs shot line
deg
-20 to +20
BM-08
Stride length (% of height)
%
25–45
BM-09
Backlift angle
deg
direction-dependent
BM-10
Bat path linearity (downswing R²)
ratio
0–1 (clean >0.85)
BM-11
Bat lag (peak)
deg
>20 elite
BM-12
Hand speed (peak, smoothed)
m/s
shot-dependent
BM-13
Follow-through angle
deg
shot-dependent
BM-14
Balance recovery time
ms
<400 elite
BM-15
Weight-transfer index (proxy)
ratio
0–1 (estimated proxy)
BM-16
Centre of mass trajectory
cm path
—
BM-17
Ground contact timing (vs release)
ms
context-dependent
Note: BM-15 is an estimated proxy (not a force measurement) and MUST be labelled accordingly per the Trust Doctrine.
### Research Findings
- Seventeen canonical measured metrics form the biomechanical vocabulary of the platform.
### Business Implications
- A fixed catalogue enables benchmarking, progress tracking, and academy comparison.
### Engineering Implications
- Modules implement these exact IDs/units/ranges; values outside range are flagged, not rejected (Book 3).
### AI Implications
- Stable IDs are training-label keys for future models.
### Future Research Questions
- Which additional metrics graduate from research (Book 1 Ch. 6) into this catalogue, and when?
### Traceability
- Implements Book 1 SR-003; feeds M10, M15.

# Chapter 4 — Physics Quantities & Provenance
Document ID: STD4-CH-004
Physics quantities are split explicitly by provenance. This split is the mechanism that keeps the Physics Engine both ambitious and honest (Book 0 §8).
ID
Quantity
Provenance
Basis
PH-01
Bat / hand linear speed
MEASURED
Position derivative (smoothed)
PH-02
Angular velocity / acceleration
MEASURED
Segment angle derivatives
PH-03
Bat lag / hip-shoulder separation
MEASURED
Relative segment orientation
PH-04
Centre of mass & balance
MEASURED
Weighted segment model
PH-05
Reaction / timing
MEASURED
Event-relative frame timing
PH-06
Momentum & impulse
ESTIMATED
Anthropometric mass × measured velocity
PH-07
Torque
ESTIMATED
Modelled from segment dynamics
PH-08
Kinetic energy & energy transfer
ESTIMATED
Modelled kinetic chain
PH-09
Ground reaction force
ESTIMATED
Modelled from kinematics (no force plate)
PH-10
Impact energy / ball-exit velocity
ESTIMATED
Modelled; requires bat/ball tracking
PH-11
Sweet-spot efficiency
ESTIMATED
Modelled contact quality
Every ESTIMATED quantity MUST be displayed with a confidence value (Chapter 7) and MUST NOT be presented as MEASURED.
### Research Findings
- Five physics quantities are measurable now; six are estimated by model.
### Business Implications
- Honest labelling is the trust differentiator with serious coaches and boards.
### Engineering Implications
- The Physics Engine emits provenance + confidence for every quantity.
### AI Implications
- Estimation models for PH-06..11 are validated against the golden dataset (Book 3 Ch. 6).
### Future Research Questions
- What validation data can bound GRF and ball-exit estimates (Book 1 Ch. 8)?
### Traceability
- Implements TRUST-001; feeds M11; consistent with Seven-Engine doc.

# Chapter 5 — The Cricket Ontology
Document ID: STD4-CH-005
The ontology is the vocabulary the Knowledge Graph reasons over. It defines the entity types and their allowed relationships. This is the schema of the platform's cricket intelligence.
## 5.1 Entity types
Entity
Definition
Examples
Shot
A classified batting stroke
Cover drive, pull, cut, sweep, defensive
Phase
A temporal segment of an action
Stance, backlift, downswing, impact, follow-through
Metric
A CIP-STD measured/estimated quantity
BM-01…, PH-01…
Fault
A named technical error
Head falling outside off; early shoulder opening
Cause
The mechanism producing a fault
Weight staying back; late foot movement
Risk
A match consequence
LBW, inside edge, outside edge, mistimed lofted shot
Drill
A corrective practice with measurable objective
Closed-shoulder drill; one-leg shadow batting
Delivery
The ball context
Line, length, pace, bowler type
## 5.2 Allowed relationships
Metric --indicates--> Fault
Fault --caused_by--> Cause
Fault --increases--> Risk (against a Delivery context)
Fault --corrected_by--> Drill
Drill --improves--> Metric
### Research Findings
- A small, fixed set of entity types and relationships expresses the full coaching logic.
### Business Implications
- The ontology is the structure of the core IP (encoded expertise).
### Engineering Implications
- The Knowledge Graph schema derives directly from these types.
- Rules (Ch. 6) are instances over this ontology.
### AI Implications
- This ontology is the grounding target for RAG-based Cricket GPT (evidence, not free text).
### Future Research Questions
- How are context-conditioned risks (per Delivery) weighted?
### Traceability
- Feeds M12, M13, M14; implements Book 1 Ch. 3 (encode coaching knowledge).

# Chapter 6 — Knowledge Rule Format
Document ID: STD4-CH-006
Every coaching rule is authored in a fixed structure so rules are reviewable, versioned, and machine-executable. This is the format the Knowledge Graph stores and the Reasoning Engine executes.
## 6.1 Rule schema
Field
Meaning
rule_id
Stable identifier (e.g. KG-RISK-002)
conditions
Metric thresholds / phase facts that trigger the rule
fault
The named fault asserted
cause
The mechanism
risk
Consequence + delivery context + magnitude
drill
Corrective drill with measurable objective
confidence
Rule confidence (0–1), authored + evidence-adjusted
author / version / status
Governance metadata (expert, version, review status)
## 6.2 Worked example
IF front_foot_plant is late (BM-17 > threshold) AND head_stability shows drift outside off (BM-01 direction) THEN fault = 'head falling outside off', cause = 'weight staying back', risk = 'LBW / inside edge vs full outside-off delivery (+~25%)', drill = 'closed-shoulder drill', confidence = 0.91.
### Research Findings
- A uniform rule schema makes thousands of expert rules governable and executable.
### Business Implications
- Rule authoring is where the founder's expertise becomes scalable IP.
### Engineering Implications
- Rules are data, not code; the Reasoning Engine executes them generically.
### AI Implications
- Rule confidence and evidence links keep AI coaching grounded and auditable.
### Future Research Questions
- Conflict resolution when multiple rules fire with different risks?
### Traceability
- Feeds M12, M13; consistent with v1 PRD Module 9 example.

# Chapter 7 — Confidence & Uncertainty Standard
Document ID: STD4-CH-007
Because trust depends on honest uncertainty (Book 0 §8, §11.4), CIP standardises how confidence is computed and communicated.
Source of uncertainty
How it is handled
Pose keypoint confidence
Aggregated to a mean; below threshold → provisional result
Spatial calibration
spatial_confidence high/medium/low on positional metrics
Monocular depth
depth_estimated flag; widened tolerance on Z-dependent metrics
Model estimation (physics)
Per-quantity confidence value (0–1)
Rule inference
Rule confidence combined with evidence strength
User-facing rule: confidence is always shown, never hidden; a low-confidence result is presented as such rather than as a precise number.
### Research Findings
- Uncertainty has defined sources and a defined communication rule.
### Business Implications
- Transparent confidence is what differentiates CIP from black-box scores.
### Engineering Implications
- Confidence propagates through the pipeline as first-class fields.
### AI Implications
- Calibration of model confidence is monitored (Book 2 Ch. 9).
### Future Research Questions
- How to combine independent confidences into a report-level confidence?
### Traceability
- Implements Book 0 §8/§11.4; feeds every engine and the Report Generator.

# Chapter 8 — Scoring Standard
Document ID: STD4-CH-008
Scores summarise performance for players and coaches. To be meaningful and comparable, they are computed from CIP-STD metrics via a defined, versioned method — not ad hoc per report.
Score
Derived from
Overall (0–100)
Weighted composite of the sub-scores below
Technique
Alignment of measured metrics to benchmark ranges
Timing
BM-17, BM-11, reaction metrics
Power
PH-01/02 (measured) + estimated energy (labelled)
Balance
BM-01, BM-14, centre-of-mass stability
Footwork
BM-07, BM-08, ground-contact timing
Confidence
Report-level confidence (Ch. 7)
Improvement
Change vs the player's own history (Cricket DNA)
Scores MUST expose their inputs on request (explainability, ENG-005) and MUST carry the report-level confidence.
### Research Findings
- A defined scoring method makes scores comparable across players and time.
### Business Implications
- Comparable scores power leaderboards, academy analytics, and progress narratives.
### Engineering Implications
- Scoring is a versioned function of CIP-STD metrics; changes are tracked.
### AI Implications
- Improvement score is grounded in the player's own longitudinal baseline (SR-001).
### Future Research Questions
- Weighting per skill tier / age band?
### Traceability
- Implements ENG-005, SR-001; feeds M14, Progress Analytics.

# Chapter 9 — Benchmark Methodology
Document ID: STD4-CH-009
Benchmarks are the reference values a player is compared against, including legend-derived benchmarks. This chapter defines how they are built, safely.
## 9.1 Benchmark types
Type
Definition
Use
Skill-tier benchmark
Aggregate metric distributions per skill level, from CIP's own dataset
Primary, rights-clean comparison
Age-band benchmark
Distributions per age group
Fair comparison for juniors
Legend-style benchmark
Reference ranges DERIVED from a legend's publicly observable technique
Aspirational comparison
Personal baseline
The player's own history
Improvement tracking
## 9.2 The endorsement guardrail (TRUST-002)
Legend-style benchmarks are reference models derived from publicly observable technique. CIP MUST NOT claim endorsement by any named professional, and MUST NOT use proprietary or licensed player datasets without permission. A 'Legend Similarity Score' compares a player across several benchmarks and explains the gaps; it never asserts a professional's involvement.
## 9.3 Governance (living standard)
- New benchmarks and metrics enter CIP-STD only after validation and expert review; each is versioned.
- Benchmark provenance and derivation method are documented in Book 5 (CIBL).
### Research Findings
- Four benchmark types, led by rights-clean skill-tier benchmarks from CIP's own data.
### Business Implications
- Legend comparison is a headline feature, delivered within safe legal bounds.
### Engineering Implications
- Benchmarks are versioned data served by M15; comparison logic is generic.
### AI Implications
- Benchmarks are derived, validated distributions — not opaque targets.
### Future Research Questions
- Minimum sample size before a skill-tier benchmark is publishable?
### Traceability
- Implements TRUST-002; feeds Book 5 and M15.

# Appendix A — Metric Identifier Registry
Stable identifiers referenced across all modules. IDs are permanent; definitions may be versioned.
Prefix
Domain
Range
BM-xx
Biomechanics (measured)
BM-01 … BM-17
PH-xx
Physics quantities
PH-01 … PH-11
KG-xxx
Knowledge rules
e.g. KG-RISK-002, KG-TIM-007, KG-PWR-014
SC-xx
Scores
Overall, Technique, Timing, Power, Balance, Footwork, Improvement
BN-xx
Benchmarks
Skill-tier, Age-band, Legend-style, Personal

# Appendix B — Traceability
Standard element
Traces to
Coordinate frame & conventions
Biomechanics Engine chapter; M10
Metric catalogue (BM)
SR-003; M10, M15
Physics provenance (PH)
TRUST-001; M11
Ontology + rule format
Book 1 Ch. 3; M12, M13
Confidence standard
Book 0 §8/§11.4
Scoring standard
ENG-005, SR-001; M14
Benchmark methodology
TRUST-002; Book 5, M15

# Appendix C — Glossary & Acronyms
Term / Acronym
Meaning
CIP-STD
Cricket Intelligence Standards (this book)
Ontology
The typed vocabulary of cricket entities and relationships
Fault → Cause → Risk → Drill
The canonical coaching reasoning chain
Provenance class
measured / estimated / modelled
Legend-style benchmark
Reference derived from publicly observable technique
Personal baseline
A player's own historical benchmark
Living standard
A versioned document expected to grow over time
X-Factor
Shoulder–hip separation, a power indicator

| Field | Value |
| Document ID | CIP-B4-STD |
| Version | 1.0 (Living Standard) |
| Status | Draft v1.0 |
| Owner | CIP Labs — Research & Architecture |
| Author | Prepared for Indrajit (Founder) |
| Classification | Confidential |
| Date | July 2026 |

| Version | Date | Author | Summary of Change |
| 0.1 | Jul 2026 | CIP Labs | Initial outline drafted in working sessions |
| 1.0 | Jul 2026 | CIP Labs | First complete professional draft of this volume |

| Role | Name | Status | Date |
| Author / Chief Architect | CIP Labs | Drafted | Jul 2026 |
| Founder / Domain Authority | Indrajit | Pending review | — |
| Engineering Lead | TBD | Pending | — |

| Axis | Direction | Positive toward |
| Origin | Ground point beneath mid-stance (ankle midpoint, first stance frame) | — |
| X | Along the batting crease | Off-side (for the normalised right-hand frame) |
| Y | Vertical | Up |
| Z | Down the pitch | The bowler |

| ID | Metric | Unit | Typical range |
| BM-01 | Head stability (X-Z displacement, stance→impact) | cm | 0–25 (elite <8) |
| BM-02 | Shoulder rotation | deg | 30–90 |
| BM-03 | Hip rotation | deg | 25–80 |
| BM-04 | X-Factor (shoulder–hip separation) | deg | 15–40 |
| BM-05 | Pelvic tilt | deg | -10 to +15 |
| BM-06 | Front knee flexion at impact | deg | 140–170 |
| BM-07 | Foot alignment vs shot line | deg | -20 to +20 |
| BM-08 | Stride length (% of height) | % | 25–45 |
| BM-09 | Backlift angle | deg | direction-dependent |
| BM-10 | Bat path linearity (downswing R²) | ratio | 0–1 (clean >0.85) |
| BM-11 | Bat lag (peak) | deg | >20 elite |
| BM-12 | Hand speed (peak, smoothed) | m/s | shot-dependent |
| BM-13 | Follow-through angle | deg | shot-dependent |
| BM-14 | Balance recovery time | ms | <400 elite |
| BM-15 | Weight-transfer index (proxy) | ratio | 0–1 (estimated proxy) |
| BM-16 | Centre of mass trajectory | cm path | — |
| BM-17 | Ground contact timing (vs release) | ms | context-dependent |

| ID | Quantity | Provenance | Basis |
| PH-01 | Bat / hand linear speed | MEASURED | Position derivative (smoothed) |
| PH-02 | Angular velocity / acceleration | MEASURED | Segment angle derivatives |
| PH-03 | Bat lag / hip-shoulder separation | MEASURED | Relative segment orientation |
| PH-04 | Centre of mass & balance | MEASURED | Weighted segment model |
| PH-05 | Reaction / timing | MEASURED | Event-relative frame timing |
| PH-06 | Momentum & impulse | ESTIMATED | Anthropometric mass × measured velocity |
| PH-07 | Torque | ESTIMATED | Modelled from segment dynamics |
| PH-08 | Kinetic energy & energy transfer | ESTIMATED | Modelled kinetic chain |
| PH-09 | Ground reaction force | ESTIMATED | Modelled from kinematics (no force plate) |
| PH-10 | Impact energy / ball-exit velocity | ESTIMATED | Modelled; requires bat/ball tracking |
| PH-11 | Sweet-spot efficiency | ESTIMATED | Modelled contact quality |

| Entity | Definition | Examples |
| Shot | A classified batting stroke | Cover drive, pull, cut, sweep, defensive |
| Phase | A temporal segment of an action | Stance, backlift, downswing, impact, follow-through |
| Metric | A CIP-STD measured/estimated quantity | BM-01…, PH-01… |
| Fault | A named technical error | Head falling outside off; early shoulder opening |
| Cause | The mechanism producing a fault | Weight staying back; late foot movement |
| Risk | A match consequence | LBW, inside edge, outside edge, mistimed lofted shot |
| Drill | A corrective practice with measurable objective | Closed-shoulder drill; one-leg shadow batting |
| Delivery | The ball context | Line, length, pace, bowler type |

| Field | Meaning |
| rule_id | Stable identifier (e.g. KG-RISK-002) |
| conditions | Metric thresholds / phase facts that trigger the rule |
| fault | The named fault asserted |
| cause | The mechanism |
| risk | Consequence + delivery context + magnitude |
| drill | Corrective drill with measurable objective |
| confidence | Rule confidence (0–1), authored + evidence-adjusted |
| author / version / status | Governance metadata (expert, version, review status) |

| Source of uncertainty | How it is handled |
| Pose keypoint confidence | Aggregated to a mean; below threshold → provisional result |
| Spatial calibration | spatial_confidence high/medium/low on positional metrics |
| Monocular depth | depth_estimated flag; widened tolerance on Z-dependent metrics |
| Model estimation (physics) | Per-quantity confidence value (0–1) |
| Rule inference | Rule confidence combined with evidence strength |

| Score | Derived from |
| Overall (0–100) | Weighted composite of the sub-scores below |
| Technique | Alignment of measured metrics to benchmark ranges |
| Timing | BM-17, BM-11, reaction metrics |
| Power | PH-01/02 (measured) + estimated energy (labelled) |
| Balance | BM-01, BM-14, centre-of-mass stability |
| Footwork | BM-07, BM-08, ground-contact timing |
| Confidence | Report-level confidence (Ch. 7) |
| Improvement | Change vs the player's own history (Cricket DNA) |

| Type | Definition | Use |
| Skill-tier benchmark | Aggregate metric distributions per skill level, from CIP's own dataset | Primary, rights-clean comparison |
| Age-band benchmark | Distributions per age group | Fair comparison for juniors |
| Legend-style benchmark | Reference ranges DERIVED from a legend's publicly observable technique | Aspirational comparison |
| Personal baseline | The player's own history | Improvement tracking |

| Prefix | Domain | Range |
| BM-xx | Biomechanics (measured) | BM-01 … BM-17 |
| PH-xx | Physics quantities | PH-01 … PH-11 |
| KG-xxx | Knowledge rules | e.g. KG-RISK-002, KG-TIM-007, KG-PWR-014 |
| SC-xx | Scores | Overall, Technique, Timing, Power, Balance, Footwork, Improvement |
| BN-xx | Benchmarks | Skill-tier, Age-band, Legend-style, Personal |

| Standard element | Traces to |
| Coordinate frame & conventions | Biomechanics Engine chapter; M10 |
| Metric catalogue (BM) | SR-003; M10, M15 |
| Physics provenance (PH) | TRUST-001; M11 |
| Ontology + rule format | Book 1 Ch. 3; M12, M13 |
| Confidence standard | Book 0 §8/§11.4 |
| Scoring standard | ENG-005, SR-001; M14 |
| Benchmark methodology | TRUST-002; Book 5, M15 |

| Term / Acronym | Meaning |
| CIP-STD | Cricket Intelligence Standards (this book) |
| Ontology | The typed vocabulary of cricket entities and relationships |
| Fault → Cause → Risk → Drill | The canonical coaching reasoning chain |
| Provenance class | measured / estimated / modelled |
| Legend-style benchmark | Reference derived from publicly observable technique |
| Personal baseline | A player's own historical benchmark |
| Living standard | A versioned document expected to grow over time |
| X-Factor | Shoulder–hip separation, a power indicator |