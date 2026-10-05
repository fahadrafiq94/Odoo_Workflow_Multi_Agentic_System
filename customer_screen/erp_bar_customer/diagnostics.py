"""Small, credential-free diagnostics shared by the app and read-only checker."""
import re

BUILD = '2026.10.05.1'
PROTOCOL = 2


def error_text(error, secrets=()):
    text = ' '.join(str(error).split()) or type(error).__name__
    for secret in secrets:
        if isinstance(secret, str) and secret:
            text = text.replace(secret, '[redacted]')
    text = re.sub(r'(?i)Bearer\s+\S+', 'Bearer [redacted]', text)
    return f'{type(error).__name__}: {text}'[:800]
