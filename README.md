# CHMSU Student Violation Management System

A Django-based student violation tracking and OSA (Office of Student Affairs) workflow system. Provides staff/faculty/student flows for reporting incidents, managing violations, scheduling meetings, issuing apology letters, and generating alerts when a student reaches disciplinary thresholds.

**Key features**
- Role-based accounts: `Student`, `Staff`, `OSA Coordinator` (custom `User` model)
- Student profiles with 8-digit student ID validation
- Violation reporting and tracking (minor/major, status lifecycle)
- Alerts when effective major violations reach a threshold (3 effective majors)
- Apology letter submission + formator verification workflow
- Document/evidence attachments and media uploads
- Activity and login auditing
- Admin UI themed with `django-jazzmin`
- Small utility scripts: `check_overdue.py` to list overdue cases
- Simple APIs: face-detection (`/api/detect-face/`) and server-side TTS (`/api/welcome-tts/`)

**Tech stack**
- Python (3.11+ recommended)
- Django 5.2.7
- Primary libs (see `requirements.txt`): `django-jazzmin`, `channels` (optional/commented), `gTTS`, `opencv-python`, `pillow`, `psycopg[binary]`, `whitenoise`, `gunicorn` (production)
- Database: PostgreSQL (production) or SQLite (development via `USE_SQLITE` env var)

Repository layout (important paths)
- `student_violation_system/` — Django project settings and WSGI/ASGI
- `violations/` — main app: models, views, admin, urls, templates, static
- `media/` — uploaded files (apology_letters, profiles, evidence)
- `staticfiles/` — collected static assets
- `check_overdue.py` — small script to list overdue violations

Getting started (Windows — local development / localhost)

1. Create and activate a virtual environment (PowerShell):

```powershell
python -m venv virtualenv
.\virtualenv\Scripts\Activate
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Use SQLite for quick local setup (optional):
- For current PowerShell session:

```powershell
$env:USE_SQLITE = "True"
```

- Or in CMD:

```cmd
set USE_SQLITE=True
```

If you prefer PostgreSQL, configure `DATABASES` in `student_violation_system/settings.py` or set environment variables accordingly (defaults in settings point to a local `postgres` user with password `1234`).

4. Run migrations and create a superuser:

```powershell
python manage.py migrate
python manage.py createsuperuser
```

5. (Optional) Collect static files for production/test staticserve:

```powershell
python manage.py collectstatic --noinput
```

6. Start the dev server (localhost):

```powershell
python manage.py runserver
```

Open http://127.0.0.1:8000/ — the app redirects to the login flow. Admin is available at http://127.0.0.1:8000/admin/ (use the superuser credentials).

Usage notes
- Login flows: `/student/` (Student ID login), `/staff/` (staff dashboard/login), `/faculty/` (OSA Coordinator)
- API endpoints:
  - `/api/welcome-tts/` — generate a short welcome audio (requires `gTTS` or `pyttsx3`)
  - `/api/detect-face/` — POST base64 image JSON to get face bounding box and head-size guidance (requires `opencv-python` and `numpy`)
- Media uploads are stored under `media/` with subfolders for `apology_letters`, `profiles`, and `violations/evidence`.
- The `check_overdue.py` script can be run to list violations older than 7 days and their status:

```powershell
python check_overdue.py
```

Configuration & security
- `DEBUG` is `True` in current settings — set to `False` for production and configure `ALLOWED_HOSTS`.
- Change `SECRET_KEY` and database credentials before deploying.
- Channels (ASGI/websockets) are present but commented — enable `channels` and a channel layer (Redis) for realtime chat.

Contribution & next steps
- Add environment-based secret/config management (e.g., `django-environ`) before deploying.
- Move production static/media serving to a CDN or proper storage (S3, etc.) and configure `whitenoise` or a web server.

License
- This repository does not include a license file. Add one if you plan to share or open-source.

---
Generated summary README for local development and quick reference.
