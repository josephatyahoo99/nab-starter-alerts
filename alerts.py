"""NBA starter injury alerts.

Runs every few minutes. When an NBA game tips off in about 45 minutes, it
checks both teams' injury reports, keeps only the players who are regular
starters, and emails the list. Bench players are ignored.

Data comes from ESPN's public JSON feeds (no key needed). Email goes out
through Resend (an API key, no 2-step verification) or Gmail (app password).
"""

import json
import os
import smtplib
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "sent.json")

# Settings (from environment / GitHub secrets and variables)
LEAD_MINUTES = int(os.environ.get("LEAD_MINUTES", "45"))
# Send when tipoff is this many minutes away or less (covers GitHub's cron delays).
WINDOW_MINUTES = LEAD_MINUTES + 3
TIMEZONE = ZoneInfo(os.environ.get("ALERT_TIMEZONE") or "America/New_York")
# "true" = email every game even when no starter is out.
ALWAYS_EMAIL = (os.environ.get("ALWAYS_EMAIL") or "false").lower() == "true"
# How many recent games decide who counts as a starter.
SAMPLE_GAMES = 5
# A player counts as a starter if he started at least this share of those games.
STARTER_SHARE = 0.4
# Injury statuses worth reporting, mapped to how they appear in the email.
REPORT_STATUSES = {
    "out": "OUT",
    "doubtful": "DOUBTFUL",
    "questionable": "QUESTIONABLE",
    "day-to-day": "GAME-TIME DECISION",
    "suspension": "SUSPENDED",
}


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "nba-starter-alerts/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception as exc:  # noqa: BLE001
            if i == tries - 1:
                raise
            print(f"retrying {url}: {exc}")
            time.sleep(2 * (i + 1))


def scoreboard(day):
    return get(f"{BASE}/scoreboard?dates={day.strftime('%Y%m%d')}")


def parse_time(s):
    s = s.replace("Z", "+00:00")
    if len(s) == 22:  # e.g. 2026-10-27T23:30+00:00 (no seconds)
        s = s[:16] + ":00" + s[16:]
    return datetime.fromisoformat(s)


def is_regular_or_playoffs(event):
    return (event.get("season") or {}).get("type") in (2, 3, 5)


# ---------- who are the starters? ----------

_summary_cache = {}


def summary(event_id):
    if event_id not in _summary_cache:
        _summary_cache[event_id] = get(f"{BASE}/summary?event={event_id}")
    return _summary_cache[event_id]


def recent_completed_games(team_ids, before, max_days=45):
    """Last SAMPLE_GAMES completed regular-season game ids for each team."""
    found = {t: [] for t in team_ids}
    day = before.astimezone(TIMEZONE).date()
    for _ in range(max_days):
        day -= timedelta(days=1)
        if all(len(v) >= SAMPLE_GAMES for v in found.values()):
            break
        try:
            sb = scoreboard(day)
        except Exception as exc:  # noqa: BLE001
            print(f"scoreboard {day} failed: {exc}")
            continue
        for ev in sb.get("events", []):
            if not is_regular_or_playoffs(ev):
                continue
            if not ev["status"]["type"].get("completed"):
                continue
            for c in ev["competitions"][0]["competitors"]:
                tid = c["team"]["id"]
                if tid in found and len(found[tid]) < SAMPLE_GAMES:
                    found[tid].append(ev["id"])
    return found


def starters_for(team_id, game_ids):
    """Players who started at least STARTER_SHARE of the team's recent games."""
    counts, names, games = {}, {}, 0
    for gid in game_ids:
        try:
            box = summary(gid).get("boxscore", {})
        except Exception as exc:  # noqa: BLE001
            print(f"summary {gid} failed: {exc}")
            continue
        for team in box.get("players", []):
            if team["team"]["id"] != team_id:
                continue
            games += 1
            for block in team.get("statistics", []):
                for a in block.get("athletes", []):
                    if a.get("starter"):
                        aid = a["athlete"]["id"]
                        counts[aid] = counts.get(aid, 0) + 1
                        names[aid] = a["athlete"].get("displayName", aid)
    if games == 0:
        return {}, 0
    keep = {aid: (names[aid], n) for aid, n in counts.items() if n / games >= STARTER_SHARE}
    return keep, games


# ---------- injuries ----------

def injury_label(inj):
    status = (inj.get("status") or "").strip().lower()
    if status in REPORT_STATUSES:
        return REPORT_STATUSES[status]
    fantasy = ((inj.get("details") or {}).get("fantasyStatus") or {}).get("abbreviation", "")
    if fantasy.upper() == "OUT":
        return "OUT"
    return None


def injury_reason(inj):
    d = inj.get("details") or {}
    parts = [d.get("side") if d.get("side") not in (None, "Not Specified") else None, d.get("type"), d.get("detail")]
    text = " ".join(p for p in parts if p)
    return text or (inj.get("shortComment") or "")[:80]


def team_injuries(event_id):
    data = summary(event_id)
    out = {}
    for team in data.get("injuries", []):
        tid = team.get("team", {}).get("id")
        out[tid] = team.get("injuries", [])
    return out


# ---------- email ----------

def send_with_resend(subject, body):
    """Send through Resend (resend.com). No domain needed when sending to the
    email address the Resend account was created with."""
    to = [x.strip() for x in (os.environ.get("ALERT_TO") or "").split(",") if x.strip()]
    if not to:
        raise SystemExit("ALERT_TO secret is missing: set it to the email you signed up to Resend with")
    sender = os.environ.get("RESEND_FROM") or "NBA Alerts <onboarding@resend.dev>"
    payload = json.dumps({"from": sender, "to": to, "subject": subject, "text": body}).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=payload, method="POST",
        headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY'].strip()}",
                 "Content-Type": "application/json", "User-Agent": "nba-starter-alerts/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Resend refused the email ({exc.code}): {exc.read().decode(errors='replace')}")
    print(f"emailed via Resend: {subject}")


def send_email(subject, body):
    if os.environ.get("RESEND_API_KEY"):
        return send_with_resend(subject, body)
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    to = [x.strip() for x in (os.environ.get("ALERT_TO") or sender).split(",") if x.strip()]
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(sender, password.replace(" ", ""))
        s.sendmail(sender, to, msg.as_string())
    print(f"emailed: {subject}")


# ---------- main ----------

def build_report(ev, tip):
    comp = ev["competitions"][0]
    teams = {c["homeAway"]: c["team"] for c in comp["competitors"]}
    home, away = teams["home"], teams["away"]
    injuries = team_injuries(ev["id"])
    recent = recent_completed_games([away["id"], home["id"]], tip)

    lines, flagged = [], 0
    for side in (away, home):
        starters, sample = starters_for(side["id"], recent[side["id"]])
        hits = []
        for inj in injuries.get(side["id"], []):
            aid = (inj.get("athlete") or {}).get("id")
            label = injury_label(inj)
            if label and aid in starters:
                name, n = starters[aid]
                reason = injury_reason(inj)
                hits.append(f"  - {name}: {label}" + (f" ({reason})" if reason else "") + f"  [started {n} of last {sample}]")
        if "--test" in sys.argv:
            print(f"[debug] {side['abbreviation']} starters from last {sample} games: "
                  + ", ".join(f"{n} ({c})" for n, c in starters.values()))
            print(f"[debug] {side['abbreviation']} injury report: "
                  + ", ".join(f"{(i.get('athlete') or {}).get('displayName')}={i.get('status')}"
                              for i in injuries.get(side["id"], [])))
        flagged += len(hits)
        lines.append(f"{side['displayName']}:")
        if not sample:
            lines.append("  (no completed games yet to tell who the starters are)")
        lines.extend(hits or ["  All regular starters available"])
        lines.append("")

    local = tip.astimezone(TIMEZONE)
    title = f"{away['abbreviation']} @ {home['abbreviation']}"
    header = f"{away['displayName']} at {home['displayName']}, tipoff {local.strftime('%-I:%M %p %Z')}"
    return title, header, "\n".join(lines).rstrip(), flagged


def main():
    test_mode = "--test" in sys.argv
    if not (os.environ.get("RESEND_API_KEY") or os.environ.get("GMAIL_APP_PASSWORD")):
        print("No email settings yet: add the RESEND_API_KEY and ALERT_TO secrets (see README).")
        return
    now = datetime.now(timezone.utc)
    state = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            state = json.load(f)

    # Today's and tomorrow's games (late West Coast games fall on the next UTC day).
    events = {}
    local_today = now.astimezone(TIMEZONE).date()
    for day in (local_today, local_today + timedelta(days=1)):
        for ev in scoreboard(day).get("events", []):
            events[ev["id"]] = ev

    due = []
    for ev in events.values():
        if ev["status"]["type"].get("state") != "pre":
            continue
        tip = parse_time(ev["date"])
        minutes = (tip - now).total_seconds() / 60
        if test_mode or (0 < minutes <= WINDOW_MINUTES and ev["id"] not in state):
            due.append((tip, ev))
    due.sort(key=lambda x: x[0])
    if test_mode:
        team = (os.environ.get("TEST_TEAM") or "").strip().lower()
        if team:
            def matches(ev):
                for c in ev["competitions"][0]["competitors"]:
                    t = c["team"]
                    names = [t.get("abbreviation", ""), t.get("displayName", ""), t.get("name", ""), t.get("shortDisplayName", "")]
                    if any(team == n.lower() or (len(team) > 3 and team in n.lower()) for n in names if n):
                        return True
                return False
            due = [d for d in due if matches(d[1])]
        due = due[:1]
        if not due:
            print(f"test mode: no upcoming game found today or tomorrow for {os.environ.get('TEST_TEAM') or 'any team'}")
            return

    if not due:
        print(f"{now.isoformat()}: no games tipping off within {WINDOW_MINUTES} minutes")
        return

    # One email per tipoff time, so a 7:00 slate with five games is one email.
    by_tip = {}
    for tip, ev in due:
        by_tip.setdefault(tip, []).append(ev)

    for tip, evs in by_tip.items():
        sections, titles, total = [], [], 0
        for ev in evs:
            title, header, body, flagged = build_report(ev, tip)
            total += flagged
            if flagged or ALWAYS_EMAIL or test_mode:
                titles.append(title + (f" ({flagged} starter{'s' if flagged > 1 else ''} on report)" if flagged else ""))
                sections.append(f"{header}\n{'-' * len(header)}\n{body}")
        if sections:
            local = tip.astimezone(TIMEZONE).strftime("%-I:%M %p")
            subject = ("[TEST] " if test_mode else "") + f"Starters out, {local} tip: " + ", ".join(titles)
            footer = ("\n\nStarters = players who started at least 40% of the team's last 5 games. "
                      "Statuses are from ESPN's injury report at send time.")
            if test_mode:
                print(subject + "\n" + "\n\n".join(sections))
            send_email(subject, "\n\n".join(sections) + footer)
        else:
            print(f"no starters out for {tip.isoformat()} games; no email")
        if not test_mode:
            for ev in evs:
                state[ev["id"]] = now.isoformat()

    if not test_mode:
        cutoff = (now - timedelta(days=3)).isoformat()
        state = {k: v for k, v in state.items() if v >= cutoff}
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=1, sort_keys=True)


if __name__ == "__main__":
    main()
