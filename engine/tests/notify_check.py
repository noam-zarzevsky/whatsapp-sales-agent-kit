"""בדיקת ההעברות לדני והסיכום היומי - בלי Whapi ובלי מודל.

וואטסאפ מדומה (שיחות ושליחות בזיכרון) ומוח מדומה, שהבדיקה קובעת לו מה להחזיר.
הנתונים נכתבים לתיקייה זמנית ונמחקים בסוף.

הרצה:  python tests/notify_check.py
"""
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, time as dtime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="master-notify-")

NOAM = "972500000088"
A, B, C, E = (f"97250000000{i}" for i in range(1, 5))
NOT_LISTED = "972500000077"
os.environ.update({
    "DATA_DIR": TMP, "MODE": "test", "PRODUCTS": "demo-project-sales.test",
    "OTHER_AGENT_KEYWORDS": "לפרטים על דירה להשכרה", "OWNER_PHONE": "972500000099",
    "OWNER_KEYWORDS": "AI", "NOAM_PHONE": NOAM, "SUMMARY_AT": "08:30",
    "NOTIFY_COOLDOWN_MIN": "10", "TEST_WHITELIST": ",".join([A, B, C, E]),
})
sys.path.insert(0, os.path.join(ROOT, "src"))

import cards    # noqa: E402
import notify   # noqa: E402
import run      # noqa: E402

SALES = "הי אשמח לפרטים על רכישת דירה 6 חד'"
RENTAL = "הי, אשמח לפרטים על דירה להשכרה"

CHATS, SENT, NEXT, LOGS = {}, [], [], []
FAIL = [False]


def fake_chat_messages(chat_id, count=20):
    ms = sorted(CHATS.get(chat_id, []), key=lambda m: -m["timestamp"])
    return ms[:count], len(ms)


def fake_send(to, body):
    if FAIL[0]:
        return False, "HTTP 500: בדיקה"
    SENT.append((to, body))
    return True, {"message": {"id": "fake", "status": "sent"}}


def fake_think(product, lead, incoming, slots=None, **_):
    out = {"reply": "תשובת בדיקה", "stage": "talking", "missing_fact": None,
           "handoff": None, "handoff_urgent": False, "other_product": None, "note": None}
    out.update(NEXT.pop(0) if NEXT else {})
    return out, []


def no_network(*a, **k):
    raise AssertionError("קריאה לרשת שלא הוחלפה")


run.whapi.chat_messages = fake_chat_messages
run.whapi.send_text = fake_send
run.whapi.health = lambda: (True, "AUTH")
run.whapi.fetch_messages = no_network
run.engine.think_checked = fake_think
run.calendar_meetings.free_slots = lambda st, now=None: []
run.calendar_meetings.heal = lambda *a, **k: []
run.log = notify.log = LOGS.append

T0 = int(time.time()) - 600
_n = [0]


def msg(phone, text, dt):
    _n[0] += 1
    m = {"id": f"m{_n[0]}", "phone": phone, "name": "", "text": text,
         "ts": T0 + dt, "chat_id": f"{phone}@s.whatsapp.net"}
    CHATS.setdefault(m["chat_id"], []).append(
        {"id": m["id"], "timestamp": m["ts"], "from_me": False})
    return m


def to_noam():
    return [b for t, b in SENT if t == NOAM]


def flush(at):
    return notify.flush_urgent(P, run.allowed, now_ts=at)


RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))


P = run.load_products()
T = time.time()

# ---- A: בקשת הנחה - דחוף ----
NEXT.append({"handoff": "מבקש הנחה", "handoff_urgent": True, "note": "ביקש הנחה על 6 חדרים",
             "reply": "את המחיר קובע דני. דני יחזור אליך ישירות."})
run.handle(msg(A, SALES, 0), P, dry=False)
flush(T)
check("דחוף ← הודעה אחת לדני", len(to_noam()) == 1)
body = to_noam()[-1] if to_noam() else ""
check("בהודעה: הסיבה, מספר ללחיצה, והדירה מהמודעה",
      "מבקש הנחה" in body and "050-0000001" in body and "דירה 6 חד'" in body)
check("בהודעה: מה הליד כתב ומה ענינו", "לפרטים על רכישת" in body and "דני יחזור אליך" in body)
check("ההעברה סומנה כנשלחה", all(h.get("sent") for h in cards.get(A)["handoffs"]))
flush(T + 3600)
check("סבב נוסף ← לא נשלח שוב", len(to_noam()) == 1)

# ---- B: שתי העברות דחופות באותו תור, ואז השהיה ----
run.handle(msg(B, SALES, 0), P, dry=False)
NEXT.append({"handoff": "רוצה לסגור", "handoff_urgent": True, "stage": "wants_close"})
run.handle(msg(B, RENTAL, 60), P, dry=False)
n = len(to_noam())
flush(T)
check("שתי העברות דחופות באותו תור ← הודעה אחת עם שתיהן",
      len(to_noam()) == n + 1 and "רוצה לסגור" in to_noam()[-1] and "מוצר אחר" in to_noam()[-1])
NEXT.append({"handoff": "כועס שלא חוזרים אליו", "handoff_urgent": True})
run.handle(msg(B, "למה אף אחד לא חוזר אליי??", 120), P, dry=False)
n = len(to_noam())
flush(T + 60)
check("דחוף נוסף לאותו ליד תוך 10 דקות ← מחכה", len(to_noam()) == n)
flush(T + 11 * 60)
check("אחרי 10 דקות ← נשלח", len(to_noam()) == n + 1 and "כועס" in to_noam()[-1])

# ---- C: לא דחוף - לסיכום ----
NEXT.append({"missing_fact": "ועד בית בדירת 6 חדרים", "reply": "אני בודק וחוזר אליך.",
             "note": "שאל על ועד בית"})
run.handle(msg(C, SALES, 0), P, dry=False)
NEXT.append({"handoff": "ביקש לדבר עם דני", "handoff_urgent": "false"})
run.handle(msg(C, "אפשר לדבר עם דני?", 60), P, dry=False)
n = len(to_noam())
flush(T + 3600)
check("עובדה חסרה ובקשה לא דחופה ← לא נשלחות מיד", len(to_noam()) == n)
check("\"false\" כמחרוזת לא נחשב דחוף",
      [(h["kind"], h["urgent"]) for h in cards.get(C)["handoffs"]]
      == [("missing_fact", False), ("handoff", False)])

# ---- E: שליחה שנכשלה ----
FAIL[0] = True
NEXT.append({"handoff": "רוצה לסגור", "handoff_urgent": True})
run.handle(msg(E, SALES, 0), P, dry=False)
flush(T)
check("שליחה נכשלה ← ההעברה לא מסומנת כנשלחה", not cards.get(E)["handoffs"][0].get("sent"))
FAIL[0] = False
n = len(to_noam())
flush(T + 60)
check("אחרי כשל - לא מנסים שוב לפני 10 דקות", len(to_noam()) == n)
flush(T + 11 * 60)
check("אחרי 10 דקות ← נשלח", len(to_noam()) == n + 1
      and cards.get(E)["handoffs"][0].get("sent"))

# ---- מצב בדיקה: ליד שלא ברשימה ----
run.handle(msg(NOT_LISTED, "היי", 0), P, dry=False)
flush(T + 7200)
check("מצב בדיקה: ליד שלא ברשימה ← לא מעבירים עליו",
      not any("050-0000077" in b for b in to_noam()))

# ---- הסיכום של 08:30 ----
tomorrow = datetime.now(cards.IL).date() + timedelta(days=1)


def at(h, m, day=tomorrow):
    return datetime.combine(day, dtime(h, m), cards.IL)


n = len(to_noam())
check("08:29 ← אין סיכום",
      not notify.daily_summary(P, run.allowed, now=at(8, 29)) and len(to_noam()) == n)
utc = at(8, 31).astimezone(timezone.utc)
check("08:31 בישראל, כשהשעון של השרת ב-UTC ← סיכום אחד",
      notify.daily_summary(P, run.allowed, now=utc) and len(to_noam()) == n + 1)
body = to_noam()[-1]
check("בסיכום: העובדה החסרה והבקשה שלא הייתה דחופה",
      "ועד בית" in body and "ביקש לדבר עם דני" in body)
check("בסיכום: מה שכבר נשלח מיד - שורה אחת, לא שוב במלואו",
      "כבר נשלחו אליך מיד" in body and "מבקש הנחה" not in body)
check("בסיכום: 4 לידים חדשים ו-4 שיחות פעילות", "לידים חדשים: 4 · שיחות פעילות: 4" in body)
check("בסיכום: ליד שלא ברשימה לא מופיע", "050-0000077" not in body)
check("העברות שנכנסו לסיכום סומנו כנשלחו",
      all(h.get("sent") and h.get("via") == "summary" for h in cards.get(C)["handoffs"]))
check("סיכום נוסף באותו יום ← לא נשלח",
      not notify.daily_summary(P, run.allowed, now=at(9, 0)) and len(to_noam()) == n + 1)
n = len(to_noam())
notify.daily_summary(P, run.allowed, now=at(8, 31, tomorrow + timedelta(days=1)))
check("יום בלי פעילות ← אין הודעה", len(to_noam()) == n)

shutil.rmtree(TMP, ignore_errors=True)
failed = [n for n, ok in RESULTS if not ok]
for name, ok in RESULTS:
    print(f"{'✅' if ok else '❌'} {name}")
print(f"\n{len(RESULTS) - len(failed)} מתוך {len(RESULTS)} עברו")
sys.exit(1 if failed else 0)
