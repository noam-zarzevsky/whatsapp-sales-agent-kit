"""בדיקת קביעת הפגישות - בלי יומן אמיתי, בלי Whapi ובלי מודל.

היומן, וואטסאפ והמוח מוחלפים לפני שהקוד רץ. הנתונים בתיקייה זמנית שנמחקת בסוף.
בודק גם שסוכן ההשכרה לא יזהה פגישת מכירה כסיור שלו - בקריאה לקוד שלו, בלי לשנות אותו.

הרצה:  python tests/calendar_check.py
"""
import importlib.util
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, time as dtime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="master-calendar-")
A, B, C, D, E, F = (f"97250000000{i}" for i in range(1, 7))
os.environ.update({
    "DATA_DIR": TMP, "MODE": "test", "PRODUCTS": "demo-project-sales.test",
    "OTHER_AGENT_KEYWORDS": "לפרטים על דירה להשכרה", "OWNER_PHONE": "972500000099",
    "OWNER_KEYWORDS": "AI", "NOAM_PHONE": "972500000088", "SUMMARY_AT": "off", "OWNER_NAME": "דני",
    "TEST_WHITELIST": ",".join([A, B, C, D, E, F]),
})
sys.path.insert(0, os.path.join(ROOT, "src"))

import calendar_meetings as cm  # noqa: E402
import cards    # noqa: E402
import engine   # noqa: E402
import notify   # noqa: E402
import run      # noqa: E402

IL = cm.IL
SALES = "הי אשמח לפרטים על רכישת דירה 6 חד'"
PRODUCT = "demo-project-sales"
RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))


P = run.load_products()
TEXT = P[PRODUCT]["text"]
ST = P[PRODUCT]["meeting"]

# ---- מה נקרא מסעיף 5 בקובץ המוצר ----
check("שעות: א'-ה' 10:00-16:30",
      ST and all(ST["windows"].get(d) == [(dtime(10), dtime(16, 30))] for d in (6, 0, 1, 2, 3)))
check("שעות: ו' 09:00-12:30, ובשבת אין",
      ST and ST["windows"].get(4) == [(dtime(9), dtime(12, 30))] and 5 not in ST["windows"])
check("משך 60 דקות, מקום בלי 🧪 ובלי ההערה בסוגריים",
      ST and ST["minutes"] == 60 and ST["place"] == "משרד המכירות, רחוב הדוגמה 1, עיר החוף")
check("שעות ❌ ← אין קביעת פגישות",
      cm.settings(TEXT.replace("א'-ה' 10:00-16:30 · ו' 09:00-12:30", "❌")) is None)
check("משך ❌ ← אין קביעת פגישות", cm.settings(TEXT.replace("| 60 דקות |", "| ❌ |")) is None)
# מוצר קצר בתוך הבדיקה - לא קובץ אמיתי, כדי שהבדיקה תרוץ גם בגרסת הקורס
check("מוצר בלי שעות פגישה ← אין", cm.settings("# מוצר לבדיקה\n\n## 5. הפגישה\n\nאין פגישות\n") is None)

# ---- מועדים פנויים ----
SAT = datetime(2026, 9, 12, 12, 0, tzinfo=IL)   # שבת בצהריים
SUN = SAT.date() + timedelta(days=1)


def at(day, h, m=0):
    return datetime.combine(day, dtime(h, m), IL)


BUSY = [(at(SUN, 10), at(SUN, 12)),        # דני חסם - פרטי
        (at(SUN, 14), at(SUN, 14, 30))]    # סיור שסוכן ההשכרה קבע
SLOTS = cm.candidate_slots(ST, BUSY, SAT)
check("ראשון: 12, 13, 15 - בלי מה שדני חסם ובלי סיור ההשכרה ב-14:00",
      [s["start"].hour for s in SLOTS if s["start"].date() == SUN] == [12, 13, 15])
check("אף פגישה לא נגמרת אחרי 16:30",
      all(s["end"] <= at(s["start"].date(), 16, 30) for s in SLOTS))
check("4 ימים עם מקום - ראשון עד רביעי",
      sorted({s["start"].date() for s in SLOTS}) == [SUN + timedelta(days=i) for i in range(4)])
ALL = cm.candidate_slots(ST, [], SAT, offer_days=20)
check("שישי: 9, 10, 11 - הפגישה נגמרת עד 12:30",
      [s["start"].hour for s in ALL if s["start"].weekday() == 4] == [9, 10, 11])
check("שבת - אף מועד", not any(s["start"].weekday() == 5 for s in ALL))
check("אותו רגע בשעון UTC של השרת ← אותם מועדים",
      [s["start"] for s in cm.candidate_slots(ST, BUSY, SAT.astimezone(timezone.utc))]
      == [s["start"] for s in SLOTS])
check("18 שעות מראש: ביום ראשון 09:00 אין מועד לאותו יום",
      not any(s["start"].date() == SUN for s in cm.candidate_slots(ST, [], at(SUN, 9))))
check("תווית בעברית", SLOTS[0]["label"] == "יום ראשון 13/9 בשעה 12:00")
check("בתוך השעות: ראשון 15:00 כן · ראשון 16:00 ושבת 10:00 לא",
      cm.in_window(ST, at(SUN, 15)) and not cm.in_window(ST, at(SUN, 16))
      and not cm.in_window(ST, at(SUN + timedelta(days=6), 10)))

# ---- האירוע ביומן ----
card = cards.new(A, "דני", PRODUCT, time.time())
card["profile"]["from_ad"] = "דירה 6 חד'"
card["notes"] = ["מחפש 6 חדרים, קומה 9"]
body = cm.event_body(ST, at(SUN, 12), card, P[PRODUCT]["name"])
check("באירוע: כותרת, טלפון, מהמודעה, סיכום השיחה ומקום",
      body["summary"] == "פגישת מכירה - דירה 6 חד'" and A in body["description"]
      and "מחפש 6 חדרים" in body["description"] and body["location"] == ST["place"])
check("באירוע: שעון ישראל, שעה אחת",
      body["start"]["timeZone"] == "Asia/Jerusalem"
      and body["end"]["dateTime"].startswith("2026-09-13T13:00"))
RENTAL_TOURS = os.path.join(ROOT, "..", "rental-leads", "src", "calendar_tours.py")
if os.path.exists(RENTAL_TOURS):
    # רק כשסוכן השכרה קובע באותו יומן (אצל דני). בגרסת הקורס אין אותו
    spec = importlib.util.spec_from_file_location("rental_calendar_tours", RENTAL_TOURS)
    rental = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rental)
    check("סוכן ההשכרה לא מזהה פגישת מכירה כסיור שלו (לא ישלח לקונה תזכורת)",
          not rental._is_tour(body))
    check("צבע אחר מסיורי ההשכרה", body["colorId"] != rental.TOUR_COLOR)


# ---- הקביעה עצמה, מול יומן מדומה ----
class _Call:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeSvc:
    """freebusy ו-events.insert, בזיכרון."""

    def __init__(self, busy=(), fail=False):
        self.busy_list, self.fail, self.inserted = list(busy), fail, []

    def freebusy(self):
        return self

    def query(self, body):
        lo = datetime.fromisoformat(body["timeMin"])
        hi = datetime.fromisoformat(body["timeMax"])
        return _Call(lambda: {"calendars": {cm.CAL: {"busy": [
            {"start": a.isoformat(), "end": b.isoformat()}
            for a, b in self.busy_list if a < hi and b > lo]}}})

    def events(self):
        return self

    def insert(self, calendarId, body):
        def go():
            if self.fail:
                raise RuntimeError("503 בדיקה")
            self.inserted.append(body)
            return {"id": "ev1", "htmlLink": "https://calendar/ev1"}
        return _Call(go)


svc = FakeSvc()
status, info = cm.book(ST, at(SUN, 12), card, "x", svc=svc)
check("פנוי ← נכנס ליומן", status == "ok" and info["id"] == "ev1" and len(svc.inserted) == 1)
svc = FakeSvc(busy=[(at(SUN, 12, 30), at(SUN, 13))])
check("הסוכן השני תפס את השעה בינתיים ← taken, ולא נכנס",
      cm.book(ST, at(SUN, 12), card, "x", svc=svc)[0] == "taken" and not svc.inserted)
check("מחוץ לשעות ← invalid, בלי לפנות ליומן", cm.book(ST, at(SUN, 16), card, "x")[0] == "invalid")
check("היומן נכשל ← error", cm.book(ST, at(SUN, 12), card, "x", svc=FakeSvc(fail=True))[0] == "error")

# ---- הבדיקות במנוע ----
good = {"reply": "אפשר ביום ראשון 13/9 ב-12:00 או ביום שני 14/9 ב-10:00 - מה מתאים?"}
check("מנוע: מועדים מהרשימה ← תקין", "slot_times" not in engine.violations(good, "", SLOTS))
check("מנוע: השעות הכלליות (10:00-16:30) ← נתפס",
      "slot_times" in engine.violations({"reply": "יש לי פתוח א'-ה' 10:00-16:30"}, "", SLOTS))
check("מנוע: book_slot שלא מהרשימה ← נתפס",
      "slot_unknown" in engine.violations({"reply": "x", "book_slot": at(SUN, 17).isoformat()},
                                          "", SLOTS))
check("מנוע: book_slot מהרשימה ← תקין",
      "slot_unknown" not in engine.violations(
          {"reply": "x", "book_slot": SLOTS[0]["start"].isoformat()}, "", SLOTS))

# חריגים במועד - על תשובות אמיתיות של המודל מ-12-09 (לקח L-1: הבדיקה נבדקת קודם בלי מודל)
FRI = ("יום שישי הפגישות רק בבוקר עד 12:30. אפשר ביום ראשון ב-13:00 או ביום שני ב-10:00 - "
       "מה מתאים?")
check("מנוע: שישי 13:00 - הציע חלופות בלי העברה ← נתפס",
      "outside_no_handoff" in engine.violations(
          {"reply": FRI, "requested_time": "outside"}, "", SLOTS, "אפשר ביום שישי ב-13:00?"))
EVE = ("שעות הסיורים הן עד 16:30 בימי ראשון-חמישי ועד 12:30 בשישי. אני בודק מול דני אם "
       "אפשר לארגן סיור ב-19:00 ויחזור אליך.")
check("מנוע: 19:00 - בודק מול דני, עם העברה ← תקין, והשעות בהסבר לא נתפסות",
      not engine.violations({"reply": EVE, "requested_time": "outside", "handoff": "מחוץ לשעות"},
                            "", SLOTS, "אני יכול רק ב-19:00. אפשר?"))
check("מנוע: ערב - 'אחרי 16:30 אין', מציע שישי, בלי העברה (declined) ← תקין",
      not engine.violations(
          {"reply": "זה אתר בנייה, אחרי 16:30 אין סיורים. אפשר ביום שני ב-10:00 - מה מתאים?",
           "requested_time": "declined"}, "", SLOTS, "אפשר ב-19:00?"))
check("מנוע: שעה שהליד עצמו כתב (10:30 לא פנוי) ← לא נתפסת",
      "slot_times" not in engine.violations(
          {"reply": "10:30 לא פנוי. אפשר ביום ראשון ב-12:00 או ביום שני ב-10:00 - מה מתאים?",
           "requested_time": "inside"}, "", SLOTS, "אפשר ב-10:30?"))
check("מנוע: 'יחזור אליך' והזמן במשפט הבא (תשובה אמיתית מההשכרה, 12-09) ← נתפס",
      "callback_time" in engine.violations(
          {"reply": "דני יחזור אליך ישירות עם הפרטים - מחיר ותנאים. תוך כמה שעות.",
           "handoff": "רוצה לקנות"}))
check("מנוע: 'אני בודק מול דני ואחזור אליך' ואז 'בשעה 13:00' ← לא נתפס",
      "callback_time" not in engine.violations(
          {"reply": "אני בודק מול דני ואחזור אליך. אפשר גם ביום ראשון בשעה 13:00",
           "handoff": "חריג"}))

PROMPTS = []


class _FakeMessages:
    def create(self, **kw):
        PROMPTS.append(kw["messages"][0]["content"])
        block = type("B", (), {"type": "text", "text": '{"reply": "x"}'})()
        return type("R", (), {"content": [block]})()


engine._client = lambda: type("C", (), {"messages": _FakeMessages()})()
engine.think(TEXT, card, "מתי אפשר?", slots=SLOTS[:2])
check("מנוע: המועדים וה-ISO שלהם מגיעים בהקשר",
      "מועדים פנויים לפגישה" in PROMPTS[-1] and SLOTS[0]["start"].isoformat() in PROMPTS[-1])
engine.think(TEXT, card, "מתי אפשר?")
check("מנוע: מוצר בלי יומן ← אין רשימת מועדים", "מועדים פנויים לפגישה" not in PROMPTS[-1])
engine.think(TEXT, dict(card, meeting={"label": "יום ראשון 13/9 בשעה 12:00"}), "אפשר להזיז?",
             slots=SLOTS)
check("מנוע: פגישה שכבר נקבעה מופיעה בתיק הליד",
      "פגישה שכבר נקבעה: יום ראשון 13/9 בשעה 12:00" in PROMPTS[-1])

# ---- הזרימה המלאה ב-run.handle ----
CHATS, SENT, NEXT, SEEN, BOOKED, LOGS = {}, [], [], [], [], []
FREE_QUEUE = []   # מה free_slots תחזיר, לפי הסדר. ריק ← SLOTS
RESULT = [("ok", {"id": "ev9", "link": "https://calendar/ev9"})]


def fake_free(st, now=None):
    r = FREE_QUEUE.pop(0) if FREE_QUEUE else SLOTS
    if isinstance(r, Exception):
        raise r
    return list(r)


def fake_book(st, start, card, product_name, svc=None):
    BOOKED.append(start)
    return RESULT[0]


def fake_think(product, lead, incoming, slots=None, **_):
    SEEN.append(slots)
    out = {"reply": "תשובת בדיקה", "stage": "talking", "missing_fact": None, "handoff": None,
           "handoff_urgent": False, "other_product": None, "book_slot": None, "note": None}
    out.update(NEXT.pop(0) if NEXT else {})
    return out, []


def fake_chat(chat_id, count=20):
    ms = sorted(CHATS.get(chat_id, []), key=lambda m: -m["timestamp"])
    return ms[:count], len(ms)


def fake_send(to, body):
    SENT.append((to, body))
    return True, {"message": {"id": "fake", "status": "sent"}}


def no_network(*a, **k):
    raise AssertionError("קריאה לרשת שלא הוחלפה")


run.whapi.chat_messages = fake_chat
run.whapi.send_text = fake_send
run.whapi.health = lambda: (True, "AUTH")
run.whapi.fetch_messages = no_network
run.engine.think_checked = fake_think
cm.free_slots = fake_free
cm.book = fake_book
cm.heal = lambda *a, **k: []
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


def last_to(phone):
    return next((b for t, b in reversed(SENT) if t == phone), "")


FIRST = SLOTS[0]["start"].isoformat()

# A: מציע ← בוחר ← נקבע ← מבקש להזיז
NEXT.append({"reply": "אפשר ביום ראשון 13/9 ב-12:00 או ביום שני 14/9 ב-10:00 - מה מתאים?"})
run.handle(msg(A, SALES, 0), P, dry=False)
check("A: המנוע קיבל את המועדים מהיומן", SEEN[-1] == SLOTS)
check("A: בלי בחירה ← לא נקבע כלום", not BOOKED and not cards.get(A).get("meeting"))
NEXT.append({"reply": "קבעתי - יום ראשון 13/9 ב-12:00, משרד המכירות.", "book_slot": FIRST})
run.handle(msg(A, "ראשון ב-12 מתאים", 60), P, dry=False)
c = cards.get(A)
check("A: הליד בחר ← נקבע ביומן במועד שבחר", BOOKED == [SLOTS[0]["start"]])
check("A: בכרטיס - הפגישה והשלב",
      c.get("meeting", {}).get("label") == SLOTS[0]["label"] and c["stage"] == "meeting_set"
      and c["meeting"]["event_id"] == "ev9")
check("A: הליד קיבל את האישור של המנוע", last_to(A).startswith("קבעתי"))
NEXT.append({"reply": "קבעתי לשני", "book_slot": SLOTS[3]["start"].isoformat()})
run.handle(msg(A, "אפשר להזיז לשני?", 120), P, dry=False)
c = cards.get(A)
check("A: יש כבר פגישה ← לא קובעים שנייה, ודני מקבל העברה מיידית",
      len(BOOKED) == 1 and "דני מאשר" in last_to(A) and c["handoffs"][-1]["urgent"]
      and "לשנות" in c["handoffs"][-1]["reason"])
check("A: ההודעה לדני כוללת את הפגישה",
      f"פגישה ביומן: {SLOTS[0]['label']}" in notify.urgent_message(c, c["handoffs"][-1:], P))

# B: המועד נתפס בינתיים
RESULT[0] = ("taken", "")
run.handle(msg(B, SALES, 0), P, dry=False)
NEXT.append({"reply": "קבעתי", "book_slot": FIRST})
FREE_QUEUE[:] = [SLOTS, SLOTS[1:]]
run.handle(msg(B, "ראשון ב-12", 60), P, dry=False)
check("B: נתפס בינתיים ← בלי 'קבעתי', ושני מועדים אחרים בימים שונים",
      not cards.get(B).get("meeting") and last_to(B)
      == f"המועד הזה כבר לא פנוי. אפשר ב{SLOTS[1]['label']} או ב{SLOTS[3]['label']} - מה מתאים?")

# C: היומן נכשל בקביעה
RESULT[0] = ("error", "503")
run.handle(msg(C, SALES, 0), P, dry=False)
NEXT.append({"reply": "קבעתי", "book_slot": FIRST})
run.handle(msg(C, "ראשון ב-12", 60), P, dry=False)
c = cards.get(C)
check("C: היומן נכשל ← 'לא נכנס ליומן', והעברה מיידית לדני",
      last_to(C).startswith("רגע - המועד הזה לא נכנס ליומן") and c["handoffs"][-1]["urgent"]
      and not c.get("meeting"))

# D: המנוע החזיר מועד שלא הוצע
RESULT[0] = ("ok", {"id": "ev9", "link": "https://calendar/ev9"})
n = len(BOOKED)
run.handle(msg(D, SALES, 0), P, dry=False)
NEXT.append({"reply": "קבעתי ל-17:00", "book_slot": at(SUN, 17).isoformat()})
run.handle(msg(D, "אפשר ב-17?", 60), P, dry=False)
check("D: מועד שלא הוצע ← לא נקבע, ומציעים מהרשימה",
      len(BOOKED) == n and last_to(D).startswith("המועד הזה כבר לא פנוי. אפשר ב"))

# E: נתפס, ואין שום מועד אחר
RESULT[0] = ("taken", "")
run.handle(msg(E, SALES, 0), P, dry=False)
NEXT.append({"reply": "קבעתי", "book_slot": FIRST})
FREE_QUEUE[:] = [SLOTS, []]
run.handle(msg(E, "ראשון ב-12", 60), P, dry=False)
check("E: אין שום מועד פנוי ← 'אני בודק מול דני', והעברה מיידית",
      "אני בודק מול דני" in last_to(E) and cards.get(E)["handoffs"][-1]["urgent"])

# F: היומן לא זמין, ויבש
FREE_QUEUE[:] = [RuntimeError("היומן לא זמין")]
run.handle(msg(F, SALES, 0), P, dry=False)
check("F: היומן לא זמין ← המנוע מקבל רשימה ריקה, והליד עדיין נענה",
      SEEN[-1] == [] and last_to(F))
n = len(BOOKED)
NEXT.append({"reply": "קבעתי", "book_slot": FIRST})
run.handle(msg(F, "ראשון ב-12", 60), P, dry=True)
check("יבש: לא קובעים ביומן", len(BOOKED) == n)

# ---- הסיכום היומי ----
text, _ = notify.summary_message(P, run.allowed, datetime.now(IL) - timedelta(days=1),
                                 datetime.now(IL) + timedelta(minutes=1))
check("בסיכום היומי: הפגישה שנקבעה", "פגישות שנקבעו: 1" in text and SLOTS[0]["label"] in text)

shutil.rmtree(TMP, ignore_errors=True)
failed = [n for n, ok in RESULTS if not ok]
for name, ok in RESULTS:
    print(f"{'✅' if ok else '❌'} {name}")
print(f"\n{len(RESULTS) - len(failed)} מתוך {len(RESULTS)} עברו")
sys.exit(1 if failed else 0)
