# NBA starter injury alerts

About 45 minutes before every NBA tipoff, this emails you which **starters** are
out (or doubtful / questionable / game-time decisions). Bench players are ignored.

- Runs free on GitHub Actions every 5 minutes, so your computer doesn't need to be on.
- Injury data: ESPN's public injury report.
- Email: Resend (or Gmail).
- "Starter" = a player who started at least 2 of the team's last 5 games.
- Games that tip off at the same time are combined into one email.
- Each email also shows the game's **schedule spot** from the Fade Calendar
  (back-to-backs, road trips, travel, altitude) and links to the calendar.
  "Bet against" and "consider betting against" games always get an email,
  even when no starters are out.
- No email is sent for a game with no starters out and no schedule edge
  (every game gets an email by default; set the variable `ALWAYS_EMAIL` to `false` to only get flagged games).

## Setup (one time)

Email is sent with **Resend** (free, 100 emails a day, no 2-step verification needed).

1. **Resend account.** Sign up at https://resend.com/signup with the email address you want
   the alerts sent to. Then go to **API Keys** → **Create API Key** (name it anything,
   "Sending access" is enough) and copy the key. It starts with `re_`.
2. **Repository secrets.** In this repo: Settings → Secrets and variables → Actions →
   New repository secret. Add two:
   - `RESEND_API_KEY`: the key from step 1
   - `ALERT_TO`: the email address you signed up to Resend with
3. **Optional variables** (same page, "Variables" tab):
   - `ALERT_TIMEZONE`: e.g. `America/Chicago` (default `America/New_York`)
   - `ALWAYS_EMAIL`: `false` to only get emails for games with a starter out or a schedule edge
4. **Test it.** Actions tab → "Starter injury alerts" → Run workflow → tick
   "Send a test email" → Run. Check your inbox (and spam the first time).

Without your own domain, Resend only delivers to the address you signed up with.
That's all this needs.

**Gmail instead (optional):** if you'd rather send from Gmail, skip the Resend secrets and add
`GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` (made at https://myaccount.google.com/apppasswords,
which needs 2-step verification).

Keep the repo **public**: running every 5 minutes is free and unlimited on public repos,
but would use up the free minutes on a private one. Nothing secret is stored in the code.

## Fade ratings

`fade/` holds the season schedule and the Fade Calendar scoring. If the schedule
changes (for example when the NBA Cup games are set), update
`fade/schedule-2026-27.csv` and run `python3 fade/analyze.py` to rebuild `fade/fade.json`.
