# GreenPick — blog ideas

Seeds for posts, captured from working-session discussion. Each is a thesis + the honest nuance that
makes it worth reading (not a cheerleading piece). The through-line for all of them: GreenPick's
credibility comes from admitting where the easy story breaks.

---

## 1. "Sustainability is good business — but only half of it is" (the OpEx alignment post)

**Thesis:** For cloud infrastructure, doing the right thing for sustainability often *is* the
cost-cutting move — but the alignment is not uniform, and pretending it is gets you burned.

**The honest frame — two halves:**
- **Efficiency / waste (strong alignment):** right-sizing, killing idle/zombie resources, greener
  (perf-per-watt) instance families, scheduling deferrable work off-peak. Here "greener" and
  "cheaper" are *the same action* — less energy per unit of work = lower bill AND lower carbon. No
  tradeoff, no appeal to values needed.
- **Location / sourcing (alignment breaks):** the cleanest region is often not the cheapest or
  lowest-latency. Moving compute to a clean-but-distant region can *raise* OpEx via egress and add
  latency. Greener and cheaper diverge.

**The payoff / hook:** You can sell efficiency to a cost-conscious engineer who doesn't care about
carbon at all — "lower your cloud bill, sustainably" — and the carbon is a free side effect. But a
tool (or consultant) that claims green is *always* cheaper will recommend the clean-distant region
and blow up your egress bill. The trustworthy move is showing *when the alignment breaks*.

**GreenPick angle:** this is literally why GreenPick shows carbon, cost, and latency as THREE
separate axes instead of one blended "good" score — and why it ships an egress-backfire check. The
divergence cases are where trust is won.

**Macro caveat worth including:** at the whole-business level, "sustainability = profit" is partly
true, partly comforting oversimplification (offsets, premium renewable sourcing, resilience spend are
real net costs absorbed for non-financial reasons). Cloud infra sits in a favourable corner because
so much of it is efficiency — which is what makes the infra thesis unusually defensible vs, say,
selling offsets.

---

## 2. "What a carbon tool should steal from FinOps — and what it must not" (the borrowing post)

**Thesis:** The cloud cost-optimization (FinOps) world has a mature playbook. A carbon tool should
borrow its *efficiency* patterns freely and ignore its *financial-engineering* ones entirely — and
the dividing line is exactly the carbon signal.

**Borrow (efficiency = cost and carbon are one lever):** right-sizing (the #1 finding, pure
dual-benefit), turning off non-prod/idle, scale-to-zero, storage tiering, and FinOps's reporting
idioms ("est. monthly savings", "pays back in N months", "waste as % of spend").

**Don't borrow (no carbon signal and/or needs the bill):** commitment discounts (reserved/savings
plans — same energy, cheaper contract, zero carbon difference), spot/preemptible (carbon-neutral,
runtime concern), and anything needing billing-account access (anomaly detection, cost allocation) —
that's what the FinOps platforms already are; competing there means leaving the design-time lane.

**The insight to land:** FinOps splits into *efficiency* (do less work) and *financial engineering*
(pay less for the same work). Only the first has a carbon twin. That single distinction tells you
precisely which ideas port to sustainability and which are mirages.

---

## 3. "Directional, not audited: why an honest estimate beats a precise lie" (the discipline post)

**Thesis:** For a *design-time decision*, a fast directional estimate is the right tool — and
chasing audited precision would make the tool worse, not better.

**The argument:** a region decision needs "Stockholm is ~30× cleaner than Sydney," made in seconds in
the editor — not a certified number that takes a vendor integration and an audit. Audited accounting
(Scope-2 / GHG-Protocol) is a *different job* for a *different user* (ESG/compliance), served by
different (paid) tools. Conflating the two produces something slow for the builder and untrustworthy
for the auditor.

**The through-line:** GreenPick repeatedly *refused* the precise-sounding-but-dishonest version —
no free-tier leaderboard, no per-vendor CFE axis, no named-model LLM greenness grade, no "is this
GDPR-compliant?" verdict. Each refusal is the same principle: don't claim a precision or an authority
you don't have. The post is really about *restraint as a feature.*

---

## 4. "The egress trap: how 'go greener' can quietly cost you money and carbon" (the counterintuitive post)

**Thesis:** The most natural sustainability move in cloud — "run it in the clean region" — can
backfire on *both* axes if your data stays where it is.

**The mechanics (teachable):** egress isn't one price; it's a tier ladder — free in-region, ~cheap
cross-region-same-cloud, expensive cross-cloud/internet. Move compute to a clean region while the
data stays put, and every byte it reads crosses a billed boundary, burning transfer energy too. A
naive green move can be net *worse* on carbon and surprise you on cost.

**The number:** same 3 TB/month is ~$30–60 across regions in one cloud, but ~$255–360 across clouds —
and a greener-region move that saves 2 kg CO₂ can add 33 kg of transfer carbon. Knowing *which tier*
you're in is the whole game.

**GreenPick angle:** the data-locality / egress check exists precisely to catch this before you
commit — surface the concern, price the right tier, flag the backfire.

---

## 5. "Where + when + check: anatomy of one carbon-aware deployment decision" (the product-shape post)

**Thesis:** A good carbon decision isn't "pick the green region" — it's a short chain: greener region
→ does it backfire (egress/residency)? → time it to the clean hours. Each step can undo the last.

**Why it's interesting:** it shows sustainability as *engineering judgment with tradeoffs*, not a
badge. The three steps map to three honest tools, and the composition is the point — the whole is a
real decision, made at design time, in the editor. (Pairs well with the decision-flow graphic.)

---

## 6. "I tested my tool on AI assistants, and they made things up" (the agent-honesty post)

**Thesis:** An MCP tool isn't only used by people. An AI assistant reads it, picks a tool, fills in the
inputs and summarises the result, and it fails in ways a human user doesn't. The fixes belong in the
tool's design, not only in the prompt.

**What actually happened in testing (Colab, Nov 2026):** an assistant skipped the pull-request tool
and wrote its own promotional paragraph; invented inputs (data sizes, regions) without saying so;
passed "15% CPU" as 15, which the tool read as 1,500% and reported "already sized right"; reported a
"net saving" the tool had explicitly not computed; and quoted only the best end of a dollar range
that crossed zero.

**The fixes, each a design choice:** a one-line `summary` as the first field (partial printouts still
show it); "NO NET VERDICT" when an input is missing, instead of silence; an error that says "did you
mean 0.15?" instead of a silent wrong answer; tool descriptions that name the right tool for the job;
and a starter prompt that makes the assistant read each tool's real parameters before calling it.

**The insight to land:** if an assistant can misread your output, it will. Design results so the
honest reading is the easiest one.

---

## 7. "Every number should say what kind of number it is" (the labelling post)

**Thesis:** A confident-looking figure with no provenance is worse than a labelled estimate, because
it looks the same as a real reading.

**The mechanics:** every GreenPick carbon figure carries a `quality` label: `live` (a current grid
reading), `typical` (this month's normal, from a year of real hourly data), `annual_average` (a sourced
yearly national figure, for grids with no free hourly data). Results also carry `verify_at`, the public
page behind each figure (grid operators, Ember via Our World in Data, the cloud providers' price pages),
and a `live_data_hint` saying why a result isn't live and how to make it so.

**The honest nuance:** labels only work if they're read. That links to post 6: assistants dropped
them, which is why the starter prompt now insists on them.

---

## 8. "Free data isn't always free to use" (the licensing post)

**Thesis:** For live grid data, licensing decides coverage more than engineering does.

**The cases:**
- **Sydney:** OpenElectricity's data is licensed CC BY-NC (non-commercial), which rules it out for an
  MIT tool owned by a company. The clean alternative, AEMO's raw files, is a much bigger build.
- **Tokyo:** TEPCO publishes excellent data (half-hourly, split by fuel, under an hour behind, no key),
  but its terms require written permission for anything beyond personal use.
- **OCCTO** (Japan's national grid coordinator) allows free reuse with attribution, but for Tokyo it
  only links back to TEPCO's files.
- **What works:** EIA (US), ENTSO-E (EU), Hydro-Québec and IESO (Canada), and Ember's CC BY yearly
  figures as a labelled fallback everywhere else.

**The insight to land:** "it's on a public website" and "I may build on it" are different questions.
Check the terms before writing the parser.

---

## 9. "When does serverless actually save money and carbon?" (the break-even post)

**Thesis:** Serverless is cheaper and cleaner for quiet or spiky services, and more expensive for busy
ones. The useful answer is the break-even point, not a slogan.

**The numbers (GreenPick 0.7.0, AWS us-east-1, list prices):** a small API on a 2 vCPU / 4 GB server at
5% CPU costs about $80 a month always on. The same 1 million requests a month at 100 ms on Lambda with
0.5 GB is about $1, and fits inside the free tier. Break-even is about 77 million requests a month at
that duration and memory.

**The honest nuance:** serverless bills time spent waiting on a database, which favours a server for
I/O-heavy services; cold starts and time limits can rule it out regardless of price; and serverless
carbon can only be a lower bound, because platform overhead isn't published. An idle server still draws
power: about a fifth of its full-load CPU power at 0% load, on Cloud Carbon Footprint's figures.

---

## 10. "The cheapest hour is the one you don't run" (the off-hours post)

**Thesis:** Switching non-production environments off outside working hours is the simplest FinOps win
there is, and its carbon saving matches its cost saving exactly.

**The number:** a 4 vCPU / 16 GB staging server in us-east-1 used 50 hours a week saves about $128 a
month, about 70% of its compute cost, with the same ~70% off carbon. Both scale with running hours.

**The honest nuance:** disks, IP addresses and snapshots still cost money while stopped; reserved
capacity and savings plans are paid regardless, so the dollar saving can vanish (the carbon saving
doesn't); and the saving only exists if something actually turns the environment off and on.

---

## 11. "Teaching cloud carbon to people who've never heard of MCP" (the teaching post)

**Thesis:** You can teach a mixed audience to use an AI assistant with a tool server, and to check its
work, without first teaching them how MCP works.

**The approach:** one analogy (the assistant is a waiter, the tool server is the kitchen, the tools are
the menu) and three checks for every answer: did it use a tool, is every number labelled, did it invent
anything. Beginners can apply the checks; experts dig into the output behind them. Scenarios move from
plain business questions (a mostly idle server costs money for nothing) to the trickier ones (the egress
trap, a dollar range that crosses zero, a move the tool says not to make).

**Best written after running a session,** with what attendees actually got stuck on.

---

## Refresh notes (checked 2026-11-10 against GreenPick 0.7.0)

Ideas 1 to 5 were written in mid-October 2026, before most of the current tools existed.

- **Idea 1:** still current. Strengthen the efficiency half with off-hours scheduling (idea 10) and
  serverless (idea 9).
- **Idea 2:** "turning off non-prod" and "scale-to-zero" are now built (`offhours_check`,
  `serverless_check`), so the post can show them rather than propose them. "Pays back in N months" now
  exists as `migration_payoff`.
- **Idea 3:** add the later refusals: Tokyo stays on a yearly figure until the data licence allows live
  use, and Azure serverless cost is left unpriced rather than guessed.
- **Idea 4:** the egress figures still hold: 3 TB a month is about $30-60 across regions in one cloud
  and $255-360 across clouds. Recheck the "saves 2 kg, adds 33 kg" example before quoting it: 3 TB now
  adds about 31 kg of transfer carbon. Natural sequel: "should the data move too?" (`migration_payoff`).
- **Idea 5:** the chain now has a fourth step, writing it up (`region_move_justification`), and a check
  on the third (`verify_at` for every number).
- **Stockholm vs Sydney:** about 27x on whole-year grid averages (19.7 vs 525 gCO2/kWh). The older
  "30x" came from Sydney's hand-set placeholder, replaced by a sourced figure in 0.4.1.
- **All numbers:** rerun them on the current version before publishing; typical values follow the
  calendar month, and live data changes by the hour.

---

## Notes on tone (for whoever writes these)
- Lead with the counterintuitive or the honest-tradeoff, not the feel-good.
- Every post should name where the easy story breaks — that's the credibility.
- Numbers are real/directional; label them as such. Never imply audited precision.
- These are think-pieces that happen to feature GreenPick, not product brochures.
