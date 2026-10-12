# GreenPick — user-questions backlog

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

_As of 2026-10-12. 8 tools: compare_regions_tri_axis, greener_alternative_to, estimate_workload_carbon,
region_carbon_now, cleanest_hours_to_run, greener_instance_family, data_locality_egress_check,
explain_methodology_and_limits._

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
- 🔭 "What's the carbon forecast for us-west-2 over the next 24h?" — forecasting source (EIA has day-ahead; Electricity Maps paid has forecast). Turns scheduling from *reactive* to *planned*.
- 🔭 "I have a flexible weekly job — what's the single best hour of the week to run it?" — multi-day history + day-of-week pattern.
- 🔭 "Batch this across the cleanest hours until it's done" — a *plan* (list of hour-slots summing to N compute-hours), not just the single cleanest hour.

### Workload shape (beyond the one always-on web service)
- ✅ "I'm training a model for ~40 GPU-hours — where and when is that greenest?" — SHIPPED as `estimate_training_carbon` (GPU power table + region ranking + cleanest-hours timing). Verified: 1×H100×40h = 33 kWh, 96% region swing + further ~57% timing.
- 🔭 "This is a spiky, mostly-idle service — does serverless change the carbon math?" — utilization-aware estimate (idle vs active watts), not flat always-on.
- 🔭 "Compare container vs VM vs serverless for the same workload's carbon." — needs a per-platform overhead model.

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

---

## How to use this doc

When a new question comes up (yours or a user's), add it to the right section. If a question keeps
recurring and sits in 🟡 or 🔭, that's the signal to build. Prefer questions that (a) have a real
carbon mechanism, (b) use data we can get for free, and (c) fit the "decision, not disclosure" line.
