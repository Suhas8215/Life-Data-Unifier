# Life Data Unifier

Local-first MVP to unify personal commitments from Gmail and Google Calendar.

## Run locally

1. Create and activate a virtual environment.
2. Install dependencies:
   - `pip install -e .`
3. Copy env template and fill OAuth settings:
   - `cp .env.example .env`
   - Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`
   - Keep redirect URI as `http://127.0.0.1:8000/auth/callback`
   - Default SQLite path: `./data/ldu.db`
4. Start the app:
   - `uvicorn app.main:app --reload`
5. Open:
   - `http://127.0.0.1:8000/`
   - `http://127.0.0.1:8000/health`

## Temporary debug endpoint

- Gmail sent messages (default 7 days, 25 messages):
  - `http://127.0.0.1:8000/debug/gmail/sent`
- With custom params:
  - `http://127.0.0.1:8000/debug/gmail/sent?days=7&limit=10&persist=true`
- Gmail inbox-side messages for response analysis:
  - `http://127.0.0.1:8000/debug/gmail/inbox`
- With custom params:
  - `http://127.0.0.1:8000/debug/gmail/inbox?days=7&limit=25&persist=true`
- Calendar events (default yesterday through next 7 days, 25 events):
  - `http://127.0.0.1:8000/debug/gcal/events`
- With custom params:
  - `http://127.0.0.1:8000/debug/gcal/events?lookback_days=1&lookahead_days=7&limit=10&persist=true`
- Extract obligations from stored Gmail records:
  - `http://127.0.0.1:8000/debug/extractor/gmail`
- With custom params:
  - `http://127.0.0.1:8000/debug/extractor/gmail?message_limit=150&persist=true`
- Parse time phrases (v0):
  - `http://127.0.0.1:8000/debug/timeparse/parse?text=I%20will%20send%20it%20tomorrow`
- Build response-needed candidates from stored inbox messages:
  - `http://127.0.0.1:8000/debug/response/gmail`
- With custom params:
  - `http://127.0.0.1:8000/debug/response/gmail?limit=200&threshold=0.4&persist=true`

## Local UI (Step 9)

- Dashboard:
  - `http://127.0.0.1:8000/obligations`
  - shows upcoming calendar events (next 7 days), excluding routine/recurring by default
  - include routine classes/events:
    - `http://127.0.0.1:8000/obligations?include_routine=1`
- Response candidates:
  - `http://127.0.0.1:8000/responses`
- Response candidate detail:
  - `http://127.0.0.1:8000/responses/{candidate_id}`
- Detail:
  - `http://127.0.0.1:8000/obligations/{obligation_id}`
- Actions from detail:
  - done / dismissed / snoozed / pending

Suggested run order:
1. Connect Google at `/`.
2. Run full scan from `/` using the "Run full scan (gmail 7d, gcal -1/+7d)" button.
3. Open `/obligations` for triage.

## One-call scan (Step 10)

- UI trigger (recommended):
  - `POST /scan?gmail_days=7&gcal_lookback_days=1&gcal_lookahead_days=7&gmail_limit=100&gcal_limit=100&message_limit_for_extraction=200`
- Debug API trigger:
  - `http://127.0.0.1:8000/debug/pipeline/scan?gmail_days=7&gcal_lookback_days=1&gcal_lookahead_days=7&gmail_limit=100&gcal_limit=100&message_limit_for_extraction=200`

Demo sequence:
1. Connect Google.
2. Click "Run full scan (gmail 7d, gcal -1/+7d)".
3. Review grouped obligations on dashboard.
4. Open detail and triage with done / dismissed / snoozed.
