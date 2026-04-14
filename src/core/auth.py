from functools import lru_cache

import requests
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError

from .configs import settings

CERTS_URL = "https://portal.igotkarmayogi.gov.in/auth/realms/sunbird/protocol/openid-connect/certs"
EXPECTED_ISSUER = "https://portal.igotkarmayogi.gov.in/auth/realms/sunbird"


# Registers as a Bearer security scheme → shows as the lock icon in Swagger UI
_bearer_scheme = HTTPBearer()


@lru_cache(maxsize=10)
def _get_public_key(kid: str) -> dict:
    """Fetch and cache the JWK for a given kid from the iGOT certs endpoint."""
    response = requests.get(CERTS_URL, timeout=10)
    response.raise_for_status()
    for key in response.json().get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


def require_cbp_creator(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> str:
    """
    FastAPI dependency that validates an iGOT JWT and enforces the cbp_creator role.
    Returns the authenticated user_id on success.
    Raises HTTP 401 for invalid/expired tokens and HTTP 403 for missing role.
    """
    token = credentials.credentials

    # Extract kid from unverified header
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: could not parse header.",
        )

    kid = unverified_header.get("kid")
    if not kid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing kid in header.",
        )

    # Fetch public key (cached by kid)
    public_key = _get_public_key(kid)
    if not public_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token validation failed: public key not found.",
        )

    # Validate signature, expiry, and issuer
    try:
        decoded = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=EXPECTED_ISSUER,
            options={"verify_aud": False},
        )
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
        )
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {str(e)}",
        )

    # Enforce required role
    user_roles = decoded.get("user_roles", [])
    if settings.REQUIRED_ROLE not in user_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: '{settings.REQUIRED_ROLE}' role required.",
        )

    # Extract and return the actual user ID from the sub claim
    raw_sub = decoded.get("sub", "")
    return raw_sub.split(":")[-1]
