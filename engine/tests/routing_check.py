"""בדיקת הניתוב וכרטיס הליד - בלי Whapi ובלי מודל.

כל קריאה לרשת מוחלפת לפני שהקוד רץ: וואטסאפ מדומה (שיחות בזיכרון) ומוח מדומה
(תשובה קבועה). הנתונים נכתבים לתיקייה זמנית ונמחקים בסוף.

הרצה:  python tests/routing_check.py
"""
import os
import shutil
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="master-routing-")

OWNER = "972500000099"
A, B, C, D, F, G, H, J, K = (f"97250000000{i}" for i in range(1, 10))
L, M, N, O, Q, R, S = (f"97250000002{i}" for i in range(7))
NOT_LISTED = "972500000077"
NOT_LISTED2 = "972500000078"
# לפני ה-import. load_dotenv לא דורס משתנה שכבר קיים, אז המפתחות של ההשכרה לא נוגעים כאן
os.environ.update({
    "DATA_DIR": TMP, "MODE": "test", "PRODUCTS": "demo-project-sales.test",
    "OTHER_AGENT_KEYWORDS": "לפרטים על דירה להשכרה", "OWNER_PHONE": OWNER, "OWNER_KEYWORDS": "AI",
    "TEST_WHITELIST": ",".join([A, B, C, D, F, G, H, J, K, L, M, N, O, Q, R, S, OWNER]),
    # ההעברות לדני נבדקות ב-notify_check.py. כאן - מספר נפרד, והסיכום היומי כבוי
    "NOAM_PHONE": "972500000088", "SUMMARY_AT": "off",
})
sys.path.insert(0, os.path.join(ROOT, "src"))

import cards    # noqa: E402
import router   # noqa: E402
import run      # noqa: E402

# משפטי הטריגר שדני הציע לקמפיינים (12-09)
SALES = "הי אשמח לפרטים על רכישת דירה 6 חד'"
RENTAL = "הי, אשמח לפרטים על דירה להשכרה"
PRODUCT = "demo-project-sales"

# ---- וואטסאפ ומוח מדומים ----
CHATS, SENT, CHAT_CALLS, THOUGHT, LOGS = {}, [], [], [], []


def fake_chat_messages(chat_id, count=20):
    CHAT_CALLS.append(chat_id)
    ms = sorted(CHATS.get(chat_id, []), key=lambda m: -m["timestamp"])
    return ms[:count], len(ms)


def fake_send(to, body):
    SENT.append((to, body))
    return True, {"message": {"id": "fake", "status": "sent"}}


def fake_think(product, lead, incoming, slots=None, **_):
    THOUGHT.append(incoming)
    return {"reply": "תשובת בדיקה", "stage": "talking", "missing_fact": None,
            "handoff": None, "handoff_urgent": False, "other_product": None,
            "note": None}, []


def no_network(*a, **k):
    raise AssertionError("קריאה לרשת שלא הוחלפה")


run.whapi.chat_messages = fake_chat_messages
run.whapi.send_text = fake_send
run.whapi.health = lambda: (True, "AUTH")
run.whapi.fetch_messages = no_network
run.engine.think_checked = fake_think
# היומן נבדק ב-calendar_check.py. כאן - בלי יומן
run.calendar_meetings.free_slots = lambda st, now=None: []
run.calendar_meetings.heal = lambda *a, **k: []
run.log = LOGS.append
run.notify.log = LOGS.append

T0 = int(time.time()) - 3600
_n = [0]


def msg(phone, text, dt):
    """הודעה נכנסת, שנרשמת גם בשיחה המדומה."""
    _n[0] += 1
    m = {"id": f"m{_n[0]}", "phone": phone, "name": "", "text": text,
         "ts": T0 + dt, "chat_id": f"{phone}@s.whatsapp.net"}
    CHATS.setdefault(m["chat_id"], []).append(
        {"id": m["id"], "timestamp": m["ts"], "from_me": False, "text": {"body": text}})
    return m


def answered_by_other_agent(phone, dt):
    _n[0] += 1
    CHATS.setdefault(f"{phone}@s.whatsapp.net", []).append(
        {"id": f"r{_n[0]}", "timestamp": T0 + dt, "from_me": True})


def sent_to(phone):
    return len([s for s in SENT if s[0] == phone])


RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))


P = run.load_products()

# ---- הכללים עצמם ----
check("המילה נקראה מקובץ הבדיקה", P[PRODUCT]["keyword"] == "לפרטים על רכישת")
check("מוצר בכרטיס - בלי .test", list(P) == [PRODUCT])
check("ניקוד, פסיק ורווח כפול לא מפריעים",
      router.hits("הָי, אשמח לפרטים,  על רכישת דירה", "לפרטים על רכישת"))
check("משפט ההשכרה לא נתפס כמכירה, ולהפך",
      not router.hits(RENTAL, "לפרטים על רכישת") and not router.hits(SALES, "לפרטים על דירה להשכרה"))
check("מה שאחרי המילה - דירה", router.after_keyword(SALES, "לפרטים על רכישת") == "דירה 6 חד'")
check("מה שאחרי המילה - פנטהאוז",
      router.after_keyword("הי, אשמח לפרטים על רכישת פנטהאוז!", "לפרטים על רכישת") == "פנטהאוז")
check("אין כלום אחרי המילה ← ריק", router.after_keyword(RENTAL, "לפרטים על דירה להשכרה") == "")
check("מילה ריקה לא תופסת כלום", not router.hits("כל טקסט", ""))
KW = ["לפרטים על רכישת", "לפרטים על דירה להשכרה"]


def from_lead(i, ts, body=""):
    return {"id": i, "timestamp": ts, "from_me": False, "text": {"body": body}}


def from_number(i, ts, body="שלום, אני עובד עם דני ממגדלי הדוגמה"):
    return {"id": i, "timestamp": ts, "from_me": True, "text": {"body": body}}


def free(chat, ts, reset=None):
    return router.claimable(chat, len(chat), {"a"}, ts, reset, KW)


check("שיחה ריקה - פנויה", free([from_lead("a", 100)], 100))
check("תשובה קודמת שיצאה מהמספר - תפוסה",
      not free([from_lead("a", 100), from_number("b", 50)], 100))
check("הודעה קודמת של הליד בלי מילה - לא תופסת (13-09)",
      free([from_lead("a", 100), from_lead("b", 50, "אשמח לפרטים על 6 חדרים")], 100))
check("הודעה קודמת של הליד עם מילת טריגר - תופסת",
      not free([from_lead("a", 100), from_lead("b", 50, RENTAL)], 100))
check("🔔 וסיכום ☀️ לדני באותה שיחה (בודק מהנייד שלו) - לא תופסים",
      free([from_lead("a", 100), from_number("b", 60, "🔔 לטיפול שלך עכשיו - 050-0000003"),
            from_number("c", 70, "☀️ סיכום מאז 12/09 08:30")], 100))
check("תמונה שיצאה מהמספר (בלי טקסט) - תופסת",
      not free([from_lead("a", 100), {"id": "b", "timestamp": 50, "from_me": True,
                                      "type": "image"}], 100))
check("הודעה מלפני איפוס - לא נחשבת",
      free([from_lead("a", 1000), from_number("b", 50)], 1000, reset=500))
check("האישור על האיפוס (דקה אחריו) - לא נחשב",
      free([from_lead("a", 1000), from_number("ack", 560, "הכרטיס שלך אופס")], 1000, reset=500))
check("תשובה אחרי האיפוס - נחשבת",
      not free([from_lead("a", 1000), from_number("b", 900)], 1000, reset=500))
check("איפוס שקרה אחרי ההודעה שבתור - לא חל עליה",
      not free([from_lead("a", 400), from_number("b", 50)], 400, reset=500))
check("יש הודעות ישנות מעבר למה שנשלף - תפוסה",
      not router.claimable([from_lead("a", 100)], 30, {"a"}, 100, None, KW))

# ---- A: ליד מכירה ----
run.handle(msg(A, SALES, 0), P, dry=False)
card = cards.get(A)
check("A: הודעה ראשונה עם מילת המכירה ← כרטיס עם product", card and card["product"] == PRODUCT)
check("A: חותמת ההודעה הראשונה נשמרה בכרטיס", card and card["first_message_at"])
check("A: על מה המודעה - נשמר בכרטיס", card and card["profile"].get("from_ad") == "דירה 6 חד'")
check("A: נשלחה תשובה אחת", sent_to(A) == 1)
a2 = msg(A, "כמה עולה דירת 5 חדרים?", 120)
run.handle(a2, P, dry=False)
check("A: הודעה שנייה בלי המילה ← עדיין מכירה, ונענתה",
      cards.get(A)["product"] == PRODUCT and sent_to(A) == 2)
run.handle(a2, P, dry=False)
check("A: אותה הודעה פעמיים ← תשובה אחת", sent_to(A) == 2)
run.handle(msg(A, "כמה אפשר לקבל על השכרה של דירה כזאת?", 180), P, dry=False)
check("A: משקיע ששואל על השכרה (לא במשפט של הקמפיין) ← נשאר במכירה, בלי העברה",
      cards.get(A)["handoffs"] == [] and sent_to(A) == 3)
run.handle(msg(A, RENTAL, 240), P, dry=False)
card = cards.get(A)
check("A: מילת ההשכרה באמצע שיחת מכירה ← העברה לדני, והמוצר לא משתנה",
      card["product"] == PRODUCT and [h["kind"] for h in card["handoffs"]] == ["other_product"])

# ---- B: ליד השכרה - לא שלנו ----
calls = len(CHAT_CALLS)
run.handle(msg(B, RENTAL, 0), P, dry=False)
check("B: מילת ההשכרה ← לא נוגעים, ובלי לפנות ל-Whapi",
      cards.get(B) is None and len(CHAT_CALLS) == calls and sent_to(B) == 0)
answered_by_other_agent(B, 20)
run.handle(msg(B, "יש חניה?", 60), P, dry=False)
check("B: המשך שיחת השכרה בלי מילה ← לא שלנו", cards.get(B) is None and sent_to(B) == 0)
run.handle(msg(B, SALES, 120), P, dry=False)
check("B: שוכר שכותב אחר כך את מילת המכירה ← לא פותחים כרטיס",
      cards.get(B) is None and sent_to(B) == 0)

# ---- C: בלי מילה ובלי רמז - פתיחה (דני, 14-09) ----


def opener_in_chat(phone, dt):
    """הפתיחה כפי ש-Whapi מחזיר אותה אחר כך - הודעה שיצאה מהמספר."""
    _n[0] += 1
    CHATS.setdefault(f"{phone}@s.whatsapp.net", []).append(
        {"id": f"o{_n[0]}", "timestamp": T0 + dt, "from_me": True, "text": {"body": run.OPENER}})


check("הפתיחה - בנוסח של דני", run.OPENER == "שלום,\nפנית אלינו למגדלי הדוגמה - כיצד אפשר לסייע?")
check("הפתיחה שיצאה מהמספר - לא תופסת את השיחה (14-09)",
      free([from_lead("a", 100), from_number("b", 50, run.OPENER)], 100))
thought = len(THOUGHT)
run.handle(msg(C, "היי, ראיתי מודעה", 0), P, dry=False)
card = cards.get(C)
check("C: הודעה ראשונה בלי מילה ובלי רמז ← פתיחה, בלי מודל ובלי 🔔 (דני, '1')",
      card and card["product"] is None and card["stage"] == "opened"
      and SENT[-1] == (C, run.OPENER) and not card["handoffs"] and len(THOUGHT) == thought)
opener_in_chat(C, 10)
run.handle(msg(C, "מה יש לכם?", 60), P, dry=False)
card = cards.get(C)
check("C: ענה משהו לא ברור ← סוכן המכירה ממשיך בעצמו ('חתירה למטרה'), עם כל מה שנאמר",
      card["product"] == PRODUCT and sent_to(C) == 2 and len(THOUGHT) == thought + 1
      and [t["text"] for t in card["history"][:3]] == ["היי, ראיתי מודעה", run.OPENER, "מה יש לכם?"])

# ---- R: כרטיס מלפני הכלל (נכנס בלי מילה, אצל דני) ----
legacy = cards.new(R, "", None, T0)
cards.add_turn(legacy, "lead", "היי, ראיתי מודעה")
cards.save(legacy)
msg(R, "היי, ראיתי מודעה", 0)
run.handle(msg(R, "?", 60), P, dry=False)
check("R: כרטיס ישן בלי מוצר, ותשובה לא ברורה ← נשאר אצל דני",
      cards.get(R)["product"] is None and sent_to(R) == 0)
run.handle(msg(R, SALES, 120), P, dry=False)
card = cards.get(R)
check("R: אחר כך כתב את משפט המכירה, ואף אחד לא ענה לו ← הסוכן לוקח ועונה (13-09)",
      card["product"] == PRODUCT and sent_to(R) == 1 and card["profile"].get("from_ad") == "דירה 6 חד'"
      and card["history"][0]["text"] == "היי, ראיתי מודעה")

# ---- D: שתי מילים ----
run.handle(msg(D, "הי, אשמח לפרטים על רכישת דירה או לפרטים על דירה להשכרה", 0), P, dry=False)
card = cards.get(D)
check("D: שתי מילות טריגר ← לדני, לא לסוכן", card and card["product"] is None
      and "שתי" in card["handoffs"][0]["reason"] and sent_to(D) == 0)
run.handle(msg(D, SALES, 60), P, dry=False)
check("D: פתח בשתי מילים, ואחר כך רק המכירה ← נשאר אצל דני",
      cards.get(D)["product"] is None and sent_to(D) == 0)

# ---- J, K: קיבל פתיחה, ואחר כך - לא לוקחים ----
run.handle(msg(J, "שלום", 0), P, dry=False)
answered_by_other_agent(J, 30)   # דני ענה לו ידנית מהמספר
run.handle(msg(J, SALES, 60), P, dry=False)
run.handle(msg(J, "אוקיי", 90), P, dry=False)
check("J: קיבל פתיחה, ודני ענה לו ידנית ← הסוכן לא לוקח, גם לא עם משפט המכירה",
      cards.get(J)["product"] is None and sent_to(J) == 1)
run.handle(msg(K, "שלום", 0), P, dry=False)
opener_in_chat(K, 10)
run.handle(msg(K, RENTAL, 60), P, dry=False)
check("K: קיבל פתיחה, ואחר כך משפט ההשכרה ← המנוע לא לוקח (סוכן ההשכרה כן)",
      cards.get(K)["product"] is None and sent_to(K) == 1)

# ---- L-S: מה הליד רוצה, גם בלי משפט הטריגר (דני, 14-09) ----
run.handle(msg(L, "שלום, אני מחפש לקנות דירה במגדלי הדוגמה", 0), P, dry=False)
check("L: 'לקנות' בלי משפט הטריגר ← ליד מכירה מיד, בלי פתיחה",
      (cards.get(L) or {}).get("product") == PRODUCT and SENT[-1] == (L, "תשובת בדיקה"))
run.handle(msg(M, "היי, מחפשת דירה להשכרה בפארק", 0), P, dry=False)
check("M: 'להשכרה' בלי משפט הטריגר ← של סוכן ההשכרה: בלי כרטיס ובלי תשובה",
      cards.get(M) is None and sent_to(M) == 0)
run.handle(msg(N, "מה המחירים? לקנות או לשכור", 0), P, dry=False)
check("N: גם קנייה וגם השכרה ← סוכן המכירה לוקח",
      (cards.get(N) or {}).get("product") == PRODUCT and sent_to(N) == 1)
run.handle(msg(O, "שלום", 0), P, dry=False)
opener_in_chat(O, 10)
run.handle(msg(O, "אני מחפש שכירות לשנה", 60), P, dry=False)
check("O: קיבל פתיחה וענה 'שכירות' ← המנוע מדלג (סוכן ההשכרה לוקח)",
      cards.get(O)["product"] is None and sent_to(O) == 1)
run.handle(msg(Q, "👍", 0), P, dry=False)
opener_in_chat(Q, 10)
run.handle(msg(Q, "רוצה לרכוש 5 חדרים", 60), P, dry=False)
check("Q: קיבל פתיחה וענה 'לרכוש' ← סוכן המכירה לוקח ועונה",
      cards.get(Q)["product"] == PRODUCT and sent_to(Q) == 2 and cards.get(Q)["stage"] != "opened")
run.handle(msg(NOT_LISTED2, "שלום", 0), P, dry=False)
check("מצב בדיקה: בלי מילה, ולא ברשימה ← נרשם, בלי פתיחה",
      cards.get(NOT_LISTED2) and sent_to(NOT_LISTED2) == 0)
run.handle(msg(S, "שלום", 0), P, dry=True)
check("יבש: בלי מילה ← בלי פתיחה ובלי כרטיס", cards.get(S) is None and sent_to(S) == 0)
real_send, run.whapi.send_text = run.whapi.send_text, lambda to, body: (False, "HTTP 500")
run.handle(msg(S, "שלום", 100), P, dry=False)
run.whapi.send_text = real_send
card = cards.get(S)
check("הפתיחה לא נשלחה ← העברה מיידית לדני",
      card and card["stage"] == "no_keyword" and card["handoffs"][-1]["urgent"])

# ---- F: בודק עם היסטוריה ישנה, אחרי AI אפס ----
msg(F, RENTAL, -5000)
answered_by_other_agent(F, -4990)
run.handle(msg(OWNER, "AI אפס 050-000-0005", 0), P, dry=False)
answered_by_other_agent(OWNER, 30)
check("F: פקודת האיפוס לא נענית ע\"י המנוע (סוכן ההשכרה מאשר)", sent_to(OWNER) == 0)
run.handle(msg(F, SALES, 400), P, dry=False)
check("F: אחרי איפוס, מילת המכירה ← כרטיס מכירה חדש",
      (cards.get(F) or {}).get("product") == PRODUCT and sent_to(F) == 1)
run.handle(msg(OWNER, "אפס AI 050-000-0005", 450), P, dry=False)
check("F: 'אפס AI' - הפקודה הפוכה (13-09) ← גם מאפסת, בשקט",
      cards.get(F) is None and cards.reset_at(F) == T0 + 450 and sent_to(OWNER) == 0)
run.handle(msg(OWNER, "AI תזכיר לי לבדוק את המלאי", 500), P, dry=False)
check("פתק של דני (לא איפוס) ← לא ליד, לא נענה", cards.get(OWNER) is None and sent_to(OWNER) == 0)
# 13-09: Whapi שלח מחדש את כל ההיסטוריה עם חותמות חדשות, ו-"AI אפס" ישנות רצו שוב
again = msg(OWNER, "AI אפס 050-000-0005", 600)
run.handle(again, P, dry=False)
run.handle(msg(F, SALES, 900), P, dry=False)
run.handle(again, P, dry=False)
check("F: אותה פקודת איפוס שוב (אותו מזהה) ← לא מתבצעת שוב, והכרטיס החדש נשאר",
      (cards.get(F) or {}).get("product") == PRODUCT and any("כבר בוצעה" in line for line in LOGS))

# ---- G: לא ברשימה הלבנה ----
thought = len(THOUGHT)
run.handle(msg(NOT_LISTED, SALES, 0), P, dry=False)
card = cards.get(NOT_LISTED)
check("מצב בדיקה: ליד שלא ברשימה ← נרשם עם המוצר, לא נענה ולא נשלח למודל",
      card and card["product"] == PRODUCT and sent_to(NOT_LISTED) == 0
      and len(THOUGHT) == thought)

# ---- H: סבב שלם - שתי הודעות ברצף, תשובה אחת ----
feed = [msg(H, SALES, 3000), msg(H, "יש גם 4 חדרים?", 3004)]
run.whapi.fetch_messages = lambda limit=50: list(feed)
thought = len(THOUGHT)
run.cycle(dry=False)
check("H: שתי הודעות ברצף ← תור אחד ותשובה אחת, עם שתיהן",
      sent_to(H) == 1 and len(THOUGHT) == thought + 1 and "4 חדרים" in THOUGHT[-1])
check("H: סימן המים התקדם", cards.watermark() == feed[-1]["ts"])
run.cycle(dry=False)
check("H: סבב נוסף על אותן הודעות ← לא עונים שוב", sent_to(H) == 1)

# ---- ליד שלא נעלם בשקט (פריט 24 של המוח, דני: "3", 14-09) ----
SEQ = []


def seq_think(product, lead, incoming, slots=None, **_):
    step = SEQ.pop(0)
    if step == "boom":
        raise RuntimeError("API down")
    if step == "empty":
        return {}, []
    return fake_think(product, lead, incoming, slots)


run.engine.think_checked = seq_think
SEQ[:] = ["empty", "ok"]
before = len(cards.get(A)["handoffs"])
run.handle(msg(A, "יש מחסן לכל דירה?", 5000), P, dry=False)
check("A: תשובה ריקה, ואז תקינה ← ניסיון חוזר אחד, והליד מקבל את התשובה, בלי העברה",
      SENT[-1] == (A, "תשובת בדיקה") and len(cards.get(A)["handoffs"]) == before and not SEQ)
SEQ[:] = ["empty", "empty"]
run.handle(msg(A, "ומה עם חניה?", 5100), P, dry=False)
card = cards.get(A)
check("A: פעמיים תשובה ריקה ← הודעה קבועה לליד, והעברה מיידית לדני עם ההודעה שלו",
      SENT[-1] == (A, run.FALLBACK_REPLY) and card["handoffs"][-1]["urgent"]
      and "ומה עם חניה" in card["handoffs"][-1]["reason"] and card["history"][-1]["text"] == run.FALLBACK_REPLY)
SEQ[:] = ["boom", "boom"]
run.handle(msg(A, "הלו?", 5200), P, dry=False)
check("A: הקריאה למודל נופלת פעמיים (חריגה) ← לא אובד: הודעה קבועה והעברה, עם סוג השגיאה",
      SENT[-1] == (A, run.FALLBACK_REPLY) and "RuntimeError" in cards.get(A)["handoffs"][-1]["reason"])
run.engine.think_checked = fake_think

# ---- השער ----
run.MODE = "live"
ok, why = run.gate_live(P)
run.MODE = "test"
check("השער: מצב חי עם קובץ בדיקה ← נחסם", not ok and ".test" in why)

# ---- יבש לא שומר, אבל איפוס חל בתוך אותו סבב ----
run.handle(msg(G, SALES, 0), P, dry=True)
check("יבש: לא נשלח ולא נשמר כרטיס", sent_to(G) == 0 and cards.get(G) is None)
answered_by_other_agent(G, 10)
run.handle(msg(OWNER, "AI אפס 050-000-0006", 600), P, dry=True)
thought = len(THOUGHT)
run.handle(msg(G, SALES, 1000), P, dry=True)
check("יבש: איפוס חל על ההודעה שאחריו באותו סבב, בלי לשמור לדיסק",
      len(THOUGHT) == thought + 1 and cards.reset_at(G) is None and sent_to(G) == 0)

# ---- מה שהמודעה ביקשה מגיע למנוע בכל הודעה - בלי מודל: הלקוח מוחלף ותופס את הפרומפט ----
PROMPTS = []


class _FakeMessages:
    def create(self, **kw):
        PROMPTS.append(kw["messages"][0]["content"])
        block = type("B", (), {"type": "text", "text": '{"reply": "x"}'})()
        return type("R", (), {"content": [block]})()


run.engine._client = lambda: type("C", (), {"messages": _FakeMessages()})()
run.engine.think(P[PRODUCT]["text"], cards.get(A), "כמה זה עולה?")
check("המנוע מקבל בכל הודעה על מה המודעה",
      PROMPTS and "ביקש בהודעה הראשונה, מהמודעה: דירה 6 חד'" in PROMPTS[-1])

shutil.rmtree(TMP, ignore_errors=True)
failed = [n for n, ok in RESULTS if not ok]
for n, ok in RESULTS:
    print(f"{'✅' if ok else '❌'} {n}")
print(f"\n{len(RESULTS) - len(failed)} מתוך {len(RESULTS)} עברו")
sys.exit(1 if failed else 0)
