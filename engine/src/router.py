"""של מי הליד.

הוכרע 12-09 (דני): סוכן ההשכרה והמנוע רצים נפרד על אותו מספר, וכל אחד לוקח רק מי
שכתב את מילת הטריגר שלו. 13-09: לא חייב בהודעה הראשונה - מספיק שאף אחד עוד לא ענה לו.
14-09: גם בלי המשפט - לפי מה שכתב ("לקנות", "להשכרה"), ומי שלא כתב שום רמז מקבל פתיחה
מהסוכן הראשי. הכללים המלאים - STATUS.md, פרק 🔀.

הקובץ לא פונה לרשת. היסטוריית השיחה מגיעה מבחוץ, כדי שאפשר לבדוק את הכללים בלי Whapi.

אותו קובץ בדיוק יושב בשני הסוכנים - master-agent/src/router.py ו-rental-leads/src/router.py -
כי כל אחד נפרס מהתיקייה שלו. שינוי ← בשני המקומות. בדיקה בהשכרה מוודאת שהם זהים.
"""
import re

# טעמים וניקוד (U+0591 עד U+05C7) - בלי האותיות עצמן
NIQQUD = re.compile(f"[{chr(0x591)}-{chr(0x5C7)}]")
# פקודת האיפוס של דני והאישור שסוכן ההשכרה שולח עליה מגיעים בדקות שאחרי האיפוס.
# הם לא שיחה עם ליד, ולכן לא נחשבים "הודעה קודמת".
RESET_GRACE_SEC = 180
# הודעות שהמספר שולח לדני עצמו: 🔔 העברה, ☀️ סיכום, סיורים של מחר, אישור על פתק ועל איפוס.
# כשדני בודק מהנייד שלו הן יושבות באותה שיחה - והן לא תשובה של סוכן לליד
TO_NOAM = ("🔔", "☀️", "סיורים ", "נרשם. מעיין", "הכרטיס שלך אופס", "לא היה כרטיס לאפס",
           "השיחה של ", "לא נמצאה שיחה של ")
# בפתיחה שהסוכן הראשי שולח למי שכתב בלי שום רמז (דני, 14-09: "שלום, פנית אלינו למגדלי
# הפארק - כיצד אפשר לסייע?"). הודעה שיש בה את זה לא תופסת את השיחה - התשובה של הליד
# עוד צריכה להגיע לסוכן הנכון
OPENER_MARK = "כיצד אפשר לסייע"
# _hint: הרמז שייך לסוכן האחר
THEIRS = "theirs"


def normalize(text):
    """בלי ניקוד, בלי סימני פיסוק ובלי רווחים כפולים - שהמילה תיתפס גם אחרי הקלדה ידנית."""
    text = NIQQUD.sub("", text or "").lower()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text)).strip()


def hits(text, keyword):
    k = normalize(keyword)
    return bool(k) and k in normalize(text)


def after_keyword(text, keyword):
    """מה שכתוב אחרי מילת הטריגר באותה שורה - החלק שמשתנה בין מודעות.
    "הי אשמח לפרטים על רכישת דירה 6 חד'" ← "דירה 6 חד'". ריק אם אין."""
    words = normalize(keyword).split()
    if not words:
        return ""
    t = NIQQUD.sub("", text or "")
    m = re.search(r"[\W_]+".join(map(re.escape, words)), t, re.I)
    if not m:
        return ""
    return t[m.end():].split("\n")[0].strip(" ,.:-!?")[:60]


def _body(m):
    return ((m.get("text") or {}).get("body") or "").strip()


def claimable(chat_msgs, total, batch_ids, newest_ts, reset_ts=None, keywords=()):
    """האם השיחה עוד פנויה - אף אחד לא תפס אותה לפני ההודעות שבתור.

    תופס: הודעה שיצאה מהמספר (תשובה של סוכן, או של דני שענה ידנית), או הודעה קודמת
    של הליד עם מילת טריגר כלשהי (keywords - של כל הסוכנים).
    לא תופס: הודעה קודמת של הליד בלי מילה - ליד שכתב קודם משהו כללי ורק אחר כך את
    משפט הקמפיין נלקח (דני, 13-09). גם לא: הודעות עד האיפוס (AI אפס), הודעות לדני עצמו,
    והפתיחה (OPENER_MARK).
    chat_msgs - מה ש-Whapi החזיר, total - כמה הודעות יש בשיחה בסך הכול."""
    # איפוס שקרה אחרי ההודעות שבתור (שניהם נקראו באותו סבב) לא חל עליהן -
    # הן עוד חלק מהשיחה הישנה
    floor = reset_ts + RESET_GRACE_SEC if reset_ts and newest_ts > reset_ts else None

    def counts(ts):
        return floor is None or ts > floor

    for m in chat_msgs:
        ts = m.get("timestamp", 0)
        if m.get("id") in batch_ids or ts > newest_ts or not counts(ts):
            continue
        body = _body(m)
        if m.get("from_me"):
            if not (body.startswith(TO_NOAM) or OPENER_MARK in body):
                return False
        elif any(hits(body, k) for k in keywords):
            return False
    if total > len(chat_msgs):
        # יש הודעות ישנות ממה שנשלף - אי אפשר לדעת מה בהן. תופסות, אלא אם גם הישנה
        # שבנשלפות קודמת לאיפוס
        oldest = min((m.get("timestamp", 0) for m in chat_msgs), default=0)
        if counts(oldest):
            return False
    return True


def _hint(text, hints, other_hints, lead_agent):
    """מה הליד רוצה לפי המילים שלו: מוצר שלנו, THEIRS, או None כשאין רמז (או שיש שניים שלנו).
    גם קנייה וגם השכרה ← של הסוכן הראשי (המכירה - המטרה, ולקוח מכירה לא מקבל הצעת השכרה)."""
    ours = [p for p, words in hints.items() if any(hits(text, w) for w in words)]
    theirs = any(hits(text, w) for w in other_hints)
    if theirs and not (ours and lead_agent):
        return THEIRS
    return ours[0] if len(ours) == 1 else None


def route(card, text, products, other_keywords, is_free, hints=None, other_hints=(),
          lead_agent=False):
    """מחזיר (פעולה, מוצר, סיבה).

    card           - הכרטיס שלנו לטלפון הזה, או None
    products       - {מוצר: מילת טריגר} של המוצרים שהשירות הזה מחזיק
    other_keywords - מילות הטריגר של סוכנים אחרים על אותו מספר
    is_free        - פונקציה שמקבלת את כל מילות הטריגר ומחזירה claimable() על השיחה.
                     נקראת רק כשצריך, כי היא פונה ל-Whapi
    hints          - {מוצר: מילים} - מה הליד רוצה גם בלי משפט הטריגר ("לקנות", "להשכרה").
                     נבדק רק כשאין בהודעה שום משפט טריגר
    other_hints    - המילים של הסוכן האחר
    lead_agent     - הסוכן ששולח פתיחה למי שכתב בלי שום רמז, וממשיך איתו כשגם התשובה לא
                     ברורה. אצל דני - המכירה ("חתירה למטרה", 14-09)

    פעולות:
      mine   - ליד שלנו. סיבה = מילת טריגר של מוצר אחר באמצע השיחה ← העברה לדני
      new    - המילה שלנו, או רמז שלנו, והשיחה פנויה ← כרטיס חדש, המוצר ננעל
      claim  - כרטיס בלי מוצר (נכנס בלי מילה) כותב עכשיו את המילה או רמז שלנו - או קיבל
               פתיחה וענה משהו לא ברור, ואנחנו lead_agent - והשיחה עוד פנויה ← הכרטיס מקבל
               מוצר, והסוכן עונה
      open   - בלי מילה ובלי רמז, השיחה פנויה, ואנחנו lead_agent ← פתיחה קבועה
      orphan - שתי מילות טריגר בהודעה הראשונה ← לדני, הסוכן לא עונה
      skip   - לא שלנו
    """
    ours_kw = {p: k for p, k in products.items() if k}
    all_kw = list(ours_kw.values()) + list(other_keywords)
    ours = [p for p, k in ours_kw.items() if hits(text, k)]
    theirs = [k for k in other_keywords if hits(text, k)]
    hint = None if ours or theirs else _hint(text, hints or {}, other_hints, lead_agent)

    if card:
        mine = card.get("product")
        if not mine:
            if ours or theirs:
                pick = ours[0] if len(ours) == 1 and not theirs else None
            elif hint and hint != THEIRS:
                pick = hint
            elif (hint is None and lead_agent and card.get("stage") == "opened"
                  and len(ours_kw) == 1):
                # קיבל פתיחה וענה משהו לא ברור - הסוכן הראשי ממשיך את השיחה בעצמו
                pick = next(iter(ours_kw))
            else:
                pick = None
            if pick and is_free(all_kw):
                return "claim", pick, None
            if theirs or hint == THEIRS:
                return "skip", None, "לפי מה שכתב - של סוכן אחר"
            return "skip", None, "נכנס בלי מילת טריגר - אצל דני"
        other = [k for p, k in ours_kw.items() if p != mine] + list(other_keywords)
        hit = next((k for k in other if hits(text, k)), None)
        return "mine", mine, (f"מילת טריגר של מוצר אחר: {hit}" if hit else None)

    if theirs and not ours:
        return "skip", None, f"מילת טריגר של סוכן אחר: {theirs[0]}"
    if hint == THEIRS:
        return "skip", None, "לפי מה שכתב - של סוכן אחר"
    if not is_free(all_kw):
        return "skip", None, "כבר ענו לו בשיחה, או שכתב קודם מילת טריגר - לא שלנו"
    if len(ours) == 1 and not theirs:
        return "new", ours[0], None
    if ours or theirs:
        return "orphan", None, "שתי מילות טריגר בהודעה הראשונה"
    if hint:
        return "new", hint, None
    if lead_agent:
        return "open", None, "הודעה ראשונה בלי מילת טריגר"
    return "skip", None, "הודעה ראשונה בלי מילת טריגר - הפתיחה אצל הסוכן הראשי"
