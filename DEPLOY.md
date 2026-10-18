# Hosting FitChat for free (Vercel + Supabase)

You will end up with a web address like `https://fitchat-yourname.vercel.app` that works from any phone, anywhere,
with your laptop switched off. Allow about 30 minutes the first time. All of this is free.

**What does what:** Vercel runs the website. Supabase stores the data and handles sign-up and sign-in. Gemini is the coach.

## 0. Before you start

- The code must be on GitHub (it is: `Rao-dev1/FitChat`) with `README.md`, `vercel.json`, `api/index.py` and
  `requirements.txt` at the top level of the repo.
- Have your Gemini API key ready (Google AI Studio).
- Make a Supabase account at supabase.com and a Vercel account at vercel.com (choose "Continue with GitHub").

## 1. Supabase: create the project

1. **New project.** Name it `fitchat`. Choose a strong database password and **save it** (you cannot see it again).
   Region: pick the one closest to you (for India, `ap-south-1` Mumbai).
2. **Sign-in settings.** Authentication, then Sign In / Providers, then Email. Keep **Confirm email** switched **on**.
   This matters: only a confirmed address can be the owner account, so nobody can claim yours.
3. **Copy three things** (put them in a note for now):
   - Project Settings, then API: the **Project URL** and the **anon public** key. Never copy the `service_role` key.
   - Connect (top of the page), then **Transaction pooler**: the connection string, port **6543**. Replace
     `[YOUR-PASSWORD]` with your database password. If the password contains symbols like `@` or `#`, replace each with
     its percent code (`@` becomes `%40`, `#` becomes `%23`), or simply choose a password with only letters and digits.

## 2. Create the tables (once, from your laptop)

In Command Prompt, in your `backend` folder with the virtual environment active:

```bat
.venv\Scripts\activate
pip install -r requirements.txt
set DATABASE_URL=postgresql://postgres.xxxx:YOURPASSWORD@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
python -m app.initdb
```

You should see `Done.`. This creates the tables, loads the exercise list and switches on row-level security so nobody
can read your tables through Supabase's public web API. After a later update that adds tables, run it again; it is safe
to repeat.

Check it worked: in Supabase, Table Editor should list tables like `meal_logs` and `profile`, each marked
**RLS enabled**.

## 3. Vercel: deploy

1. Vercel dashboard, **Add New**, **Project**, import `Rao-dev1/FitChat`.
2. Framework Preset: **Other**. Leave Build and Output settings empty. Root Directory: the top of the repo.
3. Open **Environment Variables** and add these (name on the left, value on the right):

| Name | Value |
|---|---|
| `AUTH_MODE` | `supabase` |
| `DATABASE_URL` | the Transaction pooler string from step 1 |
| `SUPABASE_URL` | the Project URL |
| `SUPABASE_ANON_KEY` | the anon public key |
| `GEMINI_API_KEY` | your Gemini key |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` |
| `ADMIN_EMAILS` | your own email address (the owner) |
| `APP_SECRET` | any long random text (30+ characters); keep it, changing it later invalidates saved personal keys |
| `AUTO_MIGRATE` | `false` |
| `APP_TZ` | `Asia/Kolkata` |
| `DAILY_CHAT_LIMIT` | `40` (coach messages per person per day on your key) |

4. **Deploy.** When it finishes, open the address Vercel shows. You should see the sign-in screen.

## 4. Tell Supabase your web address

Supabase, Authentication, **URL Configuration**: set **Site URL** to your Vercel address (for example
`https://fitchat-yourname.vercel.app`). Confirmation and reset-password emails link back to it.

## 5. First use

1. Open your address, **Create an account** with the same email you put in `ADMIN_EMAILS`, tap the link in the
   confirmation email, then sign in.
2. Progress, then **Account**. You should see **Site switch (owner only)**. Other people will not.
3. **Move your laptop data** (optional): on the laptop version, Progress, Account, **Download my data**. Send that file to
   your phone, then on the hosted app Account, **Restore from file**, type `REPLACE`. Your history appears.

## 6. Put it on your phone like an app

- **Android (Chrome):** menu, **Install app** (or Add to Home screen).
- **iPhone (Safari):** Share button, **Add to Home Screen**.

It opens full screen with its own icon. This is what "PWA" means: a website that behaves like an app.

## 7. Turning it off and on from your phone

Open the app, Progress, Account, **FitChat is on** switch. Off means everyone except you sees a "paused" screen. Nobody's
data is touched. Changes take effect within about 10 seconds.

## Good to know

- **Email limits.** Supabase's built-in email sender allows only a few emails per hour, which is fine for you and a few
  friends but will block sign-ups if many people join at once. For more, add your own mail service under Authentication,
  SMTP Settings (Resend and Brevo have free tiers).
- **Gemini limits.** Everyone shares your key's free daily quota, which is why each person is capped at `DAILY_CHAT_LIMIT`
  coach messages a day. People can paste their own free key in Account to remove their cap. Buttons, plans and dashboards
  never use the coach.
- **Free tiers sleep.** A Supabase free project pauses after about a week with no use; open the dashboard and press
  Restore. Vercel is always on.
- **Updating the app.** Push to GitHub and Vercel redeploys by itself. If an update adds tables, run
  `python -m app.initdb` again with `DATABASE_URL` set.
- **Backups.** Everyone can download their own data. As the owner you can also export the whole database from the
  Supabase dashboard.
- **Photos** are not available on the hosted version yet (it has no disk to keep them on).
- **Privacy.** Each person's data is separate. As the person running the service you can technically see the database,
  so tell your users what you promise. Do not use the `service_role` key anywhere in this project.
