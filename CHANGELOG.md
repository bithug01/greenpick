# Changelog

All notable changes to GreenPick. Dates are the release commit's date. Versions are published on
[PyPI](https://pypi.org/project/greenpick/) and the
[MCP Registry](https://registry.modelcontextprotocol.io/); each has a matching git tag.

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
