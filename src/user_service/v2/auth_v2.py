"""
Authentication endpoints for v2 API.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from user_service.v1.models.user import UserRepository, get_user_repository
from user_service.jwt_service import jwt_service
import bcrypt


router = APIRouter()


class AuthenticationRequest(BaseModel):
    """Request model for authentication."""

    name: str
    password: str
    expiry: str


class AuthenticationResponse(BaseModel):
    """Response model for authentication."""

    jwt: str


class TokenExpiryRequest(BaseModel):
    """Request model for token expiry."""

    jwt: str


@router.post("/authentications/", response_model=AuthenticationResponse)
async def create_authentication(
    request: AuthenticationRequest,
    user_repo: UserRepository = Depends(get_user_repository),
):
    """
    Create a JWT authentication token.

    Args:
        request: Authentication request with name, password, and expiry
        user_repo: User repository dependency

    Returns:
        JWT token

    Raises:
        HTTPException: 401 if credentials are invalid
    """
    # Get user by name
    user = await user_repo.get_by_name(request.name)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Verify password
    if not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not bcrypt.checkpw(
        request.password.encode("utf-8"), user.password_hash.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Issue JWT token
    try:
        jwt_token = jwt_service.issue_token(
            user.id,
            request.expiry,
            tier=getattr(user, "tier", 1),
        )

        # Expire any previous tokens for this user
        jwt_service.expire_user_tokens(user.id)
        # Reset any existing rate-limit buckets for this user so a
        # fresh token starts clean
        try:
            from user_service.v1 import api as v1_api  # lazy import to avoid cycles

            prefix = f"user:{user.id}:"
            to_delete = [
                k for k in list(v1_api._RATE_BUCKETS.keys()) if k.startswith(prefix)
            ]
            for k in to_delete:
                v1_api._RATE_BUCKETS.pop(k, None)
        except Exception:
            pass

        return AuthenticationResponse(jwt=jwt_token)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/authentications/")
async def delete_authentication(request: TokenExpiryRequest):
    """
    Expire a JWT authentication token.

    Args:
        request: Token expiry request with JWT

    Returns:
        Success message
    """
    success = jwt_service.expire_token(request.jwt)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid token")

    return {"message": "Token expired successfully"}
