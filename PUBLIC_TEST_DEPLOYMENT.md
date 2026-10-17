# Public friends-and-family test

The user explicitly authorised a public Railway URL on 17 October 2026. The public website has no password gate. The admin desk still requires its separate passcode. No live WhatsApp, accounting or payment integration is enabled.

Use the Dockerfile and a single Railway replica. Attach a persistent volume at /data and set APNA_DATA_DIR=/data. Set APNA_MODE=public-test and a strong APNA_ADMIN_KEY in Railway variables. Never commit or print the key. Configure APNA_PUBLIC_URL as the generated HTTPS origin (or let RAILWAY_PUBLIC_DOMAIN supply the hostname). The app reads Railway PORT and permits the Railway healthcheck hostname only at /healthz. Cookies are Secure in hosted mode; origin and host validation remain enabled. Default local mode retains loopback restrictions.

Only server.py, serve.py, requirements.txt and public/ are included in the runtime image. Do not upload .local, customer data, private desk keys, environment files, design references or unoptimised originals. GitHub source may remain private while the Railway website is public.

The site is a public testing preview, not a confirmed pickup service. Test requests stay on the hosted test server. Testers should use sample details; no collector, message or payment is triggered. Before a real customer launch, finish operator/contact/privacy details, production data protections, monitoring, backup/restore checks and actual integration tests.
