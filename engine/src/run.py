"""השירות של המנוע על המספר המשותף - קורא, מנתב, חושב, שולח.

סוכן ההשכרה רץ בשירות נפרד על אותו מספר (הוכרע 12-09). כל אחד לוקח רק לידים שפתחו
במילת הטריגר שלו - הכללים ב-STATUS.md, פרק 🔀, והקוד ב-router.py.

הרצה:
  python src/run.py --dry     קורא מ-Whapi, מנתב וחושב - לא שולח ולא שומר כלום
  python src/run.py           ריצה אחת
  python src/run.py --loop    בלולאה

⚠️ עד שסוכן ההשכרה ילמד לדלג על לידים של מכירה - רק --dry. היום הוא עונה לכל בודק
ברשימה הלבנה, ובודק שכותב את מילת המכירה היה מקבל תשובה משני הסוכנים.
"""
import os
import re
import sys
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# אותו מספר ואותו חשבון Whapi כמו סוכן ההשכרה. עד שלמנוע יהיה .env משלו - המפתחות
# משם. נטען, לא מודפס.
for env in (os.path.join(ROOT, ".env"), os.path.join(ROOT, "..", "rental-leads", ".env")):
    if os.path.exists(env):
        load_dotenv(env)
        break
sys.path.insert(0, os.path.join(ROOT, "src"))

import calendar_meetings   # noqa: E402
import cards    # noqa: E402
import engine   # noqa: E402
import notify   # noqa: E402
import router   # noqa: E402
import whapi    # noqa: E402


def _list(name, default=""):
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


MODE = os.getenv("MODE", "test").strip().lower()
WHITELIST = set(_list("TEST_WHITELIST"))
# כל מה שאישי למוכר מגיע ממשתני הסביבה, והקוד עצמו כללי (13-09) - אותו קוד רץ אצל דני
# ובגרסת הקורס. אצל דני ב-Railway: PRODUCTS, OWNER_NAME, CALENDAR_ID, OTHER_AGENT_KEYWORDS, OFFER_BLOCK
# קבצי המוצר שהשירות מחזיק, מתוך knowledge/
PRODUCTS = _list("PRODUCTS", "demo-project-sales")
# השם שהסוכן אומר ללקוח ("אני בודק מול X") - מי שסוגר את העסקה ומאשר שינויים
OWNER_NAME = os.getenv("OWNER_NAME", "מנהל המכירות").strip()
# מילות הטריגר של סוכנים אחרים על אותו מספר. אצל דני - משפט קמפיין ההשכרה (12-09)
OTHER_AGENT_KEYWORDS = _list("OTHER_AGENT_KEYWORDS")
OWNER_PHONE = os.getenv("OWNER_PHONE", "").strip()
OWNER_KEYWORDS = _list("OWNER_KEYWORDS", "AI")
RESET_WORDS = ("אפס", "איפוס", "reset")
# מילים של מוצר שהליד לא פנה אליו, ואסור להציע מיוזמתך. אצל דני - השכרה ("לקוח שפונה על
# מכירה - לא להציע השכרה", 13-09). נבדק בקוד בכל תשובה (engine.violations)
OFFER_BLOCK = _list("OFFER_BLOCK")
# ליד שכותב בלי משפט טריגר (דני, 14-09): "תחזור אליו בשאלה מה הוא מחפש / איך אפשר לעזור",
# "הסוכן צריך להיות יותר עם חתירה למטרה". קודם - מה שהוא כתב: מילים של קנייה ← שלנו, של
# הסוכן האחר ← שלו. בלי שום רמז ← הפתיחה (OPENER), והתשובה מנותבת באותה דרך
INTENT_WORDS = _list("INTENT_WORDS", "לקנות,לרכוש,רכישה,קנייה,קניה")
# בלי סוכן אחר על המספר - אין למי לוותר
OTHER_AGENT_INTENT_WORDS = (_list("OTHER_AGENT_INTENT_WORDS", "לשכור,שכירות,השכרה")
                            if OTHER_AGENT_KEYWORDS else [])
# "or" ולא ברירת מחדל של getenv - שורה ריקה בקובץ ההגדרות לא תשאיר "פנית אלינו ל -"
BUSINESS_NAME = (os.getenv("BUSINESS_NAME") or "מגדלי הדוגמה").strip()
# בנוסח של דני. OPENER_MARK בפנים - כך הפתיחה לא תופסת את השיחה, גם לא אצל סוכן ההשכרה
OPENER = f"שלום,\nפנית אלינו ל{BUSINESS_NAME} - {router.OPENER_MARK}?"
# דני, 13-09: ליד שאומר "אחשוב על זה" ← הודעת מעקב "לא לפני 48 שעות, בשעה 15:00"
FOLLOW_UP_HOURS = int(os.getenv("FOLLOW_UP_HOURS", "48"))
FOLLOW_UP_AT = os.getenv("FOLLOW_UP_AT", "15:00")
FOLLOW_UP_FALLBACK = "היי, רציתי לשאול - איך מתקדמים?"
# המודל לא ענה פעמיים, או נפל - הליד מקבל את זה, ודני העברה מיידית (פריט 24 של המוח, דני: "3", 14-09).
# בלי זמן - "X יחזור אליך" בלי מתי (כלל 15)
FALLBACK_REPLY = f"קיבלתי, תודה - {OWNER_NAME} יחזור אליך."

STOP_FILE = os.path.join(ROOT, "STOP")
LOG = os.path.join(ROOT, "logs", "agent.log")
# בהפעלה ראשונה בלבד (אין עדיין סימן מים) - כמה אחורה מותר להסתכל
FIRST_RUN_LOOKBACK_MIN = int(os.getenv("FIRST_RUN_LOOKBACK_MIN", "15"))
# ליד שכותב כמה הודעות ברצף מקבל תשובה אחת - כמו בסוכן ההשכרה
DEBOUNCE_SECONDS = int(os.getenv("DEBOUNCE_SECONDS", "15"))
MAX_WAIT_SECONDS = int(os.getenv("MAX_WAIT_SECONDS", "45"))


def log(msg):
    line = f"{datetime.now(cards.IL).strftime('%Y-%m-%d %H:%M:%S')} | {msg}"
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


notify.log = log


def product_id(slug):
    """המוצר בכרטיס - בלי הסיומת .test, כדי שכרטיס מהבדיקה יתאים גם לקובץ האמיתי."""
    return slug[:-len(".test")] if slug.endswith(".test") else slug


def load_products():
    """{מוצר: {slug, text, keyword}} לכל קובץ ב-PRODUCTS. נקרא בכל סבב, כך שעדכון
    בקובץ המוצר נכנס בלי הפעלה מחדש."""
    out = {}
    for slug in PRODUCTS:
        text = engine.load_product(slug)
        fm = engine.frontmatter(text)
        out[product_id(slug)] = {"slug": slug, "text": text, "name": fm.get("product", slug),
                                 "keyword": fm.get("keyword", ""),
                                 # None - למוצר אין שעות פגישה בסעיף 5, ולא נוגעים ביומן
                                 "meeting": calendar_meetings.settings(text)}
    return out


def gate_live(products):
    """מסרב לעלות למצב חי עם קובץ בדיקה, עם 🧪 בקובץ מוצר או בלי מילת טריגר.
    נבדק בכל סבב - לא משהו שצריך לזכור."""
    if MODE != "live":
        return True, ""
    for p in products.values():
        if p["slug"].endswith(".test"):
            return False, f"{p['slug']} הוא קובץ בדיקה"
        if "🧪" in p["text"]:
            return False, f"יש {p['text'].count('🧪')} ערכי בדיקה ב-{p['slug']}"
        if not p["keyword"]:
            return False, f"אין מילת טריגר ב-{p['slug']}"
    return True, ""


def allowed(phone):
    return MODE == "live" or phone in WHITELIST


def owner_command(phone, text):
    """מה שאחרי מילת הבעלים (למשל "AI אפס 050...") - או None אם זו לא פקודה.

    את הפקודות מקבל ועונה עליהן סוכן ההשכרה (rental-leads/src/owner.py). המנוע רק
    מאפס גם אצלו, בשקט - אחרת דני מקבל שני אישורים על כל איפוס."""
    if not OWNER_PHONE or phone != OWNER_PHONE:
        return None
    head = text.strip()
    for k in OWNER_KEYWORDS:
        if head[:len(k)].lower() == k.lower():
            return head[len(k):].lstrip(" ,:-").strip()
    # "אפס AI" - בעברית קל לכתוב את הפקודה הפוך. דני כתב כך בבדיקה (13-09), והאיפוס לא קרה
    words = head.split()
    if (len(words) >= 2 and words[0].lower() in RESET_WORDS
            and words[1].lower() in (k.lower() for k in OWNER_KEYWORDS)):
        return " ".join([words[0]] + words[2:])
    return None


def reset_target(text, owner_phone):
    """כרטיס מי לאפס - אותו כלל כמו rental-leads/src/owner.py:75, כדי ששני הסוכנים
    יאפסו את אותו ליד: מספר נייד שנכתב בפקודה, או הבעלים עצמו."""
    m = re.search(r"(?:\+?972[-\s]?|0)5\d(?:[-\s]?\d){7}", text)
    if not m:
        return owner_phone
    digits = re.sub(r"\D", "", m.group(0))
    return "972" + digits[1:] if digits.startswith("0") else digits


def cutoff():
    wm = cards.watermark()
    if wm is None:
        return int(time.time() - FIRST_RUN_LOOKBACK_MIN * 60)
    return wm


def merge_by_lead(msgs):
    """פקודות הבעלים - כל אחת לבד ובראש התור, כך שאיפוס קורה לפני ההודעה שאחריו.
    הודעות של ליד - מאוחדות לתור אחד ותשובה אחת. first_ts - ההודעה הראשונה בתור."""
    owner_cmds, by_lead = [], {}
    for m in sorted(msgs, key=lambda x: x.get("ts", 0)):
        if owner_command(m["phone"], m["text"]) is not None:
            owner_cmds.append(m)
        else:
            by_lead.setdefault(m["phone"], []).append(m)
    merged = [dict(ms[-1], text="\n".join(x["text"] for x in ms),
                   ids=[x["id"] for x in ms], first_ts=ms[0]["ts"])
              for ms in by_lead.values()]
    return owner_cmds + merged


def send_materials(card, prod, wanted, dry):
    """שולח את החומרים שהמנוע בחר מסעיף 7 בקובץ המוצר - כל אחד פעם אחת לכל ליד.
    מזהה שלא בטבלה, או קובץ שלא קיים - לא נשלח, ונרשם בלוג."""
    mats = engine.materials(prod["text"])
    sent = card.setdefault("sent_images", [])
    for mid in (w.strip() for w in str(wanted or "").split(",")):
        if not mid or mid.lower() in ("null", "none") or mid in sent:
            continue
        if mid not in mats:
            log(f"⚠️  {card['phone']}: המנוע בחר חומר שלא בסעיף 7 - {mid}")
            continue
        path = os.path.join(engine.KNOWLEDGE, mats[mid]["file"])
        if not os.path.exists(path):
            log(f"❌ {card['phone']}: הקובץ של {mid} לא קיים - {mats[mid]['file']}")
            continue
        if dry:
            log(f"[יבש] תמונה אל {card['phone']}: {mid}")
            continue
        ok, res = whapi.send_image(card["phone"], path, mats[mid]["caption"])
        if ok:
            sent.append(mid)
            cards.add_turn(card, "agent", f"[{mats[mid]['caption']}]")
            log(f"🖼️  {mid} ← {card['phone']}")
        else:
            log(f"❌ שליחת {mid} נכשלה ← {card['phone']}: {res}")


def note_handoff(card, kind, reason, urgent):
    """רושם העברה לדני בכרטיס. השליחה - notify.py, בסוף הסבב."""
    card.setdefault("handoffs", []).append({
        "at": cards.now(), "kind": kind, "reason": reason,
        "urgent": bool(urgent), "sent": None})
    log(f"🔔 לדני ({'מיד' if urgent else 'לסיכום'}) ← {card['phone']}: {reason}")


def _match(when, slots):
    """המועד מהרשימה שהמנוע בחר, או None. משווה זמנים ולא מחרוזות."""
    try:
        w = datetime.fromisoformat(str(when))
    except ValueError:
        return None
    if w.tzinfo is None:
        w = w.replace(tzinfo=cards.IL)
    return next((s for s in slots if s["start"] == w), None)


def _offer(slots):
    """שני מועדים חלופיים, בימים שונים."""
    picks, days = [], set()
    for s in slots:
        if s["start"].date() not in days:
            picks.append("ב" + s["label"])
            days.add(s["start"].date())
        if len(picks) == 2:
            break
    return " או ".join(picks)


def book_meeting(card, prod, when, offered, reply, dry):
    """קובע את המועד שהליד בחר. מחזיר את ההודעה ללקוח: של המנוע כשהפגישה נכנסה ליומן,
    ואחרת הודעה שלא אומרת "קבעתי" - ליד שמקבל אישור על פגישה שלא ביומן מגיע ולא מוצא
    אף אחד (קרה בהשכרה בכיוון ההפוך, באג אזור הזמן 10-09)."""
    st = prod["meeting"]
    if card.get("meeting"):
        note_handoff(card, "handoff",
                     f"מבקש לשנות את הפגישה ({card['meeting']['label']}) ל-{str(when)[:16]}",
                     urgent=True)
        return f"את השינוי במועד {OWNER_NAME} מאשר בעצמו - הוא יחזור אליך ישירות."
    slot = _match(when, offered)
    if not slot:
        status, info = "invalid", "לא מהרשימה שהוצעה"
    elif dry:
        log(f"[יבש] הייתה נקבעת פגישה ל-{slot['label']}")
        return reply
    else:
        status, info = calendar_meetings.book(st, slot["start"], card, prod["name"])

    if status == "ok":
        card["meeting"] = {"when": slot["start"].isoformat(), "label": slot["label"],
                           "event_id": info["id"], "link": info["link"],
                           "booked_at": cards.now()}
        card["stage"] = "meeting_set"
        log(f"📅 פגישה נקבעה ← {card['phone']}: {slot['label']}")
        return reply

    card["stage"] = "talking"
    if status == "error":
        log(f"❌ קביעת פגישה נכשלה ← {card['phone']}: {info}")
        note_handoff(card, "handoff", f"פגישה ל-{slot['label']} לא נכנסה ליומן", urgent=True)
        return f"רגע - המועד הזה לא נכנס ליומן. אני בודק מול {OWNER_NAME} וחוזר אליך עם מועד מאושר."
    # נתפס בינתיים, או מועד שלא הוצע - מציעים מחדש מהיומן העדכני
    log(f"⏭  {card['phone']}: {str(when)[:16]} {'נתפס בינתיים' if status == 'taken' else info}")
    try:
        fresh = calendar_meetings.free_slots(st)
    except Exception as e:
        log(f"⚠️  לא הצלחתי לקרוא מהיומן: {type(e).__name__}: {e}")
        fresh = []
    if fresh:
        return f"המועד הזה כבר לא פנוי. אפשר {_offer(fresh)} - מה מתאים?"
    note_handoff(card, "handoff", "אין מועד פנוי ביומן לפגישה", urgent=True)
    return f"המועד הזה כבר לא פנוי. אני בודק מול {OWNER_NAME} וחוזר אליך עם מועד."


# מערכת הנכסים דורסת אירועים ביומן כמה דקות אחרי שנקבעו - מחזירים צבע ותג כל 10 דקות
HEAL_MINUTES = 10
_last_heal = [0.0]


def heal_meetings(products, dry):
    if dry or not any(p["meeting"] for p in products.values()):
        return
    if time.time() - _last_heal[0] < HEAL_MINUTES * 60:
        return
    _last_heal[0] = time.time()
    for when in calendar_meetings.heal():
        log(f"🎨 פגישה ב-{when[:16]} קיבלה שוב צבע ותג ביומן")


def learn(card, learned):
    """מה שהמודל למד על הליד בתור הזה (learned) ← לכרטיס, וממנו לפרומפט של התור הבא.
    התנגדויות מצטברות, השאר מתעדכן."""
    if not isinstance(learned, dict):
        return
    for k, val in learned.items():
        if k not in engine.LEARN_KEYS or val in (None, "", "null", [], {}):
            continue
        val = " ".join(str(val).split())[:120]
        if k == "objection":
            prev = card["profile"].get(k, "")
            if val not in prev:
                card["profile"][k] = f"{prev} · {val}".strip(" ·")[-300:]
        else:
            card["profile"][k] = val


def record_usage(products, allowed_fn, dry):
    """מה שהמודל צרך מאז הסבב הקודם ← קובץ המצב, בשביל העלות השבועית. ביבש - לא נשמר."""
    entries, engine.USAGE[:] = list(engine.USAGE), []
    if entries and not dry:
        cards.add_usage(entries)


def _next_at(dt):
    """ה-FOLLOW_UP_AT הראשונה מ-dt והלאה - לא בשבת."""
    h, m = (int(x) for x in FOLLOW_UP_AT.split(":"))
    at = dt.replace(hour=h, minute=m, second=0, microsecond=0)
    if at < dt:
        at += timedelta(days=1)
    while at.weekday() == 5:
        at += timedelta(days=1)
    return at


def follow_up_time(ts):
    """"לא לפני 48 שעות, בשעה 15:00" - ה-15:00 הראשונה שאחרי 48 שעות. שבת ← ראשון."""
    return _next_at(datetime.fromtimestamp(ts, cards.IL)
                    + timedelta(hours=FOLLOW_UP_HOURS)).timestamp()


def send_follow_ups(products, allowed_fn, dry, now_ts=None):
    """הודעות המעקב שהגיע זמנן. רץ בכל סבב. חלון של שעה: שירות שהיה למטה ב-15:00
    לא שולח ב-18:00, אלא דוחה ל-15:00 הבאה."""
    now_ts = now_ts or time.time()
    for card in cards.all_cards():
        at = card.get("follow_up_at")
        if not at or now_ts < at or not allowed_fn(card["phone"]):
            continue
        prod = products.get(card.get("product") or "")
        if not prod or card.get("meeting") or card.get("stage") == "released":
            card.pop("follow_up_at", None)
        elif now_ts > at + 3600:
            card["follow_up_at"] = _next_at(datetime.fromtimestamp(now_ts, cards.IL)).timestamp()
            log(f"⏰ {card['phone']} - חלון המעקב עבר, נדחה ל-"
                f"{datetime.fromtimestamp(card['follow_up_at'], cards.IL):%d/%m %H:%M}")
        else:
            try:
                text = engine.follow_up_message(prod["text"], card)
            except Exception as e:
                log(f"⚠️  ניסוח המעקב נכשל ({type(e).__name__}) - נוסח קבוע")
                text = None
            if not text:
                log(f"⚠️  ניסוח המעקב לא תקין (stop_reason={engine.LAST_STOP[0]}) - נוסח קבוע")
            text = text or FOLLOW_UP_FALLBACK
            if dry:
                log(f"[יבש] מעקב אל {card['phone']}:\n{text}")
                continue
            ok, res = whapi.send_text(card["phone"], text)
            if not ok:
                log(f"❌ מעקב אל {card['phone']} נכשל: {res} - ננסה בסבב הבא")
                continue
            cards.add_turn(card, "agent", text)
            card.pop("follow_up_at", None)
            card.setdefault("follow_ups", []).append(cards.now())
            log(f"⏰ מעקב נשלח אל {card['phone']}")
        if not dry:
            cards.save(card)


def _think(prod, card, text, slots):
    """(תשובה, מה תוקן, למה נכשל). חריגה בקריאה למודל לא עוזבת את handle - עד 14-09 היא נתפסה רק
    ב-cycle, סימן המים התקדם, וההודעה של הליד אבדה בלי תשובה ובלי העברה."""
    try:
        out, fixed = engine.think_checked(prod["text"], card, text, slots, avoid=OFFER_BLOCK)
    except Exception as e:
        return None, [], f"{type(e).__name__}: {str(e)[:120]}"
    if out and out.get("reply"):
        return out, fixed, None
    return None, [], f"אין תשובה תקינה (stop_reason={engine.LAST_STOP[0]})"


def no_reply(card, phone, text, reason, dry):
    """המודל נכשל פעמיים - הליד לא נעלם בשקט: הודעה קבועה, והעברה מיידית לדני עם הסיבה
    וההודעה שלו. יוצאת באותו סבב (flush_urgent רץ אחרי cycle)."""
    clip = " ".join(text.split())[:200]
    note_handoff(card, "handoff", f"הסוכן לא הצליח לענות ({reason}). הליד כתב: {clip}", urgent=True)
    log(f"🆘 {phone} - אין תשובה מהמודל פעמיים ({reason}) - הודעה קבועה והעברה לדני")
    if dry:
        log(f"[יבש] אל {phone}: {FALLBACK_REPLY}")
        return False
    ok, res = whapi.send_text(phone, FALLBACK_REPLY)
    if ok:
        cards.add_turn(card, "agent", FALLBACK_REPLY)
    else:
        log(f"❌ ההודעה הקבועה ל-{phone} לא נשלחה: {res}")
    cards.save(card)
    return ok


def open_chat(msg, ids, first_ts, dry):
    """בלי משפט טריגר ובלי רמז - הפתיחה בנוסח של דני, והתשובה תנותב לפי מה שיכתוב.
    בלי 🔔 - מופיע בסיכום היומי. מיד לדני רק אם הפתיחה לא יצאה (דני, "1", 14-09)."""
    phone = msg["phone"]
    if dry:
        log(f"[יבש] 👋 {phone} - בלי מילת טריגר ← פתיחה: {' '.join(OPENER.split())}")
        return False
    card = cards.new(phone, msg.get("name", ""), None, first_ts)
    card["handled_ids"] = ids
    cards.add_turn(card, "lead", msg["text"])
    ok = False
    if not allowed(phone):
        log(f"⏭  {phone} לא ברשימה הלבנה - נרשם (בלי מילת טריגר), בלי פתיחה")
    else:
        ok, res = whapi.send_text(phone, OPENER)
        if ok:
            card["stage"] = "opened"
            cards.add_turn(card, "agent", OPENER)
            log(f"👋 {phone} - בלי מילת טריגר - נשלחה פתיחה")
        else:
            note_handoff(card, "no_keyword",
                         f"הודעה ראשונה בלי מילת טריגר, והפתיחה לא נשלחה ({str(res)[:80]})",
                         urgent=True)
    cards.save(card)
    return ok


# ריצה יבשה לא שומרת לדיסק, אבל איפוס צריך לחול על ההודעות שאחריו באותו סבב -
# אחרת היבש מראה החלטה אחרת ממה שהריצה האמיתית תעשה
_dry_resets = {}


def handle(msg, products, dry):
    phone, text = msg["phone"], msg["text"]

    cmd = owner_command(phone, text)
    if cmd is not None:
        ids = msg.get("ids") or [msg["id"]]
        if cards.owner_done(ids):
            log(f"⏭  פקודה מהבעלים שכבר בוצעה - Whapi שלח אותה שוב ({phone})")
            return False
        if not dry:
            cards.mark_owner_done(ids)
        if cmd.lower().startswith(RESET_WORDS):
            target = reset_target(cmd, phone)
            if dry:
                _dry_resets[target] = msg["ts"]
            else:
                cards.delete(target)
                cards.set_reset(target, msg["ts"])
            log(f"♻️  איפוס {target} - השיחה איתו תיחשב חדשה")
        return False

    ids = msg.get("ids") or [msg["id"]]
    card = cards.get(phone)
    if card and all(i in card["handled_ids"] for i in ids):
        return False

    def is_free(all_keywords):
        # +30: ליד שכתב כמה הודעות בלי מילה לפני משפט הקמפיין - שכולן ייקראו
        chat, total = whapi.chat_messages(msg["chat_id"], count=len(ids) + 30)
        reset = _dry_resets.get(phone) if dry else None
        return router.claimable(chat, total, set(ids), msg["ts"],
                                reset or cards.reset_at(phone), all_keywords)

    keywords = {p: v["keyword"] for p, v in products.items()}
    hints = {p: INTENT_WORDS for p in products}
    action, product, why = router.route(card, text, keywords, OTHER_AGENT_KEYWORDS, is_free,
                                        hints, OTHER_AGENT_INTENT_WORDS, lead_agent=True)
    if action == "skip":
        log(f"⏭  {phone} - {why}")
        return False

    first_ts = msg.get("first_ts", msg["ts"])
    if action == "open":
        return open_chat(msg, ids, first_ts, dry)
    if action == "orphan":
        # שתי מילות טריגר בהודעה הראשונה - לא ברור של מי, ולכן לדני
        card = cards.new(phone, msg.get("name", ""), None, first_ts)
        card["handled_ids"] = ids
        cards.add_turn(card, "lead", text)
        note_handoff(card, "no_keyword", why, urgent=True)
        if not dry:
            cards.save(card)
        return False
    if action == "new":
        card = cards.new(phone, msg.get("name", ""), product, first_ts)
    if action == "claim":
        # כתב קודם בלי מילה (אצל דני), עכשיו את משפט הקמפיין, ואף אחד עוד לא ענה לו -
        # הסוכן לוקח, עם כל מה שכתב קודם (דני, 13-09)
        card["product"], card["stage"] = product, "new"
        # 🔔 שעוד לא יצא - כבר לא לטיפול של דני
        card["handoffs"] = [h for h in card["handoffs"]
                            if h.get("sent") or h["kind"] != "no_keyword"]
        card["notes"].append("נכנס בלי מילת טריגר, ואחר כך כתב אותה - הסוכן לקח את השיחה"
                             if router.hits(text, keywords[product]) else
                             "נכנס בלי מילת טריגר - הסוכן לקח את השיחה לפי מה שכתב (14-09)")
    if action in ("new", "claim"):
        asked = router.after_keyword(text, keywords[product])
        if asked:
            # על מה המודעה - "שהסוכן יכול ישר לתת לו מידע על הדירה שהוא מבקש" (דני, 12-09)
            card["profile"]["from_ad"] = asked
        mark, tail = ("🆕", "") if action == "new" else ("🙋", " - נלקח אחרי הודעה בלי מילה")
        log(f"{mark} {phone} ← {product}{f' ({asked})' if asked else ''}{tail}")

    card["handled_ids"] = (card["handled_ids"] + ids)[-200:]
    cards.add_turn(card, "lead", text)
    # הליד כתב - מעקב שחיכה לו כבר לא נחוץ (אם שוב "אחשוב על זה" - נקבע מחדש למטה)
    card.pop("follow_up_at", None)
    if why:
        # מילת טריגר של מוצר אחר באמצע שיחה - הוכרע 10-09: עובר לדני. מיד - דני, 12-09
        note_handoff(card, "other_product", why, urgent=True)

    if not allowed(phone):
        log(f"⏭  {phone} לא ברשימה הלבנה - נרשם ({card['product']}), לא נענה")
        if not dry:
            cards.save(card)
        return False

    prod = products[card["product"]]
    slots = None
    if prod["meeting"]:
        try:
            slots = calendar_meetings.free_slots(prod["meeting"])
        except Exception as e:
            # בלי יומן המנוע לא מציע מועד (רשימה ריקה) - ולא ממציא
            log(f"⚠️  לא הצלחתי לקרוא מהיומן: {type(e).__name__}: {e}")
            slots = []

    out, fixed, failed = _think(prod, card, text, slots)
    if failed:
        # ניסיון חוזר אחד מיד (פריט 24 של המוח, דני: "3", 14-09)
        log(f"🔁 {phone} - {failed} - ניסיון חוזר")
        out, fixed, failed = _think(prod, card, text, slots)
    if failed:
        return no_reply(card, phone, text, failed, dry)
    if fixed:
        log(f"🔁 {phone} - נוסח מחדש: {' · '.join(engine.LABELS[k] for k in fixed)}")

    reply = out["reply"]
    card["stage"] = out.get("stage") or card["stage"]
    if out.get("note"):
        card["notes"].append(out["note"])
    if out.get("plan"):
        # מה המנוע החליט לפני שכתב - בלוג בלבד, לא נשלח
        log(f"🧭 {phone} - {' '.join(str(out['plan']).split())[:300]}")
    learn(card, out.get("learned"))
    if out.get("missing_fact"):
        card["open_questions"].append(out["missing_fact"])
        # פרמטר 7: "השאר - בסיכום יומי"
        note_handoff(card, "missing_fact", out["missing_fact"], urgent=False)
    if out.get("handoff"):
        # דחוף רק כשהמנוע סימן במפורש - גם "false" כמחרוזת לא ייחשב דחוף
        note_handoff(card, "handoff", out["handoff"], out.get("handoff_urgent") in (True, "true"))
    if out.get("other_product") and not why:
        note_handoff(card, "other_product", out["other_product"], urgent=True)
    if out.get("book_slot") not in (None, "", "null"):
        reply = book_meeting(card, prod, out["book_slot"], slots or [], reply, dry)
    # "אחשוב על זה" ← מעקב אחרי 48 שעות, ב-15:00 (דני, 13-09). ליד עם פגישה - לא צריך
    if ((out.get("follow_up") in (True, "true") or engine.DEFER.search(text))
            and not card.get("meeting")):
        card["follow_up_at"] = follow_up_time(msg["ts"])
        log(f"⏰ {phone} - מעקב ב-"
            f"{datetime.fromtimestamp(card['follow_up_at'], cards.IL):%d/%m %H:%M}")

    if dry:
        log(f"[יבש] אל {phone} ({card['product']}):\n{reply}")
        send_materials(card, prod, out.get("send_image"), dry=True)
        return True

    ok, res = whapi.send_text(phone, reply)
    if ok:
        cards.add_turn(card, "agent", reply)
        m = (res.get("message") or {}) if isinstance(res, dict) else {}
        log(f"✅ נשלח אל {phone} ({card['product']}, {card['stage']}) | "
            f"whapi {m.get('id', '?')} {m.get('status', '?')}")
        # התמונה אחרי ההודעה - כך הליד קורא קודם "שולח לך תוכנית", ואז מקבל אותה
        send_materials(card, prod, out.get("send_image"), dry=False)
    else:
        log(f"❌ שליחה נכשלה אל {phone}: {res}")
    cards.save(card)
    return ok


def cycle(dry=False):
    if os.path.exists(STOP_FILE):
        log("🛑 קובץ STOP קיים - לא שולחים כלום")
        return
    products = load_products()
    ok, why = gate_live(products)
    if not ok:
        log(f"🚫 השער חסם מצב חי: {why}")
        return

    healthy, status = whapi.health()
    if not healthy:
        log(f"❌ וואטסאפ מנותק ({status})")
        return

    incoming(products, dry)
    # גם בסבב בלי הודעות חדשות: העברה שחיכתה לסוף ההשהיה, והסיכום של 08:30
    for name, job in (("רישום עלויות", record_usage),
                      ("העברות לדני", notify.flush_urgent),
                      ("סיכום יומי", notify.daily_summary),
                      ("מעקב אחרי אחשוב על זה", send_follow_ups),
                      ("עלות שבועית", notify.weekly_cost)):
        try:
            job(products, allowed, dry)
        except Exception as e:
            log(f"❌ {name} נכשל: {type(e).__name__}: {e}")
    try:
        heal_meetings(products, dry)
    except Exception as e:
        log(f"❌ תיקון פגישות ביומן נכשל: {type(e).__name__}: {e}")


def incoming(products, dry):
    """הודעות נכנסות: מה חדש מאז סימן המים ← תור אחד לכל ליד ← handle."""
    msgs = whapi.fetch_messages(limit=50)
    since = cutoff()
    fresh = [m for m in msgs if m.get("ts", 0) > since]
    if not fresh:
        if not dry and cards.watermark() is None:
            cards.set_watermark(since)
        return

    now = time.time()
    newest_ts = max(m.get("ts", 0) for m in fresh)
    oldest_ts = min(m.get("ts", 0) for m in fresh)
    if now - newest_ts < DEBOUNCE_SECONDS and now - oldest_ts < MAX_WAIT_SECONDS:
        return

    batch = merge_by_lead(fresh)
    done = 0
    for m in batch:
        try:
            if handle(m, products, dry):
                done += 1
        except Exception as e:
            # כשל בליד אחד לא מפיל את השאר
            log(f"❌ נכשל בטיפול ב-{m.get('phone')}: {type(e).__name__}: {e}")

    if not dry:
        cards.set_watermark(newest_ts)
    log(f"סבב הסתיים - {len(fresh)} הודעות, {len(batch)} תורות, {done} נענו")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    dry = "--dry" in sys.argv
    products = load_products()
    kws = " · ".join(f"{p}: {v['keyword'] or '(אין מילה!)'}" for p, v in products.items())
    log(f"▶ מצב: {MODE} | {'יבש' if dry else 'שולח'} | רשימה לבנה: {len(WHITELIST)} | "
        f"מוצרים - {kws} | סוכנים אחרים: {' · '.join(OTHER_AGENT_KEYWORDS)}")
    if "--loop" in sys.argv:
        while True:
            try:
                cycle(dry)
            except Exception as e:
                log(f"❌ שגיאה בסבב: {type(e).__name__}: {e}")
            time.sleep(int(os.getenv("POLL_SECONDS", "20")))
    else:
        cycle(dry)


if __name__ == "__main__":
    main()
