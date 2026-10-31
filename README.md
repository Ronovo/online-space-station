# Space Station Explorer Online

A text-based exploration game set on a space station, played in the browser. It is a Flask web app with
accounts, where each account owns one character whose progress is saved on the server.

## Core Features

- **Accounts**: Register with a username, a password and a security question; each account owns exactly one character. **Forgot password?** resets the password with the security answer and logs the account out of every other browser; five wrong answers lock resets for 15 minutes. A question can't be changed once it is set, and five wrong passwords in a row lock a username's logins for a minute.
- **Character System**: Create a character with unique jobs (Staff Assistant to Captain), each with special access and starting credits
- **Station Navigation**: Explore a donut-shaped ring of hallways and department rooms with random events
- **Inventory System**: Carry items, store them in your quarters locker, hold them in your hands, and examine, read, use, eat, drink or drop them
- **Health System**: Track limb damage plus burns, poison, and oxygen; seek treatment in MedBay
- **Crew Roster**: Start alongside procedurally staffed NPC crew (department heads and assistants)
- **Persistent Progress**: Your character's progress is saved to the server after every action. Deleting the character erases that progress so you can roll a new one

## Station Systems

### Power Management
- Monitor and manage station battery levels
- Control system power allocation (life support, lighting, security, communications)
- Solar panel charging system
- Power modes including emergency settings
- Engineering panel access for Engineers, the Captain and the Head of Personnel

### Medical System
- Health tracking for limbs, burns, poison, and oxygen
- Paid medical treatment and health assessments in MedBay
- Free limb treatment and crew vitals monitoring for Doctors, the Captain and the Head of Personnel
- Oxygen damage when life support is underpowered, with emergency revive if it reaches critical levels

### Security System
- Access control for restricted areas
- Door locking and unlocking for authorized personnel
- Crew manifest for Security staff
- Warrants, fines and jail time: Security Guards arrest crew with warrants, wanted crew sometimes offer a bribe
  to be let go, unpaid fines are settled with a guard, and anyone who can work the Security station can pardon
  prisoners

### Stock Market
- Real-time market simulation with automatic updates
- Buy and sell shares in various companies from your quarters computer
- Price history tracking and visualization
- Holdings view of the shares you own and what they are worth
- Filtering options and detailed transaction history

### Bar System
- Order drinks from the menu
- Bartender drink mixing and recipe list
- Alcohol tracking on your character sheet
- Social interactions

### Botany System
- Seed collection from the botanist station
- Plant seeds across multiple planters, and water them before each growth stage or they die
- Planter status monitoring, Miracle Grow and Plentiful Harvest
- Mature plants are harvested from the botanist station; dead plants are cleared with a Trowel, or a Chainsaw for trees
- Special access for Botanists

### Life Support
- Oxygen levels tied to power allocation
- A station-wide emergency announcement when life support is switched off, with a short grace period before
  oxygen damage starts
- Effects on player and crew safety when systems are underpowered

### Bridge and Personnel
- Talk to ship leadership when present
- Crew manifest and NPC job assignment for the Head of Personnel
- Public Access Control terminal for job-change requests
- Captain and HoP door control for the Bridge

### Engineering
- Fabricator for creating tools and books
- Full power management panel for authorized staff

## Running it

Requires Python 3.10 or newer.

```sh
python -m venv .venv
.venv\Scripts\activate          # Windows; use `source .venv/bin/activate` elsewhere
pip install -r requirements.txt
python run_server.py
```

Open http://127.0.0.1:5000, register an account, and create your character.

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
game itself: every room and station, items and hands, crew movement, jail, power, oxygen, the stock market,
botany and the hallway events. `requirements-dev.txt` includes `requirements.txt`, which the portfolio login tests
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
- Special rooms:
  - Bridge
  - MedBay
  - Security
  - Engineering Bay
  - Bar
  - Botany Lab

## Job Access Levels

- **Staff Assistant**: Basic access
- **Engineer**: Engineering Bay + power management
- **Security Guard**: Security systems + door control
- **Doctor**: MedBay + advanced treatment
- **Bartender**: Bar + drink mixing
- **Botanist**: Botany Lab + plant cultivation
- **Head of Personnel**: Multiple department access + personnel tools
- **Captain**: Full station access

## Tips

- Monitor your health and seek treatment in MedBay when needed
- Keep track of power levels and oxygen status from Engineering
- Use the stock market on your quarters computer to earn additional credits
- Explore all rooms to discover features, items, and job-specific stations
- Progress saves automatically; Save and Exit returns you to your account page

## License

BSD 2-Clause. See [LICENSE](LICENSE).
