from typing import Annotated
import logging

from fastapi import HTTPException, Depends

from fastapi.security import OAuth2PasswordBearer

from threadmem.server.models import V1UserProfile
from .provider import default_auth_provider

user_auth = default_auth_provider()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
) -> V1UserProfile:
    try:
        print("checking user token: ", token)
        user = user_auth.get_user_auth(token)
    except Exception as e:
        logging.error(e)
        raise HTTPException(
            status_code=401,
            detail=f"-ID token was unauthorized, please log in: {e}",
        )

    return user
