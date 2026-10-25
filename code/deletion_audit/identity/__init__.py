"""Identity: who a request is about, with every identifier they have held (R1, T59, T63)."""

from __future__ import annotations

from .resolve import IdentifierSet, IdentityResolution, PeopleIndex, build_people, email_hash, resolve, resolve_with

__all__ = [
    "IdentifierSet",
    "IdentityResolution",
    "PeopleIndex",
    "build_people",
    "email_hash",
    "resolve",
    "resolve_with",
]
