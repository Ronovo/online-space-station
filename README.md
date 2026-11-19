# Space Station Explorer Online

A text-based game set on a space station, played in the browser in rounds. It is a Flask web app with
accounts, where each account owns one career whose progress is saved on the server.

## Core Features

- **Accounts**: Register with a username, a password and a security question; each account owns exactly one career. **Forgot password?** resets the password with the security answer and logs the account out of every other browser; five wrong answers lock resets for 15 minutes. A question can't be changed once it is set, and five wrong passwords in a row lock a username's logins for a minute.
- **Rounds**: Every round is one shift on the station, 15 to 45 minutes of play, and ends when the crew shuttle takes the crew to Central Command. The shift's clock only runs while the game is open, so it stands still while you are away
- **Three modes**: A Career that climbs a ladder of jobs from Staff Assistant to Captain, and single rounds in any job, Peaceful or with antagonists
- **Antagonists**: One to three per round, some hidden among the crew, raising the station alert from Green to Red until they are dealt with
- **Jobs**: Twelve jobs (Staff Assistant to Captain), each with its own station access, job events, duties and salary
- **Station Log**: Everything the game tells you goes into a log beside the screen, so nothing stops play. Getting hurt flashes the screen red and drops the health shown in the status bar. A box only appears for a question the game needs answered
- **Departments that need each other**: The Miner's ore feeds the fabricator, the Botanist's produce feeds the stove, and the Scientist's remedies stock MedBay. NPC crew do that work on their own; a player who holds the job has to
- **Station Navigation**: Explore a donut-shaped ring of hallways, a science hallway and department rooms with random events
- **Inventory System**: Carry items, store them in your quarters locker, hold them in your hands, and examine, read, use, eat, drink or drop them. A dropped item stays where it was dropped until someone picks it up
- **Health System**: Track limb damage plus burns, poison, and oxygen; seek treatment in MedBay, or rest in bed. Hunger and thirst climb all shift and wear you down if you ignore them
- **Crew Roster**: Start alongside procedurally staffed NPC crew: a holder for every post (a job in a room; the Scientist has one in each science lab), two Staff Assistants, and two or three extras in random jobs who roam. Posted crew stay at their posts and work, and a crew member who is too badly hurt stops until a Doctor treats them
- **Persistent Progress**: Progress is saved to the server after every action. Deleting the career from the lobby erases it and any round in progress

## Player Guide

The game has a wiki-style Player Guide at `/wiki/`, linked from the login and home pages and readable without logging
in. It has pages for the basics, each station system and each job, at `/wiki/<Page_Name>`, for example
`/wiki/Staff_Assistant`. Prices, credits and other numbers on its pages are read from the game, so they stay current.
The pages live in `space_online/webapp/templates/wiki/pages/`, and `space_online/webapp/wiki.py` lists them by section.

## Modes, Rounds and Careers

### Modes
- **Career**: only the jobs the career has unlocked, one to three antagonists a round, and credits and unlocks carry
  over. Everything else starts fresh each shift: the station, the crew, the locker, your health
- **Single round, Peaceful**: any job, no antagonists, and nothing can kill you. A place to practise
- **Single round, Antagonist**: any job, one to three antagonists, and death ends the round
- A single round is a throwaway character and can be abandoned from the lobby. It never touches the career

### The career ladder
- A career starts as a Staff Assistant with 1000 credits and no other job unlocked
- Ending a shift holding a job unlocks it: ask the Head of Personnel for the job at Access Control on the Bridge,
  which offers a career every job, unlocked or not
- A shift that ends without a new job, while regular jobs are still locked, lets you pick one to unlock from the
  shift report or the lobby
- Head of Personnel unlocks once every regular job is unlocked, and Captain after a round started as Head of
  Personnel
- A salary is paid every 10 minutes: a tenth of the job's starting credits, from 100 for a Staff Assistant to 1000
  for the Captain
- Shares are sold at the end of every shift and added to the career's credits
- Dying ends the round, which still counts: it unlocks the job you died in, or leaves you a pick. Being revived
  costs 5000 credits, and 1000 more each time after. A career that can't pay is over

### Rounds and the shuttle
- The Captain calls the crew shuttle, never in the first 15 minutes. An NPC Captain calls it at Red alert,
  3 minutes after the last antagonist is dealt with (but not before 22 minutes), or at a time between 22 and 37
  minutes picked for that shift
- A player Captain calls and recalls it from the Bridge, Red alert included
- Central Command only calls it at the end of a shift: at that shift's time when no Captain can work, or at 37
  minutes when the player is the Captain
- The shuttle docks at Departures 5 minutes after the call (3 at Red alert), waits 2 minutes, then flies for 1
- It can be recalled until it is halfway to the station, and then can't be called again for the length of that trip
- You survive by being aboard when it reaches Central Command. Missing it means being left behind
- The crew board too: those not at a post leave for Departures when the shuttle is called, those at a post when it
  docks. One in ten doesn't notice, jailed crew are put aboard, and a recall sends everyone back
- Aboard, the shuttle has five sections: the Common Area (strap in before it leaves or be thrown and hurt, and talk
  to the crew about the shift), Command (Head Count and paging crew who missed the call; Security and the Captain
  watch the passengers and issue warrants), the Medical Bay (a free bed that mends limbs at 30% a minute), Security
  (a cell for the wanted crew aboard and every prisoner, the player included) and the Break Room (brew a coffee)
- One thing happens during the flight: turbulence, a crew member taken ill, loose cargo, or a call from Central
  Command
- Every round ends with a shift report: the outcome, the antagonists, what each was after and its fate, duties
  done and missed, pay, and any unlock

### Antagonists
- Eight kinds: the Traitor, Vampire, Changeling and Cultist hide as crew members; the Wizard, Alien, Space Pirate and
  Rogue Bot come from outside
- Each acts in secret at first (sabotage, hurt or poisoned crew, false warrants, stolen credits, dimmed lights), then
  reveals itself by attacking someone and roams the hallways
- The station alert rises from Green through Yellow and Orange to Red with what loose antagonists have done, and Red
  calls the shuttle
- Security Guards and the Captain hunt a revealed antagonist on their own and can finish it without the player
- Every move goes into the Incident Log at the Security and Captain's stations, with the crew who were away from their
  posts at the time. A hidden antagonist is always among them, and jailing the right crew member ends it before it
  strikes
- Each antagonist has an objective (cripple the station's systems, put a crew member out of action, or steal
  credits), and the shift report says whether it was achieved
- Once the shuttle docks, a revealed antagonist makes for the Departures door. It is aboard only if it got there
  (a hidden one, only if the crew member it hides as boarded). The rest are left behind on the station
- An antagonist aboard goes for anyone aboard, picked at random. A crew member it goes for dies, and the rest of
  the crew take 5% of its full health off it for each of them who can fight, up to 60%. When it goes for you, you
  fight it with what it has left

### Combat and weapons
- Turn-based fights that can't be walked away from, against planet monsters and antagonists: Attack, or Block to cut
  the next hit and set up a counter-attack
- Melee weapons with different damage: Crowbar, Combat Knife and Fire Axe from the Engineering fabricator, and an
  Energy Sword from the Security armory. Only the stronger held weapon counts toward an Attack
- Security's Stun Baton makes an enemy lose its turns, and Handcuffs arrest a stunned antagonist on the spot
- Losing to a monster means a rescue; losing to an antagonist means death

## Station Systems

### Jobs and Duties
- Every 2 to 4 minutes a job brings its holder a job event, wherever they are. Walking the hallways no longer does
- Duties: up to three job tasks at a time on a board that opens from every screen. Each runs out after 6 minutes.
  Staff Assistants are sent to help out or bring items to department crew for 25-75 credits, the Botanist delivers
  produce to the Bartender, the Bartender serves drink orders, the Chef serves food orders, the Scientist delivers
  compounds or gas tanks or works out artifacts, by the lab they are posted to, the Miner delivers ore, the Quartermaster delivers
  supplies, and the Doctor treats injured crew
- The shift report counts duties done and missed

### PDA
- Everyone starts a shift with a PDA in their inventory. It is an item, and it only works while it is held in a hand:
  a PDA button then appears on every screen
- Messages: every job event and every duty done or missed, plus a message when something the job looks after needs
  it (the ore store, kitchen produce, MedBay's remedies, a critical crew member, a fault or hazard, bad station air
  or a low life support reservoir, a docked supply pod, a warrant or a revealed antagonist)
- Scanning: with the PDA in a hand, use it on something and the reading goes to the station log. The Botanist reads
  planters, the Chef whether an item is edible, the Bartender what a drink is mixed from, the Scientist an item's
  chemistry or a Gas Tank's gauge, the Quartermaster its prices, and the Miner a vein of ore
- Job apps: Power Readout (Engineer), Crew Vitals to look at (Doctor), Scan Crew (Security Guard), Access Control
  (Head of Personnel), Broadcast to the station (Captain) and the Ore Log (Miner)
- Order Console: every job but the Quartermaster can request a supply or a canister of gas from Central Command from
  anywhere, the same console the Cargo Bay has
- Stocks: the market from anywhere, to look at. Trading still takes the computer in your quarters
- Files: a `guide/` folder of Player Guide pages for the job, as markdown text, and a `home/` folder of up to 20
  files of your own. The Quarters computer reads, writes, edits and deletes them. The PDA only reads them. A career
  keeps its files from shift to shift

### Station Stores
- Three stores sit between the departments: ore (Mining to the fabricator), produce (Botany to the stove) and
  remedies (Chemistry to MedBay)
- An NPC at their post keeps their store topped up, cooks, mixes, treats the badly hurt and keeps the power on.
  Nobody does that work for a player who holds the post: a Scientist player is posted to one science lab a shift,
  and NPC Scientists work the others. A player who changes job takes that job's post, one lab for a new Scientist
- While a post holder is jailed or too hurt to work, the Captain covers the post, and failing that the Head of
  Personnel covers the rooms they have access to

### Hazards
- Every 4 to 7 minutes a hull breach, a fire or bad wiring breaks out in one room. It hurts whoever stays in the
  room and clears the room's crew out, which stops its work
- A Wrench seals a breach, a Fire Extinguisher puts out a fire, and Wirecutters fix wiring, from inside the room.
  The NPC Engineer deals with them in time
- Hazards reach the station's air: a breach vents it to space and drains the reservoir as the pump replaces it, a
  fire burns its Oxygen and burns hotter in Oxygen-rich air, and Plasma or Hydrogen in the air flashes into flame on
  a fire or arcing wiring, burning everyone aboard and starting a fire

### Needs and the floor
- Hunger and thirst climb all shift. Food and drink bring them down, a cooked dish most of all, and either one left
  at its worst wears down a limb every 30 seconds
- A dropped item stays on the floor of the room or hallway tile where it was dropped, with a Pick Up button there

### Power Management
- Monitor and manage station battery levels
- Control system power allocation (life support, lighting, security, communications)
- The Combustion Engine is the main power and the solar array a backup that can hold Power Saving but not Balanced
- Power modes including emergency settings
- Engineering panel access for Engineers, the Captain and the Head of Personnel
- System faults knock out lighting, security or communications until they are repaired from the Engineering panel
  with Basic Tools or a Repair Tool
- Every system does something: with Security Systems down, locked doors open and nobody is arrested on a warrant;
  with the Communication Array down, station announcements don't reach the log and nobody can be called to their
  post; a dead battery shuts life support down
- At 10% battery or less a Low Power Warning says to check the power sources, and a flat battery is a Power Outage
  with the same advice

### Medical System
- Health tracking for limbs, burns, poison, and oxygen
- Paid medical treatment and health assessments in MedBay
- Free full treatment and crew vitals monitoring for Doctors, the Captain and the Head of Personnel
- Injured crew can be treated from the crew vitals monitor, and pay for it from their own credits
- Every treatment uses a remedy from the station stores
- Resting in bed in your quarters mends every limb over time
- Oxygen damage from bad air (too little Oxygen, too much Carbon Dioxide or too thin), poison damage from Plasma in
  it, with emergency revive if oxygen damage reaches critical levels

### Security System
- Access control for restricted areas
- Door locking and unlocking for authorized personnel
- Crew manifest for Security staff
- Warrants, fines and jail time: Security Guards arrest crew with warrants, wanted crew sometimes offer a bribe
  to be let go, unpaid fines are settled with a guard, and anyone who can work the Security station can pardon
  prisoners
- Crew commit the odd petty crime, and a crime a Security Guard witnesses puts out a warrant for the culprit
- A screwdriver and wirecutters force a locked door, and forcing one that isn't yours to open puts a warrant out for
  you
- Being jailed for a fine settles it. A hidden antagonist who is jailed is held for Central Command

### Stock Market
- Real-time market simulation with automatic updates
- Buy and sell shares in various companies from your quarters computer
- Price history tracking and visualization
- Holdings view of the shares you own and what they are worth
- Filtering options and detailed transaction history
- Market news each cycle: three headlines about companies, some real and some not. A real headline moves its
  company that way at the next update

### Bar System
- Order drinks from the menu
- Bartender drink mixing and recipe list
- Drinks are free for the Bartender, and crew drink orders pay the Bartender for mixed drinks served from stock
- Alcohol tracking on your character sheet
- Social interactions
- The NPC Bartender keeps a few mixed drinks ready
- A service window shared with the Kitchen: a Bloody Mary needs celery, which only the kitchen has

### Kitchen System
- Order food from the menu while the Chef is on duty
- The Chef cooks dishes from the pantry into the kitchen's stock, with a recipe book. Tomato, potato, carrot and
  apple come from Botany through the station stores
- Food is free for the Chef, and crew food orders pay the Chef for dishes served from stock
- The service window: each side puts a counted amount of its own ingredients through for the other side's station
  to use, or asks the other side's crew member to pass some through. While they can't work, the request waits and
  comes through once they can. Nobody is paid for it

### Chemistry
- Chemistry is the east door of the Science Hall, off the east side of the ring
- A chemical dispenser mixes compounds: remedies for burns, poison, oxygen damage, hurt limbs and alcohol, Miracle
  Grow for the Botanist, and an Acid Flask, a one-use thrown weapon for any fight
- Processor products, alcohol (as Ethanol) and juices (as Fruit Acid) go straight into the beaker; a processor
  breaks solids such as produce, aloe and iron ore down into chemicals first
- Compound requests: crew ask the Scientist posted in Chemistry for a compound and pay 60-160 credits when it's
  delivered
- The Scientist posted in Chemistry sends remedies to MedBay's stock from the Chemistry Station

### Research
- The Research Lab is the south door of the Science Hall. It has two stations behind one door: the Artifact Section
  and the Teleporter Room
- Alien artifacts come up from the Miner's planet trips and from Central Command. Each is set off by one of four
  test rigs at a strength only it knows: too little gets a hint, far too much overloads it, and what it does when it
  comes alive shows what it is. A correct analysis pays 300 credits and hands over a Healer, a Power Cell or a Warper
- The teleporter sends the Scientist or an item to any tile of the station. Its console numbers follow
  `console = m x station + c` on each axis, with m and c picked afresh every shift, and two test beacon sends are
  enough to work both out. The Player Guide's Research page sets the formulas out with a worked example

### Atmospherics
- Atmospherics is the north door of the Science Hall, the Scientist's third post
- Gas follows one set of rules everywhere: pressure from the amount of gas, its temperature and the container's
  volume; mixing settles the temperature by heat capacity; a fuel and an oxidizer burn into Carbon Dioxide and heat;
  a container past its rated pressure ruptures
- Canister Rack: six 1000 L canisters (two of air, Oxygen, Nitrogen, Plasma and one empty at the start of a shift).
  Transfer between them, fill or empty a Gas Tank, vent to space, connect one to the combustion chamber's inlet, and
  run the one heater/freezer on one canister at a time
- Gas Dispenser: Oxygen, Nitrogen and Carbon Dioxide are free and unlimited; Plasma, Hydrogen and Nitrous Oxide have
  a stock for the shift. It won't fill a canister past its rated pressure
- Combustion Chamber: inject from the inlet canister, light it with the igniter, pump the hot gas out to a canister,
  or vent it. The log gives each burn's peak temperature and pressure
- A rupture loses the gas, starts a fire or a hull breach in Atmospherics, and hurts whoever is in the room
- The Tank Rack hands out an empty Gas Tank and a Gas Analyzer, which reads the station's air and every tank you
  carry. The fabricator makes more analyzers, and a Scientist's PDA reads a tank too
- Reservoir: the gas life support pumps into the station's air. A canister on the Reservoir Port can pump gas in or
  draw it off
- Air Monitor: the station's air against every breathing limit, the life support level and the pump's rate, and
  Vent the Station to clear a contaminant
- The NPC Scientist posted here flushes a tainted reservoir, vents contaminated air and tops up a low reservoir
- Gas requests: crew ask the Scientist posted in Atmospherics for a Gas Tank of a gas and pay 60-160 credits when
  it's delivered
- Transfer valve bombs: a Tank Transfer Valve (one free from the Tank Rack each shift, more from the fabricator for
  ore) joins two Gas Tanks. Opening it, in your hands or on a 10, 30 or 60 second timer, mixes them; hot fuel with an
  oxidizer burns, and the blast is a Dud, Small, Medium or Large by how far past the tanks' rating it goes. Blasts
  start fires or a hull breach, hurt or kill the crew and the player, and wear down a revealed antagonist. One set off
  with no revealed antagonist loose puts a warrant out for the player, and a Traitor may plant one. The Test Range
  reads a bomb out safely, and Central Command pays for the first test of each size and asks the Scientist for tests

### Cargo
- The Cargo Bay is off the Northeast Hallway, next to the Mining Bay
- The Quartermaster orders supplies from Central Command, which dock 90 seconds later, and sells them over the
  counter
- The export counter buys ore, every Botany product including plain Aloe, mutant produce and analysed artifacts
- Supply requests: departments ask the Quartermaster for a supply and pay 60-160 credits when it's delivered. A
  player Quartermaster approves each one on the order console, which orders it, or denies it, which counts as a duty
  done
- The Order Console: anyone else requests a supply or a canister of gas at the counter price, from the Cargo Bay or
  the PDA. The NPC Quartermaster answers 30 to 60 seconds later on the PDA: approved and charged when the requester
  can pay, denied when they can't, and left waiting while the Quartermaster is jailed, hurt or away. An approved
  order docks 90 seconds later and waits at the Cargo Bay for the requester to collect
- Dangerous gas: a full canister of Plasma, Hydrogen or Nitrous Oxide docks and goes down the tube into an empty slot
  on the Atmospherics Canister Rack, or waits at the Cargo Bay until one is free. Every order goes in the Incident
  Log, and from a person's third in a shift each one has an even chance of a warrant for stockpiling dangerous gas

### Mining
- The Miner Station is the locker room: take a Pickaxe and a Blast Shield. Ore sells at the Cargo Bay's export
  counter and goes up to the station stores
- The Magnet pulls in a rock a minute while it is on, up to ten, for common ore
- A shuttle flies down to the planet the station is passing over, which changes every 30 minutes. Searching there
  finds a vein of better ore, nothing, a monster, or now and then an alien artifact for the Research Lab
- Ore from a vein is unidentified until a Miner scans a vein of it with their PDA. After that they know it on sight
  for the rest of the shift, and the PDA's Ore Log keeps the collection. The station names the whole haul on docking
- Turn-based combat when a monster turns up: Attack or Block, with the items in your hands setting your damage and
  how much of each hit you stop. A beaten miner is flown back without the trip's ore
- When the Miner is an NPC, talking to them opens an ore counter
- Ore requests: crew ask the Miner for ore and pay 60-160 credits when it's delivered

### Botany System
- A vending machine at the botanist station sells seeds, liquids and tools for credits; each item has a limited
  stock that restocks one every 5 minutes
- Plant seeds across multiple planters, and water them before each growth stage or they die
- Planter status monitoring, Miracle Grow and Plentiful Harvest; supplies that would do nothing for a plant stay
  in your hand
- Mature plants are harvested from the botanist station; dead plants are cleared with a Trowel, or a Chainsaw for trees
- A plant dying is reported as it happens, and the station status counts planters that need water or have died
- Aloe, a medicinal herb whose leaves soothe burns
- "The Ooze" Mutagen gives a plant a chance of a mutant harvest: Blood Tomato, Glow Potato, Steelwheat, Night
  Carrot, Golden Apple or Royal Aloe, each of which does more than the plain kind
- The Botanist sends produce to the Kitchen from the Botany Station. An NPC Botanist also plants, waters and harvests the planters themselves, and may page the player for help watering when away
- Crop requests: the Bartender asks the Botanist for produce and pays 50-150 credits when it's delivered at the Bar
- When the Botanist is an NPC, talking to them opens a produce stand
- Special access for Botanists

### Life Support
- One air for the whole station. The crew breathe its Oxygen into Carbon Dioxide, and life support's scrubbers and
  pump turn it over from the reservoir in Atmospherics at a rate set by its power level
- At level 5 and above the air stays fresh for a full crew; at 4 and below it thins until it hurts. With life support
  off a full crew breathes it down to where it hurts in 2 minutes, after a station-wide emergency announcement
- The reservoir lasts the longest shift with half again to spare. Whatever is in it is what the air turns into:
  Oxygen enriches it, Carbon Dioxide suffocates, Plasma poisons, and a Traitor who can work Atmospherics may tamper
  with it
- Breathing Nitrous Oxide makes you lose time: everything aboard runs four times as fast. NPC crew fall asleep in it
- A Gas Tank held in a hand with its valve open is breathed through a mask instead of the station's air; a full one
  lasts 5 minutes

### Bridge and Personnel
- Talk to ship leadership when present
- Crew manifest and NPC job assignment for the Head of Personnel
- Public Access Control terminal for job-change requests
- Captain and HoP door control for the Bridge
- Command requests the Captain approves or denies: powering life support, a sector lockdown, Power Saving mode, or a
  warrant for a suspect
- The Incident Log at the Captain's Station

### Engineering
- Fabricator for creating tools, books and weapons out of the ore in the station stores
- Full power management panel for authorized staff
- The Combustion Engine burns fuel and oxidizer canisters sent down the tube from Atmospherics. A hot loop and a cold
  loop drive its generator, and the Engineer calibrates the mixer ratio, injection rate and coolant flow for whatever
  gases are connected
- Pushed too hard the engine stalls its pumps, overheats, and ends in a fire in the Engineering Bay, or a burst with a
  hull breach, and stays dead until repaired with tools. Sabotage can cut its coolant line
- The NPC Engineer runs it at a safe setting and sends empty canisters back to Atmospherics; the Atmospherics Scientist
  refills canisters on the rack and sends them down when a line runs low

## Running it

Requires Python 3.10 or newer.

```sh
python -m venv .venv
.venv\Scripts\activate          # Windows; use `source .venv/bin/activate` elsewhere
pip install -r requirements.txt
python run_server.py
```

Open http://127.0.0.1:5000, register an account, and start a career or a single round from the lobby.

`run_server.py` uses Flask's built-in server, which is fine for playing on your own machine or a LAN.

### Settings

| Environment variable | Default | What it does |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | Interface to bind. Use `0.0.0.0` so other machines on your network can connect. |
| `PORT` | `5000` | Port to listen on. |
| `SPACE_ONLINE_SECRET_KEY` | generated | Session signing key. If unset, one is generated once into `instance/secret_key`. |
| `SECURE_COOKIES` | Off | `1` marks the login cookie Secure, for a site served over HTTPS. |

With `PORTFOLIO_SSO_URL` (the portfolio's address) and `PORTFOLIO_SSO_PUBLIC_KEY`
(printed by the portfolio's `python sso.py`) set, the login page offers to log in with a portfolio account. It
reads **Log In as** and the portfolio username when this browser is logged in to the portfolio. The first
portfolio login here asks whether to link an account the player already has, by logging in to it once, or to
make a new one named after the portfolio username, with a number added if that name is taken. Every later
portfolio login from any device opens the linked account. A new account starts with no password of its own, so
the portfolio is the way into it. Without those two settings the app runs on its own.

Accounts and characters are stored in `instance/space_online.sqlite3`, next to `run_server.py`. The
`instance/` folder is the game's only data: back it up to keep your players, delete it to start fresh.

### Docker

The `Dockerfile` runs the game under gunicorn on port 5000, with the data in a volume at `/app/instance`:

```sh
docker build -t space-station-explorer-online .
docker run -d -p 5000:5000 -v space-online-data:/app/instance space-station-explorer-online
```

Set `SPACE_ONLINE_SECRET_KEY` with `-e` so logins survive the key file being lost.

On every start the container runs `docker/git-sync.sh` before the game. It fetches the latest commit on GitHub
`main`, so a pushed commit goes live on the next restart without rebuilding the image. When that commit hasn't
been built yet it reinstalls `requirements.txt` first, and a failed install is tried again on the next start. If
GitHub can't be reached the game starts on the code it already has.

| Variable | What it does | Default in the image |
| --- | --- | --- |
| `REPO_URL` | The repo to pull. Set it empty to run exactly what is in the image. | This repo on GitHub |
| `REPO_BRANCH` | Branch to pull | `main` |
| `SYNC_DIR` | Folder the code is pulled into | The app folder |
| `BUILD_CMD` | Runs after pulling a commit that hasn't been built yet | `pip install -r requirements.txt` |

## Tests

```sh
pip install -r requirements-dev.txt
python -m pytest
```

The tests cover accounts, password resets, portfolio login, character creation, playing and saving, and the
game itself: every room and station, items and hands, crew movement and crew work, jail, power, oxygen, hazards,
needs, the station stores, the stock market, botany, the kitchen and its service window, chemistry, research, mining,
cargo, combat, antagonists and the investigation of them, duties, the PDA and files, rounds and the shuttle, careers
and the lobby, and the hallway events. `requirements-dev.txt` includes `requirements.txt`, which the portfolio login tests
need.

The page scripts in `space_online/webapp/static/` have their own tests in `tests/js`, run with Vitest on Node.js
after `npm install` once:

```sh
npm test
```

## Coverage

```sh
python -m coverage run -m pytest
python -m coverage report
python -m coverage html
npm run coverage
```

The HTML reports go to `coverage/python` and `coverage/js`, and the coverage commands fail below 100%. The Docker
image builds both reports and serves them at `/coverage/`, under the landing page in `coverage-index/`, the
`ronovos-coverage-index` submodule, with this repo's `coverage-reports.json`. Failing tests or low coverage don't
stop the image build; the reports show what is missing.

## Project layout

```
run_server.py            Starts the game with Flask's built-in server
space_online/webapp/     Flask app: routes, accounts, SQLite storage, templates, static files
space_online/game/       The game itself: station map, rooms, items, crew, jobs, power, market
tests/                   pytest suite; js/ holds the page scripts' Vitest tests
coverage-index/          The test coverage landing page, the ronovos-coverage-index submodule
coverage-reports.json    This repo's entry for that page: its name and reports
instance/                Created on first run: the database and secret key (not committed)
docker/git-sync.sh       Updates the container from GitHub on start
Dockerfile
requirements.txt         Flask, PyJWT and ronovo-portfolio-auth (portfolio login, security questions, login lock)
requirements-dev.txt     Adds pytest and coverage
package.json             The page scripts' test tools (Vitest, jsdom)
```

## Station Layout

The station uses a hollow-square hallway ring with special rooms branching off it:
- Quarters attached at the hallway junction
- Connected hallways forming a complete circuit
- The Science Hall off the east side of the ring, with doors to Atmospherics (north), Chemistry (east) and the Research
  Lab (south)
- Special rooms:
  - Bridge
  - MedBay
  - Security
  - Engineering Bay
  - Bar
  - Kitchen, next to the Bar
  - Botany Lab
  - Mining Bay
  - Cargo Bay, next to the Mining Bay
  - Departures, where the crew shuttle docks
  - Atmospherics, Chemistry and the Research Lab, off the Science Hall

## Job Access Levels

- **Staff Assistant**: Basic access
- **Engineer**: Engineering Bay + power management
- **Security Guard**: Security systems + door control
- **Doctor**: MedBay + advanced treatment
- **Bartender**: Bar + drink mixing
- **Chef**: Kitchen + cooking
- **Botanist**: Botany Lab + plant cultivation
- **Scientist**: Every science lab, posted to one a shift: Chemistry + the chemical dispenser, the Research Lab
  + the artifact bench and the teleporter, and Atmospherics + the canisters, the gas dispenser and the combustion
  chamber
- **Miner**: Mining Bay + the magnet and the shuttle
- **Quartermaster**: Cargo Bay + the order console and the export counter
- **Head of Personnel**: Every department but Security + personnel tools
- **Captain**: Full station access, and the only one who can call the crew shuttle

## Tips

- Monitor your health and seek treatment in MedBay when needed
- Keep track of power levels and oxygen status from Engineering
- Use the stock market on your quarters computer to earn additional credits
- Explore all rooms to discover features, items, and job-specific stations
- Eat and drink before hunger or thirst reach 100%, and rest in bed when your limbs are hurt
- Progress saves automatically; Save and Exit returns you to your account page

## License

BSD 2-Clause. See [LICENSE](LICENSE).
