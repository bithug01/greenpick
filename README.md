# GreenPick

A **design-time sustainability co-pilot** that runs as an MCP server inside your vibe-coding
environment (Cursor / Claude Code / Kiro). When you're deciding **where to deploy**, it gives a
greener region choice with an honest **carbon + cost + latency** tradeoff — in-editor, in seconds.

> **Status: working.** Live carbon for US (EIA-930) and EU (ENTSO-E), cross-cloud cost parity
> (Vantage-refreshed), per-axis R/Y/G ratings, and carbon-aware scheduling — all shipped. Falls
> back to clearly-labelled mock data offline or without API keys.

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

- One workload shape: a **long-running web/API service** deployed to a cloud region.
- Providers: **AWS, GCP, Azure** regions.
- Carbon = **grid carbon intensity by region** (directional, point-in-time; live US + EU).
- Cost = **compute + egress ballpark** (deterministic static table, apples-to-apples across
  clouds; never LLM-invented).
- Latency = **geographic estimate** to a stated user location.
- **Carbon-aware scheduling** = cleanest recent hours to run a deferrable job.
- **Greener instance family** = same-size, same-region family that does the work on less energy.
- **Data-locality / egress check** = warns when moving compute away from your data backfires.
- **GPU training carbon** = energy + CO₂ of a training run, with greener region + cleanest-hours timing.
- **Free data only.** No forecasting, no flow-traced consumption accounting.

Roadmap: forecasting (reactive → planned scheduling), sub-national grid zones, CI/CD integration.

## MCP tools

| Tool | What it does |
|------|--------------|
| `compare_regions_tri_axis` | Rank candidate regions by carbon with cost + latency tradeoffs; recommend a pick, each axis rated R/Y/G. Pass `regions` to rank only the ones you'd actually consider. |
| `greener_alternative_to` | "You picked X — the greenest region within +N ms latency is Y (−Z% carbon, Δcost)." The core nudge. |
| `estimate_workload_carbon` | Rough kgCO₂/month for a workload in a region (an *estimate*, not a measurement). |
| `region_carbon_now` | Current gCO₂/kWh for a region, with source + timestamp + freshness. |
| `cleanest_hours_to_run` | Carbon-aware scheduling: cleanest recent hours to time a deferrable job (ETL, backups, training), + % reduction. Pass `window_hours` for a job of known duration → cleanest contiguous window to start at. |
| `greener_instance_family` | Suggest a greener same-size family in the same region via perf-per-watt (newer generation / ARM Graviton-class does the same work on less energy). |
| `data_locality_egress_check` | Warn when running compute away from where your data lives backfires: directional egress $ + coarse transfer carbon, and whether a greener-region move is still a net win. |
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

TBD (intended open-source).
