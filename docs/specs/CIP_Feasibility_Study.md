Cricket Intelligence Platform
Feasibility Study & Infrastructure Plan
Can this be built? What will it take? What will it cost?
Prepared for: Indrajit  |  July 2026

# 1. Bottom Line Up Front
Verdict: The Cricket Intelligence Platform is feasible to build, but not as a single monolithic product. The vision as written in the PRD spans roughly 15 distinct hard problems. About a third of them are proven and buildable today with off-the-shelf technology; a third are buildable but require serious R&D and a proprietary dataset; and a third (the parts that promise motion-capture-lab precision, force/energy measurement, and injury prediction from a phone video) are at or beyond the current research frontier and should be treated as long-term research bets, not launch features.
The correct path is a narrow, honest MVP built on the proven layer, launched to real cricketers, generating the proprietary video dataset that is the only durable moat and the only thing that makes the hard modules possible later. The technology risk is real but manageable; the bigger risks are dataset acquisition and the gap between marketing claims ("elite biomechanics from any phone") and physically achievable accuracy.
## Feasibility at a glance
Dimension
Rating
Summary
Technical (MVP scope)
Feasible
Pose estimation, shot classification, 2D biomechanics and an LLM coach are all demonstrated in shipping products and peer-reviewed papers.
Technical (full PRD vision)
Partly frontier
Force/energy/injury prediction and mocap-grade precision from monocular phone video are not solved problems; treat as research.
Infrastructure
Feasible & affordable
Per-video processing cost is a few cents. Cloud GPU + storage + LLM are mature, cheap, and elastic.
Data / dataset
Hardest problem
No public labelled cricket-biomechanics dataset at scale. You must build it. This is the true bottleneck and the moat.
Market
Validated
Competitors exist and are funded, proving demand; none dominate the AI-coaching niche for cricket batting.
Capital / team
Significant
A credible build needs ML + CV specialists, a cricket biomechanics expert, and 12-18 months to a defensible product.

# 2. Technical Feasibility, Module by Module
The single most important idea in this study: the PRD's modules are not equally hard. Grouping them by maturity turns a vague "is this possible?" into a concrete build order. Ratings below are grounded in shipping products (SwingVision, Uplift Labs, HomeCourt, StanceBeam, CricVision) and peer-reviewed work (BioPose WACV 2025, OpenCap, cricket shot-classification studies reaching 95-99% on constrained data).
## Green — proven, buildable now
Capability
Why it is feasible
Human pose estimation from phone video
MediaPipe / MoveNet / ViTPose are production-grade and free. This is the foundation and it works.
Shot classification (drive, pull, cut, sweep, etc.)
Peer-reviewed cricket studies reach 95-99% accuracy on curated clips using pose + a classifier. Real-world numbers will be lower but the approach is sound.
2D joint angles & basic biomechanics
Angles, rotations, stride, head movement in the image plane are directly computable from pose keypoints.
LLM-based AI coach / report explainer
Feeding computed metrics into a Claude/GPT prompt to generate coaching text is a solved integration pattern (SwingVision, Uplift already do this).
Progress tracking, dashboards, academy platform
Standard SaaS web/app engineering. No novel risk.
## Amber — buildable, but needs R&D + your own labelled data
Capability
The catch
True 3D biomechanics from ONE camera
Monocular 3D 'lifting' works (BioPose, OpenCap) but carries a few cm / few degrees of error and needs careful calibration. Good enough for coaching cues, not for lab-grade claims.
Bat tracking (angle, swing plane, sweet spot)
Feasible with a custom-trained detector, but you must label thousands of cricket frames — no off-the-shelf model knows a cricket bat.
Ball tracking from a phone
Hardest of the vision tasks. A cricket ball is small, and at 30-60fps a fast delivery is a motion-blurred streak. Research systems work only under 'constrained capture conditions'. Expect to require good lighting, a fixed camera, and honest confidence flags.
The Cricket Knowledge Engine (rules IP)
Technically simple (a rule engine) but the value is in thousands of expert-authored, validated rules. That is a multi-year coaching-expertise effort, not a coding task.
## Red — research frontier, do NOT promise at launch
Capability
Reality check
Force, torque, energy, ground-reaction force
You cannot measure force from a video. These require force plates or validated models. Anything shown must be labelled a rough estimate, or it is misleading.
Injury prediction
An unsolved research problem even in funded sports-science labs. Reputationally and legally risky to ship.
Digital twin / player simulation
Long-horizon research. Fine as a north-star, not a roadmap item with a date.
'Motion-capture-grade' precision from any phone
Physically constrained by monocular depth error (~4-7cm). Do not market against $50k mocap on accuracy — market on accessibility and coaching value.

# 3. The Real Bottleneck Is Data, Not Code
Every serious component above (bat detector, ball tracker, shot classifier that survives contact with real users, the whole knowledge engine) depends on a large, labelled, cricket-specific video dataset. This does not exist publicly. This is simultaneously the biggest obstacle and the only defensible moat — competitors can copy your app in months but cannot copy a proprietary dataset of hundreds of thousands of expert-annotated strokes.
Practical consequences for the plan:
- Budget for data annotation as a first-class, ongoing cost line — likely comparable to or exceeding your cloud bill in year one.
- You need a validation set filmed against real motion-capture (even a modest markerless mocap like OpenCap) to honestly state accuracy. Without ground truth you cannot claim any number.
- Design the MVP so that every user upload, with consent, becomes labelled training data. The product is also your data-collection engine. This flywheel is the strategy.
- Recruit a cricket biomechanics / coaching authority early. The knowledge engine's credibility is a human-expertise asset, not an algorithm.

# 4. Infrastructure You Actually Need
Good news: the infrastructure is mature, elastic, and cheap. Nothing here is a blocker. Below is a pragmatic MVP stack, then the cost model.
## 4.1 MVP reference architecture
Layer
Recommended for MVP
Notes
Client
React Native mobile app (capture + guidance overlay) + Next.js web dashboard
On-device camera guidance (angle/lighting/framing) massively improves downstream accuracy.
API / backend
FastAPI (Python) behind an API gateway; managed Postgres + Redis
Python keeps you in one language as backend and ML. PRD's stack choice is sound.
Object storage
S3 (or GCS) for raw + processed video
~$0.023/GB-month. Use lifecycle rules to tier old video to cold storage.
Async pipeline
Queue (SQS/Kafka) → GPU worker pool → results DB
Video analysis is a background job, not a live request. Decouple upload from processing.
GPU inference
Autoscaling pool of NVIDIA L4 (or T4) workers
L4 ~$0.72/GPU-hr on GCP; T4 ~$0.35-0.53/hr. Scale to zero when idle.
ML models
MediaPipe/ViTPose (pose) + custom YOLO (bat/ball) + classifier + monocular 3D lifter
Start with pretrained; fine-tune the cricket-specific pieces on your data.
AI Coach
Claude Haiku/Sonnet or GPT via API, RAG over the knowledge engine
No need to host your own LLM. API is cheaper and better until real scale.
Infra / ops
Docker + Kubernetes (or managed equiv.), one cloud to start
PRD lists AWS+Azure+GCP; pick ONE for the MVP to avoid multi-cloud overhead.
## 4.2 Per-video processing cost (the number that matters)
A single short batting clip (10-30s) costs only a few cents to process end to end. Illustrative build-up for a ~20-second clip, at 2026 cloud prices:
Cost component
Basis (2026 pricing)
Per-video estimate
GPU inference (pose+bat+ball+3D)
L4 @ ~$0.72/hr; ~30-90s GPU time/clip
$0.006 - $0.018
Transcode / preprocess
GCP Transcoder ~$0.01/min HD
~$0.003 - $0.005
Storage (raw + processed)
S3 @ $0.023/GB-mo; ~100-200MB/clip
~$0.003 - $0.005 / month held
AI Coach report (LLM)
Haiku $1/$5 per M tok; ~5k in / 2k out
~$0.015 (Haiku) to ~$0.05 (Sonnet)
TOTAL variable cost per analysis

~$0.03 - $0.08
Implication: unit economics are healthy. At, say, a $10/month Pro plan a user would need to run hundreds of analyses per month before processing cost becomes a concern. The cost risk is NOT per-inference — it is the fixed R&D and data-labelling investment, plus idle GPU if the pool is not scaled to zero.
## 4.3 Rough monthly infra at three scales
Scale
Approx. analyses/mo
Indicative cloud+LLM run-rate
Main driver
Prototype / beta
1,000s
$100s - low $1,000s / mo
Mostly idle GPU + dev environments
Early product
10,000s
Low-to-mid $1,000s / mo
GPU worker pool + storage growth
Scaling
100,000s+
$10,000s / mo
GPU throughput + video storage + LLM calls
These are run-rates for the compute/storage/LLM layer only. They exclude salaries, data annotation, and mocap validation, which will dominate total spend in year one.

# 5. Team, Timeline & Capital
The infrastructure is cheap; the expertise is not. A credible build requires a small but specialised team and patience through a data-gathering phase before the 'magic' features become accurate.
## Minimum credible team
- 1-2 Computer Vision / ML engineers (pose, detection, tracking, model fine-tuning).
- 1 Backend / infra engineer (pipeline, API, cloud, GPU orchestration).
- 1 Mobile + 1 web/frontend engineer (or one strong full-stack).
- 1 Cricket biomechanics / high-performance coaching expert (part-time acceptable) — non-negotiable for credibility of the knowledge engine and validation.
- A data-annotation function (outsourced labelling + expert review workflow).
## Indicative phasing
Phase
~Duration
Goal
Ships
0. Proof of concept
1-2 months
De-risk the core: does pose+shot-classification work on YOUR real clips?
Internal demo, honest accuracy numbers
1. Narrow MVP
3-5 months
One camera angle, front-foot drives, 2D biomechanics + AI coach
Private beta to real cricketers
2. Data flywheel
6-12 months
Grow labelled dataset; fine-tune bat detector + monocular 3D; validate vs mocap
Public launch, Pro tier
3. Depth & scale
12-18 months+
Ball tracking, academy platform, richer knowledge engine
Academy/enterprise tiers

# 6. Key Risks & Mitigations
Risk
Severity
Mitigation
Accuracy over-promise vs monocular physics limits
High
Market on accessibility & coaching value, not lab precision. Show confidence flags. Never claim force/injury without validation.
No proprietary dataset to train on
High
Make the MVP a data-collection engine. Budget for annotation. Recruit coaching experts to label.
Ball tracking fails in real conditions
Medium-High
Ship batting biomechanics first WITHOUT relying on ball tracking. Add it later, gated behind capture-quality requirements.
Scope: PRD tries to do 15 hard things at once
High
Enforce the green/amber/red build order. Resist launching red features.
Privacy: minors' video (users aged 8+)
High
GDPR/COPPA-grade consent, parental consent flows, strict data handling from day one — not an afterthought.
Competitors (StanceBeam, CricVision, Game Sense)
Medium
Differentiate on explanation depth + dataset moat, not on having an app. The category is validated, not saturated.
Idle GPU cost
Low
Scale worker pool to zero; batch process; use spot/preemptible instances for training.

# 7. Recommendation
Proceed — with a disciplined narrowing of scope.
The project is feasible and the market is real. Build the green layer first: a mobile app that captures a batting video from one guided camera angle, runs pose estimation and shot classification, computes 2D biomechanics, and uses an LLM to deliver a genuinely useful, explained coaching report. That product is achievable in months on cheap, mature infrastructure, and it is already differentiated if the coaching explanations are good.
Treat the amber layer (true 3D, bat/ball tracking, the deep knowledge engine) as earned progress unlocked by the dataset your MVP collects. Treat the red layer (force, energy, injury prediction, digital twin) as long-term research and marketing north-stars — never as launch commitments, because promising measurements a phone physically cannot make is the fastest way to lose credibility.
Before writing production code, do the 1-2 month proof of concept: run your candidate pipeline on a few hundred of your own real cricket clips and measure honest accuracy. That single step will tell you more about feasibility than any further planning, and it is the natural next deliverable after this study.
In one line: the code is the easy part, the infrastructure is cheap, the data and the honesty about physical limits are what will make or break this.
## Sources
- BioPose: Biomechanically-accurate 3D Pose Estimation from Monocular Videos (WACV 2025) — arxiv.org/abs/2501.07800
- OpenCap Monocular: 3D Kinematics from a Single Smartphone Video — utahmobl.github.io/OpenCap-monocular-project-page
- HGcnMLP markerless 3D pose vs VICON (Frontiers Bioeng., r=0.81-0.98) — frontiersin.org / PMC10803458
- Enhancing Cricket Performance Analysis with HPE & ML (Sensors 2023) — mdpi.com/1424-8220/23/15/6839
- Deep learning cricket batting shot classification (Scientific Reports) — nature.com/articles/s41598-026-52617-1
- Cricket umpire assistance & ball tracking, single smartphone camera — peerj.com/preprints/3402
- SwingVision (single-camera AI tennis) — swing.vision ; Uplift Labs — uplift.ai ; HomeCourt — futurism.com/athletes-ai-coaches-homecourt
- StanceBeam cricket sensor — stancebeam.com ; CricVision — cricvision.ai ; Game Sense — gamesense.au
- Cricket Analysis Software Market 2025 ($1.12B software) — dataintelo.com
- Cloud GPU pricing 2026 (L4/T4/A10G) — getdeploying.com, tcoiq.com, thundercompute.com
- Video transcoding & S3 pricing 2026 — spendark.com, cloudzero.com/blog/s3-pricing, aws.amazon.com/s3/pricing
- LLM API pricing 2026 (Claude/GPT) — platform.claude.com/docs, benchlm.ai/llm-pricing

| Dimension | Rating | Summary |
| Technical (MVP scope) | Feasible | Pose estimation, shot classification, 2D biomechanics and an LLM coach are all demonstrated in shipping products and peer-reviewed papers. |
| Technical (full PRD vision) | Partly frontier | Force/energy/injury prediction and mocap-grade precision from monocular phone video are not solved problems; treat as research. |
| Infrastructure | Feasible & affordable | Per-video processing cost is a few cents. Cloud GPU + storage + LLM are mature, cheap, and elastic. |
| Data / dataset | Hardest problem | No public labelled cricket-biomechanics dataset at scale. You must build it. This is the true bottleneck and the moat. |
| Market | Validated | Competitors exist and are funded, proving demand; none dominate the AI-coaching niche for cricket batting. |
| Capital / team | Significant | A credible build needs ML + CV specialists, a cricket biomechanics expert, and 12-18 months to a defensible product. |

| Capability | Why it is feasible |
| Human pose estimation from phone video | MediaPipe / MoveNet / ViTPose are production-grade and free. This is the foundation and it works. |
| Shot classification (drive, pull, cut, sweep, etc.) | Peer-reviewed cricket studies reach 95-99% accuracy on curated clips using pose + a classifier. Real-world numbers will be lower but the approach is sound. |
| 2D joint angles & basic biomechanics | Angles, rotations, stride, head movement in the image plane are directly computable from pose keypoints. |
| LLM-based AI coach / report explainer | Feeding computed metrics into a Claude/GPT prompt to generate coaching text is a solved integration pattern (SwingVision, Uplift already do this). |
| Progress tracking, dashboards, academy platform | Standard SaaS web/app engineering. No novel risk. |

| Capability | The catch |
| True 3D biomechanics from ONE camera | Monocular 3D 'lifting' works (BioPose, OpenCap) but carries a few cm / few degrees of error and needs careful calibration. Good enough for coaching cues, not for lab-grade claims. |
| Bat tracking (angle, swing plane, sweet spot) | Feasible with a custom-trained detector, but you must label thousands of cricket frames — no off-the-shelf model knows a cricket bat. |
| Ball tracking from a phone | Hardest of the vision tasks. A cricket ball is small, and at 30-60fps a fast delivery is a motion-blurred streak. Research systems work only under 'constrained capture conditions'. Expect to require good lighting, a fixed camera, and honest confidence flags. |
| The Cricket Knowledge Engine (rules IP) | Technically simple (a rule engine) but the value is in thousands of expert-authored, validated rules. That is a multi-year coaching-expertise effort, not a coding task. |

| Capability | Reality check |
| Force, torque, energy, ground-reaction force | You cannot measure force from a video. These require force plates or validated models. Anything shown must be labelled a rough estimate, or it is misleading. |
| Injury prediction | An unsolved research problem even in funded sports-science labs. Reputationally and legally risky to ship. |
| Digital twin / player simulation | Long-horizon research. Fine as a north-star, not a roadmap item with a date. |
| 'Motion-capture-grade' precision from any phone | Physically constrained by monocular depth error (~4-7cm). Do not market against $50k mocap on accuracy — market on accessibility and coaching value. |

| Layer | Recommended for MVP | Notes |
| Client | React Native mobile app (capture + guidance overlay) + Next.js web dashboard | On-device camera guidance (angle/lighting/framing) massively improves downstream accuracy. |
| API / backend | FastAPI (Python) behind an API gateway; managed Postgres + Redis | Python keeps you in one language as backend and ML. PRD's stack choice is sound. |
| Object storage | S3 (or GCS) for raw + processed video | ~$0.023/GB-month. Use lifecycle rules to tier old video to cold storage. |
| Async pipeline | Queue (SQS/Kafka) → GPU worker pool → results DB | Video analysis is a background job, not a live request. Decouple upload from processing. |
| GPU inference | Autoscaling pool of NVIDIA L4 (or T4) workers | L4 ~$0.72/GPU-hr on GCP; T4 ~$0.35-0.53/hr. Scale to zero when idle. |
| ML models | MediaPipe/ViTPose (pose) + custom YOLO (bat/ball) + classifier + monocular 3D lifter | Start with pretrained; fine-tune the cricket-specific pieces on your data. |
| AI Coach | Claude Haiku/Sonnet or GPT via API, RAG over the knowledge engine | No need to host your own LLM. API is cheaper and better until real scale. |
| Infra / ops | Docker + Kubernetes (or managed equiv.), one cloud to start | PRD lists AWS+Azure+GCP; pick ONE for the MVP to avoid multi-cloud overhead. |

| Cost component | Basis (2026 pricing) | Per-video estimate |
| GPU inference (pose+bat+ball+3D) | L4 @ ~$0.72/hr; ~30-90s GPU time/clip | $0.006 - $0.018 |
| Transcode / preprocess | GCP Transcoder ~$0.01/min HD | ~$0.003 - $0.005 |
| Storage (raw + processed) | S3 @ $0.023/GB-mo; ~100-200MB/clip | ~$0.003 - $0.005 / month held |
| AI Coach report (LLM) | Haiku $1/$5 per M tok; ~5k in / 2k out | ~$0.015 (Haiku) to ~$0.05 (Sonnet) |
| TOTAL variable cost per analysis |  | ~$0.03 - $0.08 |

| Scale | Approx. analyses/mo | Indicative cloud+LLM run-rate | Main driver |
| Prototype / beta | 1,000s | $100s - low $1,000s / mo | Mostly idle GPU + dev environments |
| Early product | 10,000s | Low-to-mid $1,000s / mo | GPU worker pool + storage growth |
| Scaling | 100,000s+ | $10,000s / mo | GPU throughput + video storage + LLM calls |

| Phase | ~Duration | Goal | Ships |
| 0. Proof of concept | 1-2 months | De-risk the core: does pose+shot-classification work on YOUR real clips? | Internal demo, honest accuracy numbers |
| 1. Narrow MVP | 3-5 months | One camera angle, front-foot drives, 2D biomechanics + AI coach | Private beta to real cricketers |
| 2. Data flywheel | 6-12 months | Grow labelled dataset; fine-tune bat detector + monocular 3D; validate vs mocap | Public launch, Pro tier |
| 3. Depth & scale | 12-18 months+ | Ball tracking, academy platform, richer knowledge engine | Academy/enterprise tiers |

| Risk | Severity | Mitigation |
| Accuracy over-promise vs monocular physics limits | High | Market on accessibility & coaching value, not lab precision. Show confidence flags. Never claim force/injury without validation. |
| No proprietary dataset to train on | High | Make the MVP a data-collection engine. Budget for annotation. Recruit coaching experts to label. |
| Ball tracking fails in real conditions | Medium-High | Ship batting biomechanics first WITHOUT relying on ball tracking. Add it later, gated behind capture-quality requirements. |
| Scope: PRD tries to do 15 hard things at once | High | Enforce the green/amber/red build order. Resist launching red features. |
| Privacy: minors' video (users aged 8+) | High | GDPR/COPPA-grade consent, parental consent flows, strict data handling from day one — not an afterthought. |
| Competitors (StanceBeam, CricVision, Game Sense) | Medium | Differentiate on explanation depth + dataset moat, not on having an app. The category is validated, not saturated. |
| Idle GPU cost | Low | Scale worker pool to zero; batch process; use spot/preemptible instances for training. |