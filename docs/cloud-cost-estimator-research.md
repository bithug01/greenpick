# Research: "Estimate what it'll cost to build X" + free-tier awareness — is there a gap?

Captured 2026-10-10. Sources are vendor/indie marketing + GitHub repos (paraphrased),
not hands-on testing. Directional, not gospel. The space moves fast — re-scan before acting.

## The original idea (what sparked this)
1. "Give me a good estimate of what it'll cost to build X **before** I build it."
2. Corollary: include the **free options** (AWS free tier, GitHub, free hosting, etc.) in that
   estimate — assemble the cheapest real stack and tell me **when/where it stops being free**
   (the "free cliff").
3. Added idea: an **embedded service that tracks & alerts** before a free thing becomes paid.

## Verdict (honest)
**No clean open lane.** Each layer of the idea is already occupied, and one serious attempt
has already died. This is a "build for love / open-source / portfolio" space, NOT a clear
business gap. The instinct about *what makes it valuable* is correct — it's just not novel.

## What already exists

### Estimators (describe app -> cheapest coherent stack -> cost -> scaling)
- **StackPlan** (flaviocopes.com/stackplan) — THE closest match. Describe app via
  questionnaire / free-text / **GitHub repo** -> recommended stack + real costs; forecasts at
  100 / 1k / 10k / 100k DAU; 16-provider curated KB; **deterministic cost math, LLM only writes
  rationale (never invents prices)**; agent API. Pro ($20/mo) **re-evaluates when providers
  change pricing and sends infra update alerts** — i.e. it already built BOTH the freshness
  pipeline ("an AI agent checks provider prices daily") AND the alert layer we thought was the
  gap. **Retired Oct 2026** (now redirects to a static guide) — ambiguous signal: either weak
  demand / too much maintenance, or just a solo project the author moved on from. Either way:
  idea is validated AND hard to sustain.
- **DeployCost** (deploycost.com) — "cheapest coherent stack... honest all-in monthly cost,
  not just headline $/hr." (Couldn't fetch live; from snippet.)
- **StackCost** (devpost) — "what does this stack cost at my scale, and **which limit breaks
  first**... before surprise invoices." The free-cliff idea, already built (hackathon-grade).
- Also: HostMath, aibizhub, "cheapest AI SaaS stack" guides, a claude-cto cost-estimator skill.

### Alert-before-free-turns-paid
- **AWS native, free:** Free Tier usage alerts at 85% of limit, AWS Budgets to 100%, plus
  "free account plan expiration date / credit balance / days remaining" with periodic emails.
  You can't beat the provider at watching its own account.
- **StackPlan Pro** did the cross-stack version (alerts when your stack's providers change pricing).
- Gap that remains (thin): a *cross-vendor* watcher driven by **offer/policy changes + trial/
  credit expiries** (not live metered usage). Less served, but low willingness-to-pay.

### Free-tier lists (the "catalog" layer)
- **free-for-dev** (github.com/ripienaar/free-for-dev, site free-for.dev) — DOMINANT.
  1,100+ contributors, years old, strong eligibility rules (real free tier, not trial; >=1yr if
  time-bucketed). Searchable frontends exist ("1,200+ tiers, compare side-by-side").
  Competing with this on coverage is a losing game.
- Many smaller GitHub lists: Awesome-Web-Hosting-2026, Cloud-Free-Tier-Comparison (many forks),
  costgoat/aws-free-tier, low-cost cloud stack cheatsheets.

### Open, structured, "verified-on-a-schedule" pricing datasets (the "data as product" angle)
This is a PROVEN, REPLICATED pattern — but every winner niches down hard:
- **free-llm-api-hub** (github.com/pacocartones) — nearly verbatim our value prop
  ("continuously-verified, every entry dated, sourced to provider docs, machine-readable, the
  fine print that bites") — scoped to **LLM APIs**. Validates our framing; shows the general
  version isn't the move.
- GPU prices: gpu-rental-prices (daily, CC BY 4.0, live site). AI/LLM: Portkey-AI/models
  (2,000+ models, free API), ai-agent-pricing (weekly), mytokentracker-open-data (daily).
  AWS: aws-pricing-json.

## The durable differentiator (and why it's not enough)
Across everything, the only real moat is **trustworthy, continuously-current data** (free tiers
are "becoming free trials"; offers change monthly). But: StackPlan already automated it, the
dataset pattern is replicated, and it's pure ongoing maintenance cost aimed at a low-willingness-
to-pay audience (indie builders you're helping NOT spend money).

## If pursued anyway — the only realistic shapes
1. **Open-source / portfolio build**, not a startup. A clean estimator or a maintained dataset
   is genuinely useful and a satisfying engineering problem (LLM-for-reasoning + deterministic
   data + a scheduled freshness agent — same recipe StackPlan used).
2. **Niche down HARD** (the pattern's winners all do). Pick ONE vertical nobody has given the
   "dated / sourced / fine-print / machine-readable + simple change-watcher" treatment — and
   first confirm a repo doesn't already own it.
3. **Validate willingness-to-pay with real indie builders BEFORE building** — StackPlan's death
   is the cautionary tale.

## Next steps if revisited
- Talk to 5-10 indie builders: would they *pay* for the estimate, or just the alert? (Suspect not.)
- If going the dataset route, pick a vertical and grep GitHub for an existing repo first.
- Re-scan — this space churns; today's list will be stale in months.

---

## Round 2 (2026-10-10): "Python library / in-editor tool that triggers deals as the build evolves"

Pivot idea: instead of a website, a tool that lives IN the vibe-coding environment (Cursor /
Claude Code / Kiro) and surfaces free tiers / credits / deals in real time as you scaffold.

**Verdict: the freshest delivery angle, but the MOST convergence is happening here right now —
near-exact implementation already exists, and the platform vendors are entering.**

### The near-exact match (stops this cold)
- **agentdeals** (github.com/robhunter/agentdeals) — "An MCP server that aggregates free tiers,
  startup credits, and developer tool deals — so your AI agent (or you) can find the best
  infrastructure offers **without leaving the workflow**." **4 tools, 54 categories, 1,525+
  offers.** This is essentially the idea, already shipped, as an MCP server.

### Platform owners moving in (the big squeeze)
- **AWS "Agent Plugins for AWS"** (open-sourced; works in Claude Code + Cursor). The deploy-on-aws
  plugin: analyze codebase -> **recommend services w/ rationale -> estimate costs** -> generate
  CDK/CloudFormation -> deploy after confirmation. Wired to MCP servers for docs, **real-time
  pricing**, and IaC. When the cloud giant ships "recommend + cost as you build" into your editor
  for free, an indie tool is squeezed.
- Multi-cloud pricing MCP servers already exist: **cloud-cost-mcp** (AWS/Azure/GCP/OCI compare in
  one query), AWS's own `cost-analysis-mcp-server`, GCP cost agents, FinOps skill packs.
- The "govern deps as you install" mechanism exists: **vibe-dependency-guard-agent** (intercepts
  each install, returns approve/reject/review) — i.e. the "watch the build evolve" hook is a
  demonstrated pattern already.

### Two honest nuances
1. **MCP server, not a plain Python library.** The ecosystem standardized on **MCP servers** as
   how tools plug into vibe-coding agents. A plain importable lib won't get called in the "as I
   code" loop unless exposed as an agent tool. If built, it should be an MCP server (can be written
   in Python) — which is exactly what agentdeals already is.
2. **The affiliate/"deals" model has a trust trap.** If funded by referral revenue when builders
   activate deals, incentives diverge from the builder (recommend what pays, not what's cheapest) —
   the OPPOSITE of the "honest fine-print" trust that is the only durable moat. A referral-funded
   deals aggregator is a WEAKER trust position than a neutral estimator. Avoid this funding model.

### Overall conclusion across BOTH rounds
Every framing explored — estimator (DeployCost/StackPlan[dead]/StackCost), alert layer (StackPlan
Pro + AWS native), free-tier list (free-for-dev, 1,100+ contributors), open dataset
(free-llm-api-hub etc., all niched), and now in-editor deals (agentdeals + AWS plugins) — is
occupied, increasingly by well-resourced players. **No open business gap.** Build-for-love /
learning / portfolio only. If ever pursued: ship an MCP server, niche hard, don't use the
affiliate-deals funding model, and validate willingness-to-pay with real builders first.

---

## Round 3 (2026-10-10): "Sustainability recommender MCP" (carbon axis instead of cost)

Pivot: swap the optimization axis from COST (crowded) to CARBON. Finding: carbon is the
**least-saturated axis in this whole thread** — but the exact "sustainability recommender MCP"
label is already taken, though the implementation is early/shallow. First idea where
"differentiate within the niche" looks genuinely viable (as a mission/OSS/portfolio build).

### Near-exact match: SustainOps MCP (github.com/tanvirtanmoy/sustainops-mcp)
What it does: MCP server (FastMCP, Python, works in Claude/Cursor). Ranks countries + AWS regions
by grid carbon intensity, compares locations, gives plain-English "run it here" placement advice,
exposes methodology/limitations docs. Clean, swappable data layer.
What it does NOT do — per its OWN Limitations/Roadmap (this is the daylight):
1. **Runs on MOCK DATA.** Athena/live backend "scaffolded but not yet fully wired." The hard
   part — real fresh carbon data — is unbuilt.
2. **No workload CO2 estimation** (roadmap, unchecked) — ranks places, can't say what YOUR thing emits.
3. **Country-granularity only**, approximate AWS-region->country mapping; no sub-national grid zones.
4. **"Where," not "what you're building"** — pure location ranking; doesn't look at your stack/
   architecture/instance choices or nudge greener design decisions.
5. No time-shifting, no cost tradeoff, no latency tradeoff.
=> The LABEL is taken; the SUBSTANCE is thin and early (solo project, mock data).

### Surrounding space
- Indie/hackathon MCP+pipeline: EcoOrchestrator (Climatiq via MCP, scores CI/CD jobs; page 403'd),
  GreenPipe (per-job carbon + "least-carbon region" as a merge-request comment).
- Mature MEASUREMENT tools (post-hoc, not design-time): Cloud Carbon Footprint (OSS), CodeCarbon,
  green-metrics-tool, Uptime Institute Cloud Carbon Explorer, Google Carbon Footprint + low-carbon
  region guidance.
- Strong ACADEMIC backing (good for credibility, bad for novelty): arXiv carbon-efficient training-
  location rec (best vs worst region = 97% cut), SLA-constrained carbon-aware routing (27-47% cut,
  zero SLA violations), Caribou SOSP (22-66% cut).

### The genuine daylight (evidenced, not guessed)
- (A) **Design-time, in-editor nudges tied to what you're actually coding** ("you added a nightly
  GPU job / picked us-east-1 -> greener region/schedule + the tradeoff"). SustainOps does abstract
  location ranking, NOT build-decision-aware nudging. Open.
- (B) **Honest tradeoff triad: carbon + cost + latency together** so the builder chooses informed
  (matches the SLA-constrained-routing research). No MCP tool presents all three. Differentiated.
- (C) **Real, cited, fresh data** (ElectricityMaps/WattTime/Climatiq) — SustainOps is on mock data;
  this is the universal weak point across the whole thread. Moat AND slog (feeds have their own cost/limits).
- (D) **Workload CO2 estimation at design time** — unbuilt in SustainOps; measurement tools only do
  it post-deploy.

### Honest counterweights (nastier than for cost)
- Willingness-to-pay even LOWER than cost tooling (people won't pay to save money; less to save carbon).
- Methodology is contested: "no defensible single 'greenest cloud' in 2026" (market- vs location-based
  accounting, PUE, reporting boundaries). A recommender must take stances experts will argue.
- Depends on a real-time carbon-intensity feed that often costs money / has limits.

### Verdict
Best idea of the thread for a MISSION / OPEN-SOURCE / PORTFOLIO build — carbon is fresher than cost,
science backs it, and "in-editor sustainability co-pilot tied to your build, showing carbon/cost/
latency tradeoffs on LIVE data" is genuinely under-served (SustainOps proves the label is taken but
the product is early + mock-data). NOT a clear money gap (low willingness-to-pay, methodology fights,
paid data dependency). If pursued: don't rebuild "rank regions" (done) — build the design-time,
build-aware, tri-axis, live-data co-pilot; scope to one workload type; lead with honest tradeoffs.

---

## Round 4 (2026-10-10): Data provenance — "the paid feed isn't the moat" (REVISES Round 3 caveat)

Question probed: the paid carbon feeds (Electricity Maps, WattTime) got their data somewhere —
why couldn't I get the same, or build better? Answer: **the raw data IS free & public; the moat
is the transformation + audited methodology, NOT the data.** This softens the Round 3 "paid data
dependency" caveat for an INDIE/directional tool.

### Where the paid vendors actually source it (they say so)
Electricity Maps' own research page + old OSS repo: they fetch raw production data from
**free, public, official sources** — government agencies (EIA US), technical bodies (ENTSO-E EU),
market operators (Nordpool), TSOs (RTE France, Energinet Denmark), utilities. ~75 parsers.

### Three layers — only the first is "data"
1. **Raw acquisition — EASY & FREE.** Pulling ENTSO-E + EIA etc. is doable; NOT a moat.
2. **Transformation — the REAL moat (hard, ongoing):**
   - **Flow-tracing**: grids are interconnected, so consumed carbon != produced carbon
     (imports/exports). EM runs a flow-tracing algo across connected grids for consumption-based
     intensity. Real modeling.
   - **~75+ parsers maintained** as each country's API changes/breaks — continuous ops burden.
   - **Quality validation / outlier detection** (Apache Beam pipeline) — raw TSO data is messy.
   - **Gap-filling + forecasting** (WattTime: marginal emissions + 3-day forecast, 5-min, ~99%
     of world consumption) — statistical modeling beyond the raw feed.
3. **Credibility/compliance — can't bootstrap.** EM had SGS independently verify alignment with
   **GHG Protocol Scope 2** + **ISO 14064-1**, validated vs Ember/IEA/Eurostat. For OFFICIAL carbon
   accounting, "I scraped ENTSO-E + did my own math" won't be trusted. The audited methodology IS
   the product enterprises pay for.

### Verdict on the question
- "Same raw data myself?" **YES** — free/public (ENTSO-E, EIA), plus free DERIVED datasets already
  exist (see below).
- "Build better?" For a **dev-nudge MCP you don't need to beat them — 'good enough' is free &
  achievable.** For a production-grade 200-region audited forecasted feed: years of parser
  maintenance + flow-tracing + compliance = genuinely their moat, and you wouldn't/needn't match it.

### Free sources a minimal version would wire up
- **Electricity Maps FREE TIER** — live carbon intensity, 200+ regions, one API (electricitymaps.com/free-tier).
- **ENTSO-E Transparency Platform** — free EU grid API.
- **EIA / EIA-930** — free US govt hourly fuel-mix/emissions API.
- **Open Grid Emissions** (github.com/singularity-energy/open-grid-emissions) — free OSS hourly US
  emissions, 2019+, balancing-authority level.
- **emission-factors.com** — unifies EPA eGRID + EIA-930 + eGRID + tariffs behind one REST API by US ZIP.
- (UK: NESO/ONS carbon-intensity API, also free.)

### Net effect on the carbon-recommender idea
STRENGTHENS it for the indie/OSS build: directional guidance ("us-east-1 is dirtier than
eu-north-1 right now; tradeoff +40ms latency") tolerates "good enough" data, which is FREE.
The paid-data wall only reappears if you aim for AUTHORITATIVE enterprise REPORTING (layer 3 =
standards alignment + third-party verification) — a real vendor moat, not a weekend build.
So: scope to directional design-time nudges on free data; do NOT position as audited accounting.
