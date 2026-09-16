"""כללי השיחה של 13-09 - בדיקות בקוד, זיכרון ומעקב "אחשוב על זה". בלי מודל ובלי Whapi.

המקרים - מהשיחה של דני מול הסוכן (שיחה מתועדת (לא בערכה)).
הרצה:  python tests/quality_check.py
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="master-quality-")
A = "972500000001"
os.environ.update({"DATA_DIR": TMP, "MODE": "test", "PRODUCTS": "demo-project-sales",
                   "SUMMARY_AT": "off", "NOAM_PHONE": "972500000088", "TEST_WHITELIST": A,
                   "OFFER_BLOCK": "השכרה,להשכרה,לשכור,שכירות,להשכיר"})
sys.path.insert(0, os.path.join(ROOT, "src"))

import cards    # noqa: E402
import engine   # noqa: E402
import run      # noqa: E402

P = engine.load_product("demo-project-sales")
RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))


def lead(*agent_texts):
    history = []
    for t in agent_texts:
        history += [{"who": "lead", "text": "..."}, {"who": "agent", "text": t}]
    return {"history": history}


def v(reply, incoming="", before=(), **out):
    return engine.violations({"reply": reply, **out}, P, None, incoming, lead(*before), run.OFFER_BLOCK)


INVITE = "מתי נוח לכם לבוא - השבוע או בשבוע הבא?"
OPEN6 = ("6 חדרים בקומות 9-11: 143 מ״ר בנוי + מרפסת 24 מ״ר. 2,450,000 ₪ - כולל מע״מ, 2 חניות ומחסן. "
         "הבניין כבר עומד. מסירה סביב ינואר 2027. " + INVITE)
COSTS = " המחיר כולל מע״מ, חניה ומחסן, ולא עולה עם המדד."

# ---- הזמנה לפגישה בכל הודעה ----
check("הזמנה שלישית ברצף, והליד כתב על משהו אחר ← meeting_repeat",
      "meeting_repeat" in v("יש חניה לכל דירה. מתי נוח לכם?", "יש חניה?", (INVITE, INVITE)))
check("הזמנה שנייה ברצף (תשובה מאושרת להתנגדות מסתיימת במועד) ← מותר",
      "meeting_repeat" not in v("לוח התשלומים נבנה מול כל קונה. מתי נוח לכם?", "עוד לא מכרנו", (INVITE,)))
check("הליד שאל מתי אפשר לבוא ← מותר",
      "meeting_repeat" not in v("אפשר ביום שני ב-10:00", "מתי אפשר לבוא?", (INVITE, INVITE)))

# ---- מסירה ----
check("מועד המסירה שוב, בלי שנשאל ← repeat_delivery",
      "repeat_delivery" in v("4 חדרים ב-1,850,000 ₪." + COSTS + " מסירה סביב ינואר 2027.",
                             "4 חדרים, אנחנו זוג צעיר", (OPEN6,)))
check("שאל למה 2027 ← מותר",
      "repeat_delivery" not in v("מסירה סביב ינואר 2027 - ממתינים לטופס 4.", "למה רק ב-2027?", (OPEN6,)))

# ---- השכרה לליד מכירה (דני, 13-09) ----
check("'מוצעות גם למכירה וגם להשכרה' (השיחה מהנייד, 17:01) ← offer_other",
      "offer_other" in v("בטח. הדירות האלה מוצעות גם למכירה וגם להשכרה - מה שיגיע קודם.",
                         "תן לי לחשוב על זה", (OPEN6,)))
check("הליד עצמו שאל על השכרה ← מותר",
      "offer_other" not in v("על השכרה דני יחזור אליך ישירות.", "יש גם להשכרה?", (OPEN6,),
                             other_product="השכרה"))

# ---- יקר ← יקר יותר ----
check("'יקר לי' ← דירה 58 ב-3,650,000 (השיחה מהנייד, 16:46) ← pricier",
      "pricier" in v("יש גם את דירה 58: 3,650,000 ₪." + COSTS, "מעניין אבל יקר לי",
                     ("6 חדרים - 2,450,000 ₪. קומה 12 - 2,550,000 ₪.",)))
check("פנטהאוז יקר ← 6 חדרים, זולה יותר ← מותר",
      "pricier" not in v("6 חדרים: 2,450,000 ₪." + COSTS, "יקר מדי בשבילנו", ("פנטהאוז: 4,150,000 ₪.",)))

# ---- ערב: declined, לא חריג (נמצא בהשוואה של 13-09) ----
check("'שלישי ב-19:00' סומן outside ← declined_not_outside",
      "declined_not_outside" in v("אני בודק מול דני.", "אפשר ביום שלישי ב-19:00?",
                                  requested_time="outside", handoff="מחוץ לשעות"))
check("'אפשר לבוא ב 19?' (בלי דקות, כמו בשיחה מהנייד) ← declined_not_outside",
      "declined_not_outside" in v("אני בודק מול דני.", "אפשר לבוא ב 19?", requested_time="outside",
                                  handoff="מחוץ לשעות"))
check("'שישי ב-13:00' - מחוץ לשעות, לא ערב ← חריג רגיל, בלי declined_not_outside",
      "declined_not_outside" not in v("אני בודק מול דני.", "אפשר בשישי ב-13:00?",
                                      requested_time="outside", handoff="מחוץ לשעות"))
check("ערב שסומן declined ← תקין",
      not {"declined_not_outside", "outside_no_handoff"} & set(
          v("זה אתר בנייה, אין אפשרות לשעה מאוחרת יותר.", "ב-19:00?", requested_time="declined")))

# ---- אישור רגשי ----
check("'מצוין,' בפתיחה (השיחה מהנייד, 14:41) ← praise",
      "praise" in v("מצוין, אז ה-6 חדרים מתאימה לך."))
check("'מצוין' באמצע משפט ← מותר", "praise" not in v("הדירה במיקום מצוין, על הפארק."))

# ---- מה כבר נאמר - לפרומפט ----
said = engine.already_said(lead(OPEN6, INVITE)["history"])
check("מה כבר נאמר: מחיר, מסירה, ו-2 הזמנות כולל האחרונה",
      "2,450,000 ₪" in said and "מועד המסירה" in said and "2 פעמים - כולל בהודעה האחרונה" in said)
check("שיחה בלי הודעות שלנו ← ריק", engine.already_said([{"who": "lead", "text": "היי"}]) == "")

# ---- "אחשוב על זה" ----
for s in ("תן לי לחשוב על זה", "אני יחשוב על זה", "נחשוב על זה ונחזור אליך", "צריך לחשוב"):
    check(f"'{s}' ← מעקב", engine.DEFER.search(s))
check("'חשוב לי מרפסת גדולה' ← לא מעקב", not engine.DEFER.search("חשוב לי מרפסת גדולה"))

IL = cards.IL


def at(y, mo, d, h, mi=0):
    got = datetime.fromtimestamp(run.follow_up_time(datetime(y, mo, d, h, mi, tzinfo=IL).timestamp()), IL)
    return got.strftime("%a %d/%m %H:%M")


# 13-09-2026 - יום ראשון
check("ראשון 17:00 ← רביעי 15:00 (שלישי 15:00 - פחות מ-48 שעות)", at(2026, 9, 13, 17) == "Wed 16/09 15:00")
check("ראשון 10:00 ← שלישי 15:00", at(2026, 9, 13, 10) == "Tue 15/09 15:00")
check("רביעי 10:00 ← שישי 15:00", at(2026, 9, 16, 10) == "Fri 18/09 15:00")
check("חמישי 10:00 ← לא שבת - ראשון 15:00", at(2026, 9, 17, 10) == "Sun 20/09 15:00")

# ---- learned ← כרטיס ----
card = {"profile": {}}
run.learn(card, {"budget": "סביב 2.5 מיליון", "objection": "יקר", "hack": "x"})
run.learn(card, {"objection": "לא מספיק מעניין", "rooms": None})
check("learned: תקציב נשמר, התנגדויות מצטברות, מפתח לא מוכר נזרק",
      card["profile"] == {"budget": "סביב 2.5 מיליון", "objection": "יקר · לא מספיק מעניין"})
run.learn(card, "לא מילון")
check("learned שאינו מילון ← לא נוגעים", card["profile"]["budget"] == "סביב 2.5 מיליון")

# ---- ניסוח המעקב - בלי מודל: הלקוח מוחלף ומחזיר תשובה קבועה ----
class _FakeMessages:
    def __init__(self, text):
        self.text = text

    def create(self, **kw):
        block = type("B", (), {"type": "text", "text": self.text})()
        return type("R", (), {"content": [block]})()


def fake_model(text):
    engine._client = lambda: type("C", (), {"messages": _FakeMessages(text)})()


fake_model('```json\n{"reply": "היי, חשבתם על ה-6 חדרים בקומות 9-11? מה החלטתם?"}\n```')
check("מעקב: שתי שאלות (נמצא 13-09) ← נשארת הראשונה, לא נוסח קבוע",
      engine.follow_up_message(P, {"history": []}) == "היי, חשבתם על ה-6 חדרים בקומות 9-11?")
fake_model('{"reply": ""}')
check("מעקב: המודל לא החזיר נוסח ← None (והשירות שולח את הנוסח הקבוע)",
      engine.follow_up_message(P, {"history": []}) is None)

# ---- שליחת המעקב - בלי רשת ----
SENT = []
run.whapi.send_text = lambda to, body: (SENT.append((to, body)), (True, {}))[1]
run.engine.follow_up_message = lambda product, c: "היי, איך מתקדמים עם ה-6 חדרים?"
run.log = lambda *a: None
PRODUCTS = {"demo-project-sales": {"text": P}}
T = datetime(2026, 9, 16, 15, 0, tzinfo=IL).timestamp()
c = cards.new(A, "", "demo-project-sales", T - 3 * 86400)
c["follow_up_at"] = T
cards.save(c)
run.send_follow_ups(PRODUCTS, lambda p: True, False, now_ts=T - 60)
check("מעקב: לפני הזמן ← לא נשלח", not SENT)
run.send_follow_ups(PRODUCTS, lambda p: False, False, now_ts=T + 60)
check("מעקב: לא ברשימה הלבנה ← לא נשלח", not SENT)
run.send_follow_ups(PRODUCTS, lambda p: True, False, now_ts=T + 60)
c = cards.get(A)
check("מעקב: בחלון ← נשלח פעם אחת, נרשם בשיחה, והתזמון נמחק",
      len(SENT) == 1 and "איך מתקדמים" in SENT[0][1] and not c.get("follow_up_at")
      and c["history"][-1]["who"] == "agent" and len(c["follow_ups"]) == 1)
run.send_follow_ups(PRODUCTS, lambda p: True, False, now_ts=T + 120)
check("מעקב: סבב נוסף ← לא נשלח שוב", len(SENT) == 1)
c["follow_up_at"] = T
cards.save(c)
run.send_follow_ups(PRODUCTS, lambda p: True, False, now_ts=T + 3 * 3600)
c = cards.get(A)
check("מעקב: השירות היה למטה ב-15:00 ← לא שולחים ב-18:00, נדחה למחר 15:00",
      len(SENT) == 1 and datetime.fromtimestamp(c["follow_up_at"], IL).strftime("%d/%m %H:%M") == "17/09 15:00")
c["meeting"] = {"label": "יום שני 10:00"}
c["follow_up_at"] = T
cards.save(c)
run.send_follow_ups(PRODUCTS, lambda p: True, False, now_ts=T + 60)
check("מעקב: ליד שקבע פגישה בינתיים ← לא נשלח, והתזמון נמחק",
      len(SENT) == 1 and not cards.get(A).get("follow_up_at"))

# ---- העלות השבועית (דני, 14-09: "אחת לשבוע סכום כמה עלה לי כל סוכן") ----
run.engine.USAGE[:] = [{"model": "claude-sonnet-5", "in": 10, "out": 20}]
run.record_usage(PRODUCTS, lambda p: True, False)
check("רישום עלויות: הקריאה עברה לקובץ המצב, והרשימה בזיכרון התרוקנה",
      not run.engine.USAGE and any(cards.usage_days("0000-00-00", "9999-12-31").values()))
cards.add_usage([{"model": "claude-sonnet-5", "in": 1_000_000, "out": 100_000}], day="2000-01-03")
cards.add_usage([{"model": "claude-haiku-9", "in": 5, "out": 5}], day="2000-01-04")
# ימים בעבר הרחוק: record_usage למעלה רשם את היום האמיתי. עם 15-16/09/2026 הבדיקה נפלה ב-15-09 עצמו
cost, calls, unknown = run.notify.cost_of(cards.usage_days("2000-01-03", "2000-01-04"))
check("עלות: מיליון קלט ו-100 אלף פלט ב-Sonnet 5 = $3.00 (2 + 1), ודגם בלי מחיר לא נספר",
      round(cost, 2) == 3.0 and calls == 2 and unknown == {"claude-haiku-9"})
run.notify.SUMMARY_AT = "08:30"
COST_SENT = []


def cost_send(to, body):
    COST_SENT.append(body)
    return True, {}


run.notify.WHAPI_MONTHLY_USD, run.notify.WHAPI_SHARE = 12.0, 0.5
# ראשון שהשבוע שלפניו (02/01-08/01/2000) מכיל את הימים המדומים, ולא את היום האמיתי
SUN = datetime(2000, 1, 9, 9, 0, tzinfo=IL)
run.notify.weekly_cost(PRODUCTS, lambda p: True, now=SUN.replace(hour=8, minute=0), send=cost_send)
check("עלות שבועית: ראשון לפני 08:30 ← לא נשלחת", not COST_SENT)
run.notify.weekly_cost(PRODUCTS, lambda p: True, now=SUN, send=cost_send)
check("עלות שבועית: ראשון 09:00 ← נשלחת, עם הסכום, התאריכים והדגם שחסר לו מחיר",
      len(COST_SENT) == 1 and "$3.00" in COST_SENT[0] and "02/01-08/01" in COST_SENT[0]
      and "claude-haiku-9" in COST_SENT[0])
# דני, 14-09: $12 לחודש, חצי לכל סוכן. שבוע: 12×12÷365×7×0.5 = 1.38 · 9 ימים בחודש: 1.78
check("עלות שבועית: חצי מ-Whapi, סה\"כ השבוע, ומתחילת החודש עם הפירוק",
      "Whapi (וואטסאפ, חצי מ-$12 לחודש - המספר משותף): $1.38" in COST_SENT[0]
      and 'סה"כ השבוע: $4.38' in COST_SENT[0]
      and "מתחילת החודש: $4.78 (Anthropic $3.00 · Whapi $1.78)" in COST_SENT[0])
run.notify.weekly_cost(PRODUCTS, lambda p: True, now=SUN.replace(hour=15), send=cost_send)
run.notify.weekly_cost(PRODUCTS, lambda p: True, now=SUN + timedelta(days=1), send=cost_send)
check("עלות שבועית: שוב באותו יום, או ביום שני ← לא נשלחת שוב", len(COST_SENT) == 1)

shutil.rmtree(TMP, ignore_errors=True)
failed = [n for n, ok in RESULTS if not ok]
for n, ok in RESULTS:
    print(f"{'✅' if ok else '❌'} {n}")
print(f"\n{len(RESULTS) - len(failed)} מתוך {len(RESULTS)} עברו")
sys.exit(1 if failed else 0)
