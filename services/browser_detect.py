"""Detects when the app is being viewed inside an in-app browser (the
mini-browser WhatsApp/Telegram/Instagram/Facebook open when you tap a link
shared inside those apps, instead of the phone's real Safari/Chrome).

Why this matters here specifically: those embedded browsers have a
long-documented bug where, after the user takes a photo or picks one from
their gallery via a file input, the webview fails to hand the selected file
back to the page - the picker opens and works fine, the user picks a photo,
and then nothing reaches the page's JavaScript at all. No error can be shown
for this because the failure happens before any data reaches Dash's
reactive system - dcc.Upload's `contents` property simply never changes, so
no callback ever fires. This is a bug in those apps' embedded browsers, not
fixable from application code; the only reliable fix is telling the person
to open the link in their actual browser instead, which always works.
"""
import re

# Substrings that reliably identify well-known in-app browsers' user agents.
# Not exhaustive and not perfect (WhatsApp's iOS webview in particular
# doesn't always carry a unique marker), but catches the large majority,
# especially on Android where "; wv)" is WebKit's own standard marker for
# "this is an embedded WebView, not the real browser app".
_SIGNATURES = [
    (re.compile(r"FBAN|FBAV", re.I), "Facebook / Messenger"),
    (re.compile(r"Instagram", re.I), "Instagram"),
    (re.compile(r"Line/", re.I), "Line"),
    (re.compile(r"Twitter", re.I), "Twitter/X"),
    (re.compile(r"; ?wv\)", re.I), "WhatsApp, Telegram, or a similar app"),
]


def detect_in_app_browser(user_agent: str) -> str | None:
    """Returns a human-readable app name if the user agent looks like an
    embedded in-app browser, else None. Deliberately conservative - only
    flags patterns that are well-established signatures, so a real mobile
    Safari/Chrome session is never falsely flagged."""
    if not user_agent:
        return None
    for pattern, name in _SIGNATURES:
        if pattern.search(user_agent):
            return name
    return None
