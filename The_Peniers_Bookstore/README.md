# The Peniers Bookstore

A Flask + SQLite online bookstore: customer accounts, cart, checkout with an
optional saved-account auto-debit, order tracking, and an admin panel for
managing books and orders.

## Run it locally

```bash
pip install -r requirements.txt
python3 app.py
```

Visit `http://127.0.0.1:5000`. Admin panel: `http://127.0.0.1:5000/admin-login`
(default `admin@thepeniers.com` / `ChangeThisPassword123!` — change this
before going live, see below).

## Before you put this on the internet

Set these as **environment variables** on whatever host you deploy to —
don't hardcode them in the code:

| Variable         | Why                                                              |
|------------------|-------------------------------------------------------------------|
| `SECRET_KEY`     | Random long string. Protects login sessions. Generate one with `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `ADMIN_EMAIL`    | Your real admin login email                                     |
| `ADMIN_PASSWORD` | A strong password — don't keep the default                      |
| `ANTHROPIC_API_KEY` | Powers the AI support chat widget. Get one at console.anthropic.com. Without it, the chat just tells customers to email support. |
| `SALES_USERNAME` | Login username for the sales dashboard (default `@thepeniers`) |
| `SALES_PASSWORD` | Login password for the sales dashboard — don't keep the default |
| `FLASK_ENV`      | Set to `production`                                              |
| `DATABASE_URL`   | Optional. Defaults to a local SQLite file — fine for a small site, but see note below |

The app already refuses to run with debug mode on unless you explicitly set
`FLASK_DEBUG=1` locally, and it prints a warning on startup if it detects
`FLASK_ENV=production` while still using default secrets.

**About the database:** SQLite (`instance/database.db`) works, but most
free hosting platforms wipe local disk on every redeploy — meaning your
customers, books, and orders vanish. For anything beyond a demo, use a
managed Postgres database (most hosts below offer a free one) and set
`DATABASE_URL` to its connection string. You'll also need to add
`psycopg2-binary` to `requirements.txt` if you do.

## Deploying (Render is the simplest free option)

1. Push this project to a GitHub repository.
2. On [render.com](https://render.com), create a new **Web Service** from
   that repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`
5. Add the environment variables listed above under the service's
   **Environment** tab.
6. Deploy. Render gives you a live `https://your-app.onrender.com` URL.

Railway and PythonAnywhere work too, with the same environment variables
and `gunicorn app:app` as the start command (PythonAnywhere uses its own
WSGI config file instead of a Procfile — follow their Flask quickstart).

## Project structure

```
app.py                 Flask app: routes, models, business logic
templates/              All Jinja2 HTML templates
requirements.txt        Python dependencies
Procfile                Tells the host how to start the app (gunicorn)
instance/database.db    SQLite database (created automatically)
```

## Features

- Customer registration/login, cart, and checkout
- One login page for both customers and admin — the admin email/password
  logs into the admin dashboard, anything else is checked as a customer
- Checkout supports Auto-Debit (saved bank account), Card (entered at
  checkout), Bank Transfer, and Cash on Delivery — Auto-Debit and Card
  mark the order Paid immediately (simulated; no real payment processor
  is connected)
- Every order gets a reference number like `TPB-NG-20260820-0007`
- Admin can see every real order with full customer/item details, and
  update its status
- AI support chat (bottom-right bubble) scoped to store topics only —
  answers delivery/returns/order questions and flags anything that reads
  like a complaint for the admin to review under Complaints
- Book categories and search on the homepage
- Discount badges when a book has both a price and an original price
- Customers can leave comments on any book's page
- A general Feedback / Bug Report form (`/feedback`), visible to admin
  under Feedback
- A separate Sales login (`/sales-login`) showing a sales report with
  a 14-day sales chart and revenue-by-category chart

## Editing the AI chat's store info

Open `app.py` and find `STORE_INFO` near the top — that's the block of
facts the AI chat is allowed to tell customers (delivery times, return
policy, contact email, etc.). Edit it to match your real store details.

