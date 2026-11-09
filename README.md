# Shiva Agrovet — Payroll, Attendance & Vehicles

Flask + PostgreSQL + Tailwind CSS. Salary, advances, attendance with driver DA, salary slips (PDF + WhatsApp),
vehicles with diesel/repair/loading expenses, bill photos and owner approvals.

## Secrets (passwords) — never in GitHub
`docker-compose.yml` reads all passwords from environment variables:
- **Dokploy:** paste the lines from `.env.example` (with real values) into the app's **Environment** tab.
- **Your PC:** copy `.env.example` to `.env` next to `docker-compose.yml` and fill it in. `.env` is in `.gitignore`.

`POSTGRES_PASSWORD` must match the password the database was first created with.
`ADMIN_PASSWORD` is only used once, to create the first owner login on an empty database.

## Run on your PC (Docker Desktop)
1. Open Docker Desktop and wait for "Engine running". Make sure `.env` exists.
2. Double-click **docker-start.bat** → http://localhost:5000
3. **docker-stop.bat** stops, **docker-backup.bat** backs up the database and bill photos, **docker-logs.bat** shows errors.

## Deploy (Dokploy / any Docker Compose host)
Push to GitHub → Dokploy runs `docker compose up -d --build`. On every start the container creates/updates
the database tables automatically (see `CMD` in `Dockerfile`), so nothing needs to be run by hand.

## Deploy to Render (alternative)
Render → **New → Blueprint** → select this repo. `render.yaml` creates the database and the app.

## Project layout
```
app/                Flask app (models, routes, templates, static: css, logo, fonts)
config.py           settings from environment variables
run.py / serve.py   entry points (serve.py = production server, used by Docker)
Dockerfile          image used by docker-compose, Dokploy and Render
docker-compose.yml  PostgreSQL + app (secrets from .env)
render.yaml         Render Blueprint
```

## Rebuild CSS (only if you add new Tailwind classes)
`npx tailwindcss@3 -c tailwind.config.js -i tailwind.input.css -o app/static/app.css --minify`
