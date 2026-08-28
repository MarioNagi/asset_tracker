import hashlib
import os
import secrets
import time
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.text import get_valid_filename
from pypdf import PdfReader


class PendingPDFError(ValueError):
    """A safe pending-upload error that can be shown to an operator."""


class PendingPDFInvoiceStore:
    """Short-lived, session-bound storage for invoices awaiting confirmation."""

    SESSION_KEY = 'pending_pdf_invoice_import'
    MAX_AGE_SECONDS = 30 * 60
    STALE_FILE_AGE_SECONDS = 60 * 60

    def __init__(self, request):
        self.request = request
        self.storage = FileSystemStorage(
            location=Path(settings.MEDIA_ROOT) / 'pending_invoice_imports'
        )

    def create(self, uploaded_file):
        self.discard()
        self.cleanup_stale_files()

        token = secrets.token_urlsafe(32)
        stored_name = self.storage.save(f'{token}.pdf', uploaded_file)
        digest = self._sha256(stored_name)
        original_name = get_valid_filename(Path(uploaded_file.name).name)[:180]
        self.request.session[self.SESSION_KEY] = {
            'token': token,
            'stored_name': stored_name,
            'original_name': original_name or 'invoice.pdf',
            'sha256': digest,
            'created_at': time.time(),
        }
        self.request.session.modified = True
        return self.request.session[self.SESSION_KEY]

    def get(self, token):
        pending = self.request.session.get(self.SESSION_KEY)
        if not pending or not token or not secrets.compare_digest(
            str(token), str(pending.get('token', ''))
        ):
            raise PendingPDFError(
                'The pending invoice could not be verified. Please upload it again.'
            )

        if time.time() - pending.get('created_at', 0) > self.MAX_AGE_SECONDS:
            self.discard()
            raise PendingPDFError(
                'The invoice preview expired. Please upload the PDF again.'
            )

        stored_name = pending.get('stored_name', '')
        if not stored_name or not self.storage.exists(stored_name):
            self.discard()
            raise PendingPDFError(
                'The pending invoice file is no longer available. Please upload it again.'
            )
        if not secrets.compare_digest(
            self._sha256(stored_name), pending.get('sha256', '')
        ):
            self.discard()
            raise PendingPDFError(
                'The pending invoice failed its integrity check. Please upload it again.'
            )
        return pending

    def path(self, pending):
        return self.storage.path(pending['stored_name'])

    def open(self, pending, mode='rb'):
        return self.storage.open(pending['stored_name'], mode)

    def discard(self):
        pending = self.request.session.pop(self.SESSION_KEY, None)
        self.request.session.modified = True
        if pending and pending.get('stored_name'):
            self.storage.delete(pending['stored_name'])

    def cleanup_stale_files(self):
        if not os.path.isdir(self.storage.location):
            return
        cutoff = time.time() - self.STALE_FILE_AGE_SECONDS
        for name in os.listdir(self.storage.location):
            path = os.path.join(self.storage.location, name)
            if (
                name.endswith('.pdf')
                and os.path.isfile(path)
                and os.path.getmtime(path) < cutoff
            ):
                self.storage.delete(name)

    def _sha256(self, stored_name):
        digest = hashlib.sha256()
        with self.storage.open(stored_name, 'rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()


def validate_pdf_structure(pdf_path, max_pages=25):
    """Reject encrypted, empty, or unexpectedly large PDFs before parsing."""
    try:
        reader = PdfReader(pdf_path, strict=False)
        if reader.is_encrypted:
            raise PendingPDFError('Password-protected PDF invoices are not supported.')
        page_count = len(reader.pages)
    except PendingPDFError:
        raise
    except Exception as exc:
        raise PendingPDFError('The uploaded PDF could not be opened safely.') from exc

    if page_count < 1:
        raise PendingPDFError('The uploaded PDF does not contain any pages.')
    if page_count > max_pages:
        raise PendingPDFError(
            f'The PDF contains {page_count} pages; the maximum is {max_pages}.'
        )
    return page_count
