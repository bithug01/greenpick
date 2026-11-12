# Changelog

All notable changes to GreenPick. Dates are the release commit's date. Versions are published on
[PyPI](https://pypi.org/project/greenpick/) and the
[MCP Registry](https://registry.modelcontextprotocol.io/); each has a matching git tag.

## 0.8.0 - 2026-11-11
- Live carbon for the three Tokyo regions from the Tokyo area's half-hourly generation by source, about an
  hour behind, no key needed. Source: Tokyo Electric Power Company Holdings, Inc., used with permission.
  GreenPick shows only the carbon intensity it calculates from the mix, fetches at most once every 30
  minutes, and adds a `data_attribution` credit to every result built on Tokyo data, with `verify_at`
  linking to TEPCO's source page.
- Tokyo now has a typical monthly profile, so timing advice works there; it was a yearly average before.

## 0.7.0 - 2026-11-10
- New `serverless_check`: an always-on server vs. paying per request (AWS Lambda, Google Cloud Run) for
  a mostly idle or spiky service. Monthly cost of each, the break-even request count, whether the traffic
  fits the free tier, and estimated carbon (serverless as a lower bound). Azure is carbon only.
- `estimate_workload_carbon` takes an optional `avg_cpu_utilization`. CPU power then follows load (Cloud
  Carbon Footprint min/max watts per vCPU) instead of assuming full load. Without it, results are unchanged.
- 20 tools.

## 0.6.3 - 2026-11-07
- New `verify_at` field on every result with carbon or cost figures: which kind of figure, what it is
  based on, and the public page to check it against (grid operators, Ember via Our World in Data, the
  cloud providers' pricing pages). Additive: no existing field changed.
- `region_move_justification`: when a move already raises carbon, the text no longer adds a second
  "backfires" sentence about data transfer.
- README: notebook starter prompt link and the mcprush listing card now appear on PyPI.

## 0.6.2 - 2026-11-03
- Utilisation inputs (`rightsizing_check`, `estimate_training_carbon`) must be fractions between 0
  and 1. A percentage such as 15 now returns an error suggesting 0.15, instead of being read as 1,500%.

## 0.6.1 - 2026-11-03
- `migration_payoff` now says when its dollar range crosses zero (a small net loss is possible even
  when carbon improves), and that it judges the data move only, not where compute should run.
- The descriptions of `compare_regions_tri_axis` and `greener_alternative_to` point to
  `region_move_justification` for pull-request text.
- Negative dollar amounts read as `-$4`.

## 0.6.0 - 2026-11-03
- New `migration_payoff`: does moving the data to the compute's region pay back? Payback in months,
  one-off vs monthly egress and transfer carbon, and the net over a horizon (default 12 months).
- New `region_move_justification`: a short paste-ready paragraph for a pull request or decision
  record, with each carbon figure's quality label. Says so when a move is not an improvement.
- 19 tools.

## 0.5.2 - 2026-11-02
- `data_locality_egress_check` returns a one-line `summary` as its first field.

## 0.5.1 - 2026-11-02
- `data_locality_egress_check` states plainly when no net verdict was computed (a carbon saving was
  not supplied), and adds a `verdict_status` field.

## 0.5.0 - 2026-11-02
- New `offhours_check`: the monthly dollars and carbon saved by switching a non-prod environment off
  outside the hours it is needed.
- New `greenest_regions_on_average`: ranks regions by typical monthly (or whole-year) grid carbon.
  Offline, no keys.
- 17 tools.

## 0.4.2 - 2026-10-27
- Every tool declares all four MCP annotation hints; every tool is tested by name.
- Requires `mcp>=1.7,<2`.

## 0.4.1 - 2026-10-26
- Sydney uses a sourced yearly national figure (labelled `annual_average`). No region relies on a
  placeholder value.

## 0.4.0 - 2026-10-26
- Asia: Singapore, Tokyo and Mumbai/Pune regions on sourced yearly figures (labelled
  `annual_average`; no hourly profile).

## 0.3.0 - 2026-10-26
- Canada: live Québec (Hydro-Québec) and Ontario (IESO) carbon, no key needed.

## 0.2.1 - 2026-10-26
- Live readings say whether now is cleaner or dirtier than usual for that hour this month.

## 0.2.0 - 2026-10-26
- Real "typical" data (this calendar month's average, from 12 months of hourly grid data) is the
  default and the fallback when live data is unavailable.

## 0.1.8 - 2026-10-25
- Results that are not live include a `live_data_hint` saying why and how to turn live data on.

## 0.1.7 - 2026-10-25
- Saving percentages are labelled as cost or carbon. Scheduling advice gives a start time of day.

## 0.1.6 - 2026-10-24
- README notebook usage that gets live data. The server sends instructions to MCP clients.

## 0.1.5 - 2026-10-23
- API keys are kept out of logs. Slow upstream calls are bounded.

## 0.1.4 - 2026-10-23
- Right-sizing recommends standard, buyable instance sizes.
- Removed a region that did not exist. Training results report `wall_clock_hours`.

## 0.1.3 - 2026-10-23
- README data-sources wording on PyPI.

## 0.1.2 - 2026-10-23
- Accurate data-sources text and a "Turn on live data" README section.

## 0.1.1 - 2026-10-22
- Absolute image URLs so the README renders on PyPI.

## 0.1.0 - 2026-10-22
- First public release: region, scheduling, training, inference, right-sizing, egress and serving
  tools (15), with live US (EIA) and EU (ENTSO-E) carbon.
