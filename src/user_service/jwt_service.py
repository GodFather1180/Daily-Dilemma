"""
JWT Service for handling token generation and validation.
"""

import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from authlib.jose import jwt
from authlib.jose.errors import ExpiredTokenError, InvalidTokenError


class JWTService:
    """
    Service for handling JWT token operations.
    """

    def __init__(self):
        self.private_key = self._get_or_create_private_key()
        self.public_key = self.private_key.public_key()
        self.algorithm = "RS256"

        # In-memory storage for expired tokens (in production, use Redis)
        self.expired_tokens = set()
        # Per-user last issued-at; tokens older than this are invalidated
        self.user_last_issued_at: dict[str, int] = {}

    def _get_or_create_private_key(self):
        """Get or create RSA private key for signing JWTs."""
        # In production, load from secure storage
        # For now, generate a new key each time (not recommended for production)
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        return private_key

    def _get_public_key_pem(self) -> str:
        """Get public key in PEM format."""
        pem = self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return pem.decode("utf-8")

    def _parse_expiry(self, expiry_str: str) -> int:
        """Parse expiry string to Unix timestamp."""
        try:
            # Parse format: "YYYY-MM-DD HH:MM:SS"
            dt = datetime.strptime(expiry_str, "%Y-%m-%d %H:%M:%S")
            # Convert to UTC timestamp
            dt_utc = dt.replace(tzinfo=timezone.utc)
            return int(dt_utc.timestamp())
        except ValueError:
            raise ValueError(f"Invalid expiry format: {expiry_str}")

    def _limit_expiry(self, requested_expiry: int) -> int:
        """Limit expiry to maximum 1 hour from now."""
        current_time = int(time.time())
        max_expiry = current_time + 3600  # 1 hour from now
        return min(requested_expiry, max_expiry)

    def issue_token(
        self,
        user_id: int,
        expiry_str: str,
        *,
        tier: int | None = None,
    ) -> str:
        """
        Issue a JWT token for a user.

        Args:
            user_id: The user ID
            expiry_str: Expiry datetime string in "YYYY-MM-DD HH:MM:SS" format

        Returns:
            JWT token string
        """
        try:
            requested_expiry = self._parse_expiry(expiry_str)
            actual_expiry = self._limit_expiry(requested_expiry)

            # Create payload
            issued_at = int(time.time())
            payload = {
                "sub": str(user_id),  # Subject (user ID)
                "exp": actual_expiry,  # Expiry time
                "iat": issued_at,  # Issued at
            }
            if tier is not None:
                payload["tier"] = int(tier)
            # Add unique token id to ensure tokens differ even with same payload
            import os as _os

            payload["jti"] = _os.urandom(8).hex()

            # Create header
            header = {
                "typ": "JWT",
                "alg": self.algorithm,
            }

            # Sign and encode the token
            token = jwt.encode(header, payload, self.private_key)
            # Record last issued-at for the user to expire older tokens
            self.user_last_issued_at[str(user_id)] = issued_at
            return token.decode("utf-8")

        except Exception as e:
            raise ValueError(f"Failed to issue token: {str(e)}")

    def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Validate a JWT token.

        Args:
            token: JWT token string

        Returns:
            Token payload if valid, None if invalid
        """
        try:
            # Check if token is in expired list
            if token in self.expired_tokens:
                return None

            # Decode and verify the token
            payload = jwt.decode(token, self.public_key)

            # Enforce per-user last-issued-at invalidation
            user_id = str(payload.get("sub", ""))
            last_iat = self.user_last_issued_at.get(user_id)
            if last_iat is not None and int(payload.get("iat", 0)) < last_iat:
                return None

            return payload

        except ExpiredTokenError:
            return None
        except InvalidTokenError:
            return None
        except Exception:
            return None

    def expire_token(self, token: str) -> bool:
        """
        Add a token to the expired list.

        Args:
            token: JWT token string

        Returns:
            True if token was added to expired list
        """
        try:
            # Validate token first to ensure it's properly formatted
            if self.validate_token(token):
                self.expired_tokens.add(token)
                return True
            return False
        except Exception:
            return False

    def expire_user_tokens(self, user_id: int) -> int:
        """
        Expire all tokens for a specific user.
        Note: This is a simplified implementation. In production, you'd need
        to track user tokens or use a more sophisticated approach.

        Args:
            user_id: The user ID

        Returns:
            Number of tokens expired
        """
        # This is a simplified implementation
        # In production, you'd maintain a mapping of user_id -> tokens
        # For now, we'll just return 0 as we can't easily track this
        # without a more complex token storage system
        return 0


# Global JWT service instance
jwt_service = JWTService()
