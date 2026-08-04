# HK Cleaning Hours & Cost Dashboard

A Streamlit web app showing housekeeping (HK) hours and cost per hotel, per
week, and per housekeeper - live from Google Sheets, plus monthly payroll
cost data you upload as a PDF.

This README assumes no prior developer experience. Follow the steps in
order; each one says exactly what to click or type.

---

## What you're setting up

1. A **Google Cloud service account** - a robot Google account the app uses
   to read your 4 hotel schedule sheets and to read/write a rate-history
   sheet, without needing your personal Google login.
2. The app itself, running on **Streamlit Community Cloud** (free), reachable
   at a browser link.
3. A **private allow-list** so only people you approve can open that link.

---

## Step 1 - Google Cloud project & service account (one-time)

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and
   sign in with your Google account (the same one you use for these sheets
   is fine, or any Google account).
2. **Create a project**: click the project dropdown (top left, next to
   "Google Cloud") -> **New Project**. Name it something like
   `hk-cost-dashboard` -> **Create**. Wait for the notification that it's
   ready, then make sure it's selected in the dropdown.
3. **Enable the Sheets API**: in the search bar at the top, type
   `Google Sheets API` -> open it -> click **Enable**.
4. **Create the service account**: in the search bar, type
   `Service Accounts` -> open it -> **Create Service Account**.
   - Name: `hk-dashboard`
   - Click **Create and Continue**, then **Continue**, then **Done** (you
     can skip granting it project-level roles - it only needs access to the
     specific sheets you'll share with it in Step 2).
5. **Create its key**: click on the service account you just created ->
   **Keys** tab -> **Add Key** -> **Create new key** -> choose **JSON** ->
   **Create**. A `.json` file downloads to your computer - **keep this
   file safe and never share it publicly or commit it to GitHub**; it's the
   password for this robot account.
6. Note the service account's **email address** (looks like
   `hk-dashboard@your-project-id.iam.gserviceaccount.com`) - you'll need it
   in Step 2. It's visible on the service account's page, and inside the
   downloaded JSON as `client_email`.

## Step 2 - Share your sheets with the service account

1. **Create the rate-history sheet**: in Google Sheets, create a new blank
   spreadsheet named e.g. `HK Payroll Rate History`. Copy its **Sheet ID**
   from the URL (the long string between `/d/` and `/edit`).
2. Share each of these 5 sheets with the service account email from Step 1:
   - The 4 hotel schedule sheets (VGH, PLH, KOOYK, HAI) - click **Share**,
     paste the service account email, set role to **Viewer**, uncheck
     "Notify people", click **Share**.
   - The new rate-history sheet - same steps, but set role to **Editor**
     (the app needs to write parsed payroll rates here).

## Step 3 - Install Python and the app, locally

1. Install **Python 3.11+** from [python.org/downloads](https://python.org/downloads)
   (check "Add python.exe to PATH" during install on Windows).
2. Open a terminal in this `dashboard` folder and run:

```bash
pip install -r requirements.txt
```

3. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`, and
   fill in:
   - `rate_store_spreadsheet_id` = the Sheet ID from Step 2.1.
   - `[gcp_service_account]` = open the downloaded JSON key file and copy
     each value into the matching field. `private_key` is a multi-line
     string - keep the `\n` characters as literal `\n` text (don't turn
     them into real line breaks).
4. Run the app:

```bash
streamlit run app.py
```

Your browser should open to `http://localhost:8501` showing the dashboard.

### Verify the payroll PDF parser before trusting it

```bash
python scripts/verify_payroll_pdf.py "path/to/your Overzicht Loonkosten.pdf"
```

This prints every parsed row and cross-checks totals independently, without
touching Google Sheets or Streamlit - a good first check after any payroll
system export-format change.

### A note on the HK schedule sheet format

The dashboard reads your 4 hotel sheets through the real Google Sheets API
(not the older Drive-export method some earlier automation used). The
parser is written defensively to handle either shape of data it might
receive, but it hasn't been run against your real sheets yet in this
session - **the first local run is the real test**. If a hotel's hours or
names don't look right, check the sidebar's data-coverage panel first (it
shows per-hotel errors and any unmapped names), then let me know what the
raw sheet data actually looks like and I'll adjust `hk_dashboard/hk_parser.py`.

---

## Step 4 - Put the code on GitHub (needed for Streamlit Cloud)

Streamlit Community Cloud deploys from a GitHub repository.

1. Create a free account at [github.com](https://github.com) if you don't
   have one.
2. Install [GitHub Desktop](https://desktop.github.com) - no command line
   needed.
3. In GitHub Desktop: **File -> Add Local Repository** -> pick this
   `dashboard` folder -> if prompted to create a repository, do so.
4. **Important**: before publishing, confirm `.streamlit/secrets.toml` is
   **not** listed among the files to commit (it's excluded by `.gitignore`,
   but double-check) - it contains your service account password.
5. Click **Publish repository**. Choose whether it's public or private
   (private is recommended, but Streamlit Cloud's free tier works with
   either).

## Step 5 - Deploy to Streamlit Community Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with
   your GitHub account.
2. Click **Create app** -> **From an existing repo** -> pick the repo you
   just published, branch `main`, main file path `app.py` -> **Deploy**.
3. It will fail to start the first time because secrets aren't set yet -
   that's expected. Go to the app's **Settings -> Secrets**, and paste the
   full contents of your local `.streamlit/secrets.toml` file in there.
   Save - the app will restart automatically.

## Step 6 - Make it private and set the viewer allow-list

1. On the app's page in Streamlit Community Cloud, open **Settings ->
   Sharing**.
2. Set the app to **Private**.
3. Add allowed viewer emails, one per line. Start with:
   ```
   wakdaria@gmail.com
   ```
   Add Cheng's email (and anyone else) here whenever you're ready - no code
   changes needed, just add the email in this settings page. Viewers with a
   Google account sign in automatically via Google OAuth.

---

## Step 7 - HK Hours Self-Confirmation (optional second app)

A login-free page where housekeepers confirm (or dispute) the hours
reception logged for them each day, feeding a new **Hours Submission**
admin tab used as a check-step before the monthly payroll submission.

**Why a second app:** this main dashboard is Private with a Google-account
allow-list (Step 6) - housekeepers have no Google accounts and can't be on
it. The confirmation page ships as `confirm/confirm_app.py`, deployed as its
**own, separate, Public** Streamlit Community Cloud app from this same
GitHub repo, so it's reachable with no login at all. It deliberately lives
in its own `confirm/` subfolder rather than the repo root: Streamlit treats
every file under `pages/` as a directly-reachable URL for whichever app it's
a sibling of, sidebar link or not - if the confirm app sat next to this
dashboard's `pages/` folder, admin-only pages (Staff Identity's birthdates,
Hours Submission's dispute data) would be reachable with no login on the
confirm app's public URL.

1. **Create a second Google Sheet** (separate from the rate-history one),
   e.g. `HK Hours Confirmation`. Copy its Sheet ID from the URL.
2. **Share it** with the same service account email from Step 1, role
   **Editor** (same account already used for the rate-history sheet -
   nothing in `confirm_app.py` ever touches rate-store data, but note that
   this means the public app's secrets do carry a credential that also has
   edit rights on the payroll rate sheet; accepted here for simplicity
   rather than creating a second, more narrowly-scoped service account).
3. Add `confirmation_spreadsheet_id` to **both** this dashboard's secrets
   (local `secrets.toml` and its Streamlit Cloud Settings -> Secrets) **and**
   to the new confirm-app deployment's secrets in the next step.
4. **Deploy `confirm/confirm_app.py` as a second Streamlit Cloud app**: on
   [share.streamlit.io](https://share.streamlit.io), **Create app** -> pick
   this same repo, branch `main`, main file path `confirm/confirm_app.py`.
   Leave it
   **Public** (Settings -> Sharing) - that's the point. Paste its secrets
   (the `[gcp_service_account]` block plus `confirmation_spreadsheet_id`
   only - it doesn't need `rate_store_spreadsheet_id`).
5. **Add staff**: back in this main (private) dashboard, open the new
   **Staff Identity** page and add each housekeeper (name is picked from a
   dropdown of real shift data, so it always matches reception's spelling)
   with their hotel and birthdate.
6. **Print QR codes**: run `python scripts/generate_qr_codes.py <your confirm
   app's URL>` locally - it writes one PNG per hotel
   (`https://<url>/?hotel=VGH` etc.) to print and place at each hotel.
7. Check the new **Hours Submission** page here in the main dashboard each
   month before submitting hours to loonstrookgigant - it flags disputed
   days and mismatches over 15 minutes.

## Monthly workflow

1. Each month, download the new "Overzicht Loonkosten" PDF from the payroll
   system.
2. Open the dashboard -> **Payroll Upload** page -> upload it -> check the
   preview table -> click **Save**. This is an upsert: re-uploading a PDF
   that covers months already saved overwrites those months' rates rather
   than duplicating them, so it's safe to re-upload a cumulative export.
3. Everything else (hours, weeks, trends) updates automatically from the
   live Google Sheets - no manual step needed for that part.

## Adding a new housekeeper's nickname mapping

If the sidebar flags an unmapped name, add it to `NAME_MAP` in
`hk_dashboard/config.py` (nickname -> "Initials Surname" as it appears in
payroll), then redeploy (push the change to GitHub - Streamlit Cloud
redeploys automatically).

## Phase 2 (not built): cost forecasting

A future phase could forecast cleaning cost using predicted HK hours
combined with reservation/occupancy data from Mews, via its Connector API.
This isn't built - no Mews API credentials exist yet for this project. The
data model here (per-hotel, per-day shift records with hours and cost) is
kept granular enough that a forecast view could be added later without
reshaping existing data.

## Known open item

The "known format" quirks originally documented for these sheets (pipe
characters, HTML `<span>` duration tags, `[merged]` text markers) look like
artifacts of the older Drive-text-export method, not what the real Sheets
API returns. `hk_dashboard/hk_parser.py` handles both possibilities, but
this should be confirmed against your real sheets on first run (see
"A note on the HK schedule sheet format" above).
