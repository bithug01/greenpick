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
> 1. **Build the demo artifact.** Goal: make a user conversation possible by showing the strongest path
>    without asking anyone to wire up MCP. Two valid forms — pick per audience:
>    - `docs/demo.md` — 3-4 copy-paste scenarios in narrative order (fastest to write), OR
>    - a **thin demo dashboard** — richer vehicle for a non-technical stakeholder, pointed at the SAME
>      services (no duplicated logic). For most stakeholders the webpage is the better demo.
>    Either way, **lead with `estimate_training_carbon`** (the 96% region swing on a real H100 run — the
>    one place the carbon signal is big enough to change behaviour), then `data_locality_egress_check`
>    (the backfire catch), then `carbon_forecast`.
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

_As of 2026-10-12. 11 tools: compare_regions_tri_axis, greener_alternative_to, estimate_workload_carbon,
region_carbon_now, cleanest_hours_to_run, cleanest_time_of_day, carbon_forecast, greener_instance_family,
data_locality_egress_check, estimate_training_carbon, explain_methodology_and_limits._

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

---

## New — the seeds of future tools

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
- 🔭 "What's the carbon of running this LLM inference?" — `estimate_inference_carbon`. The inference-side sibling of `estimate_training_carbon`, and a natural fit: reuses the GPU power table + live grid + the training energy→CO₂ pattern already built.
  - **Scope it as an ESTIMATOR, not a leaderboard.** Key on **model SIZE CLASS** (~8B / ~70B / ~400B-MoE) + token count + (optional) region — NOT named commercial products. Output directional Wh + gCO₂ for this usage, with the uncertainty stated as loudly as the network-energy coefficient.
  - **Best framing = self-hosted open-model inference** (Llama/Mistral on your own GPU instance): then energy is grounded in the GPU table + region grid we can actually model, not vendor secrets. The comparison ("an ~8B model is ~Nx less energy than a ~400B for this") emerges naturally without stamping a grade on a product.
  - **Data-spike first** (like forecasting): published Wh-per-1k-tokens / Wh-per-query estimates vary by >1 order of magnitude and vendors don't disclose serving hardware/batching. Confirm a defensible size-class energy table (cited, directional) BEFORE building. If the data won't support even directional per-class figures, don't ship it.
  - **Why NOT a comparative "greenness score" of named models (Claude vs GPT vs Llama):** built on numbers vendors won't confirm, stale every model release, and drifts toward disclosure/marketing — the same line we hold against the free-tier comparator and the CFE axis. See anti-questions.

### Data & storage
- 🔭 "Where should I put this 5TB bucket to minimize carbon + egress to my users?" — storage-placement counterpart to compute placement; ties into the egress tool.
- 🔭 "Does moving my data to the greener region (not just compute) pay off over 12 months?" — amortize a one-time migration-egress cost against ongoing carbon saving. Natural follow-on to `data_locality_egress_check`.

### Vendor / grid nuance
- 🔭 "Does this provider actually run this region on renewables, or is it just a clean grid?" — per-vendor CFE / renewable-matching data as a *real* axis (today we explicitly ignore RECs). Recorded earlier as "vendor-as-real-axis."
- 🔭 "What's the sub-regional / availability-zone carbon difference?" — finer grid-zone mapping than our country-level approximation.
- 🔭 "Include my CDN / edge locations in the carbon picture." — multi-location aggregate.

### Reporting / decision-capture (lower priority — drifts toward disclosure, which we said we're NOT)
- 🔭 "Give me a one-paragraph justification for choosing this region, for my PR description." — formats an existing recommendation as prose. Cheap, high-charm, no new data.
- 🔭 "What would I save (carbon + $) by making all these changes?" — aggregate across several recommendations.

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
