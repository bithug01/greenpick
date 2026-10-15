# GreenPick

A **design-time sustainability co-pilot** that runs as an MCP server inside your vibe-coding
environment (Cursor / Claude Code / Kiro). When you're deciding **where to deploy**, it gives a
greener region choice with an honest **carbon + cost + latency** tradeoff — in-editor, in seconds.

> **Status: working — 14 tools.** Live carbon for US (EIA-930) and EU (ENTSO-E), cross-cloud cost
> parity (Vantage-refreshed), per-axis R/Y/G ratings, carbon-aware scheduling + day-ahead forecast,
> GPU-training placement, right-sizing, serving-pattern and data-locality/residency checks — all
> shipped. Falls back to clearly-labelled mock data offline or without API keys.

![Same H100 training run, ~30× the carbon depending only on region (Stockholm vs Sydney)](docs/img/region-carbon-30x.svg)

*The same 40-GPU-hour training run emits ~0.7 kg CO₂ in Stockholm vs ~19 kg in Sydney — a ~30×
difference from region choice alone. GreenPick surfaces that (with the cost and latency tradeoff)
at the moment you choose.*

## Why this exists

The same web service emits very different CO₂ depending on **which region** it runs in, because
electricity grids differ in carbon intensity. Existing tools either rank regions in the abstract,
or measure carbon *after* you deploy. GreenPick does it **at the moment you choose**, and tells you
what the greener choice *costs you* in latency and dollars — so you can accept or reject it with
eyes open.

## What it is / is NOT

- **IS:** directional "greener choice" guidance for a developer picking a cloud region while
  building. Guidance, with tradeoffs stated.
- **IS NOT:** audited carbon accounting, ESG/Scope-2 reporting, or a real-time scheduler.
  GreenPick does **not** claim GHG-Protocol or ISO compliance — that's what the paid data vendors
  (Electricity Maps, WattTime) provide. GreenPick is for *decisions*, not *disclosures*.

## Scope

- Providers: **AWS, GCP, Azure** regions.
- Workloads: long-running **web/API services**, **GPU training** runs, and **deferrable jobs**
  (ETL / batch / backups) — placement and timing for each.
- Carbon = **grid carbon intensity by region** (directional, point-in-time; live US + EU), plus a
  **day-ahead forecast** (EU) for forward-looking scheduling.
- Cost = **compute + egress ballpark** (deterministic static table, apples-to-apples across
  clouds; never LLM-invented).
- Latency = **geographic estimate** to a stated user location.
- Efficiency levers: **greener instance family** (perf-per-watt), **right-sizing** (cost + carbon
  together), and a **carbon-metric scaffold** to track your app over time.
- Guardrails: **data-locality / egress** backfire checks and **cross-jurisdiction residency** flags.
- **Free data only.** No flow-traced consumption accounting; carbon forecast is relative, not absolute.

Roadmap: LLM-inference carbon, data-format/engine efficiency advice, sub-national grid zones,
CI/CD integration. See `docs/user-questions-backlog.md`.

## MCP tools

| Tool | What it does |
|------|--------------|
| `compare_regions_tri_axis` | Rank candidate regions by carbon with cost + latency tradeoffs; recommend a pick, each axis rated R/Y/G. Pass `regions` to rank only the ones you'd actually consider. |
| `greener_alternative_to` | "You picked X — the greenest region within +N ms latency is Y (−Z% carbon, Δcost)." The core nudge. |
| `estimate_workload_carbon` | Rough kgCO₂/month for a workload in a region (an *estimate*, not a measurement). |
| `region_carbon_now` | Current gCO₂/kWh for a region, with source + timestamp + freshness. |
| `cleanest_hours_to_run` | Carbon-aware scheduling: cleanest recent hours to time a deferrable job (ETL, backups, training), + % reduction. Pass `window_hours` for a job of known duration → cleanest contiguous window to start at. |
| `cleanest_time_of_day` | For a **recurring** job (nightly batch): the region's cleanest time of day, each hour-of-day averaged across the recent days. A daily pattern, not a 7-day weekly one. |
| `carbon_forecast` | Forward-looking: which **upcoming** hours will be cleanest, from the EU day-ahead wind+solar forecast (ENTSO-E). Relative ranking, not absolute gCO₂/kWh. US/uncovered zones degrade to the recent historical pattern. |
| `greener_instance_family` | Suggest a greener same-size family in the same region via perf-per-watt (newer generation / ARM Graviton-class does the same work on less energy). |
| `data_locality_egress_check` | Warn when running compute away from where your data lives backfires: directional egress $ + coarse transfer carbon, and whether a greener-region move is still a net win. |
| `serving_pattern_advice` | For a user-facing platform: serve from one region or several? Traffic-weighted latency + carbon, with the multi-region data-sync egress and cross-jurisdiction residency catches. |
| `carbon_metric_scaffold` | Emits paste-in instrumentation (Python) so your app reports its own **estimated** carbon over time — observable proxies × GreenPick's power model × live grid. Self-tracking, directional, self-labelled; not a runtime meter. |
| `rightsizing_check` | Right-sizing (the #1 FinOps win) with a carbon twin: if you're over-provisioned, a smaller size cuts **both** cost and carbon. Give provisioned size + observed utilisation → the right-sized target with monthly $ and kg CO₂ saving. |
| `estimate_training_carbon` | Carbon of a GPU training run (TDP-based energy × live grid), with greener **where** (region ranking) + **when** (cleanest hours) — the two levers that compound for portable, deferrable training. |
| `explain_methodology_and_limits` | The assumptions and what GreenPick explicitly does **not** claim. |

## Data sources (free; swappable behind one interface)

- **EIA-930** (US balancing authorities) and **ENTSO-E** (EU zones) — live grid carbon,
  auto-routed by region. Both also drive `cleanest_hours_to_run` from recent hourly history.
- **Mock** — deterministic, offline default; clearly labelled `quality: "mock"` so nothing is
  mistaken for a real reading. Used wherever a key is missing or a region isn't covered.
- Cost: a **dated static pricing table** (`data/pricing.json`), refreshed from live Vantage
  pricing via `scripts/refresh_pricing.py` using one matched method across all three clouds.
- Instance-family efficiency: directional perf-per-watt multipliers (`data/instance_families.json`).
- Latency: great-circle distance from region coordinates to the user's location.

Set `EIA_API_KEY` and `ENTSOE_TOKEN` in `.env` (both free) for live carbon; `GREENPICK_CARBON_SOURCE`
selects the source (`auto` routes US→EIA, EU→ENTSO-E, else mock).

The data layer is a swappable repository (`MOCK` by default, works offline). Nothing here invents
numbers: the LLM writes the *rationale*, the code supplies the *figures*.

## Honest limitations (shipped in the tool itself)

Directional, not audited. Region→grid-zone mapping is approximate. Carbon is point-in-time, not
flow-traced consumption. Cost is a ballpark, not a quote. Latency is a geographic estimate.
"Greener" assumes grid intensity dominates and ignores embodied/hardware carbon and provider RECs.

## Quick start

```bash
# Python 3.11+
pip install -e ".[dev]"
cp .env.example .env            # defaults to mock data — works offline
python -m greenpick             # run the MCP server (stdio)
pytest                          # run tests
```

Connect it to an MCP client (e.g. Kiro / Claude Code / Cursor) by pointing the client at
`python -m greenpick` in this directory. See `.env.example` for switching the data source.

## License

MIT — see [LICENSE](LICENSE). © 2026 Perry Beaumont.
