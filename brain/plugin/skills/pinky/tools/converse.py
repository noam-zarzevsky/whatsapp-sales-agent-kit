"""פינקי מול הסוכן - תור אחד בשיחה מדומה. בלי וואטסאפ, בלי יומן ובלי כרטיסים אמיתיים.

הרצה:
  python converse.py <קובץ-שיחה.json>

קובץ השיחה - המוח יוצר אותו, והוא מתעדכן בכל תור:
  {
    "engine": "<תיקיית המנוע - נתיב מוחלט, או יחסי לקובץ השיחה>",
    "product": "<slug של קובץ המוצר, למשל demo-project-sales>",
    "config": {"model": "claude-sonnet-5", "max_tokens": 6000, "slots": "fake" | "none",
               "avoid": ["..."]},
    "persona": "<שם הדמות - לדוח בלבד>",
    "card": {"profile": {"from_ad": "<על מה המודעה - כמו שהמנוע שומר מההודעה הראשונה>"}},
    "pending": "<ההודעה הבאה של הדמות>",
    "log": []
  }

בכל תור: ההודעה שב-pending נכנסת למנוע דרך think_checked - כולל הבדיקות בקוד והניסוח
מחדש, כמו בענן. התשובה נכתבת להיסטוריה בכרטיס ול-log, וה-pending מתרוקן. לפלט - JSON של
התור, בשביל השופט.

הכלי רק קורא את קוד המנוע, ולא משנה אותו (חוק ברזל 8 של המוח). כל תור הוא קריאה בתשלום
למודל של המנוע - מריצים רק באישור (חוק ברזל 12).
"""
import json
import os
import sys
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

IL = ZoneInfo("Asia/Jerusalem")
# מה שרץ בענן מ-13-09 (ENGINE_MODEL בשירות). בלי זה המנוע נופל לברירת המחדל שבקוד
DEFAULT_MODEL = "claude-sonnet-5"
# גם זה כמו בענן (ENGINE_MAX_TOKENS). ברירת המחדל בקוד, 1500, קטנה מדי למודל שחושב -
# בבדיקת העשן 14-09 תור 3 נחתך ב-1500 לפני שה-JSON נסגר
DEFAULT_MAX_TOKENS = 6000
FIELDS = ("stage", "handoff", "handoff_urgent", "missing_fact", "other_product",
          "book_slot", "send_image", "follow_up", "note")


def fail(msg):
    print(json.dumps({"error": msg}, ensure_ascii=False))
    sys.exit(1)


def load_engine(engine_dir, model, max_tokens):
    # המנוע קורא את המודל ואת התקרה כשהוא נטען - חייב לפני הייבוא
    os.environ["ENGINE_MODEL"] = model
    os.environ["ENGINE_MAX_TOKENS"] = str(max_tokens)
    try:
        from dotenv import load_dotenv
        # כמו ההרצה היבשה של המנוע: .env שלו, ואם אין - של סוכן ההשכרה. נטען, לא מודפס
        for env in (os.path.join(engine_dir, ".env"),
                    os.path.join(engine_dir, "..", "rental-leads", ".env")):
            if os.path.exists(env):
                load_dotenv(env)
                break
    except ImportError:
        pass
    if not os.getenv("ANTHROPIC_API_KEY"):
        fail("אין מפתח למודל - לא נמצא .env של המנוע")
    sys.path.insert(0, os.path.join(engine_dir, "src"))
    import engine
    import calendar_meetings  # רק חישוב מועדים מסעיף 5 - הגישה ליומן לא נקראת
    return engine, calendar_meetings


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        fail("שימוש: python converse.py <קובץ-שיחה.json>")
    conv_path = os.path.abspath(sys.argv[1])
    with open(conv_path, encoding="utf-8") as fh:
        conv = json.load(fh)

    incoming = (conv.get("pending") or "").strip()
    if not incoming:
        fail("אין הודעה ב-pending - הדמות עוד לא כתבה")

    engine_dir = conv.get("engine") or ""
    if not os.path.isabs(engine_dir):
        engine_dir = os.path.normpath(os.path.join(os.path.dirname(conv_path), engine_dir))
    if not os.path.exists(os.path.join(engine_dir, "src", "engine.py")):
        fail(f"לא נמצא מנוע ב-{engine_dir}")

    cfg = conv.get("config") or {}
    engine, calendar_meetings = load_engine(engine_dir, cfg.get("model") or DEFAULT_MODEL,
                                            cfg.get("max_tokens") or DEFAULT_MAX_TOKENS)
    product = engine.load_product(conv["product"])

    # מונה טוקנים לכל קריאה - הערכת העלות של הסבב הבא נשענת על מדידה, לא על ניחוש.
    # עוטף את הלקוח בזיכרון בלבד; קובץ המנוע לא משתנה
    usage = []
    real_client = engine._client

    def counted_client():
        client = real_client()

        def create(**kw):
            msg = client.messages.create(**kw)
            # סיבת העצירה - "max_tokens" אומר שהתשובה נחתכה לפני שה-JSON נסגר
            usage.append((msg.usage.input_tokens, msg.usage.output_tokens, msg.stop_reason))
            return msg
        return SimpleNamespace(messages=SimpleNamespace(create=create))
    engine._client = counted_client

    card = conv.setdefault("card", {})
    card.setdefault("name", "")
    card.setdefault("stage", "new")
    card.setdefault("profile", {})
    for k in ("history", "notes", "open_questions", "sent_images"):
        card.setdefault(k, [])

    slots = None
    st = calendar_meetings.settings(product)
    if st and cfg.get("slots", "fake") == "fake":
        # יומן ריק: המועדים לפי השעות בסעיף 5, באותו פורמט שהמנוע מקבל בענן
        slots = calendar_meetings.candidate_slots(st, [], datetime.now(IL))

    try:
        out, fixed = engine.think_checked(product, card, incoming, slots,
                                          avoid=tuple(cfg.get("avoid") or ()))
    except Exception as e:  # שגיאת API או JSON שבור - לדוח, לא קריסה
        fail(f"המנוע נכשל: {type(e).__name__}: {e} · הקריאות (קלט, פלט, עצירה): {usage}")
    if not out or not out.get("reply"):
        fail(f"המנוע לא החזיר תשובה תקינה · הקריאות (קלט, פלט, עצירה): {usage}")

    # אותו עדכון כרטיס כמו ב-run.py - כדי שהזיכרון של הסוכן יעבוד כמו בענן
    reply = out["reply"]
    card["history"] += [{"who": "lead", "text": incoming}, {"who": "agent", "text": reply}]
    card["stage"] = out.get("stage") or card["stage"]
    if out.get("note"):
        card["notes"].append(out["note"])
    for k, v in (out.get("learned") or {}).items():
        if k in engine.LEARN_KEYS and v:
            card["profile"][k] = v
    if out.get("missing_fact"):
        card["open_questions"].append(out["missing_fact"])
    booked = None
    if out.get("book_slot") not in (None, "", "null") and slots:
        want = str(out["book_slot"])[:16]
        booked = next((s for s in slots if s["start"].isoformat()[:16] == want), None)
        if booked:
            # בבדיקה לא קובעים ביומן - רק מסמנים בכרטיס, כמו אחרי קביעה
            card["meeting"] = {"label": booked["label"], "start": booked["start"].isoformat()}
    if out.get("send_image"):
        card["sent_images"].append(str(out["send_image"]))

    turn = {"lead": incoming, "agent": reply,
            "fixed": [engine.LABELS.get(k, k) for k in fixed],
            "out": {k: out.get(k) for k in FIELDS},
            "booked": booked["label"] if booked else None,
            "tokens": {"calls": len(usage), "in": sum(u[0] for u in usage),
                       "out": sum(u[1] for u in usage)}}
    conv.setdefault("log", []).append(turn)
    conv["pending"] = ""
    with open(conv_path, "w", encoding="utf-8") as fh:
        json.dump(conv, fh, ensure_ascii=False, indent=2, default=str)
    print(json.dumps(turn, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
