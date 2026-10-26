# GreenPick — user-questions backlog

> ## ▶ NEXT SESSION: START HERE
>
> **The bottleneck is evidence, not code.** 11 tools are built, tested (44 passing), and committed,
> but none has been used by a real user. Everything rests on one untested bet: *that developers will
> change infra decisions for a directional carbon signal.* The disciplined next move is to VALIDATE
> that bet before adding a 12th tool.
>
> **Framing — ONE ENGINE, TWO SURFACES (not two products):** all value lives in the surface-agnostic
> engine (services + live data + honest math). The MCP is the real product (design-time, in-context —
> "greener option at the moment you choose"). A **dashboard** is a second possible surface, best thought
> of as a *demo / credibility surface* (a URL you send someone), NOT a co-equal product. A dashboard
> drifting into "a page you visit to look at carbon" is the after-the-fact tooling GreenPick set out to
> beat — keep it in service of validating the engine. **Hard rule if we ever build it: the dashboard
> calls the SAME services the MCP calls. Never reimplement the math. Two surfaces, one engine, zero
> duplicated logic.**
>
> **Do these in order:**
> 1. ✅ **Demo artifact — DONE (markdown).** `docs/demo.md` written with the 3 headline scenarios in
>    narrative order (training → egress backfire → forecast), every number captured LIVE from the tools.
>    Still open: a **thin demo dashboard** on the SAME services for a non-technical stakeholder (webpage
>    is the better vehicle there) — build if/when you need it for that audience.
>    Either way, **lead with `estimate_training_carbon`** (the 96% region swing on a real H100 run — the
>    one place the carbon signal is big enough to change behaviour), then `data_locality_egress_check`
>    (the backfire catch), then `carbon_forecast`.
> 1b. **Publish to GitHub (flip `bithug01/greenpick` private → public).** GitHub is the default home/
>    distribution channel for MCP servers — it's how the ecosystem expects to find and install them, and
>    it's a better demo vehicle than a markdown walkthrough for a *technical* audience. Optionally also
>    publish to PyPI so people can `uvx greenpick`. **Pre-publish checklist (verified 2026-10-12):**
>    - ✅ `.env` is gitignored (line 12) and NOT tracked; no real secrets in tracked files (only env-var
>      *names* in config + dummy test values "k"/"t"). Re-scan before flipping, but currently clean.
>    - ✅ **LICENSE — DONE.** MIT (© 2026 Data Science Advisers, LLC); README updated. Chosen for max adoption +
>      ecosystem norm, and it doesn't foreclose a later commercial/services layer (permissive core pattern).
>    - Add clear install instructions (the mcp.json snippet + env-var setup) to the README.
>    - **public ≠ validated.** Stars/clones mean the pitch *reads* well; only a user saying "I changed my
>      deploy because of this" is validation. Publishing is part of step 1 (credibility artifact), NOT a
>      substitute for step 3 (real user conversations). Don't let "we shipped it" feel like "we proved it."
> 2. **Pick ONE headline use case and make it airtight** — recommend *"where and when should I run this
>    training job?"* Everything you show first should be that path, end to end.
> 3. **Then the user conversation** (your side, out-of-session) — 3-5 people who actually make cloud/
>    training decisions. Watch which tool they reach for and which they ignore. That's the real deliverable.
>
> **Hold the line:** resist adding features until step 3 gives evidence. If we do build next, the
> LLM-inference estimator jumps the queue (rising relevance, reuses the GPU table) — but it's still
> building on the unvalidated bet. Demo → user → then build what they reached for.
>
> _Loose end: the 6 newer tools aren't in the greenpick `autoApprove` list in `mcp.json` (approval
> prompt on first call each). Harmless; flip when convenient._

---

A running list of the questions a developer would naturally ask GreenPick while building, phrased
the way they'd actually type them in the editor. The point is to work *backwards from the question*
to the tool: some are already answered, some are a tweak away, and some are the seed of the next
feature.

The "when is the grid cleanest to run my nightly job?" question is what led to `cleanest_hours_to_run`.
This doc is where the next ones live.

Legend for **Status**:
- ✅ **Answered** — a current tool handles this today.
- 🟡 **Partial** — a current tool gets close but misses part of it.
- 🔭 **New** — would need a new tool or data source.

_As of 2026-10-12. 14 tools: compare_regions_tri_axis, greener_alternative_to, estimate_workload_carbon,
region_carbon_now, cleanest_hours_to_run, cleanest_time_of_day, carbon_forecast, greener_instance_family,
data_locality_egress_check, estimate_training_carbon, serving_pattern_advice, carbon_metric_scaffold,
rightsizing_check, explain_methodology_and_limits._

---

## Already answered (sanity-check these still phrase well)

| Question (as a user would ask it) | Tool | Status |
|---|---|---|
| "Where should I deploy this API to keep carbon low without wrecking latency?" | `compare_regions_tri_axis` | ✅ |
| "I picked us-east-1 — is there a greener region within +50ms?" | `greener_alternative_to` | ✅ |
| "Roughly how much CO₂/month does this service emit in eu-west-1?" | `estimate_workload_carbon` | ✅ |
| "How dirty is the grid in Sydney right now?" | `region_carbon_now` | ✅ |
| "When today is us-west-2 cleanest to run my nightly batch job?" | `cleanest_hours_to_run` | ✅ |
| "Is there a greener instance family than m5 for the same size?" | `greener_instance_family` | ✅ |
| "If I move compute to Sweden but my DB stays in Virginia, does egress kill the win?" | `data_locality_egress_check` | ✅ |

---

## Partial — close, but the current tool misses something

| Question | Nearest tool | What's missing | Status |
|---|---|---|---|
| "My job runs for 6 hours — what's the cleanest 6-hour *window* to start it?" | `cleanest_hours_to_run` | ✅ SHIPPED — `window_hours` param finds the lowest-average CONTIGUOUS run; training auto-derives the window from run duration. | ✅ |
| "What's the cleanest region to run this *in the next 12 hours*?" (forecast) | `cleanest_hours_to_run` + `compare_regions` | Both are backward-looking (recent history / now). No forecast. Would need a forecast source. | 🟡→🔭 |
| "Across a whole month, which region is greenest *on average*?" | `region_carbon_now` | Point-in-time only. Would need a rolling-average / historical-mean reading. | 🟡 |
| "Rank these three regions *I* care about, not all of them." | `compare_regions_tri_axis` | ✅ SHIPPED — `regions` filter on compare + greener_alternative_to; baseline always kept in the set. | ✅ |
| "So what time should I actually start my training job?" | `estimate_training_carbon`, `cleanest_hours_to_run` | The cleanest window is reported as a past timestamp from recent history (e.g. "start at 2026-10-17T15"), which reads like a literal start date. Present it as a time of day ("start around 15:00 UTC") with the date shown only as evidence. Found in outside-agent testing (2026-10-23). ✅ SHIPPED 0.1.7 — `start_hour_of_day` field; notes say "start around HH:00 UTC … a recent pattern, not a forecast". | ✅ |
| "I'm on the US East Coast — is there a greener region within ~30 ms?" | `greener_alternative_to` | Catalog has nothing greener near New York, so the answer is always "stay put". Adding Canada Central (Montreal, hydro-heavy, ~20 ms from NYC) and its GCP/Azure equivalents would give a real alternative. Needs a carbon source for Québec. | 🟡 |
| "How do I use GreenPick from a Jupyter notebook?" | README "Turn on live data" | The `os.environ` tip only works when GreenPick is imported in-process. When the MCP client library launches it as a server, it forwards only a few system variables, so the keys must be passed via `StdioServerParameters(env=...)`; and Jupyter's `sys.stderr` has no `fileno()`, so `stdio_client` needs `errlog=<real file>`. Add a "Use from a Jupyter notebook" section with a working cell. Found in outside-agent testing (2026-10-23). ✅ SHIPPED 0.1.6 — README cell passes keys via `env=` and uses `errlog=`; verified against a clean pip install (live with `env=`, mock without). | ✅ |
| "What is GreenPick best for?" (asked by an AI agent, not a human) | server-level `instructions` | Agents learn GreenPick from the tool list, not the README, so they lead with region-picking (the first tools registered) and skip right-sizing — the opposite of the README's positioning. Set FastMCP `instructions` (sent to every client at connect) to name the strongest uses first: right-sizing, scheduling, training/inference, then region choice, with the guardrails. ✅ SHIPPED 0.1.6 — also tells agents to report mock/cached/historical as such and to say so when output is missing. | ✅ |
| "Where's `greenpick.mcp`?" (an agent following the README notebook cell) | README "In a Jupyter notebook" cell | An agent read `from mcp import ...` as a GreenPick submodule and went looking for `greenpick.mcp`, then fell back to importing GreenPick's internals directly — which skips the MCP connection, so it never receives the server instructions. Add a one-line comment in the cell: `# "mcp" is the MCP Python SDK, installed with greenpick — not a greenpick module`. Found in outside-agent testing (2026-10-25). ✅ SHIPPED 0.1.7 — plus a "keep errlog=" comment, since the next agent dropped that line and hit the fileno error. | ✅ |
| "I see 'mock' — is live data even possible?" | every carbon tool | Tool output said `quality: mock` with no reason; the explanation only went to the server log, which clients don't show. ✅ SHIPPED 0.1.8 — results that aren't live carry a `live_data_hint` worded for the cause (set to mock / missing key / source didn't answer / region not covered); egress and per-hub serving results now label their carbon quality; the forecast fallback says `mock` (not `historical`) when the history itself is mock. | ✅ |
| "When there's no live data, how good is the fallback?" | mock data layer | Mock today is one hand-set typical value per grid (realistic ballpark, unsourced) plus a synthetic hourly curve shared by every region — so timing advice on mock is meaningless. Replace with **per-calendar-month averages and real hour-of-day profiles** computed from the last 12 months of EIA / ENTSO-E data by a refresh script (like `refresh_pricing.py`) and bundled; label them e.g. `typical` with the source and year. Seasonally right without frequent refreshes (a frozen 90-day average would be the wrong season within months). Gaps: Sydney has no free source in GreenPick (keep hand-set); EU pull waits on ENTSO-E being reachable. ✅ SHIPPED 0.2.0 — `scripts/refresh_typical.py` builds `data/typical.json` (10 regions, 12 months each, from a year of EIA/ENTSO-E data); it's the default and the fallback, labelled `quality: "typical"`; `mock` now only for Sydney. Timing notes flag when a big % swing is only a few gCO2/kWh. Refresh once or twice a year. | ✅ |
| "Is right now a clean or dirty moment for this grid?" | `region_carbon_now` (+ region tools) | Show the typical monthly value next to a live reading, e.g. "live 362 now; typical for October 354", from the `typical.json` already bundled. Deferred from 0.2.0 to keep that release to the core change. | 🟡 — next |
| "My users are in Asia — where should I serve them from?" | `serving_pattern_advice` | Sydney is the only Asia-Pacific region in the catalog, so Singapore-area users get ~199 ms. Add Singapore / Tokyo / Mumbai regions (and a carbon source or labelled mock for each). | 🟡 |

---

## Ideas by theme (shipped + still-to-build, mixed together on purpose)

> **How to read the icons** (this section mixes done and not-done, grouped by theme so related
> ideas stay together):
> - ✅ = **already built and shipped** — a live tool. NOT a to-do. Kept here with its "verified X"
>   note so the history of each theme is visible.
> - 🔭 = **not built yet** — a genuine future idea. **These are the only to-build items.**
> - 🟡 = partially built.
>
> **So the actual to-build list = the 🔭 items only.** The ✅ ones are context, not work.

> ### Value ranking of the 🔭 items (when it's time to BUILD — but validate with users first)
> Nothing below beats the "START HERE" plan (demo → GitHub → user conversations); every item is a bet
> on an untested assumption. Scored on: changes a decision? · data gettable & honest? · cheap to build
> on what exists? · stays in-lane? Items are grouped by theme below; this is the priority across them.
>
> **Tier 1 — high value, low regret**
> 1. `estimate_inference_carbon` (LLM inference by size class) — timely, reuses the GPU/grid machinery; spike the per-class energy table first; self-hosted/size-class, NOT a named-model leaderboard.
> 2. PR-justification formatter — formats an existing recommendation as prose; no new data/math; gets GreenPick into the team workflow (PR/decision record). Cheapest value on the board.
> 3. `data_profile` modifier — a lens that makes egress/serving/training realistic per workload; cheap (defaults + caveat re-ordering); surfaces the media/CDN gap.
>
> **Tier 2 — real value, more work / softer payoff**
> 4. "Batch across the cleanest hours" (a scheduling PLAN) — best pure-scheduling extension; composes on the forecast curve.
> 5. Utilization-aware estimate (spiky/idle/serverless) — makes the carbon estimate honest for bursty apps; correctness upgrade more than a wow.
> 6. Migration payoff ("move the data too, over 12 months?") — sharp follow-on to the egress tool; decisive for a smaller slice.
>
> **Tier 3 — nice, lower leverage / harder**
> 7. Sub-regional / AZ carbon (depth on our lead axis). 8. Aggregate savings roll-up (presentation layer; edges toward disclosure). 9. Container vs VM vs serverless (needs opaque platform-overhead data — spike first). 10. Storage placement (overlaps egress/serving).
>
> **Tier 4 — park / resist**
> 11. CDN/edge carbon — high value but a research problem (poor multi-location data); may graduate from the `data_profile` media insight, needs its own spike. 12. Per-vendor CFE / renewable-matching — the highest-rot, marketing-adjacent CFE trap; park unless the data situation changes.
>
> **One-line directive:** build #2 (PR formatter) first as a quick adoption win, then #1 (LLM inference) as the flagship. Let a user asking for anything else be the signal it's worth building.

### Scheduling / time
- ✅ "What's the carbon forecast for a region over the next 24h?" — SHIPPED as `carbon_forecast` (ENTSO-E A69 renewable-curve ranking, EU true-forecast + share where load exists; US degrades to historical). Verified live: SE 69% renewable-share peak, IE wind-MW peak, us-west-2 historical fallback. **Spike findings below.**

> **Forecasting data spike (ENTSO-E, live-probed):**
> - ✅ **A69 wind+solar day-ahead forecast** is reliable across zones: SE returns ~99 hourly points (several days), IE ~26h. psrType B16 (solar) + B19 (wind). This is the dependable signal.
> - ⚠️ **A65 load forecast** works for SE but is EMPTY for IE ("No matching data found"). ❌ **A71 total-generation forecast** likewise empty for IE. So load/total-gen are NOT dependable denominators across zones.
> - **Conclusion:** an absolute gCO₂/kWh *forecast* is not reliably buildable (no forecast fuel mix; load missing in places). But a RELATIVE "which upcoming hours are cleaner" signal IS — rank hours by forecast renewable (wind+solar) output. More forecast renewables = cleaner hour. Directional, honest, zone-robust.
> - **Design:** forecast tool fetches A69, builds an hourly renewable-output curve, ranks the cleanest upcoming hours/window. Where A65 load exists, optionally refine to a renewable-SHARE ratio. Degrade path: forecast → fall back to the historical pattern we already compute, relabelled `quality:"forecast"` vs `"historical"`/`"live"`. US (EIA) has no free generation-mix forecast → stays history-based for now; EU gets true forecast first.
- 🟡 "I have a flexible weekly job — what's the single best hour of the week to run it?" — PARTIALLY SHIPPED as `cleanest_time_of_day` (daily time-of-day pattern averaged across ~13 days of EIA data). True 7-day day-of-week patterning still needs a longer, weekday-labelled history window.
- 🔭 "Batch this across the cleanest hours until it's done" — a *plan* (list of hour-slots summing to N compute-hours), not just the single cleanest hour.

### Workload shape (beyond the one always-on web service)
- ✅ "I'm training a model for ~40 GPU-hours — where and when is that greenest?" — SHIPPED as `estimate_training_carbon` (GPU power table + region ranking + cleanest-hours timing). Verified: 1×H100×40h = 33 kWh, 96% region swing + further ~57% timing.
- 🔭 "This is a spiky, mostly-idle service — does serverless change the carbon math?" — utilization-aware estimate (idle vs active watts), not flat always-on.
- 🔭 "Compare container vs VM vs serverless for the same workload's carbon." — needs a per-platform overhead model.
- ✅ "What's the carbon of running this LLM inference?" — SHIPPED as `estimate_inference_carbon` (size class × output tokens × requests × live grid; low–high band; MoE handled; self-hosted-friendly, not a named-model leaderboard). Verified live: 1M req/mo @300 out-tok in Stockholm — small ~0.8–4.6 kg, frontier ~41–152 kg CO₂/mo (~50× size-class lever). +5 tests (65 passing). The inference-side sibling of `estimate_training_carbon`.
  - **Scope it as an ESTIMATOR, not a leaderboard.** Key on **model SIZE CLASS** (~8B / ~70B / ~400B-MoE) + token count + (optional) region — NOT named commercial products. Output directional Wh + gCO₂ for this usage, with the uncertainty stated as loudly as the network-energy coefficient.
  - **Best framing = self-hosted open-model inference** (Llama/Mistral on your own GPU instance): then energy is grounded in the GPU table + region grid we can actually model, not vendor secrets. The comparison ("an ~8B model is ~Nx less energy than a ~400B for this") emerges naturally without stamping a grade on a product.
  - **Data-spike first** (like forecasting): published Wh-per-1k-tokens / Wh-per-query estimates vary by >1 order of magnitude and vendors don't disclose serving hardware/batching. Confirm a defensible size-class energy table (cited, directional) BEFORE building. If the data won't support even directional per-class figures, don't ship it.
  - **✅ SPIKE DONE (2026-10-16): BUILDABLE. Richer peer-reviewed data than expected — mostly measurement studies, not marketing.** Anchors found:
    - **~0.3–0.4 Wh per typical query, frontier models (>200B).** arXiv 2509.20241: median **0.34 Wh/query** (IQR 0.18–0.67) for >200B models on an H100 node w/ realistic utilisation+PUE. Corroborated: GPT-4o short query ~**0.42–0.43 Wh** (arXiv 2505.09598).
    - **Size class is a REAL, strong driver.** arXiv 2407.16893: a 70B model uses **~2 orders of magnitude more energy per token** than small models; output-token length predicts energy (R²>0.95). So per-SIZE-CLASS directional figures ARE defensible — exactly our scoping.
    - **Output tokens, not input, dominate** — energy tracks *generated* tokens + response time. Tool should key on output-token count (or total, flagged).
    - **Caveats to bake in:** quantisation, batching, and request shaping move energy by up to ~100× for the SAME model (arXiv 2601.22362) — so our number is "typical serving," wide band, directional. **MoE breaks the size→energy trend** (a MoE runs nearer its *active*-param count, not total) — flag `~400B-MoE` separately, don't treat as dense-400B.
    - **Honesty holds:** the "How Hungry is AI" paper DOES rank named models (o3/DeepSeek-R1 highest, Claude-3.7 eco-best) — we can CITE that exists but still refuse to build a named-model leaderboard ourselves (stale every release). Size-class + self-hosted stays the honest lane.
    - **Design confirmed:** `inference_energy.json` = Wh-per-1k-output-tokens by size class (small ~1–7B / mid ~13–70B / frontier >200B dense / MoE), each a LOW–HIGH band, cited; × output tokens × requests × (region grid for CO₂). Reuses grid machinery. Build ~1 service + 1 tool + 1 data file + tests.
  - **Why NOT a comparative "greenness score" of named models (Claude vs GPT vs Llama):** built on numbers vendors won't confirm, stale every model release, and drifts toward disclosure/marketing — the same line we hold against the free-tier comparator and the CFE axis. See anti-questions.

### Serving pattern (where to serve users from)
- ✅ "My users are spread across EU/US/APAC — should I serve from one region or several?" — SHIPPED as `serving_pattern_advice` (verified live: concentrated-US → single region; EU/US/APAC spread → multi-region, 171ms→66ms, data-sync egress note fired): a DESIGN-TIME multi-region / single-region advisor. Takes a user-geography distribution (rough buckets ok) + workload, scores single-region-per-hub vs one-region-for-all on carbon + latency, and composes the egress (cross-region data-sync) + residency (cross-jurisdiction) flags we already built.
  - **In lane:** design-time, directional, stateless, reuses carbon/latency/egress/residency. NOT a runtime meter.
  - **NOT a runtime CPU/power meter.** We refuse to tell users to embed a live power meter and report back — that's runtime instrumentation GreenPick can't perform or verify, drifts into monitoring/disclosure, and CPU-util ≠ watts without a model. Point such users to real observability/carbon-measurement tools (same as ESG → audited vendors). See anti-questions.
  - **Trigger via description, not file-scanning:** an MCP server can't see the user's codebase; the host agent can. So the tool DESCRIPTION invites the agent to offer it when the user is building a user-facing platform/service. Context-aware nudge, model-mediated.
  - **Caveat:** user-geography is a soft, often-unknown-at-design-time input → accept rough % buckets, label directional loudly.

### Runtime carbon visibility (instrument the app, don't meter it)
- ✅ "Add a carbon metric to my app so I can see its footprint over time." — SHIPPED as `carbon_metric_scaffold` (Python v1; emits valid, self-labelled code with live grid baked in — verified by compile+exec tests). GreenPick EMITS instrumentation code the builder pastes in; it does NOT run or measure anything itself. (Other languages: port the methodology formula — easy follow-on.)
  - **The honest core:** software can't read its own wattage. The app measures the cheap PROXIES it CAN observe (CPU util, vCPU/RAM, region, uptime), then applies GreenPick's power model (power.json) × live grid intensity (region_carbon_now) → an ESTIMATED gCO₂. GreenPick's value = it supplies the coefficients that make the metric meaningful; a bare CPU% metric says nothing about energy.
  - **Deliverable = snippet + coefficients + methodology note.** A paste-in code block (Python v1), the power coefficients, and a comment block citing the model + limits. NOT a framework/SDK (that's a different, bigger product — resist).
  - **Self-labeling, loudly.** The generated metric is named `estimated_gco2*` with a comment that it's a DIRECTIONAL estimate from proxies × GreenPick's model, not metered energy. It'll live in production dashboards and get quoted, so it must not read as truth. If it can't be made clearly self-labeling, don't ship.
  - **v1 = SELF-tracking, not cross-app ranking.** Track YOUR app's estimated carbon over time / versions / regions / load. Cross-app comparison needs a shared spec (same proxies, boundaries, coefficients) or it's noise — that's the leaderboard trap; defer.

### Data & storage
- 🔭 "Where should I put this 5TB bucket to minimize carbon + egress to my users?" — storage-placement counterpart to compute placement; ties into the egress tool.
- 🔭 `data_profile` — an OPTIONAL modifier (not a new standalone tool) on existing tools (egress, serving_pattern, training): `structured` / `unstructured-blob` / `image` / `video` / `logs`. Data TYPE strongly predicts which of our axes dominates, because our carbon/egress/serving math is byte- and compute-driven: a DB row is bytes, an image is MBs, a minute of video is tens-hundreds of MB — the SAME "move the data" decision is ~1000× the egress/transfer-carbon for video vs structured.
  - **Three honest jobs:** (1) set REALISTIC volume defaults when the user doesn't know their GB (video → large egress; structured → small-but-chatty); (2) RE-ORDER which caveat leads (video → egress/CDN warning first; structured transactional → data-sync/latency/residency first); (3) flag the type-specific carbon driver (image/video → GPU-bound, see training/instance tools; structured analytics → region carbon dominates).
  - **Lens, NOT a detector or a verdict.** GreenPick can't see the user's data; the user/agent supplies the profile (model-mediated, like everything else). **No per-type carbon NUMBERS** (e.g. "video = X gCO₂/GB") — made-up coefficients. Volume defaults are rough → loud "override me" labels, like the user-geography input. Strictly optional so simple cases stay simple.
  - **Flagged future gap it surfaces:** media/video is egress-DOMINANT (served out repeatedly), so "where you SERVE from + CDN/edge" matters far more than "where you compute" — our serving_pattern tool reasons about origin regions, not edge caching. **Media/CDN-aware serving** may deserve its own future tool; data type is what reveals the blind spot.
- 🔭 **DECISION (2026-10-12): `data_profile` + format advice MERGE into ONE tool, `data_efficiency_advice`.** Both are the same "shape/format of your data drives its efficiency" theme; separately each is too thin, together they're one substantive tool worth reaching for. NOT two tools. Format/columnar advice is NOT its own dedicated tool — it's a facet of this combined tool. (Rationale: a static-advice-only tool is really a doc lookup; and tool sprawl dilutes discovery. The combined tool computes conditional advice from real inputs — type + format + access pattern + rough size.)
> **`data_efficiency_advice` now has THREE facets** (all the same "shape/format/engine of your data drives efficiency" theme — one tool, conditional on real inputs: data type + format + access pattern + rough size vs memory):
> 1. **data type** (from `data_profile`) — structured/image/video → which axis dominates.
> 2. **format** (below) — row (CSV/JSON) → columnar (Parquet) for repeated analytical reads.
> 3. **engine/compute pattern** (below) — in-memory (pandas) → streaming/out-of-core (Dask/Polars/DuckDB) when data approaches/exceeds RAM.

- 🔭 `data_format_advice` (FACET of `data_efficiency_advice` — not standalone). For REPEATED ANALYTICAL reads of a row-based file (CSV/JSON), recommend a columnar format (Parquet). Real mechanism, pure efficiency dual-benefit: columnar + compression reads a fraction of the bytes (column/predicate pushdown, skip row-groups) → materially less I/O, CPU, storage AND egress for analytical queries.
- 🔭 `data_engine_advice` (FACET of `data_efficiency_advice` — not standalone). When data approaches/exceeds RAM, suggest a streaming/out-of-core/columnar engine (Dask, Polars, DuckDB) over loading it all into pandas.
  - **The real mechanism is avoiding thrash, not magic.** Loading 50GB into pandas blows past RAM → swap thrash (huge wasted I/O/CPU) or OOM-crash + re-run. Streaming engines push predicates down, parallelise, don't materialise everything → same query, far less wasted work.
  - **CONDITIONAL — sharp counter-case.** For data that FITS comfortably in memory, pandas is often MORE efficient; Dask's scheduler/partition overhead makes small jobs slower + more energy-hungry. Advice is THRESHOLD-based (near/above RAM), not "use Dask for everything" (that's the "always Parquet / always greenest region" trap).
  - **Pairs with format:** columnar engine + Parquet is the combined move — exactly why these are one tool, not scattered.
  - **Mechanism, not a number** (no "Dask saves X%"); and **NOT a general tool-ranker** — name the efficiency PATTERN (streaming/out-of-core) + free tools that embody it as examples, stay on the energy lever, no general "best library" opinions.
  - **Advice, NOT detection.** GreenPick can't see the user's files; the user/agent supplies "I'm doing repeated analytical reads of a ~N GB CSV" (or the agent notices `read_csv` in a hot path and offers it). Model-mediated trigger via tool description — same pattern as serving_pattern / metric scaffold.
  - **CONDITIONAL, state the counter-cases.** Columnar wins for repeated columnar/analytical access. It's the WRONG call for tiny files, write-heavy/append-constantly data, row-by-row transactional access, or one-shot reads. "Always use Parquet" is this feature's version of "always go to the greenest region" — must name the condition + the counter-cases.
  - **Mechanism, not a magic number.** NO fake "CSV→Parquet saves X gCO₂" coefficient. Output is directional: name the I/O/compression/pushdown mechanism and that it depends on access pattern + data shape. Same discipline as the network-energy coefficient.
  - **Scope:** cheap (advice + documented rationale, no new data source); fold into `data_profile` or ship as a small sibling. Lower priority than Tier-1 (PR formatter, LLM inference) per the value ranking.

### FinOps patterns to borrow (efficiency half only)
FinOps splits into **efficiency** (do less work / waste less — cost AND carbon fall together) and
**financial engineering** (pay less for the same work — zero carbon signal). GreenPick borrows the
PATTERNS from the efficiency half (design-time, directional, no billing-account access); it does NOT
touch the financial-engineering half or anything needing the actual bill. Carbon rides the OpEx motive.

- ✅ **`rightsizing_check` — SHIPPED.** The #1 FinOps finding (over-provisioning), pure dual-benefit. Takes provisioned vcpu/ram + observed utilisation → right-sized target (keeps ~40% headroom) with monthly $ AND kg CO2 saving; only flags if saving ≥10%. Reuses power + cost coefficients; user supplies utilisation (no billing access). Verified live: 8 vCPU @15% → 1.7 vCPU, ~$216/mo + ~8 kg CO2/mo (54%). +3 tests (60 passing).
- 🔭 **Non-prod / idle scheduling** — "this doesn't need to run 24/7." Deferrable-EXISTENCE (vs our deferrable-timing): running 60h/week not 168 cuts ~64% of cost + carbon. Cheap extension to the carbon estimate.
- 🔭 **Scale-to-zero / autoscaling framing** — same lever as the backlogged utilisation-aware estimate, carbon lens on idle watts you pay + emit for. Reinforces building that item.
- 🔭 **Storage tiering** — borrow the "tier by access frequency" idea (hot→cold→archive) into storage-placement; modest carbon angle.
- 🔭 **FinOps reporting idioms** — steal the presentation patterns ("est. monthly savings", "pays back in N months", "waste as % of spend") for the PR-formatter + aggregate-savings items. Lead with the $ figure, carbon as the twin.

**OUT OF LANE — do NOT borrow (no carbon signal and/or needs billing-account data):**
- ❌ Commitment discounts (reserved instances / savings plans / committed-use) — financial engineering, SAME energy, cheaper contract. Zero carbon dual-benefit; needs account/pricing specifics.
- ❌ Spot / preemptible — carbon-neutral (same hardware), and it's runtime/orchestration not design-time. (Only curiosity: spot capacity *may* correlate with low-demand/clean-grid windows — speculative, data-thin.)
- ❌ Billing-data features (anomaly detection, tag/cost allocation, commitment-coverage) — these ARE the FinOps platforms (Vantage/CloudHealth/Cloudability); require billing access we don't and shouldn't have. Competing there drags us out of the design-time lane.

> **The dividing line:** borrow EFFICIENCY (cost & carbon are the same lever), ignore FINANCIAL ENGINEERING (no carbon signal, needs the bill).

### Graphics / visuals (for demo + README)
- ✅ Four SVGs in `docs/img/`: region-carbon-30x (hero — same H100 run, 30× between Stockholm/Sydney), cleanest-hours-us-west-2 (24h curve, ~57% overnight), egress-by-tier (the $270→$30-60/$255-360 correction), decision-flow (where→check→when). Real data, self-labelled directional. Hero + curve embedded in demo.md.
- 🔭 "Does moving my data to the greener region (not just compute) pay off over 12 months?" — amortize a one-time migration-egress cost against ongoing carbon saving. Natural follow-on to `data_locality_egress_check`.

### Data residency / sovereignty
- ✅ "Would moving compute to this region break data-residency rules (e.g. GDPR)?" — SHIPPED as a residency-AWARENESS flag (NOT a compliance checker): `jurisdiction` tags in regions.json + a neutral cross-jurisdiction heads-up on compare/greener_alternative, estimate_training_carbon, and data_locality_egress_check, with a hard "not legal advice, confirm with governance" disclaimer. **Spike findings below.**

> **Residency data spike (jurisdiction tagging):**
> - GOAL: can we get a clean, STABLE jurisdiction tag per region, to flag cross-jurisdiction moves? YES.
> - All 12 catalog regions tag cleanly: **EEA** = Ireland (eu-west-1, northeurope), Sweden (eu-north-1,
>   swedencentral), Finland (europe-north1); **US** = us-east-1, us-west-2, us-central1,
>   us-west1, eastus; **AU** = ap-southeast-2. No UK region in catalog → the thorny Brexit case doesn't arise.
> - CORRECTNESS NOTE: the GDPR boundary is the **EEA** (27 EU + Norway/Iceland/Liechtenstein), not "EU".
>   Tag the EEA. (Confirmed: ICO/EDPB.)
> - WHAT TO ENCODE: only the stable `jurisdiction` tag (is the region in the EEA/US/AU/...). **Do NOT encode
>   adequacy status or legal mechanisms** — those ROT fast (Brazil added adequacy Jan 2026; US framework is
>   legally contested). Encoding them would be the CFE/leaderboard trap again.
> - DESIGN: add `jurisdiction` to regions.json; recommendation tools raise a NEUTRAL heads-up when a move
>   crosses jurisdictions (esp. leaving the EEA), stating only the geographic fact + the category of concern,
>   with a HARD "GreenPick does not assess legal compliance — confirm with your own data governance" disclaimer.
>   A flag, never a yes/no verdict. Add "does NOT determine legal compliance" to anti-questions.

### Vendor / grid nuance
- 🔭 "Does this provider actually run this region on renewables, or is it just a clean grid?" — per-vendor CFE / renewable-matching data as a *real* axis (today we explicitly ignore RECs). Recorded earlier as "vendor-as-real-axis."
- 🔭 "What's the sub-regional / availability-zone carbon difference?" — finer grid-zone mapping than our country-level approximation.
- 🔭 "Include my CDN / edge locations in the carbon picture." — multi-location aggregate.

### Reporting / decision-capture (lower priority — drifts toward disclosure, which we said we're NOT)
- 🔭 "Give me a one-paragraph justification for choosing this region, for my PR description." — formats an existing recommendation as prose. Cheap, high-charm, no new data.
- 🔭 "What would I save (carbon + $) by making all these changes?" — aggregate across several recommendations.
- 🔭 **Sources & verification** — surface the AUTHORITATIVE primary source for each number GreenPick states ("~$0.01-0.02/GB cross-region; confirm at <AWS Data Transfer pricing>"), so "directional, go verify" says *where*. Completes the honesty posture.
  - **Low-rot, and the right way to handle data we deliberately keep directional:** a LINK to a provider's pricing page stays current on its own — unlike EMBEDDING fast-changing data (the trap we've refused for egress/CFE/adequacy). Links give the user live precision without us owning the maintenance.
  - **Contextual, not a link farm:** each tool optionally returns its source WITH its answer; `explain_methodology_and_limits` lists them. Partly just SURFACING the `_source` fields our data files already carry (pricing.json / emission_factors.json / inference_energy.json) — so it's cheap.
  - **Guardrails:** links must be PRIMARY/authoritative (provider pricing page, the actual arXiv paper, the official EEA list) — never a blog. Tie each link to a specific claim we make. Small **dead-link upkeep** cost (a dead link erodes the very trust this builds). Scope strictly to verification sources for numbers we already produce — NOT a curated "cool cloud-cost sites" directory (that rots).

---

## Anti-questions — things we should keep REFUSING to answer

Keeping these written down is as valuable as the backlog: they're the scope discipline that keeps
GreenPick honest.

- ❌ "Give me my official Scope-2 / GHG-Protocol carbon number." — GreenPick is directional decision
  support, not audited accounting. Point to the paid vendors (Electricity Maps, WattTime).
- ❌ "Which cloud has the best free tier?" — rejected earlier: no carbon signal, highest-rot data,
  wrong audience.
- ❌ "What's the exact egress bill for this transfer?" — we give a directional ballpark on purpose;
  real egress pricing (tiers, inter-region pairs, free allowances) is a quote, not our job.
- ❌ "Act as a live scheduler / actually move my workload." — design-time advice, not an orchestrator.
- ❌ "Give me a greenness leaderboard / letter-grade of named commercial LLMs (Claude vs GPT vs Llama)." — built on per-token energy and serving-hardware figures vendors don't disclose, stale every release, drifts into disclosure/marketing. We'll ESTIMATE per-inference carbon by model SIZE CLASS (esp. self-hosted), but not grade named products. Same discipline as the free-tier comparator and CFE axis.
- ❌ "Is it legally compliant to run this in region X? / Is this GDPR-ok?" — GreenPick determines NO legal compliance. It flags cross-jurisdiction moves (esp. leaving the EEA) as a geographic heads-up with a hard "confirm with your own governance" disclaimer, and encodes NO adequacy status (that rots). Residency is a flag, never a verdict.
- ❌ "Embed a live CPU/power meter in my app and report its carbon." — runtime instrumentation GreenPick can't perform or verify from an MCP server; CPU-util ≠ watts without a model; drifts into monitoring/disclosure. GreenPick is design-time. Point to real observability / carbon-measurement tooling. (serving_pattern_advice gives the design-time version — where to serve from — not a runtime meter.)

---

## Competitive landscape (researched 2026-10-17)

Baseline snapshot for strategic memory — competitors move, so re-check before any launch.
**Verdict: the uniqueness claim survives — nobody offers cross-cloud + carbon/cost/latency + workload
breadth + in-editor + design-time. The closest MCP is thin; the richer tools are the wrong moment or
single-cloud.**

**Direct overlap — WATCH:**
- **SustainOps MCP** — the one real category competitor (MCP server ranking AWS regions by carbon).
  As researched: mock data, no workload estimates, no cost, no latency. *Owns the label, substance is
  thin.* Risks: (1) **discoverability** — if it owns the search term, we're the better product nobody
  finds; (2) **it could close the gap** (mock→real + add axes isn't hard). Our durable moat is NOT the
  tri-axis (copyable) — it's the **backfire guards + honesty discipline + workload breadth**.

**Adjacent — different moment, NOT direct competitors:**
- **EcoOrchestrator / GreenPipe** — CI/CD stage: score pipeline jobs, comment least-carbon region on
  MRs. Double meaning: (a) not our moment (merge-time, not in-editor), BUT (b) they already do the
  auto-trigger-on-code-change thing our "only answers when asked" gap wants. **So the CI/CD roadmap
  item is CONTESTED ground, not greenfield — temper enthusiasm; our edge there would be tri-axis depth,
  not the trigger.**
- **Measurement tools** (Cloud Carbon Footprint, CodeCarbon, Kepler, Green Metrics Tool) — report what
  you emitted AFTER deploy. Different job (measure vs choose). Not competitors; the thing we hand off to.
- **Cloud-provider tools** (AWS CCFT, Azure Emissions Dashboard, Google Carbon Footprint + "Low CO₂"
  region leaf) — **Google's leaf is the closest conceptual overlap** (design-time carbon hint at the
  choice) but single-cloud, carbon-only, no tradeoff, inside their console. Validates the idea; our
  defense is cross-cloud neutrality + editor context + breadth (AWS won't help you pick GCP).

**Component overlap — building blocks, NOT rivals (a strength):**
- **Electricity Maps, WattTime, GSF Carbon Aware SDK** — data/SDK inputs. We already use the free
  equivalents (EIA, ENTSO-E). Data layer is a solved commodity; our value is the DECISION layer on top.

**Strategic takeaways:**
1. Uniqueness claim holds — the *combination* isn't offered elsewhere.
2. Moat is the hard-to-copy parts (guards + breadth + honesty + cross-cloud), NOT "we show 3 axes."
3. CI/CD is contested (EcoOrchestrator/GreenPipe) — enter only on tri-axis depth, not the trigger.
4. Done: a "How it differs" note is in the README (pre-empts "isn't this just CCF / Google's leaf?").

---

## Business model (NOT features) — park, don't build

These are revenue/strategy directions, not tools. Recorded so they're not lost, but they are
founder/market bets, not engineering tasks. Do NOT let them pull the engine off its honest line.

### Professional services around sustainability business objectives
- **What it is:** not a third *surface* (that's the MCP + dashboard, which share one engine). This is a
  different *business model* that would USE the engine as one input. Different house, not a third door.
- **Why it's attractive:** likely the LARGEST revenue prize in the whole picture — bigger than the tool
  earns directly. Companies already pay real money for "help us hit our sustainability objectives" (ESG
  mandates, CSRD, cloud-cost-is-also-carbon). GreenPick is a credible *wedge*: you show up as "the people
  who built the carbon-aware deployment tooling," tool = proof-of-expertise + lead-gen, engagement = revenue.
- **The trap (this is the important part):** services clients want AUDITED numbers (Scope-2 / GHG-Protocol)
  and regulated advice (procurement, CSRD audit readiness) — exactly what the engine REFUSES to fake. That
  pulls the engine toward the overclaiming its integrity is built on avoiding. You'd either compromise the
  tool's honesty, or stand up a SEPARATE audited data layer (paid vendors: Electricity Maps / WattTime)
  beside the directional engine. Real work, real identity question.
- **It runs THROUGH validation, doesn't skip it:** you can't pitch a services engagement without a credible
  artifact to point at — i.e. the demo + user conversations at the top of this doc. If an early user says
  "can you just help us DO this," that IS the signal the services model has pull — discovered for free.
- **Status:** unvalidated, bigger unknown than the tool itself ("will a company pay YOU to steer their
  sustainability strategy" is a market question, not an engineering one). Revisit only after the user step.

---

## How to use this doc

When a new question comes up (yours or a user's), add it to the right section. If a question keeps
recurring and sits in 🟡 or 🔭, that's the signal to build. Prefer questions that (a) have a real
carbon mechanism, (b) use data we can get for free, and (c) fit the "decision, not disclosure" line.
