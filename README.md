# WashAI — نظام ذكي لإدارة المغاسل

## شكل المجلد (لازم يكون كذا بالضبط)

```
washai/
├── app.py            ← السيرفر (Flask)
├── washai.py         ← منطق النظام (طلبات، تنبؤ، روبوت)
├── schema.sql        ← الجداول
├── reports.sql       ← التقارير
├── requirements.txt  ← المكتبات المطلوبة
├── Procfile          ← أمر التشغيل على الاستضافة
├── .gitignore
└── static/
    └── index.html    ← الواجهة (للعميل وللإدارة)
```

مهم: مجلد `static` يكون جنب `app.py`، وملفات `.sql` جنب `washai.py`.

## ١) تشغيله على جهازك (جرّبه أول)

```
pip install -r requirements.txt
python app.py
```

افتح http://127.0.0.1:5000 . مفتاح الإدارة الافتراضي: `demo`

## ٢) ارفع الكود على GitHub

1. سوّ حساب على github.com ثم New repository باسم `washai`.
2. ارفع كل الملفات (Add file ← Upload files) مع الحفاظ على مجلد `static`.
3. هذا يخدمك بالتسليم أيضاً: الدكتور يقدر يشوف الكود ومراحل تطويره.

## ٣) شغّله أونلاين (اختر وحدة)

### الخيار أ: Render.com
1. سجّل دخول بحساب GitHub.
2. New ← Web Service ← اختر مستودع `washai`.
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `gunicorn app:app`
5. من Environment أضف متغير `ADMIN_KEY` وقيمته كلمة سر قوية من عندك.
6. تاخذ رابط مثل `washai.onrender.com`.

### الخيار ب: PythonAnywhere.com
1. سوّ حساب مجاني، ثم Files ← ارفع الملفات (أو clone من GitHub بواسطة Bash console).
2. Web ← Add a new web app ← Flask، وحدد مسار `app.py`.
3. أضف `ADMIN_KEY` في ملف الإعدادات (WSGI file) قبل تحميل التطبيق.
4. تاخذ رابط `اسمك.pythonanywhere.com`.

## ملاحظات مهمة

- **غيّر مفتاح الإدارة** قبل ما تنشر، لا تخليه `demo`.
- **قاعدة SQLite** ممكن تنمسح في بعض الاستضافات المجانية عند إعادة التشغيل. هذا مقبول للعرض، وللإنتاج الفعلي نستخدم PostgreSQL.
- **الاستضافات المجانية** ممكن "تنام" بعد فترة بدون استخدام، فأول فتح يتأخر شوي. افتح الرابط قبل العرض بدقيقتين.
- شروط الباقات المجانية تتغير، فتأكد منها في موقع الاستضافة قبل ما تعتمد عليها.
- البيانات الموجودة بيانات تجريبية مولّدة، مو بيانات مغسلة حقيقية.

## نقاط الـ API

| الطريق | وظيفته | يحتاج مفتاح إدارة |
|---|---|---|
| `GET /api/track?order_id=&phone=` | تتبع طلب | لا |
| `POST /api/chat` | روبوت المحادثة | لا |
| `POST /api/orders` | إنشاء طلب | نعم |
| `POST /api/orders/<id>/advance` | تحديث الحالة | نعم |
| `GET /api/scan/<code>` | مسح رمز قطعة | نعم |
| `GET /api/forecast` | توقع الطلب وخطة الموظفين | نعم |
| `GET /api/reports/<name>` | التقارير | نعم |

المفتاح يُرسل في الهيدر `X-Admin-Key`.
