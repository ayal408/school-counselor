# מרחב — מערכת ליועצת בית הספר

גרסת פיתוח 0.1.0. לקוח React + TypeScript בעברית וצד שרת Python.

## ארכיטקטורה

בהתאם להפרדת השירותים ב־DOMix, בבראנץ `dev`:

| רכיב | טכנולוגיה | אחריות |
| --- | --- | --- |
| counselor-client | React 19, TypeScript, Vite, TanStack Query, Zustand, Axios | ממשק RTL; access token בזיכרון בלבד |
| auth-server | Python / FastAPI | התחברות, הנפקת JWT, refresh cookie ויציאה; ללא גישה ישירה ל־DB |
| counselor-server | Python / FastAPI, SQLAlchemy, Alembic | נתונים, הרשאות, סיסמאות Argon2, הצפנה ומיגרציות |
| postgres | PostgreSQL 16 | אחסון נתונים, refresh hashes ויומן פעולות |
| nginx | Nginx | לקוח וניתוב `/api/auth/*` לשירות האימות ו־`/api/*` לשרת הנתונים |

שרת הנתונים בלבד מחזיק חיבור למסד. שירות האימות מתקשר איתו ב־API פנימי עם מפתח שירות. נתיבי `/internal` אינם נחשפים דרך ה־gateway. אין הרשמה ציבורית.

## מה עובד

- התחברות, חידוש token חד־פעמי ויציאה עם ביטול refresh בשרת.
- רשימת תלמידות, חיפוש, הוספה, API לעריכה והעברה לארכיון.
- כרטיס תלמידה ותיעוד פגישות ידני בציר זמן.
- יומן פגישות לפי יום או שבעה ימים, קביעת פגישה, בדיקת חפיפות ושינוי מצב.
- משימות מוצפנות עם מועד יעד, סימון השלמה, סינון מצב והצגה בכרטיס תלמידה.
- הרשאות לפי בעלות: יועצת רואה רק כרטיסים שיצרה; בדיקת משתמשת פעילה בכל בקשה.
- הצפנת שם, כיתה, סיבת הפניה, הערות וסיכומים באמצעות Fernet לפני שמירה.
- יומן פעולות ללא תוכן מקצועי; כותרות no-store; הגנת Origin ו־XHR לפעולות cookie; הגבלת קצב ב־gateway.
- נעילת ממשק לאחר 15 דקות ללא פעילות; token גישה תקף עד 10 דקות.

## הרצה עם Docker

1. העתיקי `.env.example` ל־`.env`.
2. החליפי את סיסמת PostgreSQL ושני הסודות בערכים אקראיים נפרדים. השתמשי בסיסמת DB אלפאנומרית כדי שתהיה תקינה בתוך URL.
3. צרי מפתח Fernet (אחרי התקנת cryptography):

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

שימי את הערך ב־`DATA_ENCRYPTION_KEY`. אין לשמור מפתחות בגיט. איבוד המפתח מונע קריאת המידע, ולכן יש לגבות אותו בנפרד ובאופן מוגן.

```bash
docker compose up --build -d
docker compose exec counselor-server python -m app.create_user
```

הפקודה האחרונה יוצרת יועצת מורשית עם סיסמה אינטראקטיבית שאינה נשמרת בהיסטוריית הפקודות. פתחי http://localhost:8088.
המיגרציות מיושמות לפני עליית השרת. אין נתוני דוגמה או סיסמת מנהל בקוד.

`COOKIE_SECURE=false` מיועד ל־HTTP מקומי בלבד. בהפעלה אמיתית נדרשים HTTPS, `COOKIE_SECURE=true` ו־`CLIENT_ORIGIN` שתואם בדיוק לכתובת האתר. השירותים ו־PostgreSQL אינם חושפים פורטים למחשב המארח.

## בדיקות

```bash
pip install -r counselor-server/requirements.txt
python -m pytest counselor-server/tests auth-server/tests -q
cd counselor-client
npm ci
npm run build
```

בדיקות Python יוצרות נתונים פיקטיביים ב־SQLite בזיכרון בלבד ולא מתחברות ל־DB של הפיתוח או הייצור. הן בודקות בידוד משתמשות, הצפנה, אימות, חסימת נתיב פנימי, refresh חד־פעמי וארכוב. CI מפעיל את הבדיקות ואת בניית React.

## עדיין לפיתוח

הקלטה, תמלול ו־AI אינם מחוברים; הממשק מציין זאת במפורש. ניהול משתמשות בממשק, שיתוף כרטיסים, גרסאות פגישות, MFA, גיבוי ושחזור, רוטציית מפתחות ומדיניות מחיקה עדיין נדרשים. הגבלת הקצב פועלת דרך Nginx בלבד.
אין להשתמש במידע אמיתי של תלמידות לפני השלמת דרישות אלו, בדיקת פריסה מאובטחת ואישור מדיניות המוסד. הצפנת שדות אינה תחליף להצפנת דיסקים וגיבויים.

[האפיון המלא](docs/specification.he.md)

## שגיאת SSL בעת בנייה ברשת מסוננת

`CERTIFICATE_VERIFY_FAILED` בזמן pip או npm עשוי להצביע על תעודת CA של סינון רשת או proxy שהמחשב מכיר אך Docker אינו מכיר. השגיאה "No matching distribution" במצב זה אינה ראיה שחסרה גרסת החבילה.

ב־Windows, ברשת NetFree שכבר מותקנת בה תעודת שורש מהימנה, הריצי מתוך תיקיית הפרויקט:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

הסקריפט מאגד את כל תעודות השורש של NetFree שכבר מהימנות במחשב, ומפסיק אם לא נמצאה אף תעודה. ברשת אחרת, או אם לא נמצאה תעודה, קבלי ממנהל הרשת תעודת CA ציבורית והעבירי נתיב:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -CertificatePath "C:\certs\network-ca.crt"
```

אין ביטול של אימות SSL. התעודה מועברת בתור BuildKit secret, משמשת רק בהתקנת התלויות, אינה נשמרת בתמונה ואינה עולה לגיט. קובץ compose.local-ca.yml הוא אפשרות לפיתוח מקומי בלבד; בנייה רגילה אינה משתמשת בתעודה. תעודה לא תקינה או חסרה אינה נעקפת.

לאחר עליית השירותים אפשר ליצור משתמשת:

```powershell
docker compose exec counselor-server python -m app.create_user
```
