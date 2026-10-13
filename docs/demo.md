# GreenPick — 5-minute demo

A guided walkthrough of what GreenPick does, in the order that best shows the value. Every number
below is **real output from the live tools** (captured 2026-10-12, live EIA + ENTSO-E carbon) — not
mocked, not invented. Run the same calls yourself and you'll get current data.

**The one-line pitch:** the same workload emits very different CO₂ depending on *where* and *when*
you run it. GreenPick surfaces the greener choice — with the cost and latency tradeoff attached — at
the moment you decide, inside your editor. Fast, directional guidance built for the decision.

> **Setup:** GreenPick runs as an MCP server (`python -m greenpick`). Point your MCP client at it,
> set `EIA_API_KEY` + `ENTSOE_TOKEN` in `.env` (both free) for live carbon, and
> `GREENPICK_CARBON_SOURCE=auto`. Without keys it runs on clearly-labelled mock data.

---

## Scenario 1 — "Where should I run this training job?" (lead with this)

**This is the strongest demo.** Training is portable, deferrable, and energy-hungry, so the carbon
difference is large enough to actually change a decision.

**Ask:** *"I'm about to train a model — roughly 40 GPU-hours on an H100. Where's the greenest place
to run it?"*

**Tool call:** `estimate_training_carbon(gpu="h100", gpu_count=1, gpu_hours=40)`

**Real output:**

```
This run is ~33 kWh (1× H100, 40 GPU-hours).

Region ranked greenest-first (live grid carbon):
  aws/eu-north-1      (Stockholm)   20 g/kWh   live   0.66 kg CO₂   [green]
  azure/swedencentral (Sweden)      20 g/kWh   live   0.66 kg CO₂   [green]
  aws/eu-west-1       (Ireland)     79 g/kWh   live   2.62 kg CO₂   [yellow]
  gcp/europe-north1   (Finland)     79 g/kWh   live   2.63 kg CO₂   [red]

Greenest: aws/eu-north-1 at ~0.7 kg CO₂ — ~97% less than the dirtiest
option (aws/ap-southeast-2, ~19.4 kg).
```

**Why this matters:** the *same* 40-GPU-hour run is **~0.7 kg CO₂ in Stockholm vs ~19 kg in Sydney —
a ~30× difference from region choice alone.** On a small always-on web service that gap is grams; on
a real training run it's kilograms you can actually move. This is the decision GreenPick exists for.

> Note the honesty: Sweden's grid is so clean *and* flat that GreenPick tells you timing won't help
> much there — "the region choice is the lever." It doesn't manufacture a benefit that isn't there.
>
> And it doesn't let you take the win blindly: the recommendation itself reminds you that if your
> training data lives elsewhere, shipping it to Stockholm can incur egress that erases the saving —
> which is exactly Scenario 2.

---

## Scenario 2 — "...but my data is in Virginia." (the catch nobody surfaces)

The greener region is often far from where your data lives. Every byte crossing that boundary is
billed egress and burns extra transfer energy — which can **undo the whole green move.**

**Ask:** *"If I move that compute to Sweden but my 3 TB/month of training data stays in us-east-1,
is it still worth it?"*

**Tool call:** `data_locality_egress_check(compute_provider="aws", compute_region="eu-north-1",
data_provider="aws", data_region="us-east-1", monthly_cross_boundary_gb=3000,
carbon_saving_kg_co2_from_move=2.0)`

**Real output:**

```
Locality: cross-region, same cloud   Severity: HIGH
Egress cost:   ~$270 / month
Transfer carbon: ~33.6 kg CO₂ / month

VERDICT — Backfires on carbon: the move saves ~2.0 kg CO₂/mo but the extra
transfer adds ~33.6 kg — net ~31.6 kg WORSE. Keep compute near the data,
or move the data too.
```

**Why this matters:** a naive "greener region!" recommendation would have made this **worse** — 16×
worse on carbon, plus $270/month you weren't expecting. GreenPick is the only step that catches the
backfire. It leads with the concrete number (egress $) and treats transfer carbon as the directional
tiebreaker.

---

## Scenario 3 — "When, in the next 24h, should I run it?" (plan, don't guess)

For a deferrable job, *when* you start also matters. GreenPick uses the EU day-ahead wind+solar
forecast to rank the cleanest **upcoming** hours — forward-looking, not just recent history.

**Ask:** *"My job is flexible — when in the next 24h is the Stockholm grid forecast cleanest?"*

**Tool call:** `carbon_forecast(provider="aws", region="eu-north-1", hours_ahead=24)`

**Real output:**

```
Source: ENTSO-E day-ahead forecast   Quality: forecast
Forecast cleanest upcoming hours (by renewable share):
  2026-10-13T20   10,248 MW renewables   share 0.69
  2026-10-13T21    9,698 MW renewables   share 0.69
  2026-10-13T19   10,575 MW renewables   share 0.67

Cleanest ~20:00, dirtiest ~11:00. Shift deferrable work toward the
cleanest upcoming hours.
```

**Why this matters:** this turns scheduling from *reactive* ("when has it been clean lately?") to
*planned* ("start it at 20:00 tomorrow"). It's a **relative** signal — more forecast renewables =
cleaner — not an absolute gCO₂/kWh forecast, because the free data honestly can't support that. US
regions, which have no free generation forecast, degrade to the recent historical pattern (labelled
`historical`, never faked as a forecast).

---

## The three in one sentence

*Run your training in Stockholm not Sydney (~30× cleaner), **unless** your data egress would backfire
the move (GreenPick checks), and start it when the grid is forecast cleanest (~20:00 tomorrow).*

That's a complete, carbon-aware deployment decision — made at design time, with the tradeoffs stated,
inside the editor.

---

## Right-sized by design (the discipline)

GreenPick is **directional by choice** — and for a design-time decision, that's the right tool:
fast, free, and in-context, so you can make the call in seconds without leaving the editor. The
precision matches the moment.

- **Built for the choice, not the disclosure.** A region decision needs "Stockholm is ~30× cleaner
  than Sydney" — not a certified number. When you later need audited Scope-2 / GHG-Protocol figures
  for a *report*, that's a different job and a different tool (Electricity Maps, WattTime). GreenPick
  gets you to the right decision; those certify it after the fact.
- **An honest estimate, grounded in real data.** Carbon = a documented power model × *live* grid
  intensity. Cost is a dated cross-cloud ballpark; latency is a geographic estimate. Every figure is
  directional and labelled as such — no false precision.
- **Candid about its own limits.** It tells you when timing *won't* help, when a region filter matched
  nothing, and when it's on mock or historical data instead of live. You always know what you're
  looking at.

Every tool ships an `explain_methodology_and_limits` call that spells this out — the transparency is
part of the product, not a footnote.

---

## The full toolset (11 tools)

| Tool | One-liner |
|------|-----------|
| `compare_regions_tri_axis` | Rank regions by carbon with cost + latency tradeoffs (filterable). |
| `greener_alternative_to` | "You picked X — greenest region within +N ms is Y." |
| `estimate_workload_carbon` | kg CO₂/month for a workload in a region. |
| `region_carbon_now` | Current grid carbon for a region, with source + freshness. |
| `cleanest_hours_to_run` | Cleanest recent hours (+ cleanest contiguous window for a job duration). |
| `cleanest_time_of_day` | Recurring-job daily pattern — the consistently-cleanest time of day. |
| `carbon_forecast` | Forward-looking: cleanest *upcoming* hours (EU forecast; US → historical). |
| `greener_instance_family` | Greener same-size family (perf-per-watt; ARM/Graviton wins). |
| `data_locality_egress_check` | Does moving compute away from data backfire via egress? |
| `estimate_training_carbon` | GPU training carbon + greener where & when (Scenario 1). |
| `explain_methodology_and_limits` | The assumptions and what GreenPick won't claim. |
