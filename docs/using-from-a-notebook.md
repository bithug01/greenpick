# Using GreenPick from a notebook assistant

AI assistants inside notebooks (Colab, Jupyter, and similar) usually call a tool server through a
plain Python helper and do not receive the server's built-in guidance the way editors such as Kiro,
Claude Code or Cursor do. A short starter prompt gets them to connect cleanly, pick the right tool
and report the numbers faithfully.

Paste this as your first message in a fresh notebook session. If you are using GreenPick from an
editor, you do not need it.

````text
Use the GreenPick MCP server for every cloud carbon, cost, region or data-transfer question in
this notebook. Follow these rules exactly.

SETUP (one cell, run once)
- Install from PyPI: %pip install -q -U greenpick
- Do NOT clone the GitHub repo. Do NOT import greenpick modules or its server object. Do NOT use
  asyncio.run (the notebook already has a running event loop; use top-level await).
- Connect through the mcp package with exactly this helper:

import sys, json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

params = StdioServerParameters(command=sys.executable, args=["-m", "greenpick"],
                               env={"GREENPICK_CARBON_SOURCE": "auto"})

async def gp(tool, **args):
    with open("greenpick-server.log", "w") as errlog:
        async with stdio_client(params, errlog=errlog) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = await s.call_tool(tool, args)
                return json.loads(res.content[0].text)

async def info():
    with open("greenpick-server.log", "w") as errlog:
        async with stdio_client(params, errlog=errlog) as (r, w):
            async with ClientSession(r, w) as s:
                init = await s.initialize()
                return init.instructions, [t.name for t in (await s.list_tools()).tools]

async def schema(tool):
    with open("greenpick-server.log", "w") as errlog:
        async with stdio_client(params, errlog=errlog) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                t = next(t for t in (await s.list_tools()).tools if t.name == tool)
                props = t.inputSchema.get("properties", {})
                req = t.inputSchema.get("required", [])
                return {"required": req, "optional": [p for p in props if p not in req]}

- Then call info(), print the server instructions and ALL tool names (do not truncate), and follow
  those instructions for the rest of the session.
- Before you call a tool for the first time, or show me an example call, run schema("<tool>") and use
  ONLY the parameter names it returns. Never guess parameter names.

PICK THE RIGHT TOOL (do not answer from memory, and do not substitute a different tool)
- Switch off dev/test/staging outside working hours -> offhours_check
- Mostly idle or spiky service: always-on server or serverless? -> serverless_check
- Is this server oversized? -> rightsizing_check
- A greener instance family in the same region -> greener_instance_family
- Cleanest regions in a month or year -> greenest_regions_on_average
- Current carbon of one region -> region_carbon_now
- Choose between regions -> compare_regions_tri_axis or greener_alternative_to
- One region or several for users in many places -> serving_pattern_advice
- Will moving compute away from its data backfire? -> data_locality_egress_check
- Should the data move too? -> migration_payoff
- Paragraph for a pull request or decision record -> region_move_justification
  (never write PR text yourself from another tool's output)
- Rough carbon of a workload -> estimate_workload_carbon
- Best time to run a job -> cleanest_hours_to_run, cleanest_time_of_day, carbon_forecast
- GPU training or LLM serving -> estimate_training_carbon, estimate_inference_carbon
- Let an app report its own estimated carbon -> carbon_metric_scaffold
- How a number was produced -> explain_methodology_and_limits

REPORTING RULES
1. If the result has a `summary` field, show it first. If it starts with "NO NET VERDICT" or has an
   `error`, say so and ask me for the missing input.
2. When I ask for PR text, print `pr_text` word for word. Do not rewrite it or add claims about
   company goals or targets.
3. For every carbon figure show its source and quality. "typical", "cached", "annual_average" and
   "historical" are NOT live readings; never call them live.
4. Lead with money when there is a dollar figure. Always give the full low-high range, never only the
   high end, and say if a range crosses zero.
5. Never invent inputs (GB, hours per week, regions, utilisation). If I did not give one, ask. If you
   must assume, list every assumption at the end, including values carried over from an earlier
   question.
6. Pass on residency_note, live_data_hint, limitations and data_attribution when present
   (data_attribution is a credit the data provider requires; always show it). If I ask where a number
   comes from, quote its verify_at entry.
7. Write dollar amounts as "USD 20-40" or escape the sign as \$ so the notebook does not render them
   as maths.
8. If a call fails, show the error and fix the arguments from the tool's schema. After two failures,
   stop and ask me; do not switch to a different approach.
9. Make routine tool calls without asking permission.
10. Answer each question once. No repeated summary sections.
````

## Why each part is there

- **Install from PyPI and connect over stdio.** This is the supported route (see the README's quick
  start). Cloning the repo or importing the server object inside the notebook process is where most
  setup problems come from.
- **Check a tool's parameters first.** Assistants otherwise guess plausible parameter names, and the
  call fails. `schema()` reads the real names from the server.
- **Print the server instructions.** The server sends guidance to every client on connect. A helper
  that never prints it keeps it from the assistant.
- **A tool-choice list.** Assistants tend to reach for the first tool that looks close. Naming the
  right one for each question avoids, for example, drafting pull-request text from a region
  comparison.
- **Reporting rules.** GreenPick labels every carbon figure with its source and quality, and gives
  cost as a range. The rules keep the assistant from dropping those labels.

To get live data instead of `typical` figures, add your own `EIA_API_KEY` and `ENTSOE_TOKEN` to the
`env` dict (see the README).
