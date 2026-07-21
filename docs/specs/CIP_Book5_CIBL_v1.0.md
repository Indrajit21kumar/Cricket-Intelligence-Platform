CRICKET INTELLIGENCE PLATFORM
CIP BLUEPRINT
BOOK 5
Cricket Intelligence Benchmark Library
CIBL — reference profiles, derivation methodology, and the Legend Similarity Score
Document ID: CIP-B5-CIBL
Version: 1.0   ·   Status: Draft
Owner: CIP Labs  ·  Prepared for: Indrajit  ·  July 2026
CONFIDENTIAL — Founding Documentation

# Document Control
Field
Value
Document ID
CIP-B5-CIBL
Version
1.0 (Living Library)
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
- Book 0 — Manifesto (Trust Doctrine, endorsement guardrail)
- Book 3 — Engineering Standards (validation gates)
- Book 4 — CIP-STD (metric catalogue, benchmark methodology)

## Feeds Into (Downstream)
- Module 15 — Benchmark Intelligence Engine
- Module 14 — Report Generator / AI Coach (Legend Comparison)
- Module 16 — Cricket DNA (personal baselines)

# Contents
- Chapter 1 — Purpose & Legal Position
- Chapter 2 — Benchmark Profile Data Model
- Chapter 3 — Derivation Methodology
- Chapter 4 — Skill-Tier & Age-Band Benchmarks
- Chapter 5 — Legend-Style Benchmarks (Derived, Rights-Safe)
- Chapter 6 — The Legend Similarity Score
- Chapter 7 — Validation & Governance
- Appendix A — Provisional Reference Profile (Illustrative)
- Appendix B — Traceability
- Appendix C — Glossary & Acronyms

# Chapter 1 — Purpose & Legal Position
Document ID: CIBL-CH-001
The Benchmark Library is the store of reference values against which a player is compared. Comparison is central to CIP's value from the founder's first description of the product — analysis "based on the physics and all cricket legends batting." This book defines the benchmark data model, how each benchmark type is derived, and the methodology for the Legend Similarity Score.
## 1.1 The rights-safe position (binding)
CIP compares players against technical benchmarks derived from publicly observable technique. It does not claim endorsement by any named professional, and it does not use proprietary, licensed, or biometric datasets of any player without explicit permission. A 'Kohli-style backlift benchmark' is a reference model describing a publicly visible technical characteristic; it is not a claim that the player is involved with, or endorses, CIP. This position (TRUST-002) is a legal and ethical requirement, not a preference.
## 1.2 Status of values in this book
The numeric profiles in this v1.0 are PROVISIONAL and illustrative. Real benchmark values are populated only after derivation and validation per Chapters 3 and 7. No value in this document should be treated as a validated measurement until it carries a validation record.
### Research Findings
- Benchmarks are the comparison substrate; legend comparison is a headline feature delivered within strict rights limits.
### Business Implications
- Rights-safe derived benchmarks unlock the marketing hook without legal exposure.
### Engineering Implications
- Benchmarks are versioned data served by M15; comparison logic is generic.
### AI Implications
- Benchmarks are validated distributions, not opaque targets.
### Future Research Questions
- Which jurisdictions constrain likeness/technique derivation, and how?
### Traceability
- Implements TRUST-002; feeds M14, M15, M16.

# Chapter 2 — Benchmark Profile Data Model
Document ID: CIBL-CH-002
A benchmark profile is a versioned set of expected value distributions for CIP-STD metrics, scoped to a context (skill tier, age band, shot type, or legend style).
Field
Meaning
benchmark_id
Stable identifier (e.g. BN-TIER-ADV-COVERDRIVE)
type
skill_tier | age_band | legend_style | personal
scope
Context: skill tier / age band / shot type / handedness
metric_distributions
Per metric (BM/PH): mean, spread, and target range
derivation_method
How it was built (Chapter 3)
sample_size / source
Evidence base for the profile
validation_record
Validation status + date (Chapter 7)
version / status
Living-library version metadata
### Research Findings
- A single profile schema covers all four benchmark types.
### Business Implications
- Versioned profiles let CIP improve benchmarks without breaking comparisons.
### Engineering Implications
- Profiles are data; the Benchmark Engine compares generically against them.
### AI Implications
- Distributions (not single points) enable statistically honest gap statements.
### Future Research Questions
- Store full distributions or summary statistics only?
### Traceability
- Implements Book 4 Ch. 9; feeds M15.

# Chapter 3 — Derivation Methodology
Document ID: CIBL-CH-003
## 3.1 Skill-tier & age-band (primary, rights-clean)
Built from CIP's own consented dataset: aggregate the CIP-STD metric values of players grouped by skill tier (or age band), computing per-metric distributions. As the dataset grows, these benchmarks sharpen. These are the primary, safest benchmarks and carry no third-party rights concerns.
## 3.2 Legend-style (derived from public technique)
Built by characterising a legend's publicly observable technical signature (e.g. a high backlift, a still head, a particular trigger movement) from publicly available footage, and expressing it as target ranges on CIP-STD metrics. The output is a technical reference model, explicitly labelled as derived, never as the player's private data.
## 3.3 Personal baseline
A player's own historical distribution on each metric, maintained by Cricket DNA (M16). Used for improvement tracking (SR-001) and for framing gaps relative to the player's own progress.
### Research Findings
- Three derivation paths: aggregate-from-data, derive-from-public-technique, and personal-history.
### Business Implications
- Own-data benchmarks compound as a moat; legend-style benchmarks provide the aspirational hook.
### Engineering Implications
- Derivation pipelines feed the same profile schema (Ch. 2).
### AI Implications
- Legend-style derivation is a characterisation task over public footage, not dataset appropriation.
### Future Research Questions
- Minimum sample size before a tier benchmark is publishable?
### Traceability
- Implements Book 4 Ch. 9; feeds M15, M16.

# Chapter 4 — Skill-Tier & Age-Band Benchmarks
Document ID: CIBL-CH-004
Illustrative structure of a skill-tier benchmark for a cover drive. Values are PROVISIONAL placeholders to be populated from validated data.
Metric (CIP-STD)
Beginner
Intermediate
Advanced / Elite
BM-01 Head stability (cm)
12–20
8–14
<8
BM-04 X-Factor (deg)
8–18
15–30
20–40
BM-06 Front knee flexion (deg)
120–140
135–155
145–165
BM-08 Stride (% height)
20–30
28–40
32–45
BM-11 Bat lag (deg)
<12
12–22
>20
BM-14 Balance recovery (ms)
>700
400–700
<400
These bands drive the Technique score (Book 4 Ch. 8) and the 'coaching read' in reports. As CIP's dataset grows, bands narrow and become tier- and region-specific.
### Research Findings
- Tiered bands convert raw metrics into an interpretable performance level.
### Business Implications
- Tier benchmarks power fair comparison, leaderboards, and academy analytics.
### Engineering Implications
- Bands are versioned profile data; reports cite the band a player falls into.
### AI Implications
- Bands are refined continuously as the dataset grows (data flywheel).
### Future Research Questions
- Region-specific tiers (e.g. differing junior pathways) from what data volume?
### Traceability
- Feeds Book 4 scoring; M15; Progress Analytics.

# Chapter 5 — Legend-Style Benchmarks (Derived, Rights-Safe)
Document ID: CIBL-CH-005
Illustrative legend-style benchmark structure. Each is a DERIVED technical reference model from publicly observable technique, labelled 'style benchmark' — not the player's data, not an endorsement (Chapter 1). Values are PROVISIONAL.
Style benchmark
Signature technical traits (public, illustrative)
Front-foot-dominant, high-backlift style
High backlift; still head; strong front-foot transfer; full extension at impact
Compact, back-foot-strong style
Compact backlift; late play; strong back-foot game; quick hands
Unorthodox trigger-movement style
Pronounced trigger movement; deep crease position; strong leg-side access
Classical, side-on orthodox style
Textbook side-on alignment; high front elbow; straight bat path
CIP presents these as named 'styles' (optionally associated with a legend as a descriptive, rights-safe label) rather than claiming to reproduce any individual's private biomechanics. The comparison always explains the gap on CIP-STD metrics, never merely asserts a percentage.
### Research Findings
- Legend-style benchmarks are expressed as named technical styles over CIP-STD metrics.
### Business Implications
- Delivers the 'compare with legends' hook while staying rights-safe.
### Engineering Implications
- Style benchmarks share the profile schema; comparison is generic.
### AI Implications
- Derivation characterises public technique; it does not ingest proprietary data.
### Future Research Questions
- Curated set of named styles at launch — how many, and which?
### Traceability
- Implements TRUST-002; feeds M14 (Legend Comparison), M15.

# Chapter 6 — The Legend Similarity Score
Document ID: CIBL-CH-006
Rather than telling a player to copy one batter, CIP scores similarity across several style benchmarks and explains why — richer and safer than a single 'be like X' target (per Book 0 and the founder's own framing).
## 6.1 Method
- For each style benchmark, compute a per-metric distance between the player's CIP-STD metrics and the benchmark's target ranges.
- Aggregate distances into a similarity percentage per style (nearer the ranges = higher similarity).
- Return the ranked styles PLUS the specific metric gaps driving each score — the explanation, not just the number.
## 6.2 Illustrative output
Style benchmark
Similarity
Top gap explaining the score
Front-foot-dominant, high-backlift
82%
Backlift 42° vs benchmark ~65° — restricts arc
Classical side-on orthodox
79%
Front elbow lower than benchmark
Compact back-foot-strong
64%
Weaker back-foot transfer than benchmark
Every similarity figure MUST be accompanied by its driving gaps and the report-level confidence (Book 4 Ch. 7). A percentage without an explanation violates the explainability principle (ENG-005).
### Research Findings
- Multi-style similarity with explanations is superior to single-idol imitation.
### Business Implications
- A memorable, shareable feature that is also pedagogically sound.
### Engineering Implications
- Similarity is a generic distance over profile ranges; styles are pluggable.
### AI Implications
- Explanations are generated from the actual metric gaps, keeping output grounded.
### Future Research Questions
- Distance weighting per metric — equal, or importance-weighted by shot?
### Traceability
- Implements ENG-005, TRUST-002; feeds M14, M15.

# Chapter 7 — Validation & Governance
Document ID: CIBL-CH-007
- A benchmark profile MUST carry a validation record (method, sample size/source, date, reviewer) before it is served in production.
- Skill-tier and age-band benchmarks MUST meet a minimum sample size (to be fixed in governance) before publication.
- Legend-style benchmarks MUST document their public-source derivation and MUST NOT include proprietary data (TRUST-002).
- All benchmarks are versioned; changes follow the living-library governance and Book 3 versioning rules.
- Benchmarks are periodically re-validated as the dataset grows and technique norms evolve.
### Research Findings
- Benchmarks are governed artefacts with validation records, not static constants.
### Business Implications
- Documented validation is what lets CIP defend its comparisons to coaches and boards.
### Engineering Implications
- No un-validated profile is served; versioning enables safe evolution.
### AI Implications
- Re-validation keeps benchmarks aligned with the growing dataset.
### Future Research Questions
- Re-validation cadence and trigger thresholds?
### Traceability
- Implements Book 3 Ch. 6; TRUST-002; feeds M15.

# Appendix A — Provisional Reference Profile (Illustrative)
Example of one fully-structured (but PROVISIONAL) profile object, showing the fields the Benchmark Engine consumes. Values are placeholders pending validation.
Field
Example value
benchmark_id
BN-TIER-ADV-COVERDRIVE
type
skill_tier
scope
tier=advanced; shot=cover_drive; hand=normalised
BM-01 target
< 8 cm
BM-04 target
20–40 deg
BM-11 target
> 20 deg
derivation_method
Aggregate of consented advanced-tier cover drives
sample_size / source
PROVISIONAL — pending dataset
validation_record
NOT YET VALIDATED
version / status
v0.1 / draft

# Appendix B — Traceability
Element
Traces to
Rights-safe position
TRUST-002; Book 0 §11.2
Profile data model
Book 4 Ch. 9
Derivation methodology
Book 4 Ch. 9; M15, M16
Legend Similarity Score
ENG-005; Seven-Engine doc §5
Validation & governance
Book 3 Ch. 6

# Appendix C — Glossary & Acronyms
Term / Acronym
Meaning
CIBL
Cricket Intelligence Benchmark Library (this book)
Benchmark profile
Versioned set of expected metric distributions for a context
Skill-tier benchmark
Aggregate from CIP's own data, by skill level
Legend-style benchmark
Derived reference from publicly observable technique
Personal baseline
A player's own historical distribution
Legend Similarity Score
Explained similarity across several style benchmarks
Validation record
Documented evidence that a benchmark is fit to serve
Provisional
Placeholder pending derivation and validation

| Field | Value |
| Document ID | CIP-B5-CIBL |
| Version | 1.0 (Living Library) |
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

| Field | Meaning |
| benchmark_id | Stable identifier (e.g. BN-TIER-ADV-COVERDRIVE) |
| type | skill_tier | age_band | legend_style | personal |
| scope | Context: skill tier / age band / shot type / handedness |
| metric_distributions | Per metric (BM/PH): mean, spread, and target range |
| derivation_method | How it was built (Chapter 3) |
| sample_size / source | Evidence base for the profile |
| validation_record | Validation status + date (Chapter 7) |
| version / status | Living-library version metadata |

| Metric (CIP-STD) | Beginner | Intermediate | Advanced / Elite |
| BM-01 Head stability (cm) | 12–20 | 8–14 | <8 |
| BM-04 X-Factor (deg) | 8–18 | 15–30 | 20–40 |
| BM-06 Front knee flexion (deg) | 120–140 | 135–155 | 145–165 |
| BM-08 Stride (% height) | 20–30 | 28–40 | 32–45 |
| BM-11 Bat lag (deg) | <12 | 12–22 | >20 |
| BM-14 Balance recovery (ms) | >700 | 400–700 | <400 |

| Style benchmark | Signature technical traits (public, illustrative) |
| Front-foot-dominant, high-backlift style | High backlift; still head; strong front-foot transfer; full extension at impact |
| Compact, back-foot-strong style | Compact backlift; late play; strong back-foot game; quick hands |
| Unorthodox trigger-movement style | Pronounced trigger movement; deep crease position; strong leg-side access |
| Classical, side-on orthodox style | Textbook side-on alignment; high front elbow; straight bat path |

| Style benchmark | Similarity | Top gap explaining the score |
| Front-foot-dominant, high-backlift | 82% | Backlift 42° vs benchmark ~65° — restricts arc |
| Classical side-on orthodox | 79% | Front elbow lower than benchmark |
| Compact back-foot-strong | 64% | Weaker back-foot transfer than benchmark |

| Field | Example value |
| benchmark_id | BN-TIER-ADV-COVERDRIVE |
| type | skill_tier |
| scope | tier=advanced; shot=cover_drive; hand=normalised |
| BM-01 target | < 8 cm |
| BM-04 target | 20–40 deg |
| BM-11 target | > 20 deg |
| derivation_method | Aggregate of consented advanced-tier cover drives |
| sample_size / source | PROVISIONAL — pending dataset |
| validation_record | NOT YET VALIDATED |
| version / status | v0.1 / draft |

| Element | Traces to |
| Rights-safe position | TRUST-002; Book 0 §11.2 |
| Profile data model | Book 4 Ch. 9 |
| Derivation methodology | Book 4 Ch. 9; M15, M16 |
| Legend Similarity Score | ENG-005; Seven-Engine doc §5 |
| Validation & governance | Book 3 Ch. 6 |

| Term / Acronym | Meaning |
| CIBL | Cricket Intelligence Benchmark Library (this book) |
| Benchmark profile | Versioned set of expected metric distributions for a context |
| Skill-tier benchmark | Aggregate from CIP's own data, by skill level |
| Legend-style benchmark | Derived reference from publicly observable technique |
| Personal baseline | A player's own historical distribution |
| Legend Similarity Score | Explained similarity across several style benchmarks |
| Validation record | Documented evidence that a benchmark is fit to serve |
| Provisional | Placeholder pending derivation and validation |