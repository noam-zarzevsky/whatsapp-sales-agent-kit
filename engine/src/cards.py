"""כרטיס ליד - קובץ JSON אחד לכל מספר, קריא בעיניים.

כמו בסוכן ההשכרה (rental-leads/src/leads.py), ועם שדה המוצר: product ננעל בהודעה
הראשונה ולא משתנה אחר כך (הוכרע 10-09, STATUS.md 📌 4). כרטיס עם product = None
הוא ליד שנכנס בלי מילת טריגר - עבר לדני, והסוכן לא עונה לו.
"""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.getenv("DATA_DIR") or os.path.join(ROOT, "data")
LEADS = os.path.join(DIR, "leads")
STATE = os.path.join(DIR, "state.json")
# השרת בענן רץ ב-UTC. חותמות בכרטיס - בשעון ישראל, כמו שדני קורא אותן
IL = ZoneInfo("Asia/Jerusalem")


def now():
    return datetime.now(IL).isoformat(timespec="seconds")


def _path(phone):
    return os.path.join(LEADS, f"{phone}.json")


def get(phone):
    """הכרטיס של הטלפון, או None. "אין כרטיס" הוא חלק מההחלטה של מי הליד."""
    p = _path(phone)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def new(phone, name, product, first_ts):
    return {
        "phone": phone,
        "name": name,
        "product": product,
        # ההודעה הראשונה - הבסיס למדד "ליד ← סיור"
        "first_message_at": datetime.fromtimestamp(first_ts, IL).isoformat(timespec="seconds"),
        "stage": "new" if product else "no_keyword",
        "profile": {},
        "history": [],
        "open_questions": [],
        "handoffs": [],
        "notes": [],
        "created": now(),
        "last_seen": None,
        "handled_ids": [],
    }


def save(card):
    os.makedirs(LEADS, exist_ok=True)
    card["last_seen"] = now()
    with open(_path(card["phone"]), "w", encoding="utf-8") as f:
        json.dump(card, f, ensure_ascii=False, indent=2)


def add_turn(card, who, text):
    card["history"].append({"who": who, "text": text, "at": now()})


def delete(phone):
    """מוחק כרטיס ליד. מחזיר האם היה מה למחוק."""
    p = _path(phone)
    if os.path.exists(p):
        os.remove(p)
        return True
    return False


def all_cards():
    if not os.path.isdir(LEADS):
        return []
    out = []
    for fn in os.listdir(LEADS):
        if fn.endswith(".json"):
            with open(os.path.join(LEADS, fn), encoding="utf-8") as f:
                out.append(json.load(f))
    return out


# ---- מצב השירות ----
# סימן מים: עד איזו הודעה כבר טיפלנו. נשמר לדיסק ורק מתקדם קדימה - אותו מנגנון
# כמו בסוכן ההשכרה, שם חסם מבוסס-גיל ענה שוב על הודעות ישנות (09-09).

def _state():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_state(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)


def watermark():
    """חותמת הזמן של ההודעה האחרונה שטיפלנו בה, או None בהפעלה ראשונה."""
    return _state().get("last_ts")


def set_watermark(ts):
    s = _state()
    s["last_ts"] = int(ts)
    s["updated"] = now()
    _save_state(s)


def summary_state():
    """הסיכום היומי: באיזה יום נשלח (day), עד איזה רגע כיסה (until), ניסיון שנכשל (last_try)."""
    return _state().get("summary", {})


def set_summary(**fields):
    s = _state()
    s.setdefault("summary", {}).update(fields)
    _save_state(s)


def reset_at(phone):
    """מתי דני איפס את השיחה עם הטלפון הזה (AI אפס), או None.

    אחרי איפוס, ההיסטוריה הישנה בוואטסאפ לא נחשבת - הבודק מתחיל שיחה חדשה."""
    return _state().get("resets", {}).get(phone)


def set_reset(phone, ts):
    s = _state()
    s.setdefault("resets", {})[phone] = int(ts)
    _save_state(s)


def owner_done(ids):
    """פקודת בעלים שכבר בוצעה. נמצא 13-09: Whapi שלח מחדש את כל ההיסטוריה עם חותמות זמן חדשות,
    ו-"AI אפס" ישנות רצו שוב. לליד יש handled_ids בכרטיס - לפקודות אין כרטיס, ולכן כאן."""
    seen = set(_state().get("owner_ids", []))
    return bool(ids) and all(i in seen for i in ids)


def mark_owner_done(ids):
    s = _state()
    s["owner_ids"] = (s.get("owner_ids", []) + [i for i in ids if i])[-200:]
    _save_state(s)


def add_usage(entries, day=None):
    """מה הסוכן צרך מהמודל - לפי יום ודגם, בשביל העלות השבועית (דני, 14-09). נשמרים 120 יום."""
    if not entries:
        return
    day = day or datetime.now(IL).date().isoformat()
    s = _state()
    days = s.setdefault("usage", {})
    for e in entries:
        m = days.setdefault(day, {}).setdefault(e["model"], {"in": 0, "out": 0, "calls": 0})
        m["in"] += int(e.get("in") or 0)
        m["out"] += int(e.get("out") or 0)
        m["calls"] += 1
    for old in sorted(days)[:-120]:
        del days[old]
    _save_state(s)


def usage_days(first, last):
    """{יום: {דגם: {in, out, calls}}} מ-first עד last, כולל (תאריכי ISO)."""
    return {d: v for d, v in _state().get("usage", {}).items() if first <= d <= last}
