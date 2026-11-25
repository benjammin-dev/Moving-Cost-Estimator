# CLAUDE.md

Moving Cost Estimator: a Django REST + React app that prices local moves by the hour. It is becoming a **moving quote marketplace launching in Washington state**, so pricing and mover data are regulated (see "Washington regulatory rules" below).

## Layout

- `backend/`: Django 5 + DRF + Simple JWT. One app, `api/`.
  - `api/pricing.py`: the pricing engine and the `PRICING` config dict.
  - `api/models.py`: `Estimator` (an estimate), `CompletedMove`, `Note`.
  - `api/views.py`: `price_move()` is the single place views call the engine. Estimates are always priced server-side.
  - Auth: every endpoint needs a JWT except register/token and the two **public quote endpoints**, `EstimatePreview` and `PricingOptions`. Those use `AllowAny`, ignore any token sent (`authentication_classes = []`) and are rate-limited per IP by `QuotePreviewThrottle` (`QUOTE_PREVIEW_RATE` in settings). They must never save anything or read user data. Anything that saves or lists estimates stays login-only.
  - `api/serializers.py`: input validation. `price`, `estimated_hours` and `breakdown` are computed and never accepted from the client.
  - `api/tests.py` (API) and `api/test_pricing.py` (engine unit tests).
  - `backend/settings.py`: everything comes from env vars or `backend/.env`.
- `frontend/`: React 19, Vite, Tailwind v4, Vitest. `/widget` (`src/pages/QuoteWidget.jsx`) is the public, embeddable quote page. It uses `EstimateForm` with `quoteOnly`, which has no customer fields and no save. When it's embedded, `useReportHeight` (in `src/hooks.js`) posts a `moving-quote:resize` message with its height, and `public/embed.js` on the host page uses it to size the iframe. If you change the message, change both files. All other routes are wrapped in `ProtectedRoute`. Pages in `src/pages/`, components in `src/components/`, tests in `__tests__/` next to them. Design tokens are in `src/index.css`.
- `docker-compose.yml`: Postgres, gunicorn backend, nginx frontend.

## Running it

Backend (from `backend/`):

```bash
cp .env.example .env               # first time only; sets DJANGO_DEBUG=True
python3 -m venv venv && source venv/bin/activate
pip install -r ../requirements.txt
python manage.py migrate
python manage.py runserver         # http://127.0.0.1:8000
```

Frontend (from `frontend/`, second terminal):

```bash
npm install
npm run dev                        # http://localhost:5173
```

The frontend calls `http://127.0.0.1:8000` unless `VITE_API_URL` is set.

Full stack in Docker (from the repo root): `cp .env.docker.example .env && docker compose up --build`.

Without `DJANGO_DEBUG=True`, settings refuse to load unless `DJANGO_SECRET_KEY` is set. That applies to `manage.py test` too, so `backend/.env` must exist locally.

## Testing

```bash
cd backend && source venv/bin/activate && python manage.py test api
cd frontend && npm test            # vitest run
cd frontend && npm run lint        # eslint
```

- `test_pricing.py` patches `PRICING` with a frozen `TEST_PRICING` copy. Changing the real numbers in `pricing.py` should not break tests. If you add a new `PRICING` key, also add it to `TEST_PRICING`.
- New pricing rules need engine tests in `test_pricing.py`. New endpoints or validation need tests in `tests.py`.

## Rules

1. **All pricing lives in `backend/api/pricing.py`.** Rates, fees, minimums, multipliers, thresholds and pricing rules go in `PRICING` or the functions in that file. Do not hard-code prices or pricing math in views, serializers, models or the frontend. The frontend only shows what the API returns, and form choices come from `/api/pricing/options/`.
2. **Never commit `.env` files.** This covers `.env`, `backend/.env`, `frontend/.env` and any other real env file. Only `*.example` templates are committed. Check `git status` before committing, and never use `git add -f` on an env file.
3. **Always run the backend and frontend tests before committing.** Run `python manage.py test api` and `npm test`, and also `npm run lint`. Don't commit if anything fails.
4. Pricing changes apply to new and edited estimates only. Saved estimates keep their stored `breakdown` until they are edited. Don't write migrations or scripts that silently re-price saved quotes.

## Washington regulatory rules

The marketplace launches in Washington state, where household goods moving is regulated by the Utilities and Transportation Commission (UTC). Treat these as hard requirements:

- **Permits:** a mover can only be listed or quote on the marketplace if they hold a valid **UTC household goods permit**.
- **Tariff bounds:** every rate charged must stay within the **minimum and maximum rates in UTC Tariff 15-C**. Quotes must never go below the minimum or above the maximum. That includes the low/high range the engine shows (`ESTIMATE_RANGE_PCT`), not just the midpoint.
- **Hourly scope:** moves of **55 miles or less** are priced hourly. This engine is hourly-only, so it should only quote moves of 55 miles or less. Moves over 55 miles are not hourly and need a separate pricing path (on the roadmap as "Long-distance moves").

Don't make up tariff figures. If a task needs actual Tariff 15-C rates, allowed charges, or permit details, ask for the source document or have the user confirm the values. Put confirmed values in `pricing.py` with a comment naming the tariff section they come from.

### Gaps between the code and these rules (as of 2026-11-25)

The current code was built as a single-company estimating tool. It does **not** enforce these rules yet:

- No mover/company model, and no permit number or permit status. Each user just sees their own estimates.
- The public widget shows these numbers to the public. Until real tariff values are in place, it is showing placeholder prices to consumers.
- No tariff min/max check. `HOURLY_RATE_PER_MOVER`, `TRUCK_HOURLY_RATE` and `TRIP_FEE` are placeholder values, and nothing clamps or validates the final rate.
- No mileage input. Distance is only `drive_minutes`, so the 55-mile limit can't be checked.
- The flat `TRIP_FEE` and the `SPECIAL_ITEMS` flat fees have not been checked against which charges Tariff 15-C allows.

When working in these areas, close these gaps. Don't build new features that assume they're handled.
