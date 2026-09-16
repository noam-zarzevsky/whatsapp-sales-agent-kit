"""קביעת פגישות ביומן של דני - יכולת שמופעלת רק למוצר שבסעיף 5 שלו יש ימים ושעות.

שני הסוכנים (השכרה ומכירה) קובעים באותו יומן, וכל אחד רואה מה השני קבע: המועדים
הפנויים נבדקים מול היומן כולו (freebusy), ושוב רגע לפני הקביעה - ליד שבוחר מועד שעה
אחרי שהוצע לו עלול לתפוס שעה שהסוכן השני כבר נתן.

פגישת מכירה מסומנת אחרת מסיור השכרה. סוכן ההשכרה מזהה סיור לפי כותרת שמתחילה
ב"סיור -", לפי השורה הקבועה שלו בתיאור, או לפי התג rental-tour
(rental-leads/src/calendar_tours.py:170) - ובלי ההפרדה היה שולח לקונה תזכורת לסיור השכרה.
"""
import base64
import json
import os
import re
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

import engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# אצל דני - היומן הראשי שלו, מוגדר ב-Railway. בלי הגדרה - היומן של חשבון השירות עצמו
CAL = os.getenv("CALENDAR_ID", "primary")
TZ = "Asia/Jerusalem"
# השרת בענן רץ ב-UTC. כל שעה - עם אזור זמן מפורש. בהשכרה נקבע סיור ל-17:00 במקום
# 14:00 בגלל זה (10-09)
IL = ZoneInfo(TZ)
SCOPES = ["https://www.googleapis.com/auth/calendar"]

MARK = "נקבע אוטומטית על ידי סוכן המכירות."
TAG = "sales-meeting"
# ירוק (Basil). הוורוד שמור לסיורי ההשכרה, כדי שדני יבחין ביניהם ביומן
COLOR = os.getenv("MEETING_COLOR", "10")
MIN_NOTICE_HOURS = int(os.getenv("MEETING_MIN_NOTICE_HOURS", "18"))
DAYS_AHEAD = int(os.getenv("MEETING_DAYS_AHEAD", "10"))
# כמה ימים עם מקום פנוי מגיעים למנוע - בכל יום כל השעות הפנויות, כדי שליד שמבקש
# שעה מסוימת יקבל אותה אם היא פנויה
OFFER_DAYS = int(os.getenv("MEETING_OFFER_DAYS", "4"))

HEB_DAYS = {6: "ראשון", 0: "שני", 1: "שלישי", 2: "רביעי", 3: "חמישי", 4: "שישי", 5: "שבת"}
LETTERS = "אבגדהוש"
# אות היום ← weekday של פייתון (שני=0 ... ראשון=6)
WEEKDAY = {"א": 6, "ב": 0, "ג": 1, "ד": 2, "ה": 3, "ו": 4, "ש": 5}
RANGE = re.compile(r"([אבגדהוש])['׳]?\s*(?:-\s*([אבגדהוש])['׳]?)?\s+"
                   r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")


def _row(product, field):
    """הערך והסטטוס של שורה בטבלה של סעיף 5 בקובץ המוצר."""
    for line in engine.section(product, 5).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0] == field:
            return cells[1], (cells[2] if len(cells) > 2 else "")
    return "", ""


def settings(product):
    """ימים ושעות, משך ומקום - מסעיף 5 בקובץ המוצר. None כשאין שעות או משך: אז המנוע
    לא מציע מועד (כלל 9). פורמט השעות: "א'-ה' 10:00-16:30 · ו' 09:00-12:30"."""
    hours, status = _row(product, "ימים ושעות")
    minutes, mstatus = _row(product, "כמה זמן")
    m = re.search(r"(\d+)\s*דק", minutes)
    if "❌" in hours + status + minutes + mstatus or not m:
        return None
    windows = {}
    for d1, d2, h1, m1, h2, m2 in RANGE.findall(hours):
        for d in LETTERS[LETTERS.index(d1): LETTERS.index(d2 or d1) + 1]:
            windows.setdefault(WEEKDAY[d], []).append(
                (dtime(int(h1), int(m1)), dtime(int(h2), int(m2))))
    if not windows:
        return None
    place, _ = _row(product, "איפה")
    place = re.sub(r"\s*\([^)]*\)\s*$", "", place.replace("🧪", "")).strip()
    return {"windows": windows, "minutes": int(m.group(1)),
            "place": "" if "❌" in place else place}


def label(start):
    return (f"יום {HEB_DAYS[start.weekday()]} {start.day}/{start.month} "
            f"בשעה {start.hour}:{start.minute:02d}")


def in_window(st, start):
    end = start + timedelta(minutes=st["minutes"])
    return any(datetime.combine(start.date(), a, IL) <= start
               and end <= datetime.combine(start.date(), b, IL)
               for a, b in st["windows"].get(start.weekday(), []))


def candidate_slots(st, busy, now, days_ahead=DAYS_AHEAD, offer_days=OFFER_DAYS,
                    notice_h=MIN_NOTICE_HOURS):
    """מועדים פנויים, בלי רשת: בשעות עגולות, כל הפגישה בתוך החלון, ובלי חפיפה לשום
    אירוע ביומן - גם סיור השכרה וגם מה שדני חסם."""
    now = now.astimezone(IL)
    earliest = now + timedelta(hours=notice_h)
    dur = timedelta(minutes=st["minutes"])
    out, days = [], 0
    for i in range(days_ahead + 1):
        day = now.date() + timedelta(days=i)
        found = []
        for w_start, w_end in st["windows"].get(day.weekday(), []):
            s = datetime.combine(day, w_start, IL)
            if s.minute:
                s = s.replace(minute=0) + timedelta(hours=1)
            end = datetime.combine(day, w_end, IL)
            while s + dur <= end:
                if s >= earliest and not any(s < b1 and s + dur > b0 for b0, b1 in busy):
                    found.append({"start": s, "end": s + dur, "label": label(s)})
                s += timedelta(hours=1)
        if found:
            out += found
            days += 1
            if days >= offer_days:
                break
    return out


# ---- מול היומן ----

def _creds():
    from google.oauth2 import service_account
    b64 = os.getenv("GOOGLE_KEY_B64", "").strip()
    if b64:
        return service_account.Credentials.from_service_account_info(
            json.loads(base64.b64decode(b64).decode("utf-8")), scopes=SCOPES)
    # במחשב - עד שלמנוע יהיה מפתח משלו, המפתח של סוכן ההשכרה: אותו יומן, אותו חשבון שירות
    for path in (os.getenv("GOOGLE_KEY_FILE", ""),
                 os.path.join(ROOT, "google-calendar-key.json"),
                 os.path.join(ROOT, "..", "rental-leads", "google-calendar-key.json")):
        if path and os.path.exists(path):
            return service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
    raise RuntimeError("אין מפתח ליומן - GOOGLE_KEY_B64 או google-calendar-key.json")


def _svc():
    from googleapiclient.discovery import build
    return build("calendar", "v3", credentials=_creds(), cache_discovery=False)


def busy(svc, start, end):
    """הטווחים התפוסים ביומן. שגיאה על היומן - חריגה, לא "הכל פנוי"."""
    res = svc.freebusy().query(body={
        "timeMin": start.isoformat(), "timeMax": end.isoformat(),
        "timeZone": TZ, "items": [{"id": CAL}]}).execute()
    cal = res["calendars"][CAL]
    if cal.get("errors"):
        raise RuntimeError(f"היומן החזיר שגיאה: {cal['errors']}")
    return [(datetime.fromisoformat(b["start"].replace("Z", "+00:00")),
             datetime.fromisoformat(b["end"].replace("Z", "+00:00")))
            for b in cal.get("busy", [])]


def free_slots(st, now=None):
    now = (now or datetime.now(IL)).astimezone(IL)
    return candidate_slots(st, busy(_svc(), now, now + timedelta(days=DAYS_AHEAD + 1)), now)


def event_body(st, start, card, product_name):
    """האירוע ביומן. סיכום השיחה בתיאור - "ליד עם פגישה ← הסיכום בהערות של אירוע
    הפגישה" (הוכרע 11-09)."""
    ad = (card.get("profile") or {}).get("from_ad") or ""
    notes = [n for n in card.get("notes", []) if n][-5:]
    questions = card.get("open_questions", [])[-5:]
    lines = [product_name, "", f"ליד: {card.get('name') or '(ללא שם)'}",
             f"טלפון: {card['phone']}", f"מהמודעה: {ad or '-'}"]
    if notes:
        lines += ["", "מהשיחה:"] + [f"• {n}" for n in notes]
    if questions:
        lines += ["", "שאלות פתוחות:"] + [f"• {q}" for q in questions]
    lines += ["", MARK]
    end = start + timedelta(minutes=st["minutes"])
    return {
        "summary": f"פגישת מכירה - {ad}" if ad else "פגישת מכירה",
        "location": st["place"],
        "description": "\n".join(lines),
        "start": {"dateTime": start.isoformat(), "timeZone": TZ},
        "end": {"dateTime": end.isoformat(), "timeZone": TZ},
        "colorId": COLOR,
        "extendedProperties": {"private": {
            "agent": TAG, "phone": card["phone"], "product": card.get("product") or ""}},
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 60}]},
    }


def book(st, start, card, product_name, svc=None):
    """קובע את הפגישה. מחזיר (מצב, פרטים): ok · taken (נתפס בינתיים) · invalid · error."""
    start = start.astimezone(IL)
    # רשת ביטחון: רק בתוך השעות שבקובץ המוצר, גם אם המנוע החזיר מועד אחר
    if not in_window(st, start):
        return "invalid", f"מחוץ לשעות הפגישות: {start:%d/%m %H:%M}"
    end = start + timedelta(minutes=st["minutes"])
    try:
        svc = svc or _svc()
        if busy(svc, start, end):
            return "taken", ""
        ev = svc.events().insert(calendarId=CAL,
                                 body=event_body(st, start, card, product_name)).execute()
        return "ok", {"id": ev.get("id", ""), "link": ev.get("htmlLink", "")}
    except Exception as e:
        return "error", f"{type(e).__name__}: {e}"


def _ours(e):
    props = (e.get("extendedProperties") or {}).get("private") or {}
    return props.get("agent") == TAG or MARK in (e.get("description") or "")


def heal(days_ahead=30, svc=None):
    """מחזיר צבע ותג לפגישות שאיבדו אותם. מערכת הנכסים, שמסונכרנת ליומן של דני, דורסת אירועים
    כמה דקות אחרי שנקבעו (נמצא בהשכרה, 10-09). התיאור שורד, ולפיו מזהים.
    patch ולא update - כדי לא למחוק את מה שמערכת הנכסים הוסיפה."""
    svc = svc or _svc()
    now = datetime.now(IL)
    res = svc.events().list(
        calendarId=CAL, timeMin=now.isoformat(),
        timeMax=(now + timedelta(days=days_ahead)).isoformat(),
        singleEvents=True, orderBy="startTime").execute()
    fixed = []
    for e in res.get("items", []):
        if not _ours(e):
            continue
        props = (e.get("extendedProperties") or {}).get("private") or {}
        if e.get("colorId") == COLOR and props.get("agent") == TAG:
            continue
        phone = props.get("phone") or next(
            (ln.split(":", 1)[1].strip() for ln in (e.get("description") or "").splitlines()
             if ln.startswith("טלפון:")), "")
        svc.events().patch(calendarId=CAL, eventId=e["id"], body={
            "colorId": COLOR,
            "extendedProperties": {"private": {"agent": TAG, "phone": phone}}}).execute()
        fixed.append(e["start"].get("dateTime", ""))
    return fixed
