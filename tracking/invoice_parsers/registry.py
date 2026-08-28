"""Registry for focused invoice-format parsers.

Add new format parsers here in most-specific-first order. Returning ``None``
means that a parser does not recognize the document and allows the coordinator
to continue to its existing supplier and generic fallbacks.
"""

from .mechanicdesk import parse_mechanicdesk_invoice


FORMAT_PARSERS = (
    parse_mechanicdesk_invoice,
)


def parse_known_invoice(text):
    for parser in FORMAT_PARSERS:
        invoice = parser(text)
        if invoice is not None:
            return invoice
    return None
