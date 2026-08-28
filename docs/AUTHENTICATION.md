# Account Security and Future Microsoft Entra Sign-In

## Current account security

The application supports authenticator-app two-factor authentication and recovery codes.

- Admin and Manager accounts must enroll before using operational pages.
- Standard User accounts can enroll from the **Security** link.
- After enrollment, password login requires a current authenticator code or an unused recovery code.
- Recovery codes should be downloaded and stored separately from the phone running the authenticator app.
- The required roles are controlled by `DJANGO_MFA_REQUIRED_ROLES`. The default is `Admin,Manager`; use `Admin,Manager,User` to require enrollment for every account.

If someone loses both the authenticator device and all recovery codes, an administrator must first verify the person's identity through an agreed business process. Only then should an authorized operator remove that person's MFA authenticator record through the Django administration site and require immediate re-enrollment. This action should be recorded in an audit log or support record.

## Microsoft Entra roadmap

Microsoft Entra sign-in is intentionally not enabled yet. Enabling a provider before the organization confirms its tenant and application settings would create an incomplete or unsafe login option.

Before implementation, the project owner should confirm:

1. Whether sign-in is limited to one Entra tenant or supports multiple organizations.
2. Which Entra tenant owns the application registration.
3. Who controls the client ID, client secret, secret rotation, and redirect URLs.
4. Whether local username/password login remains available as an emergency fallback.
5. How Entra users and groups map to Admin, Manager, and User roles and to operational states.
6. Whether Entra's own MFA policy replaces or complements the application's authenticator challenge for Entra sessions.
7. How accounts are disabled when a person leaves the organization.

The expected callback route for the django-allauth Microsoft provider is:

```text
https://<production-domain>/accounts/microsoft/login/callback/
```

When those decisions and credentials are available, the implementation should:

1. Add the Microsoft provider application.
2. Read tenant, client ID, and client secret only from the deployment environment or approved secret store.
3. Restrict tenancy to the confirmed organization or tenant ID.
4. Add an explicit **Sign in with Microsoft** option.
5. Add tests for first login, returning login, role mapping, disabled users, tenant rejection, local fallback, and MFA behavior.
6. Pilot with non-administrator accounts before enabling it for privileged users.

Reference: <https://docs.allauth.org/en/latest/socialaccount/providers/microsoft.html>
