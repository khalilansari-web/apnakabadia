# APNA KABADI

Public friends-and-family test website for the Baripada pilot.

Your own trusted kabadiwala. Apna kabadi, sahi daam.

This is a testing preview. Use sample information. Requests do not arrange real pickups or send messages, and payments are not connected.

## Railway

Deploy the Dockerfile with one replica. Attach a persistent volume at `/data`. Set `APNA_MODE=public-test`, `APNA_DATA_DIR=/data`, a strong `APNA_ADMIN_KEY`, and `APNA_PUBLIC_URL` to the generated HTTPS origin. Never commit credentials. The health endpoint is `/healthz`. The customer website opens without a login; only `/desk` requires the owner passcode.

See [deployment notes](PUBLIC_TEST_DEPLOYMENT.md).

## Local preview

Run `python3 server.py` and open `http://127.0.0.1:8427`. Local customer data is separate from the hosted test volume.

## Before a real customer launch

Final operator details, business contacts, approved policies, backups and live integrations still need completion.
