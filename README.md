# Daily Dilemma – CMPT 276 Project

A social norm prediction game built on top of the course **user_service** backend.

**Team Members:**
- Tarun Deep Arora  
- Muskaan Sidhu  
- Fady Nasr  
- Peyton Dan-Sonier  

---

## What is Daily Dilemma?

Daily Dilemma is a web game where players face everyday dilemmas and choose between multiple actions.

### Game Modes
- **Prediction Mode:** Guess what the **majority** of players chose  
- **Personal Opinion Mode:** Choose what **YOU** would do  
- **Party Mode:** Play in a group on one device  

Our implementation includes scenario randomization, tie detection, analytics, JWT auth, user service integration, and >95% test coverage.

---

##  1. Prerequisites

- Docker  
- Docker Compose  
- Node.js & npm (required for npm run dev or building the frontend)

---

##  2. Environment Setup


1. Make a `.env` file containing the following, and DO NOT check it into git:

```
POSTGRES_HOST=db
POSTGRES_USER=<some shared username>
POSTGRES_PASSWORD=<some shared password>
ADMIN_PASSWORD=<some shared password>
```
---

## 3. Launching the Application
Start the full application (database + backend + UI):
```
docker compose watch
```

This runs:
db → PostgreSQL
web → FastAPI backend and the bundled frontend
Once it starts, visit:
Game UI: http://localhost:8000/play/ (requires Option B in the frontend setup to have been built at least once)
Admin Panel: http://localhost:8000/admin
API Docs (Swagger): http://localhost:8000/docs
ReDoc Docs: http://localhost:8000/redoc
Changes to the code will hot-reload automatically.

---
## 4. Frontend Setup (Choose One)
Option A — Development Mode (Vite Dev Server)
Use this if you want live-reloading during development:
```
cd src/frontend
npm install
npm run dev
```
The game will be available at:
```
http://localhost:5173
```

Option B — Production Build (Served at /play/)
Use this if you want the backend to serve the UI:
```
cd src/frontend
npm install
npm run build
```

This generates a dist/ folder that Docker serves at:
```
http://localhost:8000/play/
```
Rebuild only when UI code changes.

---


## 5. Seeding Scenario Data (REQUIRED)
Before playing the game, you MUST load the dilemmas into the database:
```
docker compose exec web python scripts/seed_game_data.py
```

This seeds:
- Prediction mode scenarios
- Opinion mode scenarios
- Option choices (A, B, C, …)
- Baseline percentages
- Party mode–compatible questions
If you ever reset the database (docker compose down -v), be sure to run the seed script again.

---


## 6. Playing the Game
After running the server and seeding scenarios, open:
```
http://localhost:8000/play/
```
From here, you can choose any of the three modes:

**Prediction Mode**

- Try to guess what the majority of players chose
- After answering, the game shows:
  - correct/incorrect
  - majority option
  - distribution (%)
  - total votes
  - baseline usage
  - tie detection message when applicable
  - Tracks session stats (# answered, # correct)

**Personal Opinion Mode**

- Choose what you would personally do
- View how the global player base answered
- No correctness label

**Party Mode**

- Multiple players take turns using the same device
- Each player selects their answer
- Final screen shows:
- every player’s choice
- majority
- who matched

---


## 7. Feature Overview (Mapping to Project Proposal)

This section shows how our implementation maps to the original feature list in the project proposal.

### Feature 1 – Scenario Engine and Normal Play Mode
- Implemented as the **Prediction Mode** on `/play/`.
- Backend serves dilemmas from the database (2–4 options, not hardcoded in UI).
- The game tracks which scenarios a player has already answered and prioritizes new ones.
- When all available scenarios are answered, the UI shows an “all dilemmas answered” style message.

### Feature 2 – Crowd Aggregation and Majority Reveal
- For each scenario, the backend stores counts per option from real player answers.
- Each scenario also has a baseline distribution used until enough real answers exist.
- After a prediction is submitted, the result screen shows:
  - which option is treated as the **majority**,
  - the **percentage** for each option,
  - whether the result is using baseline.
- The UI marks the player as **correct/incorrect** based on that majority.

### Feature 3 – User Accounts and Crowd Alignment Stats
- Uses the course **user_service** for signup/login and JWT-based auth.
- For logged-in users, the backend tracks their prediction history and correctness.
- We can compute a “how often you matched the majority” style stat from stored results.
- Only one prediction per user per scenario is stored (no duplicate predictions on the same dilemma).

### Feature 4 – Analytics and Community Metrics
- Backend analytics endpoints aggregate:
  - total predictions per scenario,
  - percentage of predictions that matched the majority (global correctness rate),
  - a simple “disagreement” score based on how close the top options are.
- These analytics can be queried to see which dilemmas are hardest or most controversial, and to compute engagement metrics like typical session length.

### Feature 5 – Personal Opinion Mode (“What would you do?”)
- Implemented as **Personal Opinion Mode** in the `/play/` UI.
- Players answer what they personally would do; the backend stores these answers separately from prediction-mode guesses.
- The result view shows how their choice compares to everyone else’s opinion data.
- Opinion data can be used by analytics to refine or validate which options are most popular.

### Feature 7 – Party Mode (Backup Feature)
- Implemented as **Party Mode** in the `/play/` UI.
- A host picks a number of players; the app assigns Player 1, Player 2, etc.
- All players answer the **same scenario** on one device, one at a time.
- After all players answer, the result screen shows how many players chose each option and highlights the global majority.
- A “Next dilemma” button allows multiple rounds with the same group.

---



## 8. Running Tests
To run all tests:
```
docker compose exec web pytest
```

---
