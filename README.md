# GreenPick

A **design-time sustainability co-pilot** that runs as an MCP server inside your vibe-coding
environment (Cursor / Claude Code / Kiro). When you're deciding **where to deploy**, it gives a
greener region choice with an honest **carbon + cost + latency** tradeoff — in-editor, in seconds.

> **Status: scaffold / work-in-progress.** Tool and data interfaces are wired; the live data
> source and real math are stubbed (clearly marked `TODO`). It runs on **mock data** today.

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

## v1 scope (ruthlessly small, so it ships)

- One workload shape: a **long-running web/API service** deployed to a cloud region.
- Providers: **AWS, GCP, Azure** regions.
- Carbon = **grid carbon intensity by region** (directional, point-in-time).
- Cost = **compute + egress ballpark** (deterministic static table; never LLM-invented).
- Latency = **geographic estimate** to a stated user location.
- **Free data only.** No forecasting, no flow-traced consumption accounting in v1.

Out of v1 (roadmap): batch/GPU/training workloads, time-shifting ("run the nightly job when the
grid's clean"), forecasting, sub-national grid zones, CI/CD integration.

## MCP tools

| Tool | What it does |
|------|--------------|
| `compare_regions_tri_axis` | Rank candidate regions by carbon with cost + latency tradeoffs; recommend a pick. |
| `greener_alternative_to` | "You picked X — the greenest region within +N ms latency is Y (−Z% carbon, Δcost)." The core nudge. |
| `estimate_workload_carbon` | Rough kgCO₂/month for a workload in a region (an *estimate*, not a measurement). |
| `region_carbon_now` | Current gCO₂/kWh for a region, with source + timestamp + freshness. |
| `explain_methodology_and_limits` | The assumptions and what GreenPick explicitly does **not** claim. |

## Data sources (free; swappable behind one interface)

- **Electricity Maps free tier** — live carbon intensity, 200+ regions (primary).
- **ENTSO-E** (EU), **EIA-930** (US), **NESO** (UK) — free official fallbacks.
- **Open Grid Emissions** / eGRID annual averages — offline degradation path.
- Cost: a **static, dated pricing table** (`data/pricing.json`), deterministic.
- Latency: great-circle distance from region coordinates to the user's location.

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
