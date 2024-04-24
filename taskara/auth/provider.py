from abc import ABC, abstractmethod
import logging
import os
import time
import requests

from threadmem.server.models import V1UserProfile
from threadmem.db.conn import WithDB
from .key import KeyProvider, default_key_provider, MockProvider


class AuthProvider(ABC):
    @abstractmethod
    def key_provider(self) -> KeyProvider:
        pass

    @abstractmethod
    def get_user_auth(self, token: str) -> V1UserProfile:
        pass


class HubAuthProvider(AuthProvider):
    """Hub user auth"""

    _key_provider: KeyProvider

    def __init__(self, key_provider: KeyProvider = default_key_provider()) -> None:
        self.hub_url = os.environ.get("AGENTSEA_HUB_URL")
        if not self.hub_url:
            raise ValueError(
                "$AGENTSEA_HUB_URL must be set to user the Hub key provider"
            )

        self._key_provider = key_provider

    def key_provider(self) -> KeyProvider:
        return self._key_provider

    def get_user_auth(self, token: str) -> V1UserProfile:
        try:
            if self._key_provider.is_key(token):
                user = self._key_provider.validate(token)
                print("found user: ", user)

                return user

            else:
                headers = {"Authorization": f"Bearer {token}"}
                headers.update(
                    {
                        "User-Agent": "My User Agent 1.0",
                    }
                )
                auth_url = f"{self.hub_url}/v1/users/me"
                print("authorizing token with: ", auth_url)
                response = requests.get(auth_url, headers=headers)
                response.raise_for_status()

                user_data = response.json()
                user_schema = V1UserProfile(**user_data)
                user_schema.token = token
                return user_schema

        except Exception as e:
            logging.error(f"Problem fetching user auth {e}")
            raise Exception(
                "ID token was unauthorized, please log in",
            )


def default_auth_provider() -> AuthProvider:
    return HubAuthProvider()
