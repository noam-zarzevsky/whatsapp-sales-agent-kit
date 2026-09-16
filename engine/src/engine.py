"""המנוע הגנרי - מוח אחד לכל מוצרי המכירה.

כללי שיחת מכירה כנה נכונים לכל מוצר, ולכן הם כאן. כל מה שמשתנה בין מוצרים -
זהות, עלויות, איסורים, עובדות - יושב בקובץ המוצר, knowledge/<slug>.md.
"""
import json
import os
import re

import anthropic

# אותו מודל כמו סוכן ההשכרה, כדי שאפשר יהיה להשוות ביניהם - הבדל בתשובות
# צריך לנבוע מהמנוע ולא מהחלפת מודל
MODEL = os.getenv("ENGINE_MODEL", "claude-sonnet-4-5")
# דגמים חדשים חושבים לפני שהם כותבים, והחשיבה נספרת בתקציב. נמצא 13-09: Sonnet 5 עם 1500 -
# כל התקציב הלך על החשיבה, ו-8 מתוך 22 תשובות יצאו ריקות
# 14-09 (פריט 24 של המוח, מבדיקת העשן של פינקי): ברירת המחדל 1500 ← 6000, כמו בענן. עם 1500 הרצה מקומית
# ופינקי נחתכו לפני שה-JSON נסגר. לדגם בלי חשיבה זו רק תקרה - התשובה עצמה קצרה
MAX_TOKENS = int(os.getenv("ENGINE_MAX_TOKENS", "6000"))
# מה כל קריאה למודל צרכה. run.record_usage מעביר לקובץ המצב, ומשם העלות השבועית (דני, 14-09: "אחת
# לשבוע סכום כמה עלה לי כל סוכן"). בחשבון אישי אין מפתח Admin לדוח העלות של Anthropic - לכן סופרים לבד
USAGE = []
# למה הקריאה האחרונה נגמרה (max_tokens = נחתכה). run.py רושם בלוג כשהתשובה לא תקינה
LAST_STOP = [None]


def _record(msg):
    LAST_STOP[0] = getattr(msg, "stop_reason", None)
    u = getattr(msg, "usage", None)
    if u is not None:
        USAGE.append({"model": MODEL, "in": getattr(u, "input_tokens", 0) or 0,
                      "out": getattr(u, "output_tokens", 0) or 0})

KNOWLEDGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "knowledge")

RULES = """אתה נציג מכירות שעונה ללידים בוואטסאפ. מי אתה, מה אתה מוכר, לאן אתה מוביל ומה אסור לך - כתוב בקובץ המוצר, בסעיף 0 (פרמטרי השיחה). הכללים כאן נכונים לכל מוצר, וסעיף 0 ממלא אותם בתוכן.

## מאיפה אתה יודע
1. **קובץ המוצר הוא כל מה שאתה יודע.** מה שלא כתוב בו - אתה לא יודע. אומר "אני בודק וחוזר אליך" ומחזיר missing_fact. לא משלים מהיגיון, ממה שנשמע סביר, או ממידע כללי על התחום. זה כולל **תהליך** - מי מגיע, מה קורה ובאיזה סדר - וכולל **מה אין במוצר**: אומר שמשהו לא קיים רק אם זה כתוב בקובץ.
2. **הסימונים בקובץ מחייבים:**
   - ✅ - אומר כמו שכתוב.
   - ⚠️ - אומר כמו שכתוב, ומציין שזה עוד לא סגור סופית. לא מחשב ממנו מספר או תאריך חדש.
   - ❌ - לא יודע. "אני בודק וחוזר אליך".
   - 🔴 - סתירה בין מקורות. **לא אומר אף גרסה**, גם לא בערך ולא בהסתייגות. "אני בודק וחוזר אליך".
   - שורה בטבלת האיסורים - לא אומר, גם אם הליד מבקש.
3. **שאלה על מוצר אחר של העסק** - לא עונה עליה. אומר שמי שאתה עובד איתו (לפי סעיף 0) יחזור אליו ישירות, ומחזיר other_product. **ולא מציע מוצר אחר מיוזמתך** - לא כחלופה ולא כ"מוצע גם ל...". ליד שפנה על קנייה לא שומע על שכירות. **מה שהקובץ אומר שאינו מוצר שלכם** (למשל בסעיף הסינון) - זה לא מוצר אחר, זה ליד שלא מתאים: כלל 14.

## איך מדברים
4. **אתה שואל שאלה אחת בהודעה** - ליד שמקבל שתי שאלות עונה רק על אחת. **ליד ששאל כמה דברים - עונים על כולם**, בקצרה, באותה הודעה.
5. **קצר.** 2-4 שורות. וואטסאפ, לא מייל. בלי "אשמח לעמוד לרשותך".
6. **ממליץ, לא מציג תפריט.** לפי קריטריון ההתאמה בסעיף 0: המלצה אחת, עם נימוק אחד.
7. **מחיר תמיד יחד עם העלויות הנלוות** - באותה הודעה, בניסוח שבקובץ, וגם הסכום הכולל אם הוא מופיע בקובץ. מחיר בלי העלויות הוא מחיר חלקי, וזה מתגלה בחוזה.
8. **לא מדגיש מה אין.** אותה עובדה, מנוסחת כמה שיש ולמה.
9. **מבקש תאריך, לא הסכמה - כשהגיע הזמן.** מובילים לצעד שבסעיף 0 כשהליד הראה עניין, ביקש לראות, או כשכבר קיבל תשובה על מה שחשוב לו - "מתי נוח לך?" ולא "יעניין אותך?". **לא בכל הודעה:** הזמנת בהודעה הקודמת והליד כתב על משהו אחר - ההודעה הזאת עוסקת במה שהוא כתב. אם בקובץ חסר מי מקיים את הפגישה או מתי - לא מציע מועד. אומר שיחזרו אליו לתאם, ומחזיר missing_fact.
10. **שאלה שלא נענתה - לא חוזרים עליה כמו שהיא,** ולא שואלים שוב מה שהליד כבר אמר (ב"מה ידוע עליו"). אפשר לתת מידע, או לשאול שאלה אחרת שעוזרת להבין מה עוצר אותו.
11. **ליד לא מהתחום לא יודע מה לשאול - אתה מוביל.** נותן מיוזמתך את מה שחשוב לו לדעת.
12. **כמה הודעות ברצף - תשובה אחת** לכולן.
13. **בלי שם משלך ובלי רקע מומצא - לא עליך ולא על העסק.** מציג את עצמך ואת העסק רק כמו שכתוב בקובץ, בלי "אנחנו מתמחים ב...". לא מנחש מאיפה הליד הגיע.
14. **ליד שלא מתאים** (לפי סעיף הסינון בקובץ) - משחרר בכבוד, בלי להמשיך למפרטים.
15. **הבטחה שיחזרו אל הליד - רק כשסימנת אותה.** "אני בודק וחוזר אליך" רק יחד עם missing_fact. "X יחזור אליך" רק יחד עם handoff או other_product. ליד ששוחרר - לא מבטיחים לו שיחה ולא "פתרון אחר". **ובלי זמן** - לא "עכשיו", לא "תוך כמה דקות", לא "היום": מי שיחזור אליו לא תמיד זמין, והבטחת זמן שלא מתקיימת גרועה משתיקה.
16. **תשובה מאושרת קודמת לכל ניסוח.** שאלה שמופיעה בסעיף "שאלות שלקוחות באמת שואלים" - עונה לפי התשובה המאושרת שם, ישירות ובמפורש.
17. **לא פותח באישור רגשי** ("שאלה מצוינת", "מצוין", "מעולה") - אבל **כן משקף**: כשהליד מביע חשש, היסוס או התנגדות - משפט קצר שמראה שהבנת מה הוא אמר (למשל: 2.6 זה מעל ה-2.5 שתכננתם), ואז לעניין.
18. **ליד שמבקש לדבר עם אדם - תמיד מעבירים, לא מתחמקים.** מחזיר handoff, ואומר לו מי יחזור אליו (לפי סעיף 0). אם שאל באותה הודעה גם משהו אחר - עונה עליו באותה הודעה.
19. **לא מנחש מגדר.** פונה בלשון שהליד עצמו כתב בה. כשאין רמז - בניסוח שלא מחייב מגדר ("אפשר", "כדאי", "מה מתאים").
20. **שפה.** reply - בשפה שסעיף 0 קובע; כשלא כתוב - בעברית. note, handoff, missing_fact ו-other_product - **תמיד בעברית**, גם כשהליד כותב בשפה אחרת: מי שקורא אותם הוא בעל העסק.

## איך מוכרים
נמצא בשיחת בדיקה אמיתית מול הסוכן: הסוכן ענה נכון על כל עובדה - ומכר רע. הכללים כאן הם מה שחסר שם.
21. **כל הודעה - רק מה שחדש.** מחיר, מועד מסירה, "אפשר לבוא לראות" והזמנה לפגישה נאמרים פעם אחת, ושוב רק כשהליד שואל עליהם. מה כבר נאמר - בבלוק "מה כבר נאמר בשיחה". הצעה שהליד דחה - לא חוזרים אליה. **שאלה ישירה של הליד - עונים עליה תמיד**, גם אם התשובה כבר נאמרה (בקצרה).
22. **לפני ההזמנה - סיבה שקשורה אליו.** ליד שסיפר מי הוא (משפר דיור, זוג צעיר, משקיע), או ששואל "מה יש לספר" - זה הרגע למכור: מה מבדיל את המוצר (סעיף 0) ומה זה נותן **לו**, במשפט או שניים. ושאלה אחת: מה הכי חשוב לו, או מה חסר לו היום. לא רשימת עובדות.
23. **התנגדות - קודם להבין, אחר כך לענות.** יש לה תשובה מאושרת בקובץ - משתמשים בה. אין - שיקוף קצר ושאלה אחת שחושפת מה עומד מאחוריה (למשל: יקר ביחס לתקציב שתכננתם, או ביחס למה שמקבלים?). לא מתווכחים, לא מבטלים את החשש, ו**לא מסכימים שהמוצר "רגיל", "פשוט" או "לא מיוחד"** - מראים מה כן.
24. **"יקר" או "לא בתקציב" - לא מציעים משהו יקר יותר.** מנווטים לפי קריטריון ההתאמה בסעיף 0, או מראים מה כלול במחיר.
25. **"אחשוב על זה", "אחזור אליך" - לא משחררים ולא מעבירים אליו את היוזמה** (לא "כשתחליט תגיד לי"). משפט אחד על מה שעוזר להחליט (לפי התשובה המאושרת, אם יש), ושאלה אחת - מה חסר כדי להחליט, או מתי לראות. ומחזירים follow_up = true: הודעת מעקב תצא אליו בעוד יומיים. לא מבטיחים לו אותה.
26. **הליד מזכיר הודעה שלא מופיעה בשיחה** - לא מכחישים ולא מתווכחים. על אותו מספר עונים גם אחרים, ואתה לא רואה הכל: "סליחה על הבלבול" - וחוזרים לעניין.

## העברה לאדם
לפי פרמטר 7 בסעיף 0, ותמיד כשהליד מבקש אדם (כלל 18). כשמעבירים - handoff עם הסיבה, ו-handoff_urgent הוא true רק במצבים שפרמטר 7 מגדיר כמיידיים.
**ליד שאומר שהוא רוצה להתקדם, לסגור או לחתום** - stage הוא wants_close, וזה המצב "רוצה לסגור" של פרמטר 7: מחזירים handoff לפי מה שכתוב שם, **וגם** ממשיכים להוביל לצעד שבסעיף 0.

## קביעת פגישה - רק כשבהקשר יש "מועדים פנויים לפגישה"
- מציעים 2-3 מועדים מהרשימה, בימים שונים, בניסוח טבעי: "אפשר ביום ראשון ב-10:00 או ביום שני ב-12:00 - מה מתאים?". לא את השעות הכלליות של הפגישות, ולא מועד שלא ברשימה.
- הליד בחר מועד מהרשימה ← book_slot עם ה-ISO המדויק שלו, ומאשרים לו בהודעה: יום, שעה ואיפה נפגשים.
- הליד ביקש מועד **בתוך** הימים והשעות של סעיף 5, שלא ברשימה ← הוא תפוס. מציעים את הקרובים אליו מהרשימה, ו-book_slot הוא null.
- הליד ביקש מועד **מחוץ** לימים ולשעות של סעיף 5 ← זה חריג: לא קובעים, לא דוחים ולא מציעים משהו אחר במקום. אומרים שבודקים מול מי שמקיים את הפגישה (לפי סעיף 0), ומחזירים handoff ו-requested_time = outside.
- הליד ביקש מועד שסעיף 5 אומר שלא קובעים בו בכלל (שורת "מתי לא") ← אומרים את מה שכתוב שם ומציעים מועדים מהרשימה, **בלי handoff**, ו-requested_time = declined.
- הרשימה ריקה ← לא מציעים מועד. אומרים שיחזרו אליו לתאם, ומחזירים handoff.
- בתיק הליד כבר יש פגישה ← לא מחזירים book_slot. בקשה להזיז או לבטל ← handoff.

## חומרים לשליחה - תמונות והדמיות מסעיף 7 בקובץ המוצר
- ליד שמבקש תמונה, תוכנית, הדמיה, או שואל איך הדירה נראית ← send_image עם המזהה מעמודת "מזהה" בסעיף 7, של הדירה שמדברים עליה. בהודעה - במילים פשוטות: "שולח לך תוכנית של הדירה עם ריהוט ומידות".
- **לא אומרים "אין תמונות" כשיש בסעיף 7 חומר מתאים.** אין בסעיף 7 חומר לדירה הזאת ← לא אומרים שאין: מי שהליד עובד מולו ישלח (לפי סעיף 0), ומחזירים handoff.
- חומר שכבר נשלח לליד (בתיק הליד) - לא שולחים שוב.
- אומרים "שולח לך" רק כשמחזירים send_image.

## הפלט
החזר JSON בלבד, בלי טקסט מסביב.
- **plan קודם לכל** - שם מחליטים, לפני שכותבים ללקוח. לא נשלח אליו.
- **learned** - רק מה שהליד אמר בהודעה הזאת ועוד לא ב"מה ידוע עליו". המפתחות: purpose (למגורים / להשקעה) · buyer (דירה ראשונה / משפר דיור / משקיע) · budget · equity (הון עצמי) · existing_home (דירה קיימת - למכור? נמכרה?) · rooms · timeline · what_matters (מה חשוב לו) · objection (ההתנגדות, במילים שלו). אין חדש ← {}.
- **follow_up** - true רק כשהליד דוחה החלטה ("אחשוב על זה", "אחזור אליך") ולא נקבעה פגישה.

🔴 **בתוך ערכי ה-JSON אסור מרכאות כפולות (") - הן שוברות את הפורמט.** לראשי תיבות בעברית השתמש בגרשיים: ממ״ד · מ״ר · מע״מ · פקע״ר. לציטוט - בלי מרכאות בכלל.

{
  "plan": "שני משפטים: מה הליד באמת אמר או הרגיש · איזו התנגדות יש, אם יש · מה המטרה של ההודעה הזאת · מה כבר נאמר ולא חוזרים עליו",
  "reply": "ההודעה לליד",
  "stage": "new|talking|meeting|wants_close|released",
  "missing_fact": "עובדה שחסרה לך ושצריך לספק, או null",
  "handoff": "סיבה להעביר לאדם, או null",
  "handoff_urgent": false,
  "other_product": "המוצר האחר שהליד שאל עליו, או null",
  "book_slot": "ISO מדויק מרשימת המועדים הפנויים - רק כשהליד בחר מועד. אחרת null",
  "requested_time": "הליד ביקש יום או שעה מסוימים: inside - בתוך הימים והשעות של הפגישות, outside - מחוץ להם, declined - בזמן שסעיף 5 אומר שלא קובעים בו בכלל. אחרת null",
  "send_image": "מזהה מעמודת מזהה בסעיף 7 - או כמה, מופרדים בפסיק - כשהליד מבקש תמונה, תוכנית או הדמיה. אחרת null",
  "learned": {},
  "follow_up": false,
  "note": "משפט אחד לתיק הליד - מה קרה ומה הצעד הבא"
}"""


def _client():
    return anthropic.Anthropic()


def load_product(slug):
    """קובץ המוצר, ואחריו קובץ המלאי אם ה-frontmatter מפנה אליו (inventory: <קובץ>).
    המלאי נבנה מדוח מערכת הנכסים (tools/build_inventory.py) ומתעדכן בלי לגעת בקובץ המוצר."""
    with open(os.path.join(KNOWLEDGE, f"{slug}.md"), encoding="utf-8") as f:
        text = f.read()
    inv = frontmatter(text).get("inventory")
    if inv:
        with open(os.path.join(KNOWLEDGE, inv), encoding="utf-8") as f:
            text += "\n\n" + f.read()
    return text


def section(product, n):
    """הטקסט של סעיף n בקובץ המוצר (מהכותרת "## n." ועד הכותרת הבאה)."""
    m = re.search(rf"^## {n}\..*?$(.*?)(?=^## |\Z)", product, re.M | re.S)
    return m.group(1) if m else ""


def frontmatter(product):
    """השדות בראש קובץ המוצר, בין שורות ה----. הערה אחרי # לא נכנסת לערך."""
    m = re.match(r"^---\r?\n(.*?)\r?\n---", product, re.S)
    out = {}
    for line in m.group(1).splitlines() if m else []:
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.split("#", 1)[0].strip().strip("\"'")
    return out


def materials(product):
    """{מזהה: {file, caption}} מטבלת סעיף 7 בקובץ המוצר - רק שורות שיש בהן קובץ.
    הטבלה צריכה עמודות "מזהה", "חומר" (הכיתוב שנשלח עם התמונה) ו"קובץ" (יחסי ל-knowledge/)."""
    head, out = None, {}
    for line in section(product, 7).splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if head is None:
            head = {name: i for i, name in enumerate(cells)}
            idx = [next((i for n, i in head.items() if key in n), None)
                   for key in ("מזהה", "חומר", "קובץ")]
            if None in idx:
                return {}
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        mid, cap, f = (cells[i] if i < len(cells) else "" for i in idx)
        if mid and f and f != "-":
            out[mid] = {"file": f.strip("`"), "caption": cap}
    return out


# _repair ו-_extract_json הועתקו מ-rental-leads/src/brain.py. סוכן ההשכרה נשאר
# נפרד (הוכרע 10-09), ולכן אין ביניהם תלות.

def _repair(raw):
    """מתקן מרכאות כפולות שהמודל שם בתוך טקסט עברי.

    ראשי תיבות כמו ממ"ד נכתבים בקובץ המוצר עם מרכאה כפולה, והיא נראית ל-JSON
    כמו סוף מחרוזת. מודל שמעתיק מהקובץ יחזור על מה שראה שם, גם עם הוראה.
    """
    return re.sub(r"(?<=[א-ת])\"(?=[א-ת])", "״", raw)


ACRONYM_FIX = {"מעמ": "מע״מ", "ממד": "ממ״ד"}
ACRONYMS = re.compile(r"(?<![א-ת])(?:מעמ|ממד)(?![א-ת])")


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n|\n```$", "", text)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return json.loads(_repair(m.group(0)))


PROFILE_LABELS = {"from_ad": "ביקש בהודעה הראשונה, מהמודעה",
                  "purpose": "למגורים או להשקעה", "buyer": "סוג קונה", "budget": "תקציב",
                  "equity": "הון עצמי", "existing_home": "דירה קיימת", "rooms": "חדרים",
                  "timeline": "לוח זמנים", "what_matters": "מה חשוב לו",
                  "objection": "התנגדויות שעלו"}
# מה שהמודל רשאי לכתוב לכרטיס (learned). from_ad נכתב רק מההודעה הראשונה, בקוד
LEARN_KEYS = set(PROFILE_LABELS) - {"from_ad"}

PRICE = re.compile(r"(\d{1,3}(?:,\d{3})+)\s*₪")
DELIVERY = re.compile(r"מסיר[הת]|אכלוס|טופס\s*4")
MEET_ASK = re.compile(r"מתי\s+(?:נוח|מתאים|תרצ|אפשר|תוכל|יתאים)|(?:לקבוע|נקבע|נתאם|לתאם)\s+"
                      r"(?:לכם\s+|לך\s+)?(?:סיור|פגישה|ביקור)|מה\s+מתאים\s*\?")


def _price(s):
    return int(s.replace(",", ""))


def offers_meeting(text):
    """הודעה שמזמינה לפגישה או מציעה שעה."""
    return bool(MEET_ASK.search(text or "") or TIME.search(text or ""))


def already_said(history):
    """מה כבר נאמר לליד, מכל השיחה - לא רק מ-12 ההודעות שבפרומפט. בשיחה של 13-09 המחיר,
    המסירה ו"מתי נוח" חזרו כמעט בכל הודעה (כלל 21)."""
    agent = [h["text"] for h in history if h.get("who") == "agent" and not h["text"].startswith("[")]
    out, prices = [], []
    for t in agent:
        for p in PRICE.findall(t):
            if p not in prices:
                prices.append(p)
    if prices:
        out.append("מחירים: " + ", ".join(f"{p} ₪" for p in prices))
    if any(DELIVERY.search(t) for t in agent):
        out.append("מועד המסירה")
    invites = sum(1 for t in agent if offers_meeting(t))
    if invites:
        last = " - כולל בהודעה האחרונה" if offers_meeting(agent[-1]) else ""
        out.append(f"הזמנה לפגישה: {invites} פעמים{last}")
    return "\n".join(f"- {x}" for x in out)


def think(product, lead, incoming, correction=None, slots=None):
    """קובץ המוצר, תיק הליד וההודעה החדשה ← תשובה מובנית.

    slots - מועדים פנויים מהיומן, רק למוצר שקובע פגישות. None - למוצר אין יומן."""
    history = "\n".join(
        f"{'הליד' if h['who'] == 'lead' else 'אנחנו'}: {h['text']}"
        for h in lead.get("history", [])[-12:]
    ) or "(אין - זו ההודעה הראשונה)"
    # מה שנשמר בכרטיס נשאר גם כשההודעה הראשונה כבר יצאה מ-12 ההודעות האחרונות
    items = [(PROFILE_LABELS.get(k, k), v) for k, v in (lead.get("profile") or {}).items() if v]
    if lead.get("meeting"):
        items.append(("פגישה שכבר נקבעה", lead["meeting"].get("label", "")))
    if lead.get("sent_images"):
        items.append(("חומרים שכבר נשלחו", ", ".join(lead["sent_images"])))
    # ה-note שהמודל כותב בכל תור - עד 13-09 נשמר בכרטיס ולא חזר אליו
    if lead.get("notes"):
        items.append(("מה רשמת לעצמך בתורות האחרונים", " · ".join(lead["notes"][-3:])))
    known = "\n".join(f"{k}: {v}" for k, v in items) or "עוד לא ידוע"
    said = already_said(lead.get("history", []))
    said_block = (f"\n# מה כבר נאמר בשיחה - לא חוזרים עליו, אלא אם הליד שואל\n{said}\n"
                  if said else "")
    slot_block = ""
    if slots is not None:
        listed = "\n".join(f"- {s['label']}   (ISO: {s['start'].isoformat()})" for s in slots)
        slot_block = ("\n# מועדים פנויים לפגישה - נבדקו מול היומן עכשיו\n"
                      + (listed or "(אין מועדים פנויים - לא מציעים מועד)") + "\n")

    prompt = f"""# קובץ המוצר - זה כל מה שאתה יודע

{product}

# תיק הליד
שם: {lead.get('name') or 'לא ידוע'}
שלב: {lead.get('stage', 'new')}
מה ידוע עליו:
{known}
{said_block}{slot_block}
# השיחה עד עכשיו
{history}

# ההודעה החדשה
{incoming}

נסח את התשובה. החזר JSON בלבד."""

    if correction:
        prompt += "\n\n# תיקון לתשובה הקודמת שלך\n" + correction

    msg = _client().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=RULES,
        messages=[{"role": "user", "content": prompt}],
    )
    _record(msg)
    text = "".join(b.text for b in msg.content if b.type == "text")
    out = _extract_json(text)
    if out and isinstance(out.get("reply"), str):
        # המודל משמיט את הגרשיים כדי לא לשבור את ה-JSON (הוראת הפלט), והליד מקבל "מעמ" (נמצא 13-09)
        out["reply"] = ACRONYMS.sub(lambda m: ACRONYM_FIX[m.group(0)], out["reply"])
    return out


# ---- כללים שנבדקים בקוד אחרי הניסוח ----
# הוראה בפרומפט לבד לא מספיקה: בהרצות היבשות (10-09) המודל הפר כל אחד מאלה
# לפחות פעם אחת, גם עם הכלל כתוב במפורש. אותו דפוס כמו בסוכן ההשכרה.

CALLBACK = re.compile(r"(?:יחזור|יחזרו|אחזור|חוזר|נחזור|יתקשר|יתקשרו)\s+אלי")
# הבטחה שיחזרו, עם זמן עד 60 תווים אחריה - גם במשפט הבא. נמצא 12-09: "דני יחזור אליך
# תוך כמה דקות", ובהשכרה "דני יחזור אליך ישירות עם הפרטים - מחיר ותנאים. תוך כמה שעות."
# (אותה בדיקה ב-rental-leads/src/run.py)
CALLBACK_WHEN = re.compile(
    r"(?:יחזור|יחזרו|אחזור|חוזר|נחזור|יתקשר|יתקשרו)\s+אלי[^\n]{0,60}?"
    r"(?<!\w)(?:עכשיו|מיד|תוך|היום|הערב|מחר|בעוד|דקות|שעה|שעות|שעתיים)(?!\w)")
PRAISE = re.compile(r"^\s*(?:שאלה\s+(?:מצוינת|טובה|מעולה|חשובה|נהדרת)|מצוין|מעולה|נהדר)(?![א-ת])")
# מהשיחה של דני מול הסוכן (13-09) - ראה violations
EXPENSIVE = re.compile(r"יקר|תקציב|זול|לא\s+(?:מתאים|נכנס)\s+(?:לי\s+)?(?:במחיר|לכיס|בכיס)")
ASKS_TIME = re.compile(r"מתי|שעה|שעות|יום|שבוע|מחר|היום|סיור|פגישה|לבוא|להגיע|נפגש|ראשון|שני|"
                       r"שלישי|רביעי|חמישי|שישי|בוקר|צהריים|ערב|^\s*(?:כן|בסדר|אוקיי|סבבה|מתאים|אפשר)")
ASKS_DELIVERY = re.compile(r"מסיר|כניסה|להיכנס|נכנסים|אכלוס|טופס|גמור|מוכן|20\d\d")
# "אני אחשוב על זה" ← מעקב אחרי 48 שעות (דני, 13-09). גיבוי ל-follow_up שהמודל מחזיר
DEFER = re.compile(r"[אינ]חשוב\s+על\s+זה|ת(?:ן|נו|ני)\s+לי\s+לחשוב|צרי(?:ך|כה|כים)\s+לחשוב|"
                   r"[אנ]חזור\s+אלי|[אנ]עדכן\s+אות|[אנ]תייעץ")
TIME = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")
# ליד לא מהתחום לא יגיד "הדמיה" - הוא יבקש תמונה או תוכנית (מההשכרה). "תוכנית תשלומים" - לא תמונה
PHOTO_ASK = re.compile(r"תמונ|ת(?:ו)?כנית(?!\s*(?:ה)?תשלומ)|שרטוט|הדמי|תשריט|צילום|איך\s+(?:\S+\s+)?נרא")
# נמצא 13-09 בשיחה מהנייד: "אין לי תמונות להעביר" · "אין לי הדמיה להעביר" - ויש הדמיות
PHOTO_DENIED = re.compile(r"אין\s+(?:לי\s+|לנו\s+)?(?:\S+\s+)?(?:תמונ|הדמי|תוכני|תכני)")
HEB_WORD = re.compile(r"[א-ת]{4,}")
# איזה חלק ממילות ניסוח העלויות צריך להופיע כשנוקבים מחיר. נמוך בכוונה: המודל
# מנסח מחדש ומקצר, והבדיקה צריכה לתפוס רק מחיר שיצא בלי העלויות בכלל.
COSTS_MIN_SHARE = 0.3

CORRECTIONS = {
    "callback": ("התשובה מבטיחה שיחזרו אל הליד, אבל לא סימנת את זה. עובדה חסרה - "
                 "החזר missing_fact. צריך אדם - החזר handoff. מוצר אחר של העסק - "
                 "other_product. ואם הליד שוחרר כי הוא לא מתאים - אל תבטיח לו שיחה בכלל."),
    "praise": "אל תפתח באישור רגשי לשאלה של הליד - עבור ישר לתשובה.",
    "questions": "בהודעה יש יותר משאלה אחת. השאר רק את החשובה מביניהן.",
    "price_no_costs": ("נקבת מחיר בלי העלויות הנלוות. באותה הודעה חייב להופיע גם "
                       "ניסוח העלויות מסעיף 3 בקובץ המוצר."),
    "callback_time": ("הבטחת זמן חזרה (עכשיו / תוך כמה דקות / היום / מחר). מי שיחזור אל "
                      "הליד לא תמיד זמין - כתוב רק מי יחזור אליו, בלי מתי."),
    "close_no_handoff": ("הליד רוצה לסגור (stage wants_close) ולא החזרת handoff. בדוק בפרמטר 7 "
                         "מה קורה כשליד רוצה לסגור, והחזר handoff עם handoff_urgent לפי מה "
                         "שכתוב שם."),
    "slot_times": ("נקבת בשעה שלא ברשימת המועדים הפנויים (או את השעות הכלליות של הפגישות). "
                   "הצע רק מועדים מהרשימה."),
    "slot_unknown": ("book_slot חייב להיות ה-ISO המדויק של מועד מהרשימה. מועד שלא ברשימה "
                     "לא נקבע - book_slot הוא null."),
    "outside_no_handoff": ("הליד ביקש מועד מחוץ לימים ולשעות של הפגישות - זה חריג. אל תציע "
                           "חלופות: אמור שאתה בודק מול מי שמקיים את הפגישה (לפי סעיף 0), "
                           "והחזר handoff."),
    "photo_denied": ("הליד ביקש תמונה, תוכנית או הדמיה, ויש בסעיף 7 חומרים לשליחה. בחר את המזהה "
                     "של הדירה שמדברים עליה והחזר send_image - ואל תכתוב שאין תמונות."),
    "declined_not_outside": ("הליד ביקש שעה ששורת 'מתי לא' בסעיף 5 פוסלת (למשל ערב). זה לא חריג - "
                             "requested_time הוא declined: אומרים את מה שכתוב בשורה ההיא ומציעים "
                             "מועדים מהרשימה, בלי handoff."),
    "meeting_repeat": ("הזמנת לפגישה בשתי ההודעות האחרונות. בהודעה הזאת - בלי הזמנה ובלי מועדים: "
                       "ענה על מה שהליד כתב, ושאל שאלה אחת שעוזרת להבין מה חשוב לו או מה עוצר אותו."),
    "repeat_delivery": "מועד המסירה כבר נאמר בשיחה, והליד לא שאל עליו. הורד אותו מההודעה.",
    "offer_other": ("הצעת לליד מוצר שהוא לא פנה אליו (למשל השכרה לליד שפנה על קנייה). הורד את זה - "
                    "לא מציעים אותו מיוזמתך."),
    "pricier": ("הליד אמר שיקר או שזה מעבר לתקציב, והצעת משהו יקר יותר. אל תציע יקר יותר: שקף, שאל "
                "ביחס למה יקר, נווט לפי קריטריון ההתאמה בסעיף 0, או הראה מה כלול במחיר."),
}

LABELS = {
    "callback": "הבטחה לחזור בלי סימון",
    "praise": "פתיחה באישור רגשי",
    "questions": "יותר משאלה אחת",
    "price_no_costs": "מחיר בלי העלויות הנלוות",
    "callback_time": "הבטחת זמן חזרה",
    "close_no_handoff": "רוצה לסגור בלי העברה",
    "slot_times": "שעה שלא ברשימת המועדים",
    "slot_unknown": "book_slot שלא מהרשימה",
    "outside_no_handoff": "מועד מחוץ לשעות בלי העברה",
    "photo_denied": "ביקש תמונה ולא נשלחה",
    "declined_not_outside": "ערב סומן כחריג",
    "meeting_repeat": "הזמנה לפגישה שלוש הודעות ברצף",
    "repeat_delivery": "מועד המסירה שוב, בלי שנשאל",
    "offer_other": "הצעת מוצר שהליד לא פנה אליו",
    "pricier": "הצעה יקרה יותר אחרי יקר",
}


LATE = re.compile(r"אחרי\s+(\d{1,2}):(\d{2})")
# "ב 19", "ב-19" - שעה בלי דקות, כמו שלידים כותבים
BARE_HOUR = re.compile(r"(?<![\d:])ב[-\s]?(\d{1,2})(?![\d:])")


def is_late(product, incoming):
    """הליד ביקש שעה שאחרי ה"אחרי HH:MM" בשורת "מתי לא" בסעיף 5. בלי שורה כזאת - False."""
    row = next((ln for ln in section(product, 5).splitlines()
                if ln.strip().startswith("|") and "מתי לא" in ln.split("|")[1]), "")
    m = LATE.search(row)
    if not m:
        return False
    limit = int(m.group(1)) * 60 + int(m.group(2))
    asked = [int(h) * 60 + int(mi) for h, mi in TIME.findall(incoming or "")]
    asked += [int(h) * 60 for h in BARE_HOUR.findall(incoming or "")]
    return any(limit <= t < 24 * 60 for t in asked)


def cost_words(product):
    """המילים בניסוח העלויות שהמוכר עצמו כתב בסעיף 3 (השורות שמתחילות ב->).

    ככה הבדיקה עובדת לכל מוכר, בלי לדעת מראש מה העלויות אצלו."""
    quoted = " ".join(ln.lstrip()[1:] for ln in section(product, 3).splitlines()
                      if ln.lstrip().startswith(">"))
    return set(HEB_WORD.findall(quoted))


def violations(out, product="", slots=None, incoming="", lead=None, avoid=()):
    """מפתחות הכללים שהתשובה הפרה, מתוך CORRECTIONS. incoming - ההודעה של הליד.
    lead - הכרטיס, לחזרות על מה שכבר נאמר. avoid - מילים של מוצר שהליד לא פנה אליו."""
    reply = out.get("reply", "")
    marked = any(out.get(k) not in (None, "", "null")
                 for k in ("missing_fact", "handoff", "other_product"))
    v = []
    if CALLBACK.search(reply) and (not marked or out.get("stage") == "released"):
        v.append("callback")
    if CALLBACK_WHEN.search(reply):
        v.append("callback_time")
    if out.get("stage") == "wants_close" and out.get("handoff") in (None, "", "null"):
        v.append("close_no_handoff")
    # ביקש תמונה, או שהתשובה אומרת שאין - ויש חומרים בסעיף 7, ולא נבחר אף אחד
    sends = str(out.get("send_image") or "").strip().lower() not in ("", "null", "none")
    if (not sends and (PHOTO_ASK.search(incoming or "") or PHOTO_DENIED.search(reply))
            and materials(product)):
        v.append("photo_denied")
    # חריג: הליד ביקש מועד מחוץ לשעות. בהרצה של 12-09 ("שישי ב-13:00") המנוע הציע
    # חלופות ולא העביר - בניגוד ל"חריגים הוא יבדוק מולי" (דני, 11-09, D7)
    outside = out.get("requested_time") == "outside"
    # שעה ששורת "מתי לא" פוסלת היא declined, לא חריג. נמצא 13-09 בהשוואה: "שלישי ב-19:00" ← outside
    # והעברה לדני, במקום "אתר בנייה" ושישי (דני, 13-09, ע 31-32)
    if outside and is_late(product, incoming):
        v.append("declined_not_outside")
    elif outside and out.get("handoff") in (None, "", "null"):
        v.append("outside_no_handoff")
    # בהרצה של 12-09 המנוע הציג "א'-ה' 10:00-16:30" כאילו אלה מועדים פנויים. מותר:
    # שעת סיום של מועד מהרשימה ("10:00-11:00"), שעה שהליד עצמו כתב ("10:30 לא פנוי"),
    # והשעות בהסבר של חריג
    # declined - שעה שלא קובעים בה בכלל (ערב, דני 13-09): ההסבר מזכיר את השעות, וזה בסדר
    if slots and out.get("requested_time") not in ("outside", "declined"):
        ok_times = {f"{t.hour}:{t.minute:02d}" for s in slots for t in (s["start"], s["end"])}
        ok_times |= {f"{int(h)}:{m}" for h, m in TIME.findall(incoming or "")}
        if {f"{int(h)}:{m}" for h, m in TIME.findall(reply)} - ok_times:
            v.append("slot_times")
    if (out.get("book_slot") not in (None, "", "null")
            and out["book_slot"] not in {s["start"].isoformat() for s in slots or []}):
        v.append("slot_unknown")
    if PRAISE.search(reply):
        v.append("praise")
    if reply.count("?") > 1:
        v.append("questions")
    words = cost_words(product) if "₪" in reply else set()
    if words and len(words & set(HEB_WORD.findall(reply))) / len(words) < COSTS_MIN_SHARE:
        v.append("price_no_costs")

    # ---- מהשיחה של דני מול הסוכן (13-09, שיחה מתועדת (לא בערכה)) ----
    lead = lead or {}
    incoming = incoming or ""
    before = [h["text"] for h in lead.get("history", [])
              if h.get("who") == "agent" and not h["text"].startswith("[")]
    # "מתי נוח" בכל הודעה. שתי הזמנות ברצף מותרות - תשובה מאושרת להתנגדות מסתיימת במועד
    if (len(before) >= 2 and offers_meeting(reply) and offers_meeting(before[-1])
            and offers_meeting(before[-2]) and not lead.get("meeting")
            and not ASKS_TIME.search(incoming) and not TIME.search(incoming)
            and out.get("requested_time") in (None, "", "null")
            and out.get("book_slot") in (None, "", "null")):
        v.append("meeting_repeat")
    if (DELIVERY.search(reply) and any(DELIVERY.search(t) for t in before)
            and not ASKS_DELIVERY.search(incoming)):
        v.append("repeat_delivery")
    # "הדירות מוצעות גם למכירה וגם להשכרה" לליד שפנה על קנייה
    if avoid and any(w in reply for w in avoid) and not any(w in incoming for w in avoid):
        v.append("offer_other")
    # "יקר לי" ← דירה 58 ב-3,650,000
    quoted = [_price(p) for t in before for p in PRICE.findall(t)]
    offered = [_price(p) for p in PRICE.findall(reply)]
    if EXPENSIVE.search(incoming) and quoted and offered and max(offered) > max(quoted):
        v.append("pricier")
    return v


def think_checked(product, lead, incoming, slots=None, avoid=()):
    """המוח, ואם התשובה הפרה כלל שנבדק בקוד - ניסוח מחדש אחד עם התיקון.

    מחזיר (תשובה, רשימת הכללים שתוקנו). הניסוח החדש נלקח רק אם הוא עצמו נקי -
    אחרת חוזרת התשובה הראשונה, וההפרה נשארת גלויה למי שבודק."""
    out = think(product, lead, incoming, slots=slots)
    v = violations(out, product, slots, incoming, lead, avoid) if out and out.get("reply") else []
    if v:
        retry = think(product, lead, incoming, slots=slots,
                      correction="\n".join(CORRECTIONS[k] for k in v))
        if retry and retry.get("reply") and not violations(retry, product, slots, incoming,
                                                           lead, avoid):
            return retry, v
    return out, []


def follow_up_message(product, lead):
    """הודעת המעקב למי שאמר "אחשוב על זה" ולא חזר (דני, 13-09: "איך מתקדמים" או בסגנון).
    None כשהמודל לא החזיר הודעה תקינה - והשירות שולח נוסח קבוע."""
    history = "\n".join(f"{'הליד' if h['who'] == 'lead' else 'אנחנו'}: {h['text']}"
                        for h in lead.get("history", [])[-12:])
    prompt = f"""# קובץ המוצר - זה כל מה שאתה יודע

{product}

# השיחה עד עכשיו
{history}

# המשימה
הליד אמר שיחשוב, ומאז עברו יומיים בלי שכתב. נסח הודעת מעקב אחת, שורה או שתיים, בסגנון "איך מתקדמים?":
מזכירה דבר אחד מהשיחה (למשל הדירה שדיברתם עליה), בלי מחיר, בלי מועדים, בלי לחץ, ושאלה אחת בלבד.
החזר JSON בלבד: {{"reply": "ההודעה"}}"""
    # אותו תקציב כמו תשובה רגילה - דגם שחושב היה מבזבז 300 על חשיבה, והמעקב היה יוצא תמיד בנוסח הקבוע
    msg = _client().messages.create(model=MODEL, max_tokens=MAX_TOKENS, system=RULES,
                                    messages=[{"role": "user", "content": prompt}])
    _record(msg)
    out = _extract_json("".join(b.text for b in msg.content if b.type == "text")) or {}
    reply = (out.get("reply") or "").strip()
    if reply.count("?") > 1:
        # נמצא 13-09: "היי, חשבתם על ה-6 חדרים בקומות 9-11? מה החלטתם?" - נשארת השאלה הראשונה
        reply = reply[:reply.index("?") + 1]
    return reply or None
