# Contributing to GreenPick

Thanks for your interest — contributions of any kind are welcome: bug reports, data-source
corrections, clearer caveats, docs, or code.

## The one principle that matters here

GreenPick's value is that it's **honest and directional**. Please keep contributions in that spirit:

- **No invented numbers.** Figures come from cited data (grid APIs, published coefficients) or a
  documented model — never guessed. Every data file carries a `_source` / `_comment`.
- **No precision the data can't back.** Prefer ranges and "directional" labels over false certainty.
- **Flag, don't rule.** GreenPick surfaces considerations (egress, residency) and points to the
  authority; it doesn't issue verdicts it isn't qualified to make (e.g. legal compliance).
- **Say when it's mock/estimated.** Never present a fallback or an estimate as a live measurement.

If a change would make GreenPick claim more than it can honestly support, it's probably not the right
change — even if it's technically impressive.

## How to propose a change

1. **Open an issue first** for anything non-trivial — describe the problem or idea so we can agree on
   the approach before you write code. (Ideas and bug reports are valuable on their own.)
2. Fork the repo and create a branch: `git checkout -b fix/short-description`.
3. Make the change. If it touches behavior, **add or update a test** in `tests/`.
4. Run the suite and make sure it's green:
   ```bash
   pip install -e ".[dev]"
   pytest
   ```
5. Open a pull request describing *what* changed and *why*. Link the issue.

## Project shape (so you know where things go)

- `src/greenpick/server.py` — the MCP tools (thin wrappers; they call services).
- `src/greenpick/services/` — the logic (pure, testable; the math lives here).
- `src/greenpick/data/` — static data files (pricing, emission factors, power models) with sources.
- `tests/` — pytest; `python -m pytest -q`.
- `docs/` — the demo, the design/decision history, and the roadmap/backlog.

## Reporting a bug

Open an issue with: what you did, what you expected, what happened, and (if relevant) the region /
tool / inputs involved. A failing example is worth a thousand words.

## License

By contributing, you agree your contributions are licensed under the project's [MIT License](LICENSE).
