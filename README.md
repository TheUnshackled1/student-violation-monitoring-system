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
<<<<<<< HEAD

UI text: This is the UI for each page.

=======
<h1>Staff Login Page and Dashboard</h1>
<img width="1919" height="1022" alt="Screenshot 2026-02-05 002710" src="https://github.com/user-attachments/assets/65c148f5-0cce-4879-9253-e8a3cdbbd433" />
<img width="1193" height="1023" alt="image" src="https://github.com/user-attachments/assets/7cfaa82e-be8d-479c-a85b-f5cb9426997e" />

<hr>
<h1>Student Login Page and Dashboard</h1>
<img width="1919" height="1024" alt="Screenshot 2026-02-05 002718" src="https://github.com/user-attachments/assets/10158819-548e-4c1d-b819-a402ee41535b" />
<img width="1188" height="968" alt="image" src="https://github.com/user-attachments/assets/d8c40b71-d2c0-4533-af6d-0ee123a51144" />
<hr>

<h1>OSA Coordinator Login Page and Dashboard</h1>
<img width="1918" height="1029" alt="Screenshot 2026-02-05 002729" src="https://github.com/user-attachments/assets/57c33044-81f5-4319-bba3-31f29b73efaa" />
<img width="1175" height="1009" alt="image" src="https://github.com/user-attachments/assets/4ced7b89-afa2-4b9a-b108-f0909b52b158" />
<hr>

<img width="1919" height="1027" alt="Screenshot 2026-02-05 002738" src="https://github.com/user-attachments/assets/3767a4e5-6ea9-4a57-b62c-25ada531e79c" />
<hr>

<img width="1919" height="1031" alt="Screenshot 2026-02-05 002744" src="https://github.com/user-attachments/assets/6c9624a6-0e32-450c-b76d-4720ce8653be" />
>>>>>>> 2ad885d62b0f19c2a64755bdcb1d13cf1ec2348a

