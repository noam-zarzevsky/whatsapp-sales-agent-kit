"""העברות לדני בוואטסאפ - שלב 3 של המנוע.

מיד: מה שהמנוע סימן דחוף לפי פרמטר 7 בקובץ המוצר, ליד בלי מילת טריגר, ושאלה על
המוצר השני (דני, 12-09). כל השאר - בסיכום היומי, SUMMARY_AT בשעון ישראל.

מניעת הצפה: הודעה אחת לכל ליד שמאגדת את כל ההעברות הדחופות שלו, ולא יותר מפעם
ב-COOLDOWN_MIN דקות לאותו ליד - גם כשהשליחה נכשלה, כי שגיאה מ-Whapi לא מבטיחה
שההודעה לא יצאה. ב-09-09 תשע הודעות זהות לדני ניתקו את הערוץ.
"""
import os
import time
from datetime import datetime, timedelta

import cards
import whapi

NOAM_PHONE = (os.getenv("NOAM_PHONE") or os.getenv("OWNER_PHONE", "")).strip()
COOLDOWN_MIN = int(os.getenv("NOTIFY_COOLDOWN_MIN", "10"))
# "מהרגע שהקמפיין פעיל בכל תחילת יום 0830 בבוקר שלח אלי סיכום של יום האתמול"
# (דני, 12-09). off - כבוי
SUMMARY_AT = os.getenv("SUMMARY_AT", "08:30").strip()

log = print
_warned = []

KINDS = {"handoff": "העברה", "other_product": "שאל על מוצר אחר",
         "no_keyword": "נכנס בלי מילת טריגר", "missing_fact": "עובדה חסרה"}
STAGES = {"new": "חדש", "talking": "בשיחה", "meeting": "לקראת פגישה",
          "meeting_set": "פגישה נקבעה", "wants_close": "רוצה לסגור", "released": "שוחרר",
          "no_keyword": "אצלך", "opened": "קיבל פתיחה, מחכה לתשובה"}


def _ready():
    if NOAM_PHONE:
        return True
    if not _warned:
        _warned.append(1)
        log("⚠️  אין NOAM_PHONE - העברות וסיכום לא נשלחים")
    return False


def local(phone):
    """972501234567 ← 050-1234567 - מספר שדני יכול ללחוץ עליו."""
    p = "0" + phone[3:] if phone.startswith("972") else phone
    return f"{p[:3]}-{p[3:]}"


def who(card):
    name = (card.get("name") or "").strip()
    return f"{name} ({local(card['phone'])})" if name else local(card["phone"])


def _last(card, speaker):
    """ההודעה האחרונה - בלי רישום של תמונה ששלחנו ("[...]")."""
    return next((h["text"] for h in reversed(card.get("history", []))
                 if h.get("who") == speaker and not h["text"].startswith("[")), "")


def _clip(text, n=300):
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


def _product(card, products):
    p = products.get(card.get("product") or "")
    line = p["name"] if p else (card.get("product") or "לא זוהה מוצר")
    ad = (card.get("profile") or {}).get("from_ad")
    return f"{line} · מהמודעה: {ad}" if ad else line


def _ts(iso):
    return datetime.fromisoformat(iso).timestamp() if iso else 0


# ---- מיד ----

def urgent_message(card, items, products):
    lines = [f"🔔 לטיפול שלך עכשיו - {who(card)}", _product(card, products)]
    if card.get("meeting"):
        lines.append(f"פגישה ביומן: {card['meeting']['label']}")
    lines += [f"• {KINDS.get(h['kind'], h['kind'])}: {h['reason']}" for h in items]
    lead, agent = _last(card, "lead"), _last(card, "agent")
    if lead:
        lines.append(f"\nהליד כתב: {_clip(lead)}")
    if agent:
        lines.append(f"ענינו: {_clip(agent)}")
    return "\n".join(lines)


def flush_urgent(products, allowed, dry=False, now_ts=None, send=None):
    """שולח לדני את ההעברות הדחופות שעוד לא נשלחו - הודעה אחת לכל ליד.
    רץ בכל סבב, גם בלי הודעות חדשות: העברה שחיכתה לסוף ההשהיה יוצאת כשהגיע זמנה."""
    if not _ready():
        return 0
    send = send or whapi.send_text
    now_ts = now_ts or time.time()
    sent = 0
    for card in cards.all_cards():
        pending = [h for h in card.get("handoffs", []) if h.get("urgent") and not h.get("sent")]
        # במצב בדיקה - רק על בודקים. ליד אמיתי לא נענה בבדיקה, ולא מעבירים עליו
        if not pending or not allowed(card["phone"]):
            continue
        if now_ts - card.get("last_notify_ts", 0) < COOLDOWN_MIN * 60:
            continue
        text = urgent_message(card, pending, products)
        if dry:
            log(f"[יבש] לדני:\n{text}")
            continue
        ok, res = send(NOAM_PHONE, text)
        card["last_notify_ts"] = now_ts
        if ok:
            for h in pending:
                h["sent"], h["via"] = cards.now(), "now"
            sent += 1
            log(f"📨 לדני ← {card['phone']}: {len(pending)} העברות")
        else:
            log(f"❌ העברה לדני נכשלה ({card['phone']}): {res} - "
                f"ניסיון חוזר בעוד {COOLDOWN_MIN} דקות")
        cards.save(card)
    return sent


# ---- הסיכום היומי ----

def summary_message(products, allowed, since, until):
    """הסיכום לדני, או None כשאין מה לסכם. מחזיר גם את ההעברות שנכנסו אליו."""
    s, u = since.timestamp(), until.timestamp()
    new, active, todo, done_now, booked = [], [], [], [], []
    for card in sorted(cards.all_cards(), key=lambda c: c.get("first_message_at") or ""):
        if not allowed(card["phone"]):
            continue
        if s <= _ts(card.get("first_message_at")) < u:
            new.append(card)
        if any(s <= _ts(h.get("at")) < u for h in card.get("history", [])):
            active.append(card)
        pending = [h for h in card.get("handoffs", [])
                   if not h.get("urgent") and not h.get("sent")]
        if pending:
            todo.append((card, pending))
        if any(h.get("via") == "now" and s <= _ts(h.get("sent")) < u
               for h in card.get("handoffs", [])):
            done_now.append(card)
        if card.get("meeting") and s <= _ts(card["meeting"].get("booked_at")) < u:
            booked.append(card)
    if not (new or active or todo):
        return None, []

    lines = [f"☀️ סיכום מאז {since:%d/%m %H:%M}",
             f"לידים חדשים: {len(new)} · שיחות פעילות: {len(active)} · "
             f"פגישות שנקבעו: {len(booked)}"]
    if booked:
        lines.append("\nפגישות שנקבעו ביומן:")
        lines += [f"• {who(c)} - {c['meeting']['label']}" for c in booked]
    if todo:
        lines.append("\nלטיפול שלך:")
        lines += [f"• {who(c)} - {KINDS.get(h['kind'], h['kind'])}: {h['reason']}"
                  for c, items in todo for h in items]
    if done_now:
        lines.append(f"\nכבר נשלחו אליך מיד: {', '.join(who(c) for c in done_now)}")
    if active:
        lines.append("\nהשיחות:")
        for c in active:
            lines.append(f"• {who(c)} · {_product(c, products)} · "
                         f"{STAGES.get(c.get('stage'), c.get('stage'))}")
            note = (c.get("notes") or [""])[-1]
            if note:
                lines.append(f"  {_clip(note, 200)}")
    return "\n".join(lines), todo


def daily_summary(products, allowed, dry=False, now=None, send=None):
    """הסיכום היומי לדני - פעם ביום, מ-SUMMARY_AT בשעון ישראל. מחזיר האם נשלח.
    מכסה את מה שקרה מאז הסיכום הקודם, כך שיום שהשירות היה למטה לא נופל."""
    if SUMMARY_AT.lower() == "off" or not _ready():
        return False
    # השרת בענן רץ ב-UTC. בלי ההמרה, 08:30 יוצא 11:30 בישראל
    now = (now or datetime.now(cards.IL)).astimezone(cards.IL)
    hh, mm = (int(x) for x in SUMMARY_AT.split(":"))
    if (now.hour, now.minute) < (hh, mm):
        return False
    st = cards.summary_state()
    today = now.date().isoformat()
    if st.get("day") == today:
        return False
    # ניסיון שנכשל - לא לנסות שוב בכל סבב של 20 שניות
    if now.timestamp() - st.get("last_try", 0) < COOLDOWN_MIN * 60:
        return False

    since = (datetime.fromtimestamp(st["until"], cards.IL) if st.get("until")
             else (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0))
    text, todo = summary_message(products, allowed, since, now)
    if text is None:
        log(f"☀️ אין מה לסכם מאז {since:%d/%m %H:%M}")
        if not dry:
            cards.set_summary(day=today, until=now.timestamp())
        return False
    if dry:
        log(f"[יבש] סיכום לדני:\n{text}")
        return True

    ok, res = (send or whapi.send_text)(NOAM_PHONE, text)
    if not ok:
        cards.set_summary(last_try=now.timestamp())
        log(f"❌ הסיכום היומי לא נשלח: {res} - ניסיון חוזר בעוד {COOLDOWN_MIN} דקות")
        return False
    for card, items in todo:
        for h in items:
            h["sent"], h["via"] = cards.now(), "summary"
        cards.save(card)
    cards.set_summary(day=today, until=now.timestamp())
    log(f"☀️ סיכום יומי נשלח לדני ({len(todo)} לידים לטיפול)")
    return True


# ---- העלות השבועית ----
# דני, 14-09: "אחת לשבוע סכום כמה עלה לי כל סוכן". מחירון Anthropic לכל מיליון tokens (קלט, פלט) -
# platform.claude.com/docs/en/about-claude/pricing, נבדק 14-09. usage.output_tokens כולל את החשיבה
PRICES = {"claude-sonnet-5": (2.0, 10.0), "claude-sonnet-4-5": (3.0, 15.0)}
AGENT_NAME = os.getenv("AGENT_NAME", "סוכן המכירה")
# יום בשבוע, שני = 0 ... ראשון = 6
COST_DAY = int(os.getenv("COST_DAY", "6"))
# Whapi - מחיר קבוע לחודש, בלי API לחיוב (צילום מסך מדני, 14-09: $12). 0 - השורה לא מוצגת
WHAPI_MONTHLY_USD = float(os.getenv("WHAPI_MONTHLY_USD") or 12)
# החלק של הסוכן הזה במנוי. מספר משותף עם סוכן אחר ← חצי לכל אחד (דני, "1", 14-09)
WHAPI_SHARE = float(os.getenv("WHAPI_SHARE") or (0.5 if os.getenv("OTHER_AGENT_KEYWORDS") else 1))


def whapi_cost(days):
    """החלק של הסוכן במנוי של Whapi ל-days ימים. חודשי ← יומי: ×12÷365."""
    return WHAPI_MONTHLY_USD * 12 / 365 * days * WHAPI_SHARE


def whapi_label():
    price = f"${WHAPI_MONTHLY_USD:g} לחודש"
    if WHAPI_SHARE == 1:
        return f"Whapi (וואטסאפ, {price})"
    part = "חצי" if WHAPI_SHARE == 0.5 else f"{WHAPI_SHARE:.0%}"
    return f"Whapi (וואטסאפ, {part} מ-{price} - המספר משותף)"


def cost_of(days):
    """(דולרים, קריאות, דגמים בלי מחיר) - לסכום של כמה ימים מ-cards.usage_days."""
    total, calls, unknown = 0.0, 0, set()
    for models in days.values():
        for model, u in models.items():
            calls += u.get("calls", 0)
            price = PRICES.get(model)
            if not price:
                unknown.add(model)
                continue
            total += u.get("in", 0) / 1e6 * price[0] + u.get("out", 0) / 1e6 * price[1]
    return total, calls, unknown


def weekly_cost(products, allowed, dry=False, now=None, send=None):
    """פעם בשבוע, ביום COST_DAY מ-SUMMARY_AT: כמה עלה הסוכן ב-7 הימים שלפני היום, ומתחילת החודש.
    הודעה נפרדת מהסיכום - הסיכום לא יוצא ביום שקט, והעלות צריכה לצאת תמיד."""
    if SUMMARY_AT.lower() == "off" or not _ready():
        return False
    now = (now or datetime.now(cards.IL)).astimezone(cards.IL)
    hh, mm = (int(x) for x in SUMMARY_AT.split(":"))
    if now.weekday() != COST_DAY or (now.hour, now.minute) < (hh, mm):
        return False
    st = cards.summary_state()
    today = now.date()
    if st.get("cost_day") == today.isoformat():
        return False
    if now.timestamp() - st.get("cost_try", 0) < COOLDOWN_MIN * 60:
        return False

    first, last = today - timedelta(days=7), today - timedelta(days=1)
    week, calls, unknown = cost_of(cards.usage_days(first.isoformat(), last.isoformat()))
    month, _, _ = cost_of(cards.usage_days(today.replace(day=1).isoformat(), today.isoformat()))
    lines = [f"💰 {AGENT_NAME} - עלות השבוע ({first:%d/%m}-{last:%d/%m})",
             f"Anthropic (המודל): ${week:.2f} · {calls} קריאות"]
    total = week
    if WHAPI_MONTHLY_USD:
        wa_week, wa_month = whapi_cost(7), whapi_cost(today.day)
        total += wa_week
        lines += [f"{whapi_label()}: ${wa_week:.2f}", f'סה"כ השבוע: ${total:.2f}',
                  f"מתחילת החודש: ${month + wa_month:.2f} (Anthropic ${month:.2f} · Whapi ${wa_month:.2f})"]
    else:
        lines.append(f"מתחילת החודש: ${month:.2f}")
    # דני, 13-09: "על כל פלטפורמה". ל-Railway אין כאן טוקן - אומרים את זה, לא מדלגים בשקט
    lines.append("(Railway - עוד לא נספר)")
    tracked = sorted(cards.usage_days("0000-00-00", today.isoformat()))
    if tracked and tracked[0] > first.isoformat():
        lines.append(f"(נספר מ-{tracked[0][8:10]}/{tracked[0][5:7]} - לפני זה לא נמדד)")
    if unknown:
        lines.append(f"⚠️ דגם בלי מחיר, לא נספר: {', '.join(sorted(unknown))}")
    text = "\n".join(lines)
    if dry:
        log(f"[יבש] לדני:\n{text}")
        return True
    ok, res = (send or whapi.send_text)(NOAM_PHONE, text)
    if not ok:
        cards.set_summary(cost_try=now.timestamp())
        log(f"❌ העלות השבועית לא נשלחה: {res} - ניסיון חוזר בעוד {COOLDOWN_MIN} דקות")
        return False
    cards.set_summary(cost_day=today.isoformat())
    log(f"💰 עלות שבועית נשלחה לדני: ${total:.2f}")
    return True
