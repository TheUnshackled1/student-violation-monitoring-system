# 🚀 CHMSU Student Violation Monitoring System — Setup Instructions

> Detailed step-by-step guide for setting up the project on **Windows** with **Python 3.11+**.

---

## 📋 Table of Contents

- [Prerequisites](#-prerequisites)
- [1. Clone the Repository](#1-clone-the-repository)
- [2. Set Up a Virtual Environment](#2-set-up-a-virtual-environment)
- [3. Install Dependencies](#3-install-dependencies)
- [4. Configure the Database](#4-configure-the-database)
  - [Option A — SQLite (Recommended for Local Dev)](#option-a--sqlite-recommended-for-local-dev)
  - [Option B — PostgreSQL (Recommended for Production)](#option-b--postgresql-recommended-for-production)
- [5. Run Migrations](#5-run-migrations)
- [6. Create a Superuser](#6-create-a-superuser)
- [7. Collect Static Files](#7-collect-static-files-optional)
- [8. Start the Development Server](#8-start-the-development-server)
- [Troubleshooting](#-troubleshooting)
- [Running in Production](#-running-in-production)

---

## ✅ Prerequisites

Make sure the following are installed on your Windows machine before you begin:

| Tool | Minimum Version | Download |
|---|---|---|
| **Python** | 3.11 | https://www.python.org/downloads/ |
| **pip** | Latest | Bundled with Python |
| **Git** | Any | https://git-scm.com/download/win |
| **PostgreSQL** *(optional)* | 14+ | https://www.postgresql.org/download/windows/ |

> 💡 During Python installation, check **"Add Python to PATH"** to ensure `python` and `pip` are available in PowerShell.

---

## 1. Clone the Repository

Open **PowerShell** and run:

```powershell
git clone <repository-url>
cd syande
```

Replace `<repository-url>` with the actual GitHub URL of this project.

---

## 2. Set Up a Virtual Environment

It is strongly recommended to use a virtual environment to isolate project dependencies.

```powershell
# Create the virtual environment
python -m venv virtualenv

# Activate it (PowerShell)
.\virtualenv\Scripts\Activate
```

You should see `(virtualenv)` prepended to your shell prompt, confirming activation.

> ⚠️ If you see a script execution policy error, run this first:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

To deactivate the environment at any time:
```powershell
deactivate
```

---

## 3. Install Dependencies

With your virtual environment active, install all required packages:

```powershell
pip install -r requirements.txt
```

This installs:
- Django 5.2.7
- django-jazzmin (Admin theme)
- OpenCV + NumPy (Face detection API)
- gTTS (Text-to-speech API)
- Pillow (Image handling)
- psycopg[binary] (PostgreSQL adapter)
- WhiteNoise (Static file serving)
- Gunicorn (Production WSGI server)
- Django Channels (WebSocket support)

> 💡 If you encounter errors installing `opencv-python` or `psycopg[binary]`, ensure your Python version is 3.11+ and pip is up to date:
> ```powershell
> python -m pip install --upgrade pip
> ```

---

## 4. Configure the Database

### Option A — SQLite *(Recommended for Local Dev)*

SQLite requires zero configuration and is perfect for local development. Simply set the `USE_SQLITE` environment variable **before** running any management commands.

**PowerShell (current session only):**
```powershell
$env:USE_SQLITE = "True"
```

**CMD (current session only):**
```cmd
set USE_SQLITE=True
```

**Persist across sessions (PowerShell profile):**

Add the following line to your PowerShell profile (`$PROFILE`):
```powershell
$env:USE_SQLITE = "True"
```

> The `db.sqlite3` file will be created automatically in the project root when you run migrations.

---

### Option B — PostgreSQL *(Recommended for Production)*

**Step 1 — Create the database and user in psql:**

```sql
CREATE DATABASE syande_db;
CREATE USER syande_user WITH PASSWORD 'your_strong_password';
GRANT ALL PRIVILEGES ON DATABASE syande_db TO syande_user;
```

**Step 2 — Update `student_violation_system/settings.py`:**

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'syande_db',
        'USER': 'syande_user',
        'PASSWORD': 'your_strong_password',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
```

> The default config in settings uses `postgres` / `1234` as credentials. Change these before deploying.

---

## 5. Run Migrations

Apply all database migrations to set up the schema:

```powershell
python manage.py migrate
```

Expected output: a list of applied migrations ending with `Applying violations.XXXX_... OK`.

---

## 6. Create a Superuser

Create the first admin/OSA Coordinator account:

```powershell
python manage.py createsuperuser
```

You will be prompted to enter:
- **Username** — choose any username
- **Email** — optional but recommended
- **Password** — must meet Django's password strength requirements

This account will have full access to the Django Admin panel at `/admin/`.

---

## 7. Collect Static Files *(Optional)*

Only required if you are testing static file serving (e.g., with WhiteNoise) or deploying:

```powershell
python manage.py collectstatic --noinput
```

Static files are collected into the `staticfiles/` directory.

---

## 8. Start the Development Server

```powershell
python manage.py runserver
```

The application will be available at:

| URL | Description |
|---|---|
| **http://127.0.0.1:8000/** | Main application (redirects to login) |
| **http://127.0.0.1:8000/admin/** | Django Admin panel |
| **http://127.0.0.1:8000/student/** | Student login |
| **http://127.0.0.1:8000/staff/** | Staff / Guard / Formator login |
| **http://127.0.0.1:8000/faculty/** | OSA Coordinator login |

Log in to `/admin/` with the superuser credentials you just created.

---

## 🔧 Troubleshooting

### `'python' is not recognized as an internal or external command`
Python is not on your PATH. Re-install Python and check **"Add Python to PATH"**, or use the full path: `C:\Users\<you>\AppData\Local\Programs\Python\Python311\python.exe`.

---

### `ModuleNotFoundError: No module named 'django'`
Your virtual environment is not activated. Run:
```powershell
.\virtualenv\Scripts\Activate
```

---

### `psycopg.OperationalError: connection refused`
PostgreSQL is not running. Start it via **Services** (`services.msc`) or:
```powershell
net start postgresql-x64-16
```
Or switch to SQLite for local dev: `$env:USE_SQLITE = "True"`.

---

### `django.db.utils.OperationalError: no such table`
You have not run migrations yet. Run:
```powershell
python manage.py migrate
```

---

### Script execution policy error on `Activate`
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

### Static files not loading in browser
Run collectstatic and ensure `DEBUG = True` in `settings.py` for local development (Django serves static files automatically in debug mode).

---

### `pip install` fails on `opencv-python`
Try installing a pre-built wheel:
```powershell
pip install opencv-python-headless
```

---

## 🌐 Running in Production

> ⚠️ Review all security settings before exposing this to the internet.

**1. Set environment variables:**
```powershell
$env:DEBUG = "False"
$env:SECRET_KEY = "your-random-secret-key-here"
$env:ALLOWED_HOSTS = "yourdomain.com,www.yourdomain.com"
```

**2. Use Gunicorn as the WSGI server:**
```bash
gunicorn student_violation_system.wsgi:application --bind 0.0.0.0:8000 --workers 3
```

**3. Serve static files with WhiteNoise** — already installed. Ensure `whitenoise.middleware.WhiteNoiseMiddleware` is in your `MIDDLEWARE` list in `settings.py`.

**4. Use PostgreSQL** — do not use SQLite in production.

**5. Recommended: manage secrets with `django-environ`:**
```powershell
pip install django-environ
```
Then load from a `.env` file in `settings.py`:
```python
import environ
env = environ.Env()
environ.Env.read_env()

SECRET_KEY = env('SECRET_KEY')
DEBUG = env.bool('DEBUG', default=False)
```

---

## 🗂️ Quick Reference

```powershell
# Full setup from scratch (PowerShell)
git clone <repo-url> && cd syande
python -m venv virtualenv
.\virtualenv\Scripts\Activate
pip install -r requirements.txt
$env:USE_SQLITE = "True"
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

---

*For an overview of the system and its features, see [README.md](README.md).*
