Cricket Intelligence Platform
The Seven-Engine Architecture
Explainable AI cricket coaching, built on physics and legend benchmarks
Phase 1 in detail  ·  Honest roadmap to Phase 4
Prepared for: Indrajit  |  July 2026

# 1. What You Are Building
The product is not a pose-detection app. It is an explainable cricket coach that answers WHY, not just WHAT. Where existing tools stop at "your elbow is 118°," this platform continues: "that elbow angle reduces bat acceleration ~9%, which against 135 km/h bowling raises inside-edge probability — here is the drill to fix it."
That reasoning chain is the entire product, and it is built from two things generic AI companies do not have: physics, and encoded elite cricket expertise (20+ years of Ranji cricket and PIR Cricket Academy). Software alone is easy to copy; cricket intelligence is not.
## The explainable chain (the spine of every report)
Video
↓  Computer Vision  (pose · bat · ball)
↓  Biomechanics     (angles · timing · positions)
↓  Physics          (speed · momentum · energy transfer)
↓  Cricket Knowledge (why it matters, coach reasoning)
↓  Match Consequence (which deliveries punish it)
↓  Fix              (drill + expected improvement)
Two features sit at the centre of this vision from your very first description — analysis "based on the physics and all cricket legends batting": the Physics Engine and Legend Comparison. They are not add-ons; they are the founding premise, and this architecture treats them as core.

# 2. The Architecture at a Glance
Your seven Intelligence Engines are the top layer of the platform. They sit on a shared Foundation (the vision pipeline that gives them data, and the SaaS platform that delivers it). Legend Comparison is a cross-engine capability powered by Physics, Biomechanics, and Batting DNA together.
Layer
Contains
Role
Intelligence Engines (7)
Physics · Knowledge Graph · Batting DNA · Match Intelligence · Learning · Digital Twin · Cricket GPT
The brain. Turns measurements into explanation, comparison, prediction, coaching.
Vision Foundation
Video Intelligence · Pose · Bat Detection · Ball Tracking · Shot Recognition · Biomechanics Measurement
The eyes. Extracts raw movement data the engines reason over.
SaaS Platform
Auth & Roles · Subscription/Billing · Player Profile & Progress · Dashboards · Academy Console · Admin
The product. Accounts, payments, delivery, academies.
Legend Comparison: a comparison layer that scores the player's physics + biomechanics against reference benchmarks derived from legends' publicly observable technique — highlighted throughout because it is central to your idea.

# 3. The Foundation (Vision + SaaS)
Built first, because every engine depends on it. This is the proven, standard-engineering layer — no engine can reason without the data the Foundation produces.
## 3.1 Vision Foundation — the eyes
Component
What it produces
Phase 1?
Video Intelligence
Stabilised, normalised clip; camera-angle & quality check; capture guidance
Yes
Pose Engine
Body keypoints per frame (MediaPipe/MoveNet/ViTPose)
Yes
Biomechanics Measurement
Angles, rotations, stride, head movement, timing (2D)
Yes
Bat Detection
Bat position, angle, swing plane per frame (custom-trained)
Phase 2
Ball Tracking
Line, length, bounce, contact, speed (constrained conditions)
Phase 2
Shot Recognition
Cover drive, pull, cut, sweep, defensive, etc.
Phase 1 (basic) → 2
## 3.2 SaaS Platform — the product
Auth & Roles (player / coach / academy / admin, multi-tenant); Subscription & Billing (Free / Pro / Academy / Enterprise); Player Profile & Progress Tracking; Dashboard, Notifications & annotated-video Media Library; Academy / Coach Console; Admin & Platform Analytics. Standard SaaS engineering, reused by all disciplines.

# 4. The Seven Intelligence Engines
Each engine below states its purpose, when it comes online, and — for the physics-heavy ones — an honest split between what is MEASURED from video and what is ESTIMATED by model. That labelling is what makes the numbers trustworthy (your own "Confidence 97%" instinct), not a reduction of ambition.
## Engine 1 — Cricket Physics Engine  (your biggest IP)
Purpose: convert movement into the physics of the shot — the layer almost no competitor models from ordinary smartphone video. This is the core differentiator.
MEASURED from video (feasible now)
ESTIMATED by model (show as estimate + confidence)
Bat & hand speed
Angular velocity / acceleration
Bat lag
Hip–shoulder separation
Center of mass & balance
Reaction / timing (ms)
Bat face orientation (with bat detection)
Momentum & impulse
Torque
Kinetic energy & energy transfer
Ground reaction force
Impact energy & ball-exit velocity
Sweet-spot efficiency
Phase 1 ships the measured kinematics (speed, timing, separation, balance). Phase 2 adds the estimated dynamics once bat/ball tracking and validated models are in — each clearly labelled "estimated." You never lose the physics story; you tell it honestly.
## Engine 2 — Cricket Knowledge Graph  (your expertise, encoded)
Purpose: reason like a coach, not a sensor. Turns a measurement into a causal chain: elbow 122° → early shoulder opening → head falls outside off → weight stays back → bat comes across → likely LBW or inside edge → drill. This is where your Ranji + academy experience becomes irreplaceable IP. Comes online in Phase 1 with a starter rule-set, growing continuously (target thousands of rules).
## Engine 3 — Batting DNA  (permanent player fingerprint)
Purpose: a lasting technical genome per player — aggression, timing, balance, power, backlift style, front-foot/back-foot strength, leg-side/off-side, shot selection, mental discipline — updated every session. Phase 1 seeds a basic profile from the measurable metrics; deepens across Phase 2–3 as more data and physics arrive.
## Engine 4 — Match Intelligence  (tactical, not just technical)
Purpose: translate technique into match consequences — "against left-arm fast, over the wicket, good length outside off, you are vulnerable ~78%." This is where most systems stop and you continue. Requires accumulated data + the knowledge graph; roadmapped for Phase 3.
## Engine 5 — Learning Engine  (personalised improvement)
Purpose: learn how each player improves — learning speed, which drills work, fatigue and retention patterns — and optimise the coaching plan accordingly. Two players with the same fault may need 200 vs 2000 balls; the engine adapts. Phase 3, once longitudinal data exists.
## Engine 6 — Digital Twin  (virtual batter — research frontier)
Purpose: build a virtual model of the batter from many videos and simulate deliveries (swing, spin, bouncer, yorker) to predict performance without facing them. Genuinely ambitious research; belongs in Phase 4 as a north-star, presented as vision rather than a launch claim.
## Engine 7 — Cricket GPT  (conversational coach)
Purpose: a chat coach the player can ask "why am I edging?" — answering from their biomechanics, physics, history, and video evidence, grounded (RAG) in the Knowledge Graph so it explains rather than guesses. A simple Q&A-over-report version is feasible early (Phase 2–3); the full context-aware coach deepens with the dataset.

# 5. Legend Comparison  (core feature, powered by Engines 1–3)
Central to your idea from sentence one. The player is scored against reference benchmarks for each parameter, and — crucially — the platform explains the gap, not just shows it.
Parameter
You
Legend-style benchmark
Coaching read
Backlift angle
42°
~65°
23° lower — restricts downswing arc & bat speed
Head stability
78%
~97%
Head drifts ~14cm; aim <5cm for balance at contact
Balance
80%
~98%
Weight staying back; drill weight-transfer
Timing
71%
~95%
Front foot ~0.19s late; throwdown timing work
## The one rule that keeps this safe (you already flagged it)
Compare against technical benchmarks DERIVED FROM legends' publicly observable technique — never claim endorsement, and never use proprietary or licensed player datasets without permission. A "Kohli-style backlift benchmark" is a reference model; it is not a claim that Kohli is involved. A "Legend Similarity Score" (e.g. Kohli 82%, Root 79%, Smith 64%) compares your shape across several benchmarks and explains why — richer and safer than telling a player to copy one batter.

# 6. The Trust Principle: Measured / Estimated / Modelled
You asked for high-quality biomechanics, not hype. Every number the platform shows carries an honest label. This is a feature, not a limitation — it is exactly what makes a serious coach or academy trust the tool over a black box.
Label
Meaning
Examples
MEASURED
Directly computed from what the camera sees
Angles, bat/hand speed, stride, head movement, timing
ESTIMATED
Inferred by a validated model; shown with a confidence score
Force, energy, ground reaction, ball-exit velocity
MODELLED / PREDICTED
Forward-looking simulation or prediction
Match vulnerability, improvement forecast, Digital Twin
Rule of the house: never show an estimated or modelled number as if it were measured. That single discipline is what separates a credible cricket-intelligence platform from the pose-detection apps you are out-building.

# 7. Phase 1 in Detail — What Ships First
A focused, genuinely useful, honest product — and already differentiated because the report explains WHY. Batting only, one guided camera angle.
Area
Phase 1 scope
Capture & upload
Mobile upload with on-screen capture guidance (angle, distance, lighting) to protect accuracy
Vision
Pose estimation + 2D biomechanics measurement; basic shot recognition
What's analysed
Stance, backlift, head stability, footwork, follow-through, balance, timing
Physics (measured slice)
Bat/hand speed, angular velocity, hip–shoulder separation, timing — the measurable kinematics of Engine 1
Legend Comparison
Benchmark scores + explained gaps on the Phase-1 parameters (backlift, head, balance, timing)
Knowledge Graph
Starter coaching rules turning findings into why-it-matters + a drill
Report & AI
Annotated video + an explained coaching report (LLM), each issue: what · why · impact · drill
Progress
Player profile + improvement tracking over sessions (seeds Batting DNA)
Deliberately NOT in Phase 1: force/energy estimates, ball tracking, match vulnerability, Digital Twin. These are sequenced below, not dropped.
# 8. Honest Roadmap — Phases 1 to 4
Phase
Engines / capabilities coming online
Theme
Phase 1
Foundation + Pose/2D biomechanics + Physics (measured kinematics) + Legend benchmarks + Knowledge Graph (starter) + AI report + progress
Explainable batting coach — MVP
Phase 2
Bat & Ball tracking + Physics (estimated dynamics, labelled) + full Shot Classification + richer drills + basic Cricket GPT (Q&A over report)
Deeper physics & the full shot picture
Phase 3
Batting DNA (full) + Match Intelligence + Learning Engine + Academy platform + Legend Similarity Score
Tactical + personalised + academy scale
Phase 4
Digital Twin + performance prediction + Bowling / Keeping / Fielding modules + Cricket Foundation Model (dataset moat)
Research frontier & full cricket OS
This matches how you and your earlier planning already sequenced it: prove the explainable batting coach first, let the data you collect unlock the deeper engines, and keep the research-frontier features (Digital Twin, injury/ball-exit prediction, other disciplines) as honest Phase-4 vision. The dataset you accumulate along the way is the real moat — nobody else has it.

| Layer | Contains | Role |
| Intelligence Engines (7) | Physics · Knowledge Graph · Batting DNA · Match Intelligence · Learning · Digital Twin · Cricket GPT | The brain. Turns measurements into explanation, comparison, prediction, coaching. |
| Vision Foundation | Video Intelligence · Pose · Bat Detection · Ball Tracking · Shot Recognition · Biomechanics Measurement | The eyes. Extracts raw movement data the engines reason over. |
| SaaS Platform | Auth & Roles · Subscription/Billing · Player Profile & Progress · Dashboards · Academy Console · Admin | The product. Accounts, payments, delivery, academies. |

| Component | What it produces | Phase 1? |
| Video Intelligence | Stabilised, normalised clip; camera-angle & quality check; capture guidance | Yes |
| Pose Engine | Body keypoints per frame (MediaPipe/MoveNet/ViTPose) | Yes |
| Biomechanics Measurement | Angles, rotations, stride, head movement, timing (2D) | Yes |
| Bat Detection | Bat position, angle, swing plane per frame (custom-trained) | Phase 2 |
| Ball Tracking | Line, length, bounce, contact, speed (constrained conditions) | Phase 2 |
| Shot Recognition | Cover drive, pull, cut, sweep, defensive, etc. | Phase 1 (basic) → 2 |

| MEASURED from video (feasible now) | ESTIMATED by model (show as estimate + confidence) |
| Bat & hand speedAngular velocity / accelerationBat lagHip–shoulder separationCenter of mass & balanceReaction / timing (ms)Bat face orientation (with bat detection) | Momentum & impulseTorqueKinetic energy & energy transferGround reaction forceImpact energy & ball-exit velocitySweet-spot efficiency |

| Parameter | You | Legend-style benchmark | Coaching read |
| Backlift angle | 42° | ~65° | 23° lower — restricts downswing arc & bat speed |
| Head stability | 78% | ~97% | Head drifts ~14cm; aim <5cm for balance at contact |
| Balance | 80% | ~98% | Weight staying back; drill weight-transfer |
| Timing | 71% | ~95% | Front foot ~0.19s late; throwdown timing work |

| Label | Meaning | Examples |
| MEASURED | Directly computed from what the camera sees | Angles, bat/hand speed, stride, head movement, timing |
| ESTIMATED | Inferred by a validated model; shown with a confidence score | Force, energy, ground reaction, ball-exit velocity |
| MODELLED / PREDICTED | Forward-looking simulation or prediction | Match vulnerability, improvement forecast, Digital Twin |

| Area | Phase 1 scope |
| Capture & upload | Mobile upload with on-screen capture guidance (angle, distance, lighting) to protect accuracy |
| Vision | Pose estimation + 2D biomechanics measurement; basic shot recognition |
| What's analysed | Stance, backlift, head stability, footwork, follow-through, balance, timing |
| Physics (measured slice) | Bat/hand speed, angular velocity, hip–shoulder separation, timing — the measurable kinematics of Engine 1 |
| Legend Comparison | Benchmark scores + explained gaps on the Phase-1 parameters (backlift, head, balance, timing) |
| Knowledge Graph | Starter coaching rules turning findings into why-it-matters + a drill |
| Report & AI | Annotated video + an explained coaching report (LLM), each issue: what · why · impact · drill |
| Progress | Player profile + improvement tracking over sessions (seeds Batting DNA) |

| Phase | Engines / capabilities coming online | Theme |
| Phase 1 | Foundation + Pose/2D biomechanics + Physics (measured kinematics) + Legend benchmarks + Knowledge Graph (starter) + AI report + progress | Explainable batting coach — MVP |
| Phase 2 | Bat & Ball tracking + Physics (estimated dynamics, labelled) + full Shot Classification + richer drills + basic Cricket GPT (Q&A over report) | Deeper physics & the full shot picture |
| Phase 3 | Batting DNA (full) + Match Intelligence + Learning Engine + Academy platform + Legend Similarity Score | Tactical + personalised + academy scale |
| Phase 4 | Digital Twin + performance prediction + Bowling / Keeping / Fielding modules + Cricket Foundation Model (dataset moat) | Research frontier & full cricket OS |