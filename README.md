# Shiva Agrovet — Payroll, Attendance & Vehicles

Flask + PostgreSQL + Tailwind CSS. Salary, advances, attendance with driver DA, salary slips (PDF + WhatsApp),
vehicles with diesel/repair/loading expenses and owner approvals.

## Run on your PC (Docker Desktop)
1. Open Docker Desktop and wait for "Engine running".
2. Double-click **docker-start.bat** → http://localhost:5000 (login `admin` / `admin123`, change it in Settings).
3. **docker-stop.bat** stops, **docker-backup.bat** backs up the database and bill photos, **docker-logs.bat** shows errors.

## Deploy to Render (from GitHub)
1. Push this folder to a **private** GitHub repository.
2. Render → **New → Blueprint** → select the repo. `render.yaml` creates the database and the app.
3. Enter an **ADMIN_PASSWORD** when Render asks, then **Apply**.
4. When the deploy is "Live", open the `onrender.com` link and log in as `admin`.

On every start the container automatically creates/updates the database tables and the owner login
(see the `CMD` line in `Dockerfile`), so there is nothing to run by hand. Every `git push` redeploys.

Render free plan: sleeps after 15 min idle (~1 min to wake), uploaded bill photos are lost on redeploy,
free database expires after 30 days. Use paid plans + a persistent disk for real use.

## Project layout
```
app/                Flask app (models, routes, templates, static: css, logo, fonts)
config.py           settings from environment variables
run.py / serve.py   entry points (serve.py = production server, used by Docker)
Dockerfile          image used by docker-compose and Render
docker-compose.yml  local PC: PostgreSQL + app
render.yaml         Render Blueprint
```

## Rebuild CSS (only if you add new Tailwind classes)
`npx tailwindcss@3 -c tailwind.config.js -i tailwind.input.css -o app/static/app.css --minify`
