"""Send a magic-link email, or print it when no mail provider is configured."""

import json
import urllib.request

from app import config


def send_magic_link(email, url):
    subject = "Your Kerning sign-in link"
    text = "Open this link to read your digest:\n\n" + url + "\n\nIt expires in 20 minutes."
    if config.RESEND_API_KEY:
        payload = json.dumps({
            "from": config.MAIL_FROM,
            "to": [email],
            "subject": subject,
            "text": text,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=payload,
            headers={
                "Authorization": "Bearer " + config.RESEND_API_KEY,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as res:
            res.read()
        return "sent"
    print("magic link for %s:\n  %s" % (email, url), flush=True)
    return "logged"
