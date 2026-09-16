"""קריאה ושליחה מול וואטסאפ דרך Whapi.

הועתק מ-rental-leads/src/whapi.py (12-09), ונוספה chat_messages. שני הסוכנים רצים
נפרד על אותו מספר (הוכרע 12-09) וכל אחד נפרס מהתיקייה שלו, ולכן אין ביניהם import.
"""
import os
import requests

BASE = os.getenv("WHAPI_URL", "https://gate.whapi.cloud").rstrip("/")
TOKEN = os.getenv("WHAPI_TOKEN", "")
TIMEOUT = 30


def _headers():
    return {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


# וואטסאפ מזהה שולחים לפעמים ב-LID (מזהה פנימי) במקום במספר טלפון.
# בלי תרגום, הרשימה הלבנה לא מזהה איש והסוכן לא עונה לאף אחד.
_LID_CACHE = {}


def resolve_lid(lid):
    """מתרגם מזהה LID למספר טלפון. מחזיר None אם נכשל."""
    key = lid.split("@")[0]
    if key in _LID_CACHE:
        return _LID_CACHE[key]
    try:
        r = requests.get(f"{BASE}/contacts/ids/{key}@lid",
                         headers=_headers(), timeout=TIMEOUT)
        if r.status_code == 200:
            phone = r.json().get("id", "").split("@")[0]
            if phone.isdigit():
                _LID_CACHE[key] = phone
                return phone
    except Exception:
        pass
    _LID_CACHE[key] = None
    return None


def health():
    """בודק שהחיבור לוואטסאפ חי. מחזיר (תקין, תיאור)."""
    r = requests.get(f"{BASE}/health", headers=_headers(), timeout=TIMEOUT)
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    d = r.json()
    ok = d.get("status", {}).get("text") == "AUTH"
    return ok, d.get("status", {}).get("text", "?")


def fetch_messages(limit=50):
    """מושך הודעות אחרונות. מחזיר רק הודעות נכנסות מאנשים - לא קבוצות, לא שלנו."""
    r = requests.get(
        f"{BASE}/messages/list",
        headers=_headers(),
        params={"count": limit},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    out = []
    for m in r.json().get("messages", []):
        # from_me = הודעה שיצאה מהמספר - של סוכן זה או של סוכן ההשכרה
        if m.get("from_me"):
            continue
        chat = m.get("chat_id", "")
        if "@g.us" in chat:
            continue
        # type unknown / null-text = הודעות פרוטוקול של וואטסאפ, לא כתב אותן אדם
        if m.get("type") != "text":
            continue
        body = ((m.get("text") or {}).get("body") or "").strip()
        if not body:
            continue

        sender = m.get("from", "")
        phone = sender.split("@")[0]
        if "@lid" in sender:
            resolved = resolve_lid(sender)
            if not resolved:
                continue  # לא הצלחנו לזהות מי זה - לא עונים לזר
            phone = resolved

        out.append({
            "id": m.get("id"),
            "phone": phone,
            "name": m.get("from_name") or "",
            "text": body,
            "ts": m.get("timestamp", 0),
            "chat_id": chat,
        })
    out.sort(key=lambda x: x["ts"])
    return out


def chat_messages(chat_id, count=20):
    """ההודעות האחרונות בשיחה אחת (מהחדשה לישנה) ומספר ההודעות הכולל בה.

    כוללת הודעות שיצאו מהמספר - גם של סוכן ההשכרה. כך יודעים אם ליד כבר מדבר
    עם סוכן אחר, בלי גישה לכרטיסים שלו."""
    r = requests.get(f"{BASE}/messages/list/{chat_id}", headers=_headers(),
                     params={"count": count}, timeout=TIMEOUT)
    r.raise_for_status()
    d = r.json()
    return d.get("messages", []), d.get("total", 0)


def send_text(to_phone, body):
    """שולח הודעת טקסט. to_phone בפורמט 9725XXXXXXXX."""
    r = requests.post(
        f"{BASE}/messages/text",
        headers=_headers(),
        json={"to": to_phone, "body": body},
        timeout=TIMEOUT,
    )
    ok = r.status_code in (200, 201)
    return ok, (r.json() if ok else f"HTTP {r.status_code}: {r.text[:200]}")


def send_image(to_phone, path, caption=""):
    """שולח תמונה מקובץ מקומי, כ-base64 בתוך ההודעה - כמו בסוכן ההשכרה, שם נקודת
    ההעלאה של Whapi (/media) החזירה שגיאת שרת בבדיקה."""
    import base64
    import mimetypes
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    r = requests.post(
        f"{BASE}/messages/image",
        headers=_headers(),
        json={"to": to_phone, "media": f"data:{mime};base64,{b64}", "caption": caption},
        timeout=90,
    )
    ok = r.status_code in (200, 201)
    return ok, (r.json() if ok else f"HTTP {r.status_code}: {r.text[:200]}")
