"""הרצה יבשה: המנוע מנסח תשובות - בלי וואטסאפ ובלי שליחה.

הרצה:
  python src/dry_run.py <slug>        למשל: python src/dry_run.py demo-project-sales

המקרים לבדיקה לא כתובים כאן - הם באים מקובץ המוצר של המוכר עצמו (סעיף 8,
"שאלות שלקוחות באמת שואלים"), ועוד מקרים גנריים שנכונים לכל מוצר.
התוצאות נכתבות ל-tests/dry-run-<slug>-<תאריך>.md, לקריאה בעיניים.
"""
import os
import re
import sys
from datetime import datetime

import anthropic
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# למנוע אין עדיין .env משלו - נופלים למפתח של סוכן ההשכרה. נטען, לא מודפס.
for env in (os.path.join(ROOT, ".env"), os.path.join(ROOT, "..", "rental-leads", ".env")):
    if os.path.exists(env):
        load_dotenv(env)
        break
sys.path.insert(0, os.path.join(ROOT, "src"))

import engine  # noqa: E402

# בודקים כללים של המנוע עצמו, ולכן מתאימים לכל מוצר
GENERIC = [
    ("פתיחה", "היי, ראיתי את המודעה, אשמח לפרטים"),
    ("בקשת הנחה", "יש הנחה אם אני סוגר היום?"),
    ("לדבר עם הבעלים", "אפשר לדבר ישירות עם הבעלים?"),
    # שני מצבים שכל מוכר מגדיר בפרמטר 7 - בודקים שהדחיפות מסומנת לפי הקובץ
    ("רוצה להתקדם", "אני רוצה להתקדם. איך סוגרים?"),
    ("כועס", "כותב כבר פעם שלישית ואף אחד לא חוזר אליי. לא רציני"),
]

FIELDS = ("stage", "missing_fact", "handoff", "handoff_urgent", "other_product")


def real_questions(product):
    """השאלות מסעיף 8 בקובץ המוצר - מה שלקוחות אמיתיים שאלו את המוכר."""
    cases = []
    for line in engine.section(product, 8).splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cell = line.strip().strip("|").split("|")[0].strip()
        if not cell or set(cell) <= set("-: ") or cell == "השאלה":
            continue
        src = re.search(r"\(([^)]*)\)\s*$", cell)
        question = re.sub(r"\s*\([^)]*\)\s*$", "", cell).strip().strip('"״')
        cases.append((f"שאלה אמיתית ({src.group(1) if src else question[:25]})", question))
    return cases


def flags(out, product):
    """מה שנשאר מסומן אחרי הבדיקה של המנוע. כל השאר - קריאה בעיניים."""
    f = [f"נשאר אחרי ניסוח מחדש: {engine.LABELS[k]}"
         for k in engine.violations(out, product)]
    if len([ln for ln in out["reply"].splitlines() if ln.strip()]) > 6:
        f.append("ארוך מ-6 שורות")
    return f


def quote(text):
    return "\n".join(f"> {ln}" for ln in text.splitlines())


def run_case(product, text):
    lead = {"name": "", "stage": "new", "history": []}
    try:
        out, fixed = engine.think_checked(product, lead, text)
        return out, fixed, None
    except anthropic.RateLimitError:
        return None, [], "מגבלת קצב של ה-API"
    except anthropic.APIStatusError as e:
        return None, [], f"שגיאת API {e.status_code}"
    except anthropic.APIConnectionError:
        return None, [], "אין חיבור ל-API"
    except ValueError as e:
        return None, [], f"JSON שבור גם אחרי תיקון: {e}"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        sys.exit("חסר שם מוצר. למשל: python src/dry_run.py demo-project-sales")
    slug = sys.argv[1]
    product = engine.load_product(slug)
    real = real_questions(product)
    if not real:
        print("⚠️  בסעיף 8 בקובץ המוצר אין שאלות - רצים רק המקרים הגנריים")
    if not engine.cost_words(product):
        print("⚠️  בסעיף 3 אין ניסוח עלויות (שורות שמתחילות ב->) - בדיקת המחיר כבויה")
    cases = GENERIC + real

    now = datetime.now()
    lines = [
        f"# הרצה יבשה - {slug}",
        "",
        f"> {now:%d-%m-%Y %H:%M} · מודל: `{engine.MODEL}` · בלי וואטסאפ ובלי שליחה",
        f"> {len(GENERIC)} מקרים גנריים + {len(real)} שאלות אמיתיות מסעיף 8 בקובץ המוצר",
        "",
    ]
    flagged = retried = 0
    for title, text in cases:
        out, fixed, err = run_case(product, text)
        lines += [f"## {title}", "", "**הליד:**", quote(text), ""]
        if err or not out or not out.get("reply"):
            lines += [f"❌ **אין תשובה:** {err or 'המודל לא החזיר JSON תקין'}", ""]
            flagged += 1
            print(f"❌ {title}: {err or 'אין JSON'}")
            continue
        lines += ["**הסוכן:**", quote(out["reply"]), ""]
        if fixed:
            retried += 1
            lines += [f"🔁 **נוסח מחדש** אחרי שהבדיקה במנוע תפסה: "
                      f"{' · '.join(engine.LABELS[k] for k in fixed)}", ""]
        lines += ["| שדה | ערך |", "|---|---|"]
        lines += [f"| {k} | {out.get(k)} |" for k in FIELDS]
        lines.append("")
        f = flags(out, product)
        if f:
            flagged += 1
            lines += [f"⚠️ **מסומן:** {' · '.join(f)}", ""]
        print(f"{'⚠️ ' if f else '✅'} {title}{' 🔁' if fixed else ''}")

    tests = os.path.join(ROOT, "tests")
    os.makedirs(tests, exist_ok=True)
    path = os.path.join(tests, f"dry-run-{slug}-{now:%Y-%m-%d-%H%M}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"\n{len(cases)} מקרים · {retried} נוסחו מחדש · {flagged} מסומנים · {path}")


if __name__ == "__main__":
    main()
