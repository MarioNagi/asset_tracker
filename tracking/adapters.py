from allauth.account.adapter import DefaultAccountAdapter


class ClosedAccountAdapter(DefaultAccountAdapter):
    """Keep account creation under company administrator control."""

    def is_open_for_signup(self, request):
        return False
