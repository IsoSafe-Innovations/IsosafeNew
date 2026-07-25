"""Shared request field types.

EmailAddress deliberately avoids pydantic's EmailStr: on-prem deployments use
internal domains (.local, .lan, .internal) that strict deliverability checks
reject.
"""
from typing import Annotated

from pydantic import StringConstraints

EmailAddress = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]
