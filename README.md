<div align="center">

<img src="frontend/public/favicon.svg" width="96" alt="Crewly beaver" />

# Crewly

### Unlock collaborations. Save money. Everyone wins!

**Utilities build right next to each other without knowing it. Crewly finds every overlap, puts a sourced price
on it, and helps both sides act on it, before the next storm hits.**

![ShellHacks 2026](https://img.shields.io/badge/ShellHacks-2026-5b2bb5?style=flat-square)
![Sperry Tech GridLock Challenge](https://img.shields.io/badge/Sperry_Tech-GridLock_Challenge-1b2447?style=flat-square)
![Solana](https://img.shields.io/badge/Solana-devnet-9945FF?style=flat-square&logo=solana&logoColor=white)
![Gemini](https://img.shields.io/badge/Agent-Gemini-2f6bff?style=flat-square)

### [**→ Open the live app: crewly.miami**](https://crewly.miami/)

[Agent abilities](docs/crewly-abilities.md) · [Cost model](docs/cost-savings-model.md) · [Solana bounties](solana/bounty.md)

</div>

---

## The problem

Two utilities are planning to build power lines a few miles apart, on opposite banks of the same river, in
the same year. Each will haul in its own cranes, set up its own laydown yard, survey its own right-of-way and
put its own crews in hotels. Neither knows the other is there.

This happens constantly, and not because the information is secret. It is public, but it is scattered across
dozens of regulatory filings, 400-page PDFs, spreadsheets and planning-authority websites, each in its own
format. Nobody has the time to read them all side by side.

It is costly enough that federal regulators stepped in. In 2024, FERC issued **Order No. 1920** because
utilities have historically planned in isolation, leading to duplicated work and delays in building the grid.

Then a storm hits, and the same thing happens at speed: restoration crews from neighboring utilities work
block by block next to each other, with no shared picture of who is where.

## The fix

Crewly gives a utility the whole picture, and an agent that works through it.

### 1. Every project, on one map

A utility logs in and sees its own planned projects **and its neighbors'**, parsed out of the public record:
Dominion Energy South Carolina's five-year budget filings, Georgia Power's ten-year transmission plan, and about
20 regional planners from PJM and MISO to ERCOT, CAISO and SERTP. Crewly extracts each project's name, voltage,
build window, cost and route, places it on the map, and keeps watching the sources for new editions.

<img width="1468" height="803" alt="Screenshot 2026-09-27 at 1 56 17 AM" src="https://github.com/user-attachments/assets/2ea8a91a-4b01-49bb-aea9-fc990a7539ca" />


### 2. Every overlap, ranked

Crewly applies the challenge's rule exactly. Two projects overlap when their **closest points are within
40 km (25 mi)**, the distance a crew will drive from one staging yard. Each overlap is then ranked by what the
two utilities could share:

| Distance | Tier | What they can share |
|---|---|---|
| Touching or crossing | **Crossing** | Outage timing, crossing structures |
| Under 1.6 km | **Land** | Right-of-way, access roads, permits |
| Under 8 km | **Site** | Laydown yards, deliveries |
| Under 40 km | **Crew** | Crews and equipment |

Timeline overlap is the second signal. Crewly lines up each project's phases (survey, clearing, construction,
energization) month by month to find when both are building at once, and checks the **real road drive time**
between the sites, not just the straight-line distance.

<img width="1466" height="796" alt="Screenshot 2026-09-27 at 1 57 38 AM" src="https://github.com/user-attachments/assets/1fe08d1f-7333-4f73-a953-5052ce646f25" />


### 3. A price on every overlap that you can check

Each overlap gets a savings range, broken into cost lines: one mobilization instead of two, one laydown yard,
shared per diem, one corridor survey, less right-of-way to buy. **Every price is a published figure**: MISO
cost guides, BLS wage and cost indices, GSA per diem rates, FEMA equipment rates, USDA land values. Each one is
cited with its page, and the quantities are calibrated against MISO's published totals by the test suite. **No
number comes from a language model.** The model can explain the arithmetic; it never supplies it.

→ [How Crewly estimates the savings](docs/cost-savings-model.md)

<img width="1462" height="796" alt="Screenshot 2026-09-27 at 1 58 38 AM" src="https://github.com/user-attachments/assets/78d967d3-380c-4373-8f6f-6383021fd0a2" />


### 4. The storm, before it arrives

Crewly pulls live feeds from **NWS, SPC, WPC, NHC, NIFC, USGS and CPC**, and reads the news for outages,
damage and delays. It flags which active sites sit in a storm's path, where two utilities will be restoring
power side by side, and what sharing crews there would save. It can run a what-if storm over any county,
replay **Hurricane Helene** hour by hour against today's projects, and replay ten years of real weather to find
the cheapest months to build a pair.

### 5. Coordinate without leaving the app

An agent with **68 tools** does the legwork. Ask it in plain English:

> *"Line up collaboration on our top 5 overlaps with Georgia Power next year."*

It ranks the overlaps, checks whether each is realistic (location, timing, weather, news, the partner's track
record), builds a quarter plan, and drafts the collaboration requests, emails, call agendas and cost-sharing
memos. Requests go to the other utility inside Crewly and arrive in real time. **Nothing leaves your company
until a person taps Confirm**, and one utility never sees another's private data.

<img width="2400" height="1296" alt="image" src="https://github.com/user-attachments/assets/fdb59451-05af-4eaa-baa5-cd7d91c99a6b" />



### 6. Bring in the public

Not every job needs a truck. Crewly lets a utility post **bounties** for simple tasks like "photograph the
downed lines on this street after the storm". A resident claims one and leaves a Solana address and an email.
When the utility approves, the reward is paid **on Solana** in the same transaction, from an escrow the
resident could verify before doing the work.

The utility gets eyes on the ground for a fraction of a crew hour. A two-person storm crew costs
[$400–500 an hour](https://www.pressherald.com/2023/01/29/storm-surge-to-get-lights-back-on-maine-pays-a-premium-for-crews-from-away/).
The resident gets paid within seconds for two minutes of work.

→ [How the Solana bounty system works](solana/bounty.md)


## Challenge checklist

| GridLock asks for | Crewly |
|---|---|
| Ingest public future-construction data from at least two utilities | DESC and Georgia Power filings, plus about 20 regional planners |
| Geographic overlap: closest points within 40 km | Closest-point distance, four tiers exactly as specified |
| Timeline overlap as the secondary signal | Phase-by-phase build-window overlap, plus road drive time |
| **Required:** interactive UI showing both utilities, overlaps highlighted | MapLibre map: pan, zoom, click any project or overlap for its detail panel |
| **Required:** ranked list of top coordination opportunities | Ranked by tier, timing and savings; filter by partner, tier, region or years |
| **Bonus:** cost/impact estimate for a flagged opportunity | Every overlap, with a line-by-line breakdown and a source for every price |
| *Beyond the brief* | Storm and hazard intelligence, a 68-tool agent, in-app coordination, public bounties on Solana |

## Architecture

```mermaid
flowchart LR
    subgraph Sources["Public sources"]
        F[Utility filings<br/>DESC · Georgia Power]
        R[Regional planners<br/>PJM · MISO · SPP · ERCOT<br/>CAISO · SERTP · …]
        H[Hazard feeds<br/>NWS · SPC · NHC · USGS · …]
        N[News]
    end

    subgraph Backend["Crewly backend · FastAPI"]
        I[Ingest<br/>PDF parsing · LLM extraction<br/>geolocation]
        E[Engine<br/>overlaps · savings · plans]
        Z[Hazards · storms<br/>news verification]
        A[Crewly agent<br/>68 tools]
    end

    DB[(Postgres<br/>PostGIS · TimescaleDB)]

    subgraph Client["Browser · React"]
        M[Map · overlaps · plans]
        C[Chat with cards]
        B[Bounty board]
    end

    G[Gemini]
    S[Supabase<br/>auth · realtime]
    SOL[Solana<br/>bounty escrow]

    F & R --> I --> DB
    H & N --> Z --> DB
    DB <--> E
    E --> A
    Z --> A
    A <--> G
    A <--> C
    E --> M
    S <--> Client
    B <--> SOL
```

**How the agent answers a question:**

```mermaid
sequenceDiagram
    actor U as Planner
    participant C as Chat
    participant A as Crewly agent
    participant G as Gemini
    participant T as Tools (scoped to your company)

    U->>C: "What would sharing a yard on #18 save?"
    C->>A: last 20 messages
    A->>G: prompt + 68 tool definitions
    G->>T: estimate_savings(18)
    T-->>G: numbers with sources
    G-->>A: answer using only those numbers
    A->>A: guard flags any number not from a tool
    A-->>C: answer + cards (map moves, cost table, Confirm)
```

## Tech stack

| Layer | Built with |
|---|---|
| Frontend | React 19, TypeScript, Vite, Tailwind CSS, MapLibre GL, three.js (the beaver) |
| Backend | Python 3.12, FastAPI, psycopg, Shapely, OR-Tools (plan scheduling), pypdfium2, trafilatura |
| Data | PostgreSQL with PostGIS and TimescaleDB |
| AI | Gemini, with a 68-tool agent, sourced-number guard and model fallback |
| Auth and realtime | Supabase |
| Blockchain | Solana: Anchor program, `@solana/kit`, Wallet Standard, Codama |
| Email | Resend |
| Deploy | Docker on DigitalOcean App Platform |

## Try it

Open **[crewly.miami](https://crewly.miami/)** and log in as either utility from the challenge:

| Utility | Username | Password |
|---|---|---|
| Dominion Energy South Carolina | `dominion` | `crewly123` |
| Georgia Power | `georgia` | `crewly123` |

Then ask Crewly:

- *"Show our top overlaps with Georgia Power."*
- *"What would coordinating on the best one save, and where do the numbers come from?"*
- *"Replay Hurricane Helene against our active sites."*
- *"Build a plan for next quarter and draft the emails."*

Bounties are public at **[crewly.miami/bounties](https://crewly.miami/bounties)**, no login needed.

## Run it locally

You need Python 3.12+, Node.js 22+, [`uv`](https://docs.astral.sh/uv/), and Docker for the local database.

```sh
cp .env.example .env
docker compose up -d db

cd backend && uv sync
uv run python -m scripts.build_all    # downloads and processes the public data; takes a while
uv run uvicorn app.main:app --reload --port 8000
```

In a second terminal:

```sh
cd frontend && npm ci && npm run dev
```

Open http://localhost:5173. Vite proxies `/api` to the backend on port 8000.

`.env.example` lists every setting. `DATABASE_URL` defaults to the Compose database
(`postgresql://postgres:opencrew@localhost:5433/opencrew`). The agent, outreach and place lookups use
`GEMINI_API_KEY`, `RESEND_API_KEY` and `GOOGLE_PLACES_KEY` when those features are on.

**Checks:** `cd backend && uv run pytest` for the backend tests, `cd frontend && npm run build` for the
type-check and production build. The `Dockerfile` builds both into one image.

## Documentation

- [How Crewly estimates the savings](docs/cost-savings-model.md): every cost line, its published price, and
  where the estimate should not be trusted.
- [What Crewly can do](docs/crewly-abilities.md): all 68 agent tools, generated from the code.
- [The Solana bounty system](solana/bounty.md): how utilities and the public work together, and how Solana
  holds and pays the rewards.
