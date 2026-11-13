"""Fica à parte de ``download`` para que a abertura não carregue ``requests`` só para declarar esta classe."""

import requests


class ResponseTooLargeError(requests.RequestException):
    """Raised when a body exceeds the allowed size.

    Subclasses ``requests.RequestException`` so existing download error handling
    (which already catches request failures) treats an oversized body the same
    way as any other failed request.
    """
