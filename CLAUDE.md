# CLAUDE.md

Moving Cost Estimator: a Django REST + React app for hours-based moving estimates. It also tracks completed moves, compares estimated with actual hours, and keeps a staff-managed directory of moving companies.

Background that doesn't belong in this public repo is in `../PROJECT_CONTEXT.md`, outside the repo. Read it before tasks that involve product, business or regulatory decisions. Never copy its private details into the repo.

## Layout

- `backend/`: Django + DRF + Simple JWT. Two apps: `api/` (estimates) and `movers/` (mover profiles).
  - `api/pricing.py`: the pricing engine. All tunable numbers are in the `PRICING` dict at the top.
  - `api/models.py`: `Estimator` (one estimate), `CompletedMove`, `Note`.
  - `api/views.py`: views price moves through `price_move()`. Estimates are always priced on the server.
  - `api/serializers.py`: input validation. `price`, `estimated_hours` and `breakdown` are calculated, never accepted from the client.
  - `api/tests.py` (API) and `api/test_pricing.py` (pricing engine).
  - `movers/`: the `Mover` and `ImportRun` models, the staff-only movers API (`views.py`), and `manage.py import_fmcsa_movers`.
    - `fmcsa.py` downloads and combines FMCSA's public "Carrier – All With History" records (dataset `6eyk-hxee`, no API key). It's a May 2026 snapshot that FMCSA no longer updates.
    - `importer.py` has the import rules. `services.run_import` runs an import and records it as an `ImportRun`. The command and the Movers page both use it.
  - `backend/settings.py`: all settings come from environment variables or `backend/.env`.
- `frontend/`: React 19, Vite, Tailwind v4, Vitest.
  - `src/pages/`, `src/components/`, tests in `__tests__/` folders next to them.
  - `src/api.js`: axios with the JWT header. Defaults to `http://127.0.0.1:8000`; override with `VITE_API_URL`.
  - `src/index.css`: color tokens with light and dark palettes. Use the token classes (`bg-surface`, `text-ink-2`, etc.), not raw colors.
- `docker-compose.yml`: Postgres, Django on gunicorn, frontend on nginx.

### Access

- **Login (JWT):** every endpoint and page needs it, except register, token, and the two public quote endpoints.
- **Public quote endpoints:** `EstimatePreview` and `PricingOptions`. They allow anyone, ignore any token sent, and are rate-limited per IP (`QUOTE_PREVIEW_RATE`). They must never save anything or return user data. Anything that saves or lists estimates stays login-only.
- **Staff only:** the movers API (`IsAdminUser`) and the `/movers` and `/movers/:id` pages, because anyone can register an account. The nav link shows only when `/api/user/me/` says `is_staff`, and the pages show `StaffOnly` on a 403. `PATCH /api/movers/<id>/` only changes `utc_permit_number` and `status`.

### Quote widget

`/widget` (`src/pages/QuoteWidget.jsx`) is the public, embeddable quote page. It uses `EstimateForm` with `quoteOnly`, which has no customer fields and no save button. When it's embedded, `useReportHeight` (`src/hooks.js`) posts a `moving-quote:resize` message, and `public/embed.js` on the host site resizes the iframe. If you change that message, change both files.

## Running it

Backend (terminal 1):

    cd backend
    cp .env.example .env               # first time only; turns on DEBUG
    python3 -m venv venv               # first time only
    source venv/bin/activate
    pip install -r ../requirements.txt # first time, or after requirements change
    python manage.py migrate
    python manage.py runserver         # http://127.0.0.1:8000

Frontend (terminal 2):

    cd frontend
    npm install                        # first time, or after package.json changes
    npm run dev                        # http://localhost:5173

Full stack in Docker: `cp .env.docker.example .env && docker compose up --build`.

Django won't start without `DJANGO_DEBUG=True` or a `DJANGO_SECRET_KEY`, and that includes `manage.py test`. So `backend/.env` has to exist locally.

Import movers from the Movers page (staff), or with `python manage.py import_fmcsa_movers --dry-run` and then without `--dry-run`. To give an account staff access:

    python manage.py shell -c "from django.contrib.auth.models import User; User.objects.filter(username='USERNAME').update(is_staff=True)"

## Testing

    cd backend && source venv/bin/activate && python manage.py test
    cd frontend && npm test
    cd frontend && npm run lint

- `python manage.py test` runs every backend app. Don't narrow it to `test api`, or the movers tests get skipped.
- `test_pricing.py` swaps `PRICING` for a frozen copy (`TEST_PRICING`), so tuning the real numbers won't break tests. If you add a key to `PRICING`, add it to `TEST_PRICING` too.
- New pricing rules need tests in `test_pricing.py`. New endpoints or validation need tests in that app's tests.
- Tests never call real external APIs. Mock them or use sample data.

## Rules

1. **All pricing lives in `backend/api/pricing.py`.** Rates, fees, minimums, multipliers and pricing logic don't go in views, serializers, models or the frontend. The frontend only shows what the API returns. Form choices come from `/api/pricing/options/`.
2. **Never commit `.env` files or secrets.** Only the `*.example` templates are committed. API keys go in `backend/.env`. Check `git status` before each commit, add files by name, and never force-add an ignored file.
3. **Always run the backend and frontend tests, plus lint, before committing.** Don't commit if anything fails.
4. **This repo is public.** Never commit private business details: plans, strategy, pricing deals, or anything from `../PROJECT_CONTEXT.md` that isn't already in the code.
5. **Never commit `*:Zone.Identifier` files.** Windows creates them when files are copied into WSL. They're in `.gitignore`.
6. **Saved estimates keep their price.** Changing `PRICING` affects new and edited estimates only. Don't write migrations or scripts that quietly re-price saved estimates.

## Git workflow

- Work directly in this repo. Don't hand over patches or zip files.
- One feature branch per task, created from an up-to-date `main`. Make small commits, push, open a PR, merge, then delete the branch.
- The owner is newer to git. When asked, run the git commands yourself and briefly explain each step in plain language.

## Working style

- Keep answers concise, with steps that can be copied and pasted.
- Show the plan before big changes, and wait for a go-ahead.
- Keep the app polished: it should look and read like professional software.
