# GreenPick (working name) — v1 Scope

An MCP server that gives **design-time, build-aware sustainability nudges** inside the
vibe-coding loop (Cursor / Claude Code / Kiro). The differentiator vs. existing tools
(SustainOps, EcoOrchestrator): it ties a greener choice to **the decision you're making right
now** and shows the honest **carbon + cost + latency tradeoff** — not an abstract region ranking,
and not post-deploy measurement.

Status: scope only. Nothing built. See cloud-cost-estimator-research.md for why this is the
chosen idea and the competitive/provenance findings behind it.

---

## Positioning (what it is / is NOT)
- IS: a directional "greener choice" co-pilot for a developer picking a region / schedule /
  instance while building. Guidance, with tradeoffs stated.
- IS NOT: audited carbon accounting, enterprise ESG reporting, or a real-time scheduler. We do
  not claim Scope-2 / ISO compliance (that's the paid vendors' moat). Say so plainly in output.

## v1 scope boundaries (ruthless, so it ships)
- ONE workload shape: a **long-running web/API service deployed to a cloud region** (the most
  common vibe-coded thing). NOT batch/GPU/cron/training in v1 (they're the roadmap).
- Three providers: **AWS, GCP, Azure** region sets only.
- Carbon = **grid carbon intensity by region** (directional). Cost = **compute + egress ballpark**.
  Latency = **approx from region geography / to a stated user location**.
- Free data only. Point-in-time + short-horizon; no forecasting, no flow-traced consumption
  accounting in v1 (cite the limitation).

## The tri-axis output (the core idea)
Every recommendation returns, for each candidate region:
  { region, gCO2/kWh (now + source + timestamp), relative_carbon_rank,
    est_monthly_cost_usd (compute+egress, ballpark), latency_ms_estimate (to user_location),
    tradeoff_sentence }
...plus a plain-English "greenest within your constraints" pick, e.g.:
  "eu-north-1 (Stockholm) is ~70% lower carbon than your default us-east-1 right now.
   Tradeoff: +95ms latency to US-East users, ~same cost. Pick it if latency budget allows."

## MCP tools (v1 — keep it to ~5)
1. **compare_regions_tri_axis**
   in: { providers[], user_location, workload={vcpu, ram_gb, est_monthly_egress_gb},
         optimize_for="carbon|balanced", max_added_latency_ms? }
   out: ranked candidates with the tri-axis fields above + a recommended pick + tradeoff text.
2. **greener_alternative_to**
   in: { current_region, user_location, workload, max_added_latency_ms }
   out: "you picked X; the greenest region within +Nms latency is Y (−Z% carbon, Δcost)."
   (This is the "nudge me about the decision I just made" tool — the wedge.)
3. **estimate_workload_carbon**
   in: { region, workload, hours_per_month=730 }
   out: rough kgCO2/month = power_estimate(vcpu,ram) * PUE_assumption * gridIntensity(region).
   (SustainOps explicitly does NOT do this — real daylight. Label it an estimate.)
4. **region_carbon_now**
   in: { region }  out: current gCO2/kWh, source, timestamp, freshness.
   (Thin wrapper over the data layer; also what SustainOps-style ranking covers — table stakes.)
5. **explain_methodology_and_limits**
   out: static resource — sources, assumptions (PUE, power model), what we DON'T claim.
   (Trust move; mirrors how the credible vendors front-load caveats.)

## Data layer (free sources, swappable behind one interface)
- Grid carbon intensity: **Electricity Maps free tier** (primary; 200+ regions, one API) with
  fallbacks to **ENTSO-E** (EU), **EIA-930** (US), **NESO** (UK). Cache aggressively; degrade to
  **annual averages** (eGRID / Open Grid Emissions) when live is unavailable — and SAY which was used.
- Region->grid-zone mapping: start country/zone-approximate (like SustainOps); note imprecision.
- Cost ballpark: a small **static, dated pricing table** for the common instance sizes + egress
  per provider (deterministic; LLM never invents numbers — the StackPlan lesson). Refreshable.
- Latency estimate: great-circle distance from region coords to user_location -> rough ms
  (or an optional ping if a measured number is wanted later).
- Power model for carbon estimate: simple published coefficients (vCPU + RAM -> watts) * PUE
  assumption (document the numbers; it's an estimate, not a measurement).

## Architecture (mirror SustainOps' clean shape; it's a good template)
MCP client -> FastMCP server -> services (carbon / cost / latency / recommend) ->
data repositories (electricitymaps | entsoe | eia | static-pricing), swappable via config.
Python 3.11+, FastMCP, Pydantic models, aggressive caching (carbon data changes hourly at most).

## Honest limitations to ship IN the tool (non-negotiable, it's the trust)
- Directional, not audited. Region/zone mapping approximate. Carbon is point-in-time, not
  consumption/flow-traced. Cost is a ballpark, not a quote. Latency is geographic estimate.
- "Greener" assumes grid intensity dominates; ignores embodied/hardware carbon and provider RECs.

## Explicitly OUT of v1 (roadmap)
Batch/GPU/training workloads; time-shifting ("run the nightly job at 2am when the grid's clean");
forecasting; flow-traced consumption accounting; multi-stage architecture modeling; sub-national
grid zones; CI/CD pipeline integration (that's EcoOrchestrator/GreenPipe territory).

## Build plan (small, finishable)
1. Data layer w/ ONE live source (Electricity Maps free tier) + static pricing table + mock
   fallback. (Repository interface first, so sources are swappable — SustainOps got this right.)
2. compute: carbon service, cost service, latency service (pure functions, unit-tested).
3. The 5 MCP tools over those services (FastMCP).
4. methodology/limits resource.
5. Wire into Kiro/Claude/Cursor; dogfood: "where should I deploy a small FastAPI app for US users,
   greenest within +100ms?" and sanity-check the tradeoff output.
6. Open-source it; write the honest README (sources, assumptions, what it does NOT claim).

## Success test for v1
A builder mid-session asks "where should I deploy this?" and gets, in-editor, a greener region
with a one-line carbon/cost/latency tradeoff they can accept or reject — on free, cited, dated
data — in under 10 seconds. That's the whole product.

---

## Dogfood it (scaffold is built + working in ~/Desktop/greenpick)

The scaffold runs on mock data, offline. 5 MCP tools register; 5 unit tests pass; the recommender
produces correct tri-axis output with working latency-budget logic.

### 1. Add to Kiro MCP config
Edit `~/.kiro/settings/mcp.json` yourself (agent is blocked from writing there by policy).
Add this inside "mcpServers" (comma after the previous entry):

```json
"greenpick": {
  "command": "python",
  "args": ["-m", "greenpick"],
  "cwd": "C:\\Users\\beaperry\\Desktop\\greenpick",
  "env": { "GREENPICK_CARBON_SOURCE": "mock" },
  "disabled": false,
  "autoApprove": [
    "compare_regions_tri_axis", "greener_alternative_to",
    "estimate_workload_carbon", "region_carbon_now", "explain_methodology_and_limits"
  ]
}
```
Notes: `python -m greenpick` is used because the console script isn't on PATH. `cwd` makes the
module resolve + loads `.env`. Mock source = no token/network needed. For LIVE data later:
set `GREENPICK_CARBON_SOURCE=electricitymaps` and add `"ELECTRICITYMAPS_TOKEN": "..."` to env.

### 2. Reconnect MCP
Command palette -> search "MCP" (reconnect), or the MCP Server view in the Kiro panel. GreenPick
should appear with its 5 tools.

### 3. Test prompts
- "I'm deploying a small FastAPI service for users in Washington DC — ~2 vCPU, 4GB RAM, 10GB
  egress/month. Where should I deploy to be greener, within +100ms latency?"
- "You picked us-east-1 — is there a greener region within 150ms for US-East users?"
- "Roughly how much CO2/month does a 4 vCPU / 16GB always-on service emit in aws/eu-north-1?"

### 4. The real test
Does the in-editor answer (greener region + carbon/cost/latency tradeoff) actually feel USEFUL to
you? If yes -> wire the live Electricity Maps call (the one TODO in electricitymaps_repository.py)
and expand regions/pricing. If it feels like a gimmick -> you learned that for the price of a
scaffold, not a quarter. Highest-value next step is this dogfood, NOT more code.

## Build status (as of scaffold)
DONE: project skeleton, config, models, swappable data repo (mock + EM stub w/ fallback), 3 pure
services + recommender, 5 FastMCP tools, static regions/pricing/power data, 5 passing tests,
honest README. Installs via `pip install -e ".[dev]"`.
TODO (localized): harden ElectricityMaps live call (currently stub->mock fallback); expand region
catalog; date/refresh pricing.json; add ENTSO-E/EIA repos; (roadmap) batch/GPU, time-shifting,
forecasting, workload CO2 refinements.

---

## Evaluation plan (run after config + reconnect)

Evaluate TWO separate things — don't conflate them:
- **(A) Plumbing (pass/fail):** does Kiro call the right tool and return tri-axis output with no
  errors? Low bar, quick.
- **(B) Usefulness (the real verdict):** would a developer mid-build actually ACT on this? Only you
  can judge. (A) can pass while (B) fails — a working tool can still feel like a gimmick. (B) decides
  whether this is worth more than a scaffold.

IMPORTANT: it's on MOCK DATA — evaluate the SHAPE/usefulness of the answer, NOT the numbers.
If the shape compels even on mock data -> wire live data (the one TODO). If it doesn't grab you
even when working -> that's your signal, learned cheaply.

### Prompts (increasing realism)
1. Plumbing + core nudge: "Deploying a small FastAPI service for users in Washington DC — ~2 vCPU,
   4GB RAM, 10GB egress/month. Where should I deploy to be greener, within +100ms latency?"
2. Nudge-my-choice: "I was going to use us-east-1. Is there a meaningfully greener region within
   150ms for my US-East users?"
3. Estimate tool: "Roughly how much CO2/month does a 4 vCPU / 16GB always-on service emit in
   aws/eu-north-1 vs aws/us-east-1?"
4. Honesty test: "How accurate is this? Should I trust it for reporting?" (should surface limits)
5. Realistic edge: "Users are global, latency isn't critical — just make it as green as possible."

### What to judge on (B)
- Did the tradeoff sentence tell me something I'd ACT on, or just restate the obvious?
- Was the latency/cost context what made it decision-grade (vs. a bare carbon ranking I could guess)?
- Did I trust it — or did mock data / caveats make me shrug?
- Would I keep it installed, or uninstall after the novelty?

### Decision gate
- Shape compelling -> wire live Electricity Maps call + expand regions/pricing.
- Shape meh -> stop; it was a scaffold, not a quarter. Record the verdict either way.

---

## Dogfood round 1 — results + fixes (done)

Ran all 5 eval prompts through the live MCP tools in Kiro (mock data).

**(A) Plumbing: PASS.** greenpick connected (green), all 5 tools registered and callable, returned
tri-axis output with honest quality=mock labels + limitations string.

**(B) Usefulness: shape compelling, but found 2 real recommender bugs (the value of dogfooding):**
- Winners that worked well: the **estimate tool** is the most visceral output — same 4vCPU/16GB
  always-on service = **6.25 kg CO2/mo in us-east-1 vs 0.45 kg in eu-north-1** (~14x), a concrete
  number a builder can quote. The **tri-axis tradeoff lines** ("~69% cleaner; +105ms; ~$64/mo") are
  the real differentiator. The **honesty tool** returns the right what-it-is/is-NOT posture.
- **Bug 1 — rigid latency budget:** a +105ms option under a +100ms cap was excluded, so it
  recommended "stay on us-east-1" while DISPLAYING a 69%-cleaner option. Felt broken.
- **Bug 2 — bad default baseline:** with no current region given, it compared everything against the
  DIRTIEST candidate (ap-southeast-2), producing confusing "~96% cleaner than Sydney; -272ms" lines.

**Fixes applied to services/recommender.py (all verified: 5/5 tests + live re-run):**
1. **Latency tolerance band** — treat the cap as "~", allow the larger of +15ms or +10% slack, so
   near-misses (+105 vs +100) qualify. -> Prompt 1 now picks aws/us-west-2 (~69% cleaner within ~100ms).
2. **"No meaningful improvement" handling** — if nothing in-budget is >=5% cleaner than baseline, say
   "staying on X is reasonable / about as good as it gets; the greenest overall is Y (~Z% cleaner,
   +Nms) — widen the budget to reach it." No more dressing the baseline up as a win.
3. **Nearest-region default baseline** — when no current region is given, baseline = region nearest
   the user (lowest latency). -> Prompt 5 tradeoff lines now read "~93% cleaner than us-east-1;
   +198ms; ~$64/mo" (natural), not "-272ms vs Sydney".

**Net:** logic is now right; numbers are still MOCK (real only when the Electricity Maps call is
wired — the remaining TODO). (B) verdict is stronger post-fix: decision-grade, act-on-able answers.

### Status / next
- To see fixes in Kiro: RECONNECT greenpick (it loads code at connect time), then re-ask the prompt.
- Remaining real-data TODO: wire electricitymaps_repository.py live call; expand regions; date pricing.
- Decision gate still stands: pursue live data only if the in-editor feel is genuinely useful to you.

---

## Live data wiring (done, pending your token)

Decision: dogfood felt useful -> go to live data. Wired Electricity Maps free tier.

### Code changes (all tested; 8/8 pass)
- Verified the real API shape: GET https://api.electricitymap.org/v3/carbon-intensity/latest?zone=XX
  header `auth-token: <key>` -> { carbonIntensity, datetime, isEstimated, ... }.
- Rewrote `electricitymaps_repository.py` with honest degradation:
  - 401/403 (bad token) -> warn once, stop retrying, mock fallback.
  - 404 (zone not on free tier) -> silent per-region mock fallback.
  - network/parse error -> mock fallback.
  - API `isEstimated: true` -> quality="live_estimated" (real but modelled); else "live".
  - fresh cache -> quality="cached".
- Added `live_estimated` to the DataQuality enum in models.py.
- Added 3 tests using httpx.MockTransport (no real token/network): live+isEstimated parse,
  bad-token->mock+stop, no-token->mock.
- Created `.env` (gitignored) with GREENPICK_CARBON_SOURCE=electricitymaps and an empty
  ELECTRICITYMAPS_TOKEN placeholder.

### YOUR remaining steps (can't be automated)
1. Get a free token: https://electricitymaps.com/free-tier (email sign-in, no card).
2. Paste it into greenpick/.env after ELECTRICITYMAPS_TOKEN= .
3. Reconnect greenpick in Kiro (reloads code + config).
4. Re-run the DC prompt. Verify via the `source`/`quality` fields:
   - source=electricitymaps, quality=live|live_estimated -> real data for that zone.
   - quality=mock -> zone not covered/mapped -> fell back (labelled honestly).

### Expect a MIX (live + mock)
Free tier doesn't cover every zone and our region->zone map is approximate. Regions that come
back mock just need their `zone` fixed in data/regions.json. This is expected and labelled, not a bug.

### State of v1
Logic correct, live data wired + honestly labelled, 8/8 tests. Remaining polish (not blockers):
expand/verify region->zone mappings against what the free tier actually covers; date/refresh
pricing.json; (roadmap) annual-average middle tier, batch/GPU, time-shifting, forecasting.

---

## Live data attempt — blocked on Electricity Maps free-tier access (external, not code)

Wired live data, got the token in, and hit an EXTERNAL blocker. Full diagnosis below so it's
resumable without re-deriving it.

### Code gap found + fixed along the way
- `.env` was never being read: config.py used raw os.environ and nothing loaded the file. The MCP
  client launches the server with its own env (not a shell that sourced .env), so
  GREENPICK_CARBON_SOURCE + token were invisible -> everything silently stayed mock.
- Fix: added `python-dotenv` dependency; config.py now `load_dotenv()` at import (find_dotenv, with
  a project-root fallback) BEFORE reading settings. Verified: source=electricitymaps, token loaded.

### The blocker (diagnosed by probing the API directly; token never printed)
- Token AUTHENTICATES fine (correct header is `auth-token`). Using it returns a ZONE/ENDPOINT-
  specific 401, not "invalid token" — proving the key is valid.
- Authorized zone per the EM portal: **US-NY-NYIS (New York ISO)**. But that zone ALSO 401s.
- Probed all four endpoints for US-NY-NYIS (carbon-intensity/latest, power-breakdown/latest, and
  both /history): **all 401.** Body: "You do not have access to this specific endpoint for this
  specific zone."
- Conclusion: key is valid + scoped to US-NY-NYIS but returns NO data on ANY endpoint yet. This is
  an EM-side account state (pending activation / dataset not subscribed to the key / free tier may
  not include the `latest` endpoint), NOT our bug. Our 401->mock fallback handled it correctly and
  honestly (everything showed source=mock, quality=mock).

### Proven end-to-end regardless
Recommender logic (post-fix: us-west-2 pick, tolerance band, honest "stay put" + natural baseline),
tri-axis output, .env/config loading, live API wiring, and 401->mock honest fallback ALL work.
8/8 tests pass. The ONLY missing piece is a data key that actually returns data.

### Options to get real numbers (resume here)
1. **Fix EM key in the portal** — look for activate/verify, or explicitly SUBSCRIBE the US-NY-NYIS
   carbon-intensity dataset to the key (viewing a zone != enabling it). If it starts returning 200,
   map a GreenPick region to zone US-NY-NYIS in data/regions.json (~1 min) -> instant live data.
2. **Write an EIA-930 repository** (free US govt data, no gating; US ISOs incl. NY-ISO are covered).
   Data layer is already swappable (CarbonRepository Protocol) — clean, self-contained add. Best if
   EM's free tier won't serve `latest`.
3. **Pause** — fully working prototype with honest mock fallback; live data is a known isolated step.

### Honest overall status of the whole idea
Prototype complete + verified; live data blocked only by an external free-tier access state. The
larger strategic verdict from the research still stands: mission/portfolio build, not a validated
business (crowded space, low willingness-to-pay). Decide if real data is worth chasing before
investing more.

---

## LIVE DATA ACHIEVED — via EIA-930 (US govt), after Electricity Maps dead-ended

Electricity Maps free/trial tier never granted API access (its own "first request" example 401'd),
so switched sources. Built an EIA repository; it worked immediately — the swappable-data-source
architecture paid off (one new file + config flip, no changes to recommender/tools/tests).

### What was built
- `data/eia_repository.py` — fetches latest hourly fuel mix by balancing authority from
  https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/, weights by per-fuel emission
  factors -> directional gCO2/kWh. Honest fallbacks: no key / non-US region (no BA) / API error -> mock.
- `data/emission_factors.json` — per-fuel gCO2/kWh (IPCC AR5-ish, documented as directional estimates).
- `regions.json` — added `eia_ba` codes to US regions (PJM/BPAT/MISO/NYIS) + a new `us-east-nyc`
  region mapped to NYISO.
- config.py: added EIA_API_KEY; data factory branches on source=eia. 3 new tests (mix->intensity
  math, non-US->mock, no-key->mock). 11/11 tests pass.
- Also fixed earlier: `.env` now actually loads (python-dotenv in config.py).

### Live probe result (real current fuel-mix-derived carbon intensity)
- us-east-nyc (NYISO):  257.3 gCO2/kWh  eia/live
- us-east-1   (PJM):    348.9            eia/live
- us-west-2   (BPAT):    75.2            eia/live  (hydro-heavy Pacific NW — plausibly cleanest)
- us-central1 (MISO):   356.2            eia/live
- eu-north-1  (Sweden):  25.0            mock      (EIA is US-only; honest fallback)
Values sanity-check: clean hydro grid low, fossil grids 250-360. Pipeline verified end to end.

### EIA key = free + instant (vs Electricity Maps gating)
Register at https://www.eia.gov/opendata/ -> key emailed immediately. No licenses/activation.
This is why EIA is the right primary source for US regions.

### Net
GreenPick now gives REAL current US grid carbon in-editor. With live data, the DC nudge is a
genuine environmental call (us-west-2 ~78% cleaner than us-east-1: 75 vs 349, real hydro vs fossil).
To see in Kiro: reconnect greenpick (reloads source=eia + key), re-run the DC prompt.

### Remaining (optional polish, not blockers)
- Non-US live data: add an ENTSO-E repository (EU) the same way for eu-* regions (currently mock).
- Verify/expand BA mappings; refresh pricing.json; cite emission factors precisely if moving beyond
  directional. Roadmap: annual-average middle tier, batch/GPU, time-shifting, forecasting.

### Strategic verdict unchanged
Working, live, in-editor prototype — a strong mission/portfolio artifact. NOT a validated business
(crowded space, low willingness-to-pay). Live data was the last real build step; it's done.

---

## ENTSO-E (EU) source + auto router added; greenpick now on GitHub

### Version control
- greenpick is now a git repo, pushed to **github.com/bithug01/greenpick (PRIVATE)**.
- `.env` is gitignored and NOT tracked — EIA key never committed (verified).
- Commits: 36e55ce (initial), 4418462 (ENTSO-E + auto router).

### What was built this round
- `data/entsoe_repository.py` — ENTSO-E Transparency Platform source for EU zones. Queries
  A75 (actual generation per production type) XML, takes latest period MW per psrType, weights by
  per-fuel factors -> directional gCO2/kWh. Honest fallbacks (no token / non-EU region / error -> mock).
- `data/auto_repository.py` + `GREENPICK_CARBON_SOURCE=auto` — routes per region: EIA for US
  (has eia_ba), ENTSO-E for EU (has entsoe_eic), mock otherwise. One setting -> live on both continents.
- regions.json: added `entsoe_eic` codes (Sweden 10YSE-1--------K, Finland, Ireland).
- emission_factors.json: added ENTSO-E psrType (B01..B20) -> factor map (reuses same values).
- config.py: added ENTSOE_TOKEN; factory branches on entsoe/auto.
- 3 new tests (ENTSO-E XML->251 math, non-EU->mock, auto-router routes US->eia/EU->entsoe/other->mock).
  14/14 pass.

### Key-access reality (important)
- **EIA (US): free + INSTANT** — register at eia.gov/opendata, key emailed immediately.
- **ENTSO-E (EU): free but MANUAL approval** — register at transparency.entsoe.eu THEN email
  transparency@entsoe.eu to request API access; approval can take a day+. Until the token arrives,
  EU regions fall back to mock (labelled). No code change needed when it does — just paste into
  ENTSOE_TOKEN and reconnect.

### .env note
`.env` was rewritten to auto mode (adds ENTSOE_TOKEN slot); this BLANKED the EIA key (gitignored,
can't be preserved by the agent). Must re-paste EIA_API_KEY to keep US live. Set to GREENPICK_
CARBON_SOURCE=auto.

### State
Code complete + tested for US (EIA, live now) and EU (ENTSO-E, live once token approved), auto-routed.
Non-US/EU (e.g. Sydney) stays mock by design. Everything pushed to GitHub.

---

## ENTSO-E token: REQUESTED (awaiting approval)

User emailed transparency@entsoe.eu ("RESTful API access") on 2026-10-11 to request API access.
Expect approval in hours-to-~3 working days. When the token arrives:
  1. It appears in the ENTSO-E account under "Web API Security Token".
  2. Paste into greenpick/.env after ENTSOE_TOKEN= , save.
  3. Re-run the live probe -> EU regions (Sweden/Finland/Ireland) flip mock -> entsoe/live.
No code changes needed (auto router already handles it). US (EIA) already live; nothing blocked
in the meantime.

---

## Design clarification: vendor vs. region (what the recommendation unit actually is)

Recommendation unit = a **(provider, region) pair** (e.g. aws/us-east-1, azure/eastus,
gcp/us-central1). Rankings mix vendors + regions in one list.

BUT the carbon intelligence is **region/grid-level, not vendor-level**:
- Carbon intensity comes from the region's GRID ZONE. So aws/us-east-1 and azure/eastus (both in
  PJM) get ~the SAME carbon — they're on the same electricity.
- Vendor is essentially a LABEL today: it only shifts the cost ballpark slightly and the region
  footprint. It carries no distinct carbon signal.

Two user framings this implies:
1. "Already on AWS — which region?" -> vendor fixed, region is the whole game. GreenPick serves
   this well via the `providers` filter. Likely the MORE COMMON real case (teams are vendor-locked).
2. "Vendor-agnostic — greenest anywhere?" -> cross-vendor matters, but today GreenPick adds no real
   vendor-level carbon nuance beyond "same grid = same carbon," so cross-vendor comparison is thin.

### Roadmap item: make vendor a REAL axis
Incorporate per-vendor-per-region clean-energy data (e.g. Google's region carbon-free-energy %,
provider PUE, 24/7 CFE claims, REC/procurement differences). THEN aws/us-east-1 vs azure/eastus
would legitimately diverge and vendor would carry signal. Data-hungry; not v1. Until then, the
strongest/most-defensible use is the within-a-vendor "which region" decision.

---

## Roadmap direction: data-platform providers (Snowflake, Databricks, etc.)

Question raised: why only AWS/Azure/GCP — what about Snowflake/Databricks?

Key distinction: AWS/Azure/GCP are the PHYSICAL layer (own datacenters -> real grid zone -> real
carbon). Snowflake/Databricks are SaaS/PaaS that RUN ON those clouds — when you pick a Snowflake
"region" or a Databricks workspace, it's actually an AWS/Azure/GCP region underneath.

Implications:
- **Carbon: maps cleanly (nearly free).** A Snowflake warehouse in AWS-us-east-1 has PJM-grid
  carbon — which GreenPick already computes. Adding these = a MAPPING table: SaaS region ->
  underlying (provider, grid zone). No new carbon data needed.
- **Cost + workload: needs rework (real work).** GreenPick's cost model is vCPU+RAM+egress; these
  bill in credits/warehouse-seconds (Snowflake) and DBUs (Databricks) — different model entirely.
  And the workload isn't "long-running web service" (v1's only shape) — it's queries/jobs/warehouses.
  Latency axis also less relevant for batch/analytics.

Why it's attractive: data-platform workloads (big ETL, training) are compute-heavy = where region
choice is MOST carbon-material, and that audience (data teams / sustainability-conscious enterprises)
is plausibly more willing-to-pay than indie web devs. Reframes the ideal user from "indie deploying
a web app" to "data team choosing where heavy compute runs."

To build: (a) SaaS-region -> underlying-grid-zone mapping, (b) per-platform cost model
(credits/DBUs), (c) a job/warehouse workload abstraction (not web service). Carbon half ~free;
cost/workload half is new. Good FUTURE direction, not a config tweak.

---

## Free vs. paid data fidelity — is our data "just as good"? (HONEST: no, but good enough)

Question: we chose free sources (EIA + ENTSO-E) over paid (Electricity Maps/WattTime). Is ours
just as good? Answer: NOT just as good — lower fidelity, real gap — but good enough for GreenPick's
actual job. Must never over-claim.

### Same at the raw-input level
The raw fuel-mix we pull IS what the paid vendors ingest from (EIA, ENTSO-E, TSOs). No loss there.

### Worse at the transformation level (the real gap)
1. **Fixed factors vs. flow-tracing (biggest).** We do production-based: fuel mix x static per-fuel
   factors. Grids are interconnected; paid vendors run FLOW-TRACING for consumption-based carbon
   (includes imports). Can differ substantially in import-heavy zones (much of EU). Ours approximates.
2. **Generic vs. calibrated factors.** We use round IPCC-ish medians (gas=490 everywhere); real
   plants vary; paid feeds use regionally-tuned factors.
3. **No forecasting.** Paid (WattTime) has marginal emissions + 3-day forecasts (time-shifting).
   We do point-in-time averages only.
4. **Coverage + latency.** We cover US + EU (once ENTSO-E approved); rest = mock. Paid ~200 regions,
   tighter freshness. Govt feeds can lag hours.

### Verdict: compass, not scale
Free data = a trustworthy COMPASS (which direction is greener) — reliable because GreenPick only
needs the relative RANKING right ("Pacific-NW hydro >> mid-Atlantic fossil" comes through even with
crude factors). It is NOT a trustworthy SCALE (exact grams). Fine for GreenPick's directional,
design-time nudge; NOT fine for ESG/Scope-2/audited accounting (which we explicitly don't serve, per
explain_methodology_and_limits).

This is Round-4's "data isn't the moat, the transformation is" felt directly: we got the same raw
inputs free but don't replicate the transformation (flow-tracing, calibrated factors, forecasting) —
that transformation IS the quality difference, and the paid vendors' real product.

### The one rule
Honesty is the whole trust position of a free directional tool. The moment it pretends the compass
is a scale, it loses the only thing that makes it credible. Keep the "directional, not audited"
labeling prominent, always.

---

## Alerting ("notify when a region becomes greener") — DEFER; mostly a trap as naive feature

Question: is a dynamic alert-when-a-better-region-appears feature value-add? Verdict: only the
durable-change version, and it's a separate build — NOT a v1 MCP tool. Don't build now.

### Two cases, only one actionable
- **Case A — hourly grid fluctuation** ("us-west-2 is cleaner this afternoon"). NET-NEGATIVE for
  GreenPick today: v1 models a LONG-RUNNING web service you can't relocate hourly, so these alerts
  fire constantly and can't be acted on -> notification fatigue (kills tools). Acting on hourly
  swings = TIME-SHIFTING, only valid for batch/deferrable workloads, which v1 doesn't model.
- **Case B — durable structural change** (region persistently dirtier; new greener region opened;
  grid added major renewables). GENUINELY actionable (response = a one-time migration decision), but
  rare/slow — more an occasional "reconsider" than an alert stream.

### Hard architectural constraint
MCP tools are REQUEST/RESPONSE — the model calls them; they can't PUSH when you're not in a session.
Real alerting needs a separate BACKGROUND WATCHER (scheduled poll of carbon data vs. your recorded
deployments + a notify channel) — outside the MCP model, a meaningfully bigger build. Same wall as
the earlier "track free tiers + alert" idea.

### Strategic echo
This "alert before/when X changes" layer is exactly StackPlan's paid-tier feature and the piece
flagged as hardest-to-sustain / lowest willingness-to-pay. The alerting instinct keeps recurring
and keeps hitting the same two problems: push doesn't fit MCP, and most alerts aren't actionable
enough to beat fatigue.

### Decision
Do NOT build alerting now. Keep GreenPick as the sharp, honest, PULL-based "ask me when deciding"
tool. IF the batch/time-shifting or data-platform direction lands later, THEN durable-change
alerting becomes meaningful — build it as a companion background service (with deployment state +
trend/persistence detection + restraint), not bolted onto the MCP. Post-core, not v1.

---

## Companion dashboard (webpage) — YES in two stages; better fit than alerting

Question: add a webpage/dashboard showing optimal regions' current state + trend columns
(30/90/120d)? Verdict: good direction — complementary to the MCP, pull-model fit. Build in stages.

### Why it fits (unlike alerting)
- A webpage is PULL-based (you choose to visit) -> sidesteps the "MCP can't push" wall that sank
  alerting.
- Complementary, not redundant: MCP = "decide NOW" (in-editor, one deploy question);
  dashboard = "understand the landscape + durable trends" (browsing). Clean division of labor.

### Stage 1 — single-page CURRENT-STATE dashboard: CHEAP, do it if continuing
Table of regions ranked by carbon now + cost/latency columns, color-coded. Every number already
computed by existing services; thin web view over them. Could reuse the FastAPI + static-page
pattern from kiro-meet-up. Days, not weeks. Great visual demo / portfolio artifact.

### Stage 2 — TREND columns (30/90/120d): bigger, same cost as alerting
Requires HISTORICAL data GreenPick doesn't store today (it's point-in-time, fetch-and-discard).
Need a background poller (scheduled EIA/ENTSO-E fetch) + a datastore. Backfill is possible because
EIA and ENTSO-E both offer HISTORY endpoints (good news) — but it's real ingestion work + storage +
the ongoing data-collection maintenance the research flagged as the true cost in this space.
Stage this LATER, only once the core tool proves worth that commitment.

### Strategic caution
A dashboard quietly drifts GreenPick from "MCP tool" toward "website product" — which is the
CROWDED space (DeployCost, dead StackPlan, etc.) found at the start. The MCP-in-your-editor angle is
the differentiation; keep the dashboard a COMPANION, don't let it become the main thing or you're
back competing with the website players.

---

## MILESTONE: EU live data achieved (ENTSO-E) — both continents now live

ENTSO-E token arrived (same day) and was added to .env. Live data confirmed on BOTH continents
via GREENPICK_CARBON_SOURCE=auto.

### Diagnosis along the way
- Token authenticates; all EU zones return HTTP 200 with real TimeSeries.
- EU regions were INTERMITTENTLY falling back to mock (Finland live one run, Sweden/Ireland live the
  next) — ENTSO-E is occasionally slow/empty per zone (their docs warn re: response times). Our
  honest fallback handled it (degraded that zone to mock), but it was flaky.
- Parser was fine (zones parse correctly when data arrives); it was transient upstream misses.

### Fix: light retry in entsoe_repository.py
3 attempts with brief backoff (0.6s, 1.2s) on empty/error before degrading to mock; auth 401/403
does NOT retry. Plus the existing 30-min cache holds a zone once fetched. Result: all EU regions
now reliably live.

### Confirmed live readings (plausible)
- Sweden (eu-north-1):   ~20.6 gCO2/kWh  entsoe/live  (hydro+nuclear+wind — very clean)
- Finland (europe-north1): ~73.6         entsoe/live
- Ireland (eu-west-1):   ~383.1          entsoe/live  (gas-heavy)
- US (EIA): us-west-2 ~99, NYISO ~272, PJM ~390       eia/live
14/14 tests pass. Committed + pushed.

### State: v1 feature-complete on live data
- US via EIA (instant key), EU via ENTSO-E (manual-approval key, now in hand), auto-routed.
- Non-US/EU -> mock, labelled. Both continents live + reliable. On GitHub (private).
- Remaining = roadmap only (vendor-as-real-axis, data platforms, dashboard stage 1/2, batch/time-
  shifting, deferred alerting). Strategic verdict unchanged: strong mission/portfolio artifact.

---

## Design decision: per-axis R/Y/G ratings alongside raw values (IMPLEMENTED)

Instead of collapsing to a single "us-east is best," expose each axis's rating so the USER applies
their own weighting (the tool can't know if they're latency-critical vs. carbon-first).

### Decisions
- **Per-axis R/Y/G** for carbon, latency, cost on each candidate — SHOWN NEXT TO the raw value
  (color backed by a number, never a bare light).
- **Relative banding** (transparent, no smuggled absolute thresholds): rank candidates within the
  current set per axis -> cleanest/fastest/cheapest third = green, middle = yellow, worst = red.
  Honest meaning = "best available among your options," not "good in absolute terms."
- **Aggregate stays LIGHT** — an "optimized_for" label (carbon|balanced|latency), NOT a blended
  single score (a blend would re-introduce the exact hidden-weighting black box we're removing).
- Fidelity reminder: carbon=live/real, latency=geographic estimate, cost=static ballpark. The
  ratings inherit that — ratings are directional, like everything else.

### Where it lives
- MCP output: carbon_rating / latency_rating / cost_rating fields per candidate (implemented now).
- Dashboard (future stage 1): where R/Y/G visually shines.

---

## Cost data: refreshed from live Vantage (Option A) — IMPLEMENTED

Cost was the weakest triad leg (hand-typed static table). Asked: scrape a live source? Finding:
no need to scrape — official/structured sources exist. Compared Infracost (unified 3-cloud GraphQL,
10M+ prices, auto weekly, needs key/self-host — more data) vs. Vantage ec2instances.info (free bulk
JSON, no key, VM-focused + specs — enough data, less friction). Both ultimately mirror providers'
official prices, so accuracy ~equal; chose VANTAGE for today's directional compute ballpark, with
Infracost noted as the upgrade path if cost becomes first-class or managed-services are added.

Also reframed "real-time": cloud on-demand list prices barely change (few times/year), so the need
is "current + auto-maintained," not real-time. (Spot/GPU prices DO fluctuate — out of scope.)

### Option A chosen (vs. Option B full instance-aware repo)
A = refresh script that rewrites pricing.json coefficients from live data; keeps GreenPick's
directional per-vCPU+RAM model unchanged. B = map workload->instance type->regional price (more
accurate but a modeling change + 317MB live dep + AWS-only). Picked A: fits the directional design,
low risk, no runtime dep.

### What was built: scripts/refresh_pricing.py
- Streams Vantage instances.json (~317MB) to a temp file, parses with ijson (dev-only tool, fast,
  constant memory), keeps only m5/m6i samples.
- Gotcha hit + fixed: those families all share 4GB-RAM/vCPU, so vCPU vs RAM are COLLINEAR — a 2-coef
  least-squares fails (det~0). Fix: take real mean $/vCPU across regions, split 25% to RAM
  (RAM_SHARE) consistent with the model. Honest, documented.
- Writes pricing.json with _as_of date + _source note. Fails SAFE (leaves file untouched on any error).
- Run occasionally: `python scripts/refresh_pricing.py`.

### Result (verified)
Real AWS coefficients from 71 regions: 0.0469 USD/vCPU-hr, 0.0039 USD/GB-RAM-hr (old stale guess was
0.034/0.0045). Sample 2vCPU/4GB/10GB-egress AWS service: ~81 USD/mo (was ~61 — the drift this fixes).
15/15 tests pass; cost model unchanged, only inputs refreshed.

### Honest scope
- AWS now real/current/refreshable; GCP/Azure coeffs + ALL egress still static (Vantage sample was
  AWS m5/m6i). GCP/Azure parity = small follow-up (sample their families).
- Still a DIRECTIONAL ballpark (no commitments/discounts/SKU specifics) — upgraded from "stale" to
  "current," not to "your actual bill."
- ijson is script-time only, NOT an MCP runtime dependency.

---

## Cross-cloud cost PARITY — fixed (apples-to-apples AWS/Azure/GCP)

Question: is cost comparison apples-to-apples across the 3 clouds? It was NOT:
- Only AWS had been refreshed from live data; GCP (0.032) + Azure (0.035) were stale hand-typed
  guesses. Comparing a fresh AWS price to a stale GCP guess = false signal (GCP looked ~30% cheaper
  just because it hadn't been updated). Most dangerous version of the gap.
- Even if all refreshed, the METHOD must match (same instance class, basis, derivation).

### Fix: refresh_pricing.py now does all 3 clouds with ONE matched method
- Matched general-purpose, 4GB/vCPU families per cloud: AWS m5/m6i, GCP n2-standard, Azure D-series
  v5 (regex ^d\d+[a-z]*v5$, excluding the 'l' low-memory 2GB/vCPU variants).
- Same basis (on-demand Linux), same derivation (mean $/vCPU across regions, 25% split to RAM),
  same _as_of date. Per-cloud failure leaves THAT cloud unchanged (fails safe).
- Vantage endpoints: aws instances.json, gcp/instances.json, azure/instances.json. Field gotcha:
  AWS/GCP use "vCPU", Azure uses "vcpu".

### Result (2026-10-12, verified) — now consistent
- AWS   (m5/m6i, 71 regions):     0.0469 /vCPU-hr, 0.0039 /GB-RAM-hr
- GCP   (n2-standard, 42 regions):0.0438,          0.0037   (slightly cheapest — plausible)
- Azure (D v5, 61 regions):       0.0472,          0.0039
All within ~8% — a plausible consistent picture, vs. the old false ~30% GCP gap. 15/15 tests pass.

### Honest limit
True parity is impossible (vendors define vCPU/RAM + discounts differently). This achieves
same-method / same-freshness / same-class = a CONSISTENT DIRECTIONAL comparison, not certified.
Egress still static per cloud (not refreshed). Still a ballpark, now apples-to-apples.

---

## Secondary sustainability features — prioritized menu (what fits vs. scope-creep)

Litmus for "belongs in GreenPick": grounded in a REAL fetched number + framed as a DESIGN-TIME
directional tradeoff. Not generic advice, not after-the-fact accounting.

### Tier 1 — natural extensions, low effort, high fit
- **Carbon-aware scheduling (time-shifting)** — "when today is region X cleanest?" for deferrable
  jobs (nightly ETL, batch training, backups). Highest-impact lever in the literature; reuses
  EIA/ENTSO-E (which also expose recent history). *** BUILDING THIS FIRST. ***
- **Greener instance family** — flag ARM/Graviton / newer-gen as more compute-per-watt
  ("use m7g instead of m5, ~same price, lower energy"). Specs already in Vantage data.

### Tier 2 — the "pull data more efficiently" idea, split honestly
- **Data-locality warning (fits)** — "compute far from your data = egress cost + transfer carbon;
  prefer the greenest region that doesn't force a big data move." Data-driven, complements the
  region picker. Good.
- **Generic query/transfer tips (weaker)** — compression, columnar, incremental, caching. Real
  sustainability advice but NOT grounded in a live number -> drifts toward a generic "green-coding
  linter," diluting GreenPick's data-grounded identity. Be cautious.

### Tier 3 — plausible, watch scope
- Embodied-carbon nudge (serverless/shared beats idle always-on VMs for bursty work). Directional, fits.
- Right-sizing nudge ("8 vCPU asked, 2 suffices") — overlaps cost tools; carbon framing is the distinct angle.
- Carbon budget / cumulative estimate (extends estimate_workload_carbon) — useful but edges toward
  the accounting/reporting use case we DON'T serve. Keep clearly directional if ever built.

### Tier 4 — AVOID (scope-creep traps)
- Full carbon accounting / ESG reporting (paid vendors' audited turf).
- Live measurement of running infra (needs billing-API integration; not design-time).
- Anything needing the background-watcher architecture (already rejected for alerting: MCP can't push).

### Common thread
Build only what reuses a real fetched number and stays design-time + directional. The region picker,
scheduling, instance-family, and data-locality all pass; generic tips and accounting do not.

---

## Secondary feature #1 BUILT: carbon-aware scheduling (cleanest_hours_to_run)

New MCP tool `cleanest_hours_to_run(provider, region, top_n)`: given a region, returns its cleanest
recent hours + % carbon reduction vs. the dirtiest hour, so a user can TIME a deferrable job
(nightly ETL, batch, backups, training) when the grid is greenest. Directional, design-time.

### How (no new endpoint)
- Added `carbon_history()` to the CarbonRepository Protocol -> list[HourlyCarbon].
- EIA: the existing carbon_now call already returns ~60+ recent hours; refactored to a shared
  `_fetch_rows`, then compute weighted intensity PER hour. Zero extra API cost.
- Mock: synthetic 24h curve (clean overnight/midday, evening peak) so it's testable offline.
- ENTSO-E (EU): v1 returns the synthetic fallback curve (multi-hour A75 XML parse = flagged TODO);
  honestly labelled via quality field, not hidden.
- Auto router + ElectricityMaps stub also implement carbon_history.
- New scheduling_service.cleanest_hours(); SchedulingAdvice/HourlyCarbon models.

### Live result (real EIA history, verified)
- NYISO (us-east-nyc): cleanest ~06-08:00 (~228 g); ~31% cut vs dirtiest hour (63 hrs analyzed).
- Pacific NW (us-west-2): cleanest ~02-03:00 (~41 g); ~82% cut (72 hrs) — hydro grids swing hard.
That ~82% shows WHEN can matter as much as WHERE for deferrable work — the literature's top lever.
17/17 tests pass (added mock-curve + EIA-multihour tests). 6 tools now register.

### Honest scope
US = real hourly history (EIA). EU = synthetic curve placeholder until ENTSO-E multi-hour parsing
is added (TODO). Flat-grid regions get a "time-shifting won't help, focus on region" note.
