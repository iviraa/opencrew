# How Crewly estimates the savings from a collaboration

When Crewly finds two utilities planning transmission work close together, the overlap detail shows a dollar range and a table
breaking it into cost types. This document is the working behind that range: what each line means, which published document sets
its price, how the quantities were chosen, and where the estimate should not be trusted.

The short version: **savings = the duplicated work one partner stops paying for.** Every line is a quantity times a published unit
price, scaled down by how much of the two schedules and locations genuinely overlap. No figure is produced by a language model.

- Prices live in `ASSUMPTIONS` in [`backend/app/config.py`](../backend/app/config.py) and
  [`backend/app/crew_costs.json`](../backend/app/crew_costs.json). Each carries its source, page and a `verified` flag.
- Quantities live in `DRIVERS` in the same config file.
- The calculation is [`backend/app/engine/cost.py`](../backend/app/engine/cost.py).
- `uv run python -m scripts.cost_evidence` prints every price, every quantity and a worked example.

## 1. What counts as a saving

Only a cost that would genuinely be paid **twice** if the two utilities worked separately, and **once** if they coordinated. That
rules out a few things people expect to see:

- **Not the projects themselves.** Two substations are still two substations. Coordination changes setup, access, land and
  timing, not the asset.
- **Not weather standby.** Crewly already prices shared standby on bad-weather days separately, in the weather tab and in the
  line under the cost analysis. Counting it here as well would double count it. See
  [`backend/app/hazards/cost.py`](../backend/app/hazards/cost.py).
- **Not anything a language model produced.** The model in the app can move the sliders and explain the arithmetic; it never
  supplies a number.

## 2. The nine lines

Each line names the cost type it belongs to, because that is what the table groups by: **labor, equipment, travel, time, land and
permits, site and overhead.**

| Line | Cost type | Quantity | Price from | Applies when |
|---|---|---|---|---|
| Hauling the fleet in and out once | travel | 45% of one project mobilization | MISO 2018 guide, s. 4.1.1.3 | schedules and drive time allow one fleet |
| Standing the site up and tearing it down once | labor | 35% of one project mobilization | MISO 2018 guide, s. 4.1.1.3 | same |
| One set of temporary facilities | overhead | 20% of one project mobilization | MISO 2018 guide, s. 4.1.1.3 | same |
| One laydown yard instead of two | overhead | 1 yard | MISO 2018 guide, s. 4.2.1.2 | sites within 5 mi and a 45 min drive |
| Per diem and lodging for one crew, not two | travel | shared days × crew size × 10–25% | GSA Per Diem Bulletin FTR 27-01 | the two build windows actually overlap |
| Crane and stringing gear held once | equipment | 10–20 of the shared days × 15–35% | FEMA 2025 equipment rates, Caltrans delay factors | sites within 5 mi and windows overlap |
| Width saved by sharing one corridor | land | 30–60% of one right-of-way width × corridor length | USDA NASS 2026, MISO MTEP24 p. 32 | the lines run side by side |
| One route survey and environmental walk-down | labor | corridor miles × 0.5–1.5 crew-days | BLS OEWS May 2025 × BLS ECEC | the lines run side by side |
| One switching crew for a shared outage | labor | 2 crews × 2 shifts × 10 h | derived from loaded crew-hours | the lines cross |
| Months of waiting taken out of the schedule | time | 1–3 months × tier weight | BLS ECI and BLS PPI | the filing gives a project cost |

### Why mobilization is split three ways

MISO publishes a single mobilization figure per project — $100k at 115 kV, $200k at 230 kV — for "mobilizing and demobilizing all
equipment and people". A single figure cannot tell a planner whether the saving is trucks, people or site setup, so Crewly splits
it 45% hauling / 35% crew / 20% temporary facilities (`MOB_SPLIT`). That split is Crewly's, not MISO's, and it is checked from the
bottom up in `test_mobilization_split_reconciles_with_crew_and_move_rates`:

- **Crew share.** 14 crew-days × 10 h × a loaded crew-hour of $207 (4 workers at the SC mean wage of $36.25 with 1.425 benefit
  loading) is $28.9k, against the split's $35k. Within 0.83×.
- **Hauling share.** 10 crew moves × $3,100 a move is $31k, against the split's $45k. Within 0.69×.

The test requires both to land within a factor of two. It initially failed: the first guesses of 4–8 crew moves and 6–14 crew-days
were far too small to explain MISO's published figure, and were raised to 10–18 and 14–20 to reconcile. That is the point of the
check — the quantities are calibrated to the published aggregate rather than asserted.

### Why the corridor line is not a whole right-of-way

Two lines sharing a corridor still need a corridor. What co-location avoids is the **extra width**, not a second easement. Crewly
credits 30–60% of one line's right-of-way width (`row_shared_frac`). Multiplying the full width, as an earlier version did, made a
two-mile overlap look like a half-million-dollar land saving on its own.

### Where the time saving comes from

Coordinating means the second project stops waiting for the first to clear the corridor and release the outage. Waiting costs
money because construction escalates. Crewly prices 1–3 months of avoided waiting, weighted by how much the projects really
obstruct each other (`TIER_WEIGHT`: crossing 1.0, same land 0.8, same site 0.5, crew range 0.3), against the smaller project's
budget from the filing, at BLS construction escalation. This is the only line that needs a project cost; pairs whose filing has no
cost simply do not get it.

This is also how Crewly answers "what does this save over several years": the escalation rate is per year, so a saving realised
three years out is worth `budget × rate × months / 12` more than the same coordination today.

## 3. How the scaling works

A line's full price is what one partner would avoid if the two jobs were the same job in the same place at the same time. They
never are, so four factors cut it down. All four are in `factors()` in `cost.py`.

| Factor | What it does | Rule |
|---|---|---|
| `same_time` | how much of the shorter build window overlaps the other | the overlap fraction, or a chaining credit (below) |
| `drive` | commuting eats into sharing | 100% next door, falling to 70% at 45 minutes, **0% past 45 minutes** |
| `size` | places the pair inside MISO's 115 kV–230 kV band | 0 at 115 kV, 1 at 230 kV, from the lower voltage of the pair |
| `SHARE` | how much of a duplicated setup one partner really avoids | 50% at the low end, 100% at the high end |

**The 45 minute rule.** Past a 45 minute road drive, crews, yards and equipment stop being shareable and every line that depends
on them goes to zero. This is why some overlaps that look close on the map show no savings.

**Chaining.** Two jobs that do not overlap can still hand a crew from one to the next if they are close in time. Windows within
180 days get a credit that decays to nothing at 180 days (`CHAIN_DAYS`). Jobs years apart share nothing.

**Days, not fractions.** The per diem and equipment lines run on the *actual count of days both work windows are open*, not on a
fraction, because a 14-month shared window houses a crew far longer than a two-week one. These are the lines marked "over N shared
months" in the table.

## 4. Low and high

Every price and most quantities are ranges, never point estimates, and the two ends are computed independently: the low total uses
every low price with every low quantity, the high total every high. The result is deliberately wide. A range of $214k to $921k is
an honest statement that the published sources disagree by that much — the crane standby rate alone spans 9× between Caltrans's
idle-ownership rate and a rental yard's full day rate.

Reading the ends:

- **Low** is the defensible floor: cheapest state wages, ownership-only equipment rates, half the duplicated setup, M&IE without
  lodging, the narrowest corridor credit.
- **High** is the optimistic case with everything aligned: highest state wages, full rental rates, the whole duplicated setup,
  full per diem, the widest corridor credit.

Planners should treat the low end as the number worth acting on and the high end as the case for a conversation.

## 5. Sanity check against the project budget

The detail panel reports the estimate as a percentage of the smaller project's budget, and the model exposes it as
`share_of_budget`. Typical results:

These are the four cases `scripts.cost_evidence` prints, so the table can be regenerated rather than trusted:

| Pair | Estimate | Share of the smaller budget |
|---|---|---|
| crew range, chained 60 days apart, $5M project | $13.6k to $30.3k | 0.3% to 0.6% |
| same site, 80% concurrent, 230 kV, $20M project | $167k to $593k | 0.8% to 3.0% |
| crossing, fully concurrent, 1.9 mi shared corridor, $8M project | $214k to $921k | 2.7% to 11.5% |
| same site but a 60 minute drive apart | $0 | — |

A test asserts the high end stays under 15% of the smaller project's budget. If a pair ever exceeds that, the model is wrong
rather than the opportunity being extraordinary.

## 6. Sources

Each is a public document or a public API series. The `verified` column says whether the number is read directly from the source
(**yes**) or derived from it (**derived**); derived figures carry a note in the config explaining the arithmetic.

| Price | Range | Unit | Verified | Source |
|---|---|---|---|---|
| `mobilization_usd` | 100,000 – 200,000 | $ | yes | [MISO Transmission and Substation Project Cost Estimation Guide, MTEP 2018](https://cdn.misoenergy.org/Transmission-and-Substation-Project-Cost-Estimation-Guide-for-MTEP-2018144804.pdf), p. 16 s. 4.1.1.3 |
| `yard_usd` | 157,590 – 262,660 | $ | derived | Same guide, p. 39 s. 4.2.1.2 (substation site mobilization, used as a proxy — no public unit cost exists for a temporary laydown yard) |
| `outage_usd` | 28,000 – 84,000 | $ | derived | Loaded line-worker crew-hours; 2 crews × 2 shifts × 10 h |
| `row_width_m` | 27 – 38 | m | yes | [MISO MTEP24 Cost Estimation Guide](https://cdn.misoenergy.org/20240501%20PSC%20Item%2004%20MISO%20Transmission%20Cost%20Estimation%20Guide%20for%20MTEP24632680.pdf), p. 32 table 3.1-1 (90 ft at 115 kV, 125 ft at 230 kV) |
| `land_usd_per_acre` | 4,500 – 15,300 | $/acre | yes | [USDA NASS Land Values 2026 Summary](https://www.nass.usda.gov/Publications/Todays_Reports/reports/land0726.pdf), p. 15 (SC $4,500, GA $5,100 pasture; high end applies MISO's 3× cropland rule) |
| `per_diem_usd_day` | 68 – 181 | $/person-day | yes | [GSA Per Diem Bulletin FTR 27-01](https://www.gsa.gov/policy-regulations/regulations/federal-travel-regulation/ftr-and-related-files/gsa-per-diem-bulletin-ftr-2701), FY2027 standard CONUS ($68 M&IE, $113 lodging) |
| `escalation_pct_yr` | 3.2 – 5.12 | %/year | derived | [BLS ECI, construction total compensation](https://api.bls.gov/publicAPI/v2/timeseries/data/CIU2012300000000I) and [BLS PPI, inputs to construction industries, goods](https://api.bls.gov/publicAPI/v2/timeseries/data/WPUIP2300001) |
| `lineworker_hourly_usd` | 36.25 – 60.23 | $/hour | yes | [BLS OEWS May 2025, SOC 49-9051](https://www.bls.gov/oes/current/oes499051.htm) via the BLS Public API (SC mean 36.25, CA mean 60.23; national mean 44.22, median 45.83) |
| `labor_burden_factor` | 1.425 – 1.464 | × wages | derived | [BLS Employer Costs for Employee Compensation](https://www.bls.gov/news.release/archives/ecec_09122025.pdf) (wages are 70.2% of private-industry compensation, 68.3% for installation/maintenance/repair) |
| `crane_standby_usd_day` | 274 – 2,439 | $/day | derived | [Caltrans Equipment Rental Rates](https://dot.ca.gov/-/media/dot-media/programs/construction/documents/equipment-rental-rates-and-labor-surcharge/book_26v3.pdf) delay factors and [FEMA 2025 Schedule of Equipment Rates](https://www.fema.gov/sites/default/files/documents/fema_pa_schedule-equipment-rates_2025.pdf) |
| `digger_derrick_standby_usd_day` | 159 – 1,036 | $/day | derived | FEMA 2025 rates #358 with Caltrans truck rate and delay factor |
| `puller_tensioner_standby_usd_day` | 70 – 333 | $/day | derived | FEMA 2025 rates #464, #465 — a floor only; no public transmission-class puller rate exists |
| `demob_remob_usd` | 3,100 – 6,200 | $/crew move | derived | [APPA Mutual Aid principles](https://www.publicpower.org/system/files/documents/20240624-Mutual-Aid-Agreement-Statement-of-Principles-For-Signature.pdf) and the PowerSouth restoration scope; modelled from the worked example in `crew_costs.json` |

The escalation figures are nine-year compound growth on the same period each year, so they are not distorted by a single spike:

| Series | 2016 | 2025 | Compound growth |
|---|---|---|---|
| ECI, construction total compensation (Q2) | 124.6 | 165.4 | 3.20%/yr |
| PPI, inputs to construction, goods (Aug) | 209.5 | 328.3 | 5.12%/yr |

Labour-heavy work sits near the low end, material-heavy work near the high end.

## 7. Quantities

These are Crewly's counts, not published figures. `crew_moves` and `setup_crew_days` are calibrated against MISO's mobilization as
described above; the rest are stated modelling choices and every one is a range.

| Driver | Range | Meaning |
|---|---|---|
| `crew_size` | 4 – 6 | workers on a transmission line crew, matching the range `crew_day_usd` is built on |
| `shift_hours` | 10 | a normal, non-storm field shift |
| `crew_moves` | 10 – 18 | crew-and-equipment round trips inside one project mobilization |
| `setup_crew_days` | 14 – 20 | crew-days standing a site up and tearing it down |
| `survey_days_per_mile` | 0.5 – 1.5 | crew-days of route survey and environmental walk-down per corridor mile |
| `row_shared_frac` | 0.3 – 0.6 | share of one right-of-way width co-location avoids buying twice |
| `switch_crews` / `switch_shifts` | 2 / 2 | one crew at each end of the line, out of service and back in |
| `gear_days` | 10 – 20 | days a crane and stringing set sit on one site per campaign |
| `gear_share` | 0.15 – 0.35 | share of those days a single shared set covers both sites |
| `crew_share` | 0.10 – 0.25 | share of shared field days one crew genuinely covers both sites |
| `months_pulled_in` | 1 – 3 | months the second project stops waiting on the corridor and the outage |

## 8. What this model does not know

Read the estimate as an assessment that justifies a phone call, not as a number for a work order or a filing.

- **No contractor overhead or profit.** Every rate is direct cost. Caltrans adds 15% on equipment in force-account work; a real
  contract would add more.
- **Two prices are proxies.** There is no public unit cost for a temporary laydown yard (MISO's substation site mobilization
  stands in) or for a transmission-class puller and tensioner (small FEMA units stand in, as a floor).
- **MISO's mobilization is in 2018 dollars** and is not escalated forward. Applying the 5.12% PPI growth would raise it by roughly
  a half. Leaving it alone keeps the estimate conservative.
- **Land value is agricultural.** USDA pasture and cropland values are far below what an easement through developed land costs,
  and they are statewide averages rather than parcel values.
- **The share parameters are judgement.** `SHARE`, `crew_share`, `gear_share` and `row_shared_frac` encode how much of a
  duplicated cost coordination really removes. They are the least evidenced part of the model and the first thing to argue with.
- **Schedules move.** Windows come from utility filings, and filings slip. Where Crewly has seen a project's date change it flags
  it, but the savings are computed from the current window.
- **No transaction cost.** Negotiating a joint build, agreeing liability and aligning two procurement departments costs real
  money and time. None of it is subtracted here.

## 9. Changing the numbers

Every price is overridable at runtime without editing code — the planner UI exposes sliders, and the assistant's
`set_assumptions` tool recomputes any overlap against new values. Overrides are never saved; they answer "what if land were
twice as expensive" and then go away. Quantities in `DRIVERS` are code, on purpose: changing how many crew moves a mobilization
involves should be a reviewed commit, not a slider.
