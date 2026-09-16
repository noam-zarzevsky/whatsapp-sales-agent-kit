"""בדיקת שליחת ההדמיות (לבנה 16) - בלי Whapi ובלי מודל.

וואטסאפ ומוח מדומים, הנתונים בתיקייה זמנית שנמחקת בסוף. בודק גם את התשובה האמיתית מהשיחה
של דני מהנייד (13-09): "אין לי תמונות להעביר" - כשיש הדמיות.

הרצה:  python tests/images_check.py
"""
import os
import shutil
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="master-images-")
A, B = "972500000001", "972500000002"
os.environ.update({
    "DATA_DIR": TMP, "MODE": "test", "PRODUCTS": "demo-project-sales.test",
    "OTHER_AGENT_KEYWORDS": "לפרטים על דירה להשכרה", "OWNER_PHONE": "972500000099",
    "OWNER_KEYWORDS": "AI", "NOAM_PHONE": "972500000088", "SUMMARY_AT": "off",
    "TEST_WHITELIST": ",".join([A, B]),
})
sys.path.insert(0, os.path.join(ROOT, "src"))

import cards   # noqa: E402
import engine  # noqa: E402
import run     # noqa: E402

PRODUCT = "demo-project-sales"
P = run.load_products()
TEXT = P[PRODUCT]["text"]
MATS = engine.materials(TEXT)
RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))


# ---- טבלת החומרים ----
check("סעיף 7: שבעה חומרים עם קובץ, והאתר לא ביניהם",
      set(MATS) == {"rooms-4", "rooms-5", "rooms-6", "unit-58", "unit-62", "unit-63", "unit-65"})
check("כל הקבצים קיימים בתיקיית המנוע",
      all(os.path.exists(os.path.join(engine.KNOWLEDGE, m["file"])) for m in MATS.values()))
check("58 - '6 חדרים', לא פנטהאוז (על ההדמיה כתוב PH)",
      "6 חדרים" in MATS["unit-58"]["caption"] and "פנטהאוז" not in MATS["unit-58"]["caption"])
check("62 ו-63 - מיני-פנטהאוז",
      all("מיני-פנטהאוז" in MATS[k]["caption"] for k in ("unit-62", "unit-63")))
# מוצר קצר בתוך הבדיקה - לא קובץ אמיתי, כדי שהבדיקה תרוץ גם בגרסת הקורס
NO_MATERIALS = "# מוצר לבדיקה\n\n## 7. חומרים לשליחה\n\nאין חומרים\n"
check("מוצר בלי טבלת חומרים ← אין חומרים", engine.materials(NO_MATERIALS) == {})

# ---- הבדיקה במנוע - על התשובה האמיתית מהנייד ----
REAL = "אין לי תמונות להעביר בוואטסאפ, אבל הפרויקט מוכן ואפשר לעלות לדירה לראות הכל במציאות."
check("התשובה האמיתית 'אין לי תמונות להעביר' (13-09) ← נתפס",
      "photo_denied" in engine.violations({"reply": REAL}, TEXT, None, "יש לך תמונות"))
check("'אין לי הדמיה להעביר' ← נתפס",
      "photo_denied" in engine.violations({"reply": "אין לי הדמיה להעביר."}, TEXT, None, "יש הדמיה?"))
check("ביקש תוכנית ולא נבחר חומר ← נתפס",
      "photo_denied" in engine.violations({"reply": "מתי נוח לך?"}, TEXT, None, "אפשר לראות תוכנית?"))
check("ביקש תמונה ונבחר חומר ← תקין",
      "photo_denied" not in engine.violations(
          {"reply": "שולח לך תוכנית של הדירה", "send_image": "rooms-6"}, TEXT, None, "יש לך תמונות"))
check("'יש תוכנית תשלומים?' ← לא בקשת תמונה",
      "photo_denied" not in engine.violations(
          {"reply": "את לוח התשלומים דני בונה מולך בפגישה."}, TEXT, None, "יש תוכנית תשלומים?"))
check("מוצר בלי חומרים ← לא נבדק",
      "photo_denied" not in engine.violations({"reply": "אין לי תמונות"},
                                              NO_MATERIALS, None, "יש תמונות?"))

# ---- הזרימה ב-run.handle ----
CHATS, SENT, IMAGES, NEXT, LOGS = {}, [], [], [], []


def fake_think(product, lead, incoming, slots=None, **_):
    out = {"reply": "שולח לך תוכנית של הדירה עם ריהוט ומידות.", "stage": "talking",
           "missing_fact": None, "handoff": None, "handoff_urgent": False,
           "other_product": None, "book_slot": None, "send_image": None, "note": None}
    out.update(NEXT.pop(0) if NEXT else {})
    return out, []


def fake_chat(chat_id, count=20):
    ms = sorted(CHATS.get(chat_id, []), key=lambda m: -m["timestamp"])
    return ms[:count], len(ms)


def fake_send(to, body):
    SENT.append((to, body))
    return True, {"message": {"id": "fake", "status": "sent"}}


def fake_image(to, path, caption=""):
    IMAGES.append((to, os.path.basename(path), caption))
    return True, {}


run.whapi.chat_messages = fake_chat
run.whapi.send_text = fake_send
run.whapi.send_image = fake_image
run.whapi.health = lambda: (True, "AUTH")
run.engine.think_checked = fake_think
run.calendar_meetings.free_slots = lambda st, now=None: []
run.calendar_meetings.heal = lambda *a, **k: []
run.log = run.notify.log = LOGS.append

T0 = int(time.time()) - 600
_n = [0]


def msg(phone, text, dt):
    _n[0] += 1
    m = {"id": f"m{_n[0]}", "phone": phone, "name": "", "text": text,
         "ts": T0 + dt, "chat_id": f"{phone}@s.whatsapp.net"}
    CHATS.setdefault(m["chat_id"], []).append({"id": m["id"], "timestamp": m["ts"], "from_me": False})
    return m


NEXT.append({"reply": "שלום, אני עובד עם דני. 6 חדרים, 2,450,000 ₪."})
run.handle(msg(A, "הי אשמח לפרטים על רכישת דירה 6 חד'", 0), P, dry=False)
NEXT.append({"send_image": "rooms-6"})
run.handle(msg(A, "יש לך תמונות?", 60), P, dry=False)
card = cards.get(A)
check("נבחרה הדמיה ← נשלחת אחרי ההודעה, עם הכיתוב מסעיף 7",
      IMAGES == [(A, "rooms-6.jpg", MATS["rooms-6"]["caption"])] and SENT[-1][0] == A)
check("בכרטיס: נשלח, ובהיסטוריה רישום של התמונה",
      card["sent_images"] == ["rooms-6"] and card["history"][-1]["text"].startswith("[תוכנית דירת 6"))
NEXT.append({"send_image": "rooms-6"})
run.handle(msg(A, "תשלח שוב את התוכנית", 120), P, dry=False)
check("אותה הדמיה פעם שנייה ← לא נשלחת שוב", len(IMAGES) == 1)
NEXT.append({"send_image": "unit-62, unit-63"})
run.handle(msg(A, "ויש של המיני-פנטהאוז?", 180), P, dry=False)
check("שני מזהים ← שתי הדמיות", [i[1] for i in IMAGES[1:]] == ["unit-62.jpg", "unit-63.jpg"])
NEXT.append({"send_image": "unit-99"})
run.handle(msg(A, "ושל דירה 99?", 240), P, dry=False)
check("מזהה שלא בסעיף 7 ← לא נשלח, ונרשם בלוג",
      len(IMAGES) == 3 and any("unit-99" in str(x) for x in LOGS))
check("בתיק הליד שהמנוע רואה - מה כבר נשלח",
      cards.get(A)["sent_images"] == ["rooms-6", "unit-62", "unit-63"])
NEXT.append({"reply": "שלום, 5 חדרים ב-2,050,000 ₪."})
run.handle(msg(B, "הי אשמח לפרטים על רכישת דירה 5 חד'", 0), P, dry=False)
NEXT.append({"send_image": "rooms-5"})
run.handle(msg(B, "יש תמונה?", 60), P, dry=True)
check("יבש ← לא נשלחת תמונה", len(IMAGES) == 3)

PROMPTS = []


class _FakeMessages:
    def create(self, **kw):
        PROMPTS.append(kw["messages"][0]["content"])
        block = type("B", (), {"type": "text", "text": '{"reply": "x"}'})()
        return type("R", (), {"content": [block]})()


engine._client = lambda: type("C", (), {"messages": _FakeMessages()})()
engine.think(TEXT, cards.get(A), "עוד משהו?")
check("המנוע רואה בתיק הליד מה כבר נשלח", "חומרים שכבר נשלחו: rooms-6, unit-62, unit-63" in PROMPTS[-1])

shutil.rmtree(TMP, ignore_errors=True)
failed = [n for n, ok in RESULTS if not ok]
for name, ok in RESULTS:
    print(f"{'✅' if ok else '❌'} {name}")
print(f"\n{len(RESULTS) - len(failed)} מתוך {len(RESULTS)} עברו")
sys.exit(1 if failed else 0)
