from django import forms

from allauth.mfa.totp.forms import ActivateTOTPForm
from allauth.mfa.totp.internal import auth


class StableActivateTOTPForm(ActivateTOTPForm):
    """Keep one pending TOTP secret until enrollment succeeds.

    Allauth normally regenerates the secret on every unbound GET. That makes a
    previously scanned QR code invalid after a refresh or repeated middleware
    redirect. The pending secret already lives in the signed-in user's session,
    so reuse it for both GET and POST until allauth clears it on activation.
    """

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")
        forms.Form.__init__(self, *args, **kwargs)
        self.secret = auth.get_totp_secret(regenerate=False)
