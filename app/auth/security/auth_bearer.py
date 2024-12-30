from fastapi import Request, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.auth.security.tokens import verify_token


class JWTBearer(HTTPBearer):
    def __init__(self, auto_error: bool = True, expected_token_type: str = "access"):
        super().__init__(auto_error=auto_error)
        self.expected_token_type = expected_token_type

    async def __call__(self, request: Request):
        credentials: HTTPAuthorizationCredentials = await super().__call__(request)
        if credentials:
            if credentials.scheme != "Bearer":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid authentication scheme."
                )
            try:
                payload = verify_token(credentials.credentials, self.expected_token_type)
                return payload
            except HTTPException as e:
                raise e
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid authorization code."
            )