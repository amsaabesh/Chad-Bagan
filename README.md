# ছাদ বাগান — Render-ready Nursery Website

এই প্রজেক্টটি Flask + SQLAlchemy দিয়ে তৈরি এবং Render-এ deploy করার জন্য প্রস্তুত। আপনার দেওয়া `ছাদ বাগান` ছবিটি login/branding-এ ব্যবহার করা হয়েছে।

## প্রধান ফিচার

- Login page-এ User/Admin toggle
- User registration এবং Admin registration
- প্রথম Admin সরাসরি সক্রিয়
- পরবর্তী Admin registration `pending` হয়, existing admin dashboard notification + registered email notification পায়
- Existing admin pending admin approve করতে পারে
- User email + phone active accounts-এর মধ্যে unique হিসেবে enforce করা হয়
- Banned account login করলে lifetime-ban message + Contact Us দেখায়
- Ban করলে email/phone blacklist-এ যায়
- Blacklist থেকে email/phone delete করলে নতুন account-এ আবার ব্যবহার করা যায়; পুরোনো banned account banned-ই থাকে
- User navbar categories: গাছ, সার, মাছ, চাষাবাদ আনুষাঙ্গিক, অন্যান্য
- গাছসহ সব category-তে dropdown subcategory
- Admin product add/edit: name, unique ID, price, exact 300×300 image, details, category, subcategory
- Product image database-এ store হয়, তাই Render-এর ephemeral disk সমস্যা নেই
- Cart, checkout, order history
- Invoice page + PDF download
- Admin team সব order/invoice copy দেখতে পারে
- Admin order status update করতে পারে
- CSRF protection, password hashing, role-based access

## লোকাল রান

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
python app.py
```

তারপর খুলুন: `http://127.0.0.1:5000`

প্রথমে `/register/admin` থেকে প্রথম Admin account তৈরি করুন।

## Render deploy

এই repository-তে `render.yaml` দেওয়া আছে। GitHub-এ push করে Render -> New -> Blueprint থেকে repo নির্বাচন করলে web service + PostgreSQL database তৈরি হবে।

Build command:

```text
pip install -r requirements.txt
```

Start command:

```text
gunicorn app:app
```

## Email notification-এর জন্য Environment Variables

Gmail ব্যবহার করলে App Password প্রয়োজন। Render Environment-এ দিন:

```text
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-google-app-password
MAIL_FROM=your-email@gmail.com
```

SMTP configure না থাকলেও website কাজ করবে; শুধু email পাঠানো skip হবে। Dashboard notification থাকবে।

## গুরুত্বপূর্ণ আচরণ

এই implementation-এ দ্বিতীয় ও পরবর্তী Admin registration নিরাপত্তার জন্য pending থাকে এবং existing admin approval-এর পর login করতে পারে। এটি আপনার notification requirement-এর সাথে একটি approval step যোগ করে, যাতে যে কেউ registration form দিয়ে সঙ্গে সঙ্গে admin access না পায়।

## Product Image Rule

Admin upload-এর সময় image অবশ্যই ঠিক **300 × 300 px** হতে হবে এবং JPG/PNG/WEBP হতে হবে।

## Contact Info

Designed By: Ahmed Mahir Shoaib.  
If you need any help, contact with us at mahiraabesh@gmail.com
# chadbagan-php-render-app
# Chad-Bagan
