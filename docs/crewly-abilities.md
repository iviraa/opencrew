# What Crewly can do

Crewly is the assistant inside crewly. It assesses where our planned transmission work overlaps with a neighboring utility's work and what coordinating would be worth. It never dispatches crews or gives go/stop orders, and nothing reaches another company without a person tapping Confirm.

This document lists every ability, what invokes it, and what the person sees. The catalogue section is generated from the code, so it stays accurate; regenerate it with:

```
cd backend && uv run python -m scripts.tool_catalogue
```

## How an ability runs

1. The person types in the chat. The frontend posts the last 20 messages to `POST /api/app/chat`.
2. The backend builds the system prompt (`app_system`) and the tool registry (`app_tools`) for the logged-in company and hands both to Gemini.
3. Gemini picks tools. Each tool runs against the database scoped to the company (every overlap query goes through `mine_sql`, so one utility never sees another's data) and returns two things: a result for the model, and zero or more cards for the person.
4. The model writes a short answer using only the numbers in tool results. A guard (`unsourced`) flags numbers that did not come from a tool, and a settle step keeps the cards matching the answer: overlap cards follow the ids the answer names, and a report is never shadowed by the plan it read.
5. The frontend renders the answer plus the cards. Cards are React components in the chat column, and the map, the side panel and the tabs react to them.

Rules the prompt enforces: numbers only from tools, one kind of card per question, "Tap Confirm to send" for anything that leaves the company, assessment language only, build a plan only when asked to plan.

## Who invokes what

Most abilities are chat tools, but several run from buttons, timers or other services.

| Invoker | What runs | Where |
|---|---|---|
| Chat message | any tool in the catalogue below, chosen by the model | `POST /api/app/chat` → `app/crewly/agent.py` |
| Find overlaps button (scan) | overlap and partner-site discovery, then other utilities' public sites, with a refresh check for stale sources during the animation | `GET /api/app/overlaps`, `GET /api/app/scan_context`, `POST /api/app/refresh/check` |
| Plan card buttons | accept, skip, change months, execute accepted (creates requests behind a Confirm) | `PATCH /api/app/plan/{id}/items/{item}`, `POST /api/app/plan/{id}/execute` |
| What-if card knobs | rerun the experiment with new values, compose scenarios, star, compare | `POST /api/app/experiment`, `POST /api/app/compare`, `POST /api/app/finding/{id}/star` |
| Report card | open the printable page | `GET /api/app/report/{id}` |
| Draft card Confirm | send an email draft through the comms provider | `POST /api/app/comms/send` |
| Download / share cards | fetch an export file, open or revoke a share link | `GET /api/app/export/{id}`, `GET /share/{token}`, `DELETE /api/app/share/{id}` |
| Refresh card Apply | promote a staged source edition into the live tables | `POST /api/app/refresh/{id}/promote` |
| Bell (suggestions) | proactive scan: requests waiting on us, follow-ups, weather risks on our best overlaps, overlaps gone cold, due reminders | `CREWLY_PROACTIVE_MINUTES` loop and `POST /api/app/proactive/run` → `app/crewly/proactive.py` |
| Nightly planner | rebuild each company's quarter plan and notify when items were added or dropped | `PLANNER_MINUTES` loop → `app/planner/nightly.py` |
| Hazards refresh | pull live hazard layers (NWS, SPC, WPC, NHC, NIFC, USGS, CPC) | `HAZARDS_REFRESH_MINUTES` loop and `POST /api/app/hazards/refresh` |
| News refresh | utility-first news pipeline with linking and verification | `NEWS_REFRESH_MINUTES` loop and `POST /api/app/news/refresh` |
| Source refresh | check stable planner sources for new editions, stage them, detect drift | `REFRESH_MINUTES` loop and `POST /api/app/refresh/check` |
| Realtime | Supabase Realtime pushes notifications and request changes to the bell and the history panel | Supabase `notification`, `collab_request` tables |

## What the person sees

Every tool result that should be visible becomes a card. The card types and what they look like:

| Card | Appearance |
|---|---|
| show_overlaps | overlap cards in the chat and highlighted on the map, in the order named |
| open_overlap, fly, select | the detail panel opens and the map moves |
| confirm | a Confirm button; the request, answer or email only goes when tapped |
| goal | a goal chip that opens the goal panel with one draft request per overlap |
| plan | the plan card: totals, pairs with accept / skip / change months, timeline, execute |
| chart, table | a chart with PNG and CSV downloads; a table with a CSV download |
| report | a document preview that opens the printable page (Print / Save as PDF) |
| finding, compare | a what-if card: the result in sentences, top deltas, details in a drawer, knobs to try again |
| draft | an email, agenda or memo draft with edit and Confirm |
| note, reminder, status, pipeline, profile, brief, history, views, notebook | workspace cards |
| refresh | a source-refresh card with what changed and an Apply button |
| map_view, projects, timeline, forecast, route, explain, download, share | map and hand-over cards |
| memory | the list of what Crewly remembers |

## Limits

- Gemini's free tier allows a small number of requests per model per day; `app/llm.py` falls through models and reports when they are spent.
- Numbers come from the tools. If a tool has no data for a question, Crewly says so instead of guessing.
- Cross-company data never crosses: overlap, hazard, finding, note and export lookups check ownership and refuse foreign ids.
- Documents (email, agenda, memo) are drafts until confirmed. Slack, Teams and other channels are out of scope.

## Catalogue

<!-- catalogue:start -->

68 tools, generated from `app_tools()` by `backend/scripts/tool_catalogue.py`. Bold inputs are required.

### Overlaps and projects

| Tool | What it does | Inputs | Shows |
|---|---|---|---|
| `my_overlaps` | Overlaps between our projects and neighboring utilities' projects, best first. Optional date range (both projects building inside it), tier, region and partner_company (a utility's name). Plots them on the map and lists them in the chat as clickable cards. | start_date, end_date, tier, region, partner_company, limit | overlap cards + map highlight |
| `open_overlap` | Full details for one overlap (both projects, windows, what can be shared, savings) and open it in the side panel. | **opportunity_id** | overlap detail panel |
| `show_overlaps` | Show exactly these overlaps as cards and on the map, in this order. Call it last, once you have decided which overlaps your answer names (e.g. 'top 2', 'best by criteria'), so the cards match what you said. | **ids**, title | overlap cards + map highlight |
| `search_projects` | Find projects by name and how many opportunities each has. | **query**, org | text only |
| `project_details` | Everything about one project by name: window and where it came from, in-service date, location quality, source page, earlier plans, and its opportunities. Also finds projects still waiting for location review. | **query**, org | view/tab switch, map moves |
| `compare_projects` | Distance, center distance, build-window overlap and in-service gap between any two placed projects, even when they are not an opportunity. | **a**, **b** | map moves |
| `focus_map` | Fly the map to an opportunity or a named region (savannah, augusta, charleston, columbia, savannah river, hilton head). | opportunity_id, region | overlap selected, map moves |
| `estimate_savings` | Recompute the savings range for an opportunity, optionally with assumption overrides (keys: row_width_m, land_usd_per_acre, yard_usd, mobilization_usd, outage_usd; each {low, high}). | **opportunity_id**, assumptions | overlap selected |
| `assess_feasibility` | Feasibility assessment of one of our overlaps: can coordinating with the partner actually happen? Judges location, timing, cost, forecast and season, news, the counterparty's history and future considerations, each with a verdict (strong, possible, unlikely) and the evidence. Opens the overlap in the side panel. | **opportunity_id**, refresh | overlap detail panel |
| `explain_numbers` | Where a figure for one overlap comes from: the formula in words, each line with its basis, the assumptions used with their sources. | **what**, **opportunity_id** | explanation card |
| `explain_method` | How a model works, in a few sentences with sources: overlaps, savings, hazard_days, weather_cost, feasibility, storm_scenario, replay, sensitivity, plan_ranking. | **topic** | explanation card |

### Requests, goals and pipeline

| Tool | What it does | Inputs | Shows |
|---|---|---|---|
| `collab_requests` | Our collaboration requests: ones we sent (and whether they were approved or declined, with feedback) and ones sent to us. Newest first. | direction, status, limit | overlap cards + map highlight |
| `propose_request` | Prepare a collaboration request to the utility on the other side of one of our overlaps. It does NOT send anything: it shows the user a Confirm button with the note. If note is empty a friendly note is drafted. | **opportunity_id**, note | Confirm button (nothing sent until tapped) |
| `propose_answer` | Prepare an approve or decline answer to a pending request another utility sent us. It does NOT answer: it shows the user a Confirm button. | **request_id**, **decision**, feedback | Confirm button (nothing sent until tapped) |
| `start_goal` | Start a multi-step goal like 'line up collaboration on our top 5 overlaps': ranks our best overlaps that have no pending or approved request, drafts a request note for each and saves them as a goal the user reviews and sends from the goal panel. Nothing is sent. | **goal**, count, start_date, end_date, tier | goal chip + goal panel, overlap cards + map highlight |
| `goal_status` | Progress on a goal (latest one if no id): which drafts are still unsent, sent, approved, declined or skipped, with their feedback. | task_id | goal chip + goal panel |
| `set_status` | Move one of our overlaps along the coordination pipeline: not_contacted, drafted, sent, replied, call_scheduled, agreed, declined. Logged in its history. | **opportunity_id**, **status** | status chip, pipeline card |
| `pipeline` | Our overlaps by pipeline status, as a board: counts per status and the top overlaps in each. | none | pipeline card |
| `overlap_history` | Everything that happened on one of our overlaps: status changes, requests and answers with feedback, feasibility assessments, findings, notes, in order. | **opportunity_id** | history card |

### Weather, hazards and news

| Tool | What it does | Inputs | Shows |
|---|---|---|---|
| `outlook` | What official forecasts say is coming in the next 7 days for Georgia and South Carolina: SPC severe storm outlooks, WPC flash flood outlooks, NHC tropical outlooks and wind probabilities, NWS watches, with the active work sites and substations inside. Use for 'what should we worry about this week'. Shows the forecast on the map. | at, region | weather panel, map moves |
| `weather_alerts` | Active NWS alerts for Georgia and South Carolina from the last live poll. | none | live damage view |
| `site_hazards` | Long-range hazard check for a planned project: FEMA 100-year floodplain and how many hurricanes passed within 50 miles since 1950. | **project** | map moves |
| `site_forecast` | The NWS 7-day forecast at a site (project id), an overlap's meet point (#18) or one side (#18 ours), or a region: daily gusts, thunder chance, rain, ice, snow and heat index, with notes where a value crosses a work-affecting threshold. Assessment only. | **site** | forecast card |
| `hazard_exposure` | Hazard exposure of one site (project id) or overlap zone (#id) in a period: which work-affecting hazards touch it and the affected days (forecast for now7; low/high from ten years of history for weeks, season, month or the build window). Assessment only. Opens the hazards view. | **site_or_zone**, period, month | hazard panel |
| `hazard_cost` | Expected extra cost of weather in a period for one site (project id) or overlap (#id): affected days x standby or demobilization cost plus storm-rate labor, with low/high ranges; for an overlap also what coordinating with the neighbor saves (shared standby, one-off mobilization) and the three cheapest months to work the pair. Assessment only. Opens the hazards view. | **site_or_zone**, period, month | hazard panel |
| `incidents_near` | Grid incidents (downed lines, substation damage, outages) merged from NWS/SPC reports and news, with confidence, verified status and nearest utility assets. Replay = Hurricane Helene; live = last 24 h. | region, opportunity_id, time, hours_from_landfall, mode, power_only, limit | storm view, live damage view |
| `news_for` | Recent news about our company, a neighboring utility, or an overlap (#id): outages, damage, delays, opposition, regulatory decisions, supply chain, security. Each story says how it could affect the work and which projects it touches. | company_or_overlap, days, impact | text only |

### Planning

| Tool | What it does | Inputs | Shows |
|---|---|---|---|
| `build_plan` | Build or rebuild our coordination plan for a horizon: which overlaps to pursue, the cheapest months to work each pair by weather history, expected savings, risks and conflicts. Shows the plan card in the chat. Nothing is sent. | horizon | plan card |
| `plan_status` | The current plan for a horizon: pairs, months, savings, which items the user accepted or skipped. | horizon | plan card |
| `explain_plan_item` | Why a plan item was chosen and why those months: feasibility, savings, weather cost vs the naive window, risks, news. | **item_id**, horizon | plan card |
| `plan_bulk` | Accept or skip many plan items at once, filtered by partner utility, verdict or ids. | **action**, horizon, filter | plan card |

### What-if, storms and math

| Tool | What it does | Inputs | Shows |
|---|---|---|---|
| `run_experiment` | Run a what-if on an overlay of the real data (nothing real changes) and return a finding: base vs scenario metrics with deltas. Kinds: shift_window, assumption, exclude_partner, add_project, cancel_project, rule, capacity, budget, storm, replay_year, compose, swap_partner, best_windows, sensitivity, event. params by kind: shift_window {opportunity_id, side: ours/theirs, months} or {job_id, months} or {job_id, start, end}; assumption {name: crew_day_usd, pct: 20} or {name, value} (an overlap via opportunity_id, else the plan); swap_partner {opportunity_id, partner}; exclude_partner {partner, horizon?, opportunity_id?}; add_project {name, kv, start, end, from: station name or {lon, lat}, to: same}; cancel_project {opportunity_id, side} or {job_id}; rule {phase, months: [8, 9], where: coast/everywhere, horizon?}; capacity {crews, quarter: 'Q2', year, horizon?}; budget {cap_usd or target_savings_usd, horizon?}; best_windows {opportunity_id or job_ids}; storm {place: county or city name or {lon, lat}, date, category, opportunity_id?}; replay_year {year, opportunity_id?}; sensitivity {opportunity_id, metric?}; compose {changes: [{kind, params}, ...], base_finding_id?} stacks several changes and evaluates once. | **kind**, params, question | what-if card |
| `calculate` | Exact arithmetic over numbers from earlier tool results: + - * / ^ %, sum, min, max, avg, abs, round, sqrt, pct(a, b), pct_change(a, b), mi_km, km_mi. Pass the numbers in values and refer to them by name in the expression. | **expression**, values | text only |
| `compare_findings` | Shared metrics of two saved findings side by side. | **a**, **b** | comparison card |
| `list_findings` | Saved findings from earlier experiments, newest first. | starred | text only |
| `findings_bulk` | Star, unstar or delete many findings at once, filtered by overlap id, experiment kind or ids. | **action**, filter | notebook card |
| `storm_scenario` | What-if storm over our active sites and our neighbors': a place (county or city), a date and a category (or max wind mph); or historical='helene' for the real Helene track. Returns exposed sites, affected days, extra cost, neighbor capacity nearby and coordination savings as a finding card. | place, state, lon, lat, date, category, max_wind_mph, historical, heading_deg | what-if card |
| `history_replay` | Run overlaps, sites or the latest plan through each of the last ten real years of weather: distribution of affected days and cost, best and worst year, with a chart. | opportunity_ids, job_ids, plan_id, years, hazards | what-if card |
| `sensitivity` | Which assumption moves an overlap's coordination savings or weather cost most: each knob is moved 25% below and above on its own and ranked by swing (a tornado chart). | **opportunity_id**, metric, knobs, month | what-if card |

### Charts, tables, reports and exports

| Tool | What it does | Inputs | Shows |
|---|---|---|---|
| `make_chart` | Build a chart card in the chat from one dataset: overlaps_by_month (our overlaps with both projects building, per month; options years [from, to], partner), hazard_days_by_month (typical weather-affected days per month for a site or overlap; options id, hazards), savings_by_partner (estimated savings summed by neighboring utility; options top), projects_by_year (our projects by in-service year, optionally a partner's too; options years, partner), cost_by_category (one overlap's savings by cost type; options id), news_by_impact (our news stories by impact; options days, partner), plan_totals (the latest plan's pairs and savings; options horizon). options: kind (bar, line, stacked), years [from, to], partner (utility name), id (site or overlap), hazards, top, days, horizon. The card has PNG and CSV downloads. | **dataset**, options | chart card |
| `get_data` | Hand over data as a table card with a CSV download. Tables: overlaps, projects, hazard_exposure, news, requests; or any chart dataset's rows. filters: years [from, to], partner, tier, verdict, state, status, id (site or overlap), period, month, days, impact, direction, top. | **dataset**, filters | table card |
| `query_data` | Group, aggregate and sort any dataset (overlaps, projects, hazard_exposure, news, requests, overlaps_by_month, hazard_days_by_month, savings_by_partner, projects_by_year, cost_by_category, news_by_impact, plan_totals): e.g. average drive_min of overlaps by partner, or sum of savings_high by tier. Returns a table card, plus a chart when grouped. | **dataset**, filters, group_by, aggregate, sort, limit | table card, chart card |
| `make_report` | Write a printable report (opens as a page with Print / Save as PDF): feasibility, cost_analysis or hazard_exposure for an overlap (#id) or site, plan for the plan the user last saw (no id needed; id = horizon picks another), or pack (brief + feasibility + cost + hazards for one overlap). Optional sections to include. Never build a plan first. | **kind**, id, sections | report card (Print / Save as PDF page) |
| `export` | Build a file to download: overlaps, projects, plan, findings or hazard_exposure as geojson or kml (for ArcGIS and Google Earth), csv, xlsx, or ics (calendar entries for plan target windows or project build windows). Only what we can see. | **kind**, **format**, filters | download card |
| `share_link` | An expiring link (default 7 days) that shows a report, finding or the latest plan to someone without a login; revocable from the card. | **kind**, id, expires_days | share-link card |

### Documents for people

| Tool | What it does | Inputs | Shows |
|---|---|---|---|
| `draft_email` | Write an email draft to a partner utility (or an address) about one of our overlaps (#id), the latest plan, or a request (request:<id>). The user edits it in a card and copies or sends it; nothing is sent by this tool. | **to**, **about**, tone, attach | draft card + Confirm |
| `draft_agenda` | A coordination-call agenda for an overlap (#id) or the latest plan: context numbers, decisions to make, data each side brings, open questions. Opens as a printable report. | **about**, when | report card (Print / Save as PDF page) |
| `draft_memo` | A cost-sharing memo for an overlap (#id) or the latest plan: purpose, projects, savings with sources, weather and timing, the split to agree, risks, next steps. audience regulator or internal. Opens as a printable report. | **about**, audience | report card (Print / Save as PDF page) |

### Notes, reminders, views and memory

| Tool | What it does | Inputs | Shows |
|---|---|---|---|
| `add_note` | Save a note for our company on an overlap (#id), a project (id), a utility (name) or a plan item. Shared with everyone at our company, shown on the detail panel. | **target_kind**, **target_id**, **text** | note card |
| `list_notes` | Our notes, all of them or those on one target. | target_kind, target_id | note card |
| `set_reminder` | Remind us later: 'follow up with Duke in 7 days'. Lands in the bell when due. Give due_at (ISO date or datetime) or in_days; optionally what it is about. | **text**, due_at, in_days, target_kind, target_id | reminder card |
| `list_reminders` | Our open reminders, soonest first. | include_done | reminder card |
| `done_reminder` | Mark a reminder done. | **reminder_id** | reminder card |
| `save_view` | Bookmark what is on screen (tab, neighbor filter, shown overlaps, map area) under a name. | **name** | view saved |
| `open_view` | Bring back a saved view by name. | **name** | view/tab switch |
| `list_views` | Our saved views. | none | views card |
| `weekly_brief` | One card for the week: overlaps that appeared or went away since the last brief, requests waiting on us and on them, plan items pending, hazards touching our active sites this week, news about us, findings starred this week. Assessment only. | none | brief card |
| `company_profile` | Everything we know about a utility: states, projects by kV, type and status, overlaps with us, request history with us, recent news and our notes about them. | **company** | profile card |
| `remember` | Save a lasting preference or fact for our company, e.g. 'we never share crews in hurricane season'. Use when the user states a standing rule or says remember. | **text** | memory list |
| `forget` | Delete one saved note by id (use list_memory to find it). | **memory_id** | memory list |
| `list_memory` | List the notes our company asked Crewly to remember. | none | text only |

### Map control

| Tool | What it does | Inputs | Shows |
|---|---|---|---|
| `map_view` | Drive the map: switch tab (overlaps, hazards, news), set the hazards period and month and which hazard layers show, narrow the overlaps list and map with filters (partner, tier, kv, type, status, county, state, years), fit the map to ours, overlaps, one overlap or a bbox, and show or hide the grey context layer of other utilities' projects (layers.others). | **tab**, period, month, hazards, filters, fit, layers | map view change |
| `filter_projects` | Find and highlight our own projects by kv, type, status, county, state, name or build years; they light up on the map and list in a card. | filters, limit | project filter on the map |
| `timeline` | Our projects (and optionally a partner utility's) on a month timeline for a year range. | years, filters, partner | month grid timeline |
| `route_between` | Road distance and drive time between two places (project ids, #18 ours / #18 theirs, regions or lon,lat), drawn on the map. | **a**, **b** | route card + map line |

### Source refresh

| Tool | What it does | Inputs | Shows |
|---|---|---|---|
| `check_for_updates` | Whether the planner project lists we load (PJM, MISO, SPP, ERCOT, WestConnect, CAISO) have a newer edition than what is on the map: the last check per source, its status and a summary. run=true starts a fresh check in the background. | source, run | refresh card |
| `what_changed` | The diff of the latest staged or promoted edition for one planner: projects added, changed (which fields), removed, and how many rows need review. Shows a refresh card. | **source** | refresh card |
| `promote_update` | Offer to apply a staged edition: shows the card with an Apply update button. Nothing changes until the user taps it. | **source** | refresh card |
<!-- catalogue:end -->
