from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote, urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

from .config import Settings
from .models import (
    ContextImportRequest,
    ContextNoteCreate,
    IntegrationView,
    OAuthStartView,
    Provider,
    ProviderCapabilityView,
)
from .repository import SQLiteRepository


class IntegrationError(RuntimeError):
    pass


class Requester(Protocol):
    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, object] | None = None,
    ) -> httpx.Response: ...

    async def post(
        self,
        url: str,
        *,
        data: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        auth: tuple[str, str] | None = None,
    ) -> httpx.Response: ...


class HTTPRequester:
    def __init__(self, timeout_seconds: float = 20.0) -> None:
        self.timeout_seconds = timeout_seconds

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, object] | None = None,
    ) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            return await client.get(url, headers=headers, params=params)

    async def post(
        self,
        url: str,
        *,
        data: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        auth: tuple[str, str] | None = None,
    ) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            return await client.post(url, data=data, headers=headers, auth=auth)


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    provider: Provider
    client_id: str | None
    client_secret: str | None
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...]
    use_pkce: bool


class TokenCipher:
    def __init__(self, secret: str | None) -> None:
        self.secret = secret

    def _fernet(self) -> Fernet:
        if not self.secret or len(self.secret) < 32:
            raise IntegrationError(
                "OAUTH_ENCRYPTION_KEY must be configured with at least 32 characters"
            )
        derived = hashlib.sha256(self.secret.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(derived))

    def encrypt(self, value: dict[str, object]) -> str:
        return self._fernet().encrypt(json.dumps(value).encode()).decode()

    def decrypt(self, value: str) -> dict[str, object]:
        try:
            payload = self._fernet().decrypt(value.encode())
        except InvalidToken as exc:
            raise IntegrationError(
                "Stored OAuth credentials cannot be decrypted with this encryption key"
            ) from exc
        parsed = json.loads(payload)
        if not isinstance(parsed, dict):
            raise IntegrationError("Stored OAuth credentials are invalid")
        return parsed


def provider_specs(settings: Settings) -> dict[Provider, ProviderSpec]:
    return {
        Provider.GOOGLE: ProviderSpec(
            provider=Provider.GOOGLE,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            scopes=(
                "openid",
                "email",
                "profile",
                "https://www.googleapis.com/auth/calendar.readonly",
                "https://www.googleapis.com/auth/meetings.space.readonly",
            ),
            use_pkce=True,
        ),
        Provider.SLACK: ProviderSpec(
            provider=Provider.SLACK,
            client_id=settings.slack_client_id,
            client_secret=settings.slack_client_secret,
            authorize_url="https://slack.com/oauth/v2/authorize",
            token_url="https://slack.com/api/oauth.v2.access",
            scopes=(
                "channels:read",
                "channels:history",
                "groups:read",
                "groups:history",
            ),
            use_pkce=False,
        ),
        Provider.MICROSOFT: ProviderSpec(
            provider=Provider.MICROSOFT,
            client_id=settings.microsoft_client_id,
            client_secret=settings.microsoft_client_secret,
            authorize_url=(
                "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
            ),
            token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
            scopes=(
                "openid",
                "profile",
                "email",
                "offline_access",
                "User.Read",
                "Calendars.Read",
                "OnlineMeetings.Read",
                "Chat.Read",
            ),
            use_pkce=True,
        ),
        Provider.ZOOM: ProviderSpec(
            provider=Provider.ZOOM,
            client_id=settings.zoom_client_id,
            client_secret=settings.zoom_client_secret,
            authorize_url="https://zoom.us/oauth/authorize",
            token_url="https://zoom.us/oauth/token",
            scopes=(),
            use_pkce=True,
        ),
    }


def provider_capabilities() -> list[ProviderCapabilityView]:
    return [
        ProviderCapabilityView(
            provider=Provider.GOOGLE,
            role="meeting",
            oauth_supported=True,
            context_imports=["calendar_event", "meet_space"],
            live_audio_input="developer_preview",
            live_voice_output="not_supported_by_media_api",
            requirement=(
                "Meet Media API enrollment and in-meeting consent; use companion mode "
                "for voice output"
            ),
        ),
        ProviderCapabilityView(
            provider=Provider.SLACK,
            role="context",
            oauth_supported=True,
            context_imports=["channel"],
            live_audio_input="not_applicable",
            live_voice_output="not_applicable",
            requirement="Slack OAuth app installed with channel history scopes",
        ),
        ProviderCapabilityView(
            provider=Provider.MICROSOFT,
            role="meeting",
            oauth_supported=True,
            context_imports=["calendar_event", "teams_chat"],
            live_audio_input="calling_bot_required",
            live_voice_output="calling_bot_required",
            requirement="Azure Bot registration plus Microsoft Graph calling permissions",
        ),
        ProviderCapabilityView(
            provider=Provider.ZOOM,
            role="meeting",
            oauth_supported=True,
            context_imports=["meeting"],
            live_audio_input="meeting_sdk_required",
            live_voice_output="meeting_sdk_required",
            requirement="Zoom Meeting SDK app, SDK JWT, and meeting authorization",
        ),
    ]


class OAuthManager:
    def __init__(
        self,
        settings: Settings,
        repository: SQLiteRepository,
        requester: Requester | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.requester = requester or HTTPRequester()
        self.specs = provider_specs(settings)
        self.cipher = TokenCipher(settings.oauth_encryption_key)

    def redirect_uri(self, provider: Provider) -> str:
        return f"{self.settings.app_base_url}/integrations/{provider}/callback"

    def configured(self, provider: Provider) -> bool:
        spec = self.specs[provider]
        return bool(
            spec.client_id and spec.client_secret and self.settings.oauth_encryption_key
        )

    def list_integrations(self) -> list[IntegrationView]:
        result: list[IntegrationView] = []
        for provider in Provider:
            connected = self.repository.get_integration(provider)
            if connected:
                connected.configured = self.configured(provider)
                result.append(connected)
            else:
                result.append(
                    IntegrationView(
                        provider=provider,
                        connected=False,
                        configured=self.configured(provider),
                    )
                )
        return result

    def start(self, provider: Provider) -> OAuthStartView:
        spec = self.specs[provider]
        if not self.configured(provider):
            raise IntegrationError(
                f"{provider.value} OAuth client credentials or encryption key are missing"
            )

        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64) if spec.use_pkce else None
        params: dict[str, str] = {
            "response_type": "code",
            "client_id": str(spec.client_id),
            "redirect_uri": self.redirect_uri(provider),
            "state": state,
        }
        if provider is Provider.SLACK:
            params["user_scope"] = ",".join(spec.scopes)
        elif spec.scopes:
            params["scope"] = " ".join(spec.scopes)
        if provider is Provider.GOOGLE:
            params.update(
                {
                    "access_type": "offline",
                    "include_granted_scopes": "true",
                    "prompt": "consent",
                }
            )
        if verifier:
            challenge = hashlib.sha256(verifier.encode()).digest()
            params["code_challenge"] = (
                base64.urlsafe_b64encode(challenge).decode().rstrip("=")
            )
            params["code_challenge_method"] = "S256"

        self.repository.create_oauth_state(state, provider, verifier)
        return OAuthStartView(
            provider=provider,
            authorization_url=f"{spec.authorize_url}?{urlencode(params)}",
        )

    async def callback(
        self, provider: Provider, *, code: str, state: str
    ) -> IntegrationView:
        spec = self.specs[provider]
        if not self.configured(provider):
            raise IntegrationError(f"{provider.value} OAuth is not configured")
        try:
            verifier = self.repository.consume_oauth_state(state, provider)
        except ValueError as exc:
            raise IntegrationError(str(exc)) from exc

        data: dict[str, object] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri(provider),
        }
        auth: tuple[str, str] | None = None
        if provider in {Provider.SLACK, Provider.ZOOM}:
            auth = (str(spec.client_id), str(spec.client_secret))
        else:
            data.update(
                {"client_id": spec.client_id, "client_secret": spec.client_secret}
            )
        if verifier:
            data["code_verifier"] = verifier

        response = await self.requester.post(spec.token_url, data=data, auth=auth)
        try:
            payload = response.json()
        except ValueError as exc:
            raise IntegrationError(
                f"{provider.value} returned an invalid OAuth response"
            ) from exc
        if response.status_code >= 400 or not isinstance(payload, dict):
            raise IntegrationError(f"{provider.value} OAuth token exchange failed")
        if provider is Provider.SLACK and not payload.get("ok", False):
            raise IntegrationError(
                f"Slack OAuth failed: {payload.get('error', 'unknown error')}"
            )

        token_payload = payload
        account_id: str | None = None
        account_label: str | None = None
        if provider is Provider.SLACK:
            user_payload = payload.get("authed_user")
            if isinstance(user_payload, dict) and user_payload.get("access_token"):
                token_payload = {
                    **payload,
                    "access_token": user_payload["access_token"],
                    "scope": user_payload.get("scope", payload.get("scope", "")),
                }
            team_payload = payload.get("team")
            if isinstance(team_payload, dict):
                account_id = str(team_payload.get("id") or "") or None
                account_label = str(team_payload.get("name") or "") or None
        access_token = token_payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise IntegrationError(
                f"{provider.value} OAuth response has no access token"
            )

        scopes_raw = token_payload.get("scope", "")
        scopes = [value for value in str(scopes_raw).replace(",", " ").split() if value]
        encrypted = self.cipher.encrypt(token_payload)
        return self.repository.save_integration(
            provider,
            encrypted,
            account_id=account_id,
            account_label=account_label,
            scopes=scopes,
        )

    def access_token(self, provider: Provider) -> str:
        encrypted = self.repository.get_encrypted_credentials(provider)
        if not encrypted:
            raise IntegrationError(f"{provider.value} account is not connected")
        payload = self.cipher.decrypt(encrypted)
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise IntegrationError(f"{provider.value} access token is unavailable")
        return token


class ContextImporter:
    def __init__(self, oauth: OAuthManager) -> None:
        self.oauth = oauth

    async def import_context(self, request: ContextImportRequest) -> ContextNoteCreate:
        token = self.oauth.access_token(request.provider)
        headers = {"Authorization": f"Bearer {token}"}
        if request.provider is Provider.SLACK:
            return await self._slack(request, headers)
        if request.provider is Provider.GOOGLE:
            return await self._google(request, headers)
        if request.provider is Provider.MICROSOFT:
            return await self._microsoft(request, headers)
        if request.provider is Provider.ZOOM:
            return await self._zoom(request, headers)
        raise IntegrationError("Unsupported provider")

    async def _slack(
        self, request: ContextImportRequest, headers: dict[str, str]
    ) -> ContextNoteCreate:
        if request.resource_type != "channel":
            raise IntegrationError("Slack supports resource_type=channel")
        response = await self.oauth.requester.get(
            "https://slack.com/api/conversations.history",
            headers=headers,
            params={"channel": request.resource_id, "limit": min(request.limit, 15)},
        )
        payload = self._payload(response, Provider.SLACK)
        if not payload.get("ok", False):
            raise IntegrationError(
                f"Slack context import failed: {payload.get('error', 'unknown error')}"
            )
        messages = payload.get("messages", [])
        lines = [
            f"[{item.get('ts', '')}] {item.get('user', 'unknown')}: {item.get('text', '')}"
            for item in reversed(messages)
            if isinstance(item, dict) and item.get("text")
        ]
        return ContextNoteCreate(
            source="slack",
            title=f"Slack channel {request.resource_id}",
            content="\n".join(lines) or "No recent messages were returned.",
        )

    async def _google(
        self, request: ContextImportRequest, headers: dict[str, str]
    ) -> ContextNoteCreate:
        resource_id = quote(request.resource_id, safe="")
        if request.resource_type == "calendar_event":
            calendar_id = quote(request.container_id or "primary", safe="")
            url = (
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}"
                f"/events/{resource_id}"
            )
            response = await self.oauth.requester.get(url, headers=headers)
            payload = self._payload(response, Provider.GOOGLE)
            title = str(payload.get("summary") or "Google Calendar event")
            return ContextNoteCreate(
                source="google-calendar",
                title=title,
                content=json.dumps(payload, indent=2, ensure_ascii=False)[:100_000],
            )
        if request.resource_type == "meet_space":
            response = await self.oauth.requester.get(
                f"https://meet.googleapis.com/v2/spaces/{resource_id}", headers=headers
            )
            payload = self._payload(response, Provider.GOOGLE)
            return ContextNoteCreate(
                source="google-meet",
                title=f"Google Meet space {request.resource_id}",
                content=json.dumps(payload, indent=2, ensure_ascii=False)[:100_000],
            )
        raise IntegrationError(
            "Google supports resource_type=calendar_event or meet_space"
        )

    async def _microsoft(
        self, request: ContextImportRequest, headers: dict[str, str]
    ) -> ContextNoteCreate:
        resource_id = quote(request.resource_id, safe="")
        if request.resource_type == "calendar_event":
            response = await self.oauth.requester.get(
                f"https://graph.microsoft.com/v1.0/me/events/{resource_id}",
                headers=headers,
            )
            payload = self._payload(response, Provider.MICROSOFT)
            return ContextNoteCreate(
                source="microsoft-calendar",
                title=str(payload.get("subject") or "Microsoft calendar event"),
                content=json.dumps(payload, indent=2, ensure_ascii=False)[:100_000],
            )
        if request.resource_type == "teams_chat":
            response = await self.oauth.requester.get(
                f"https://graph.microsoft.com/v1.0/chats/{resource_id}/messages",
                headers=headers,
                params={"$top": request.limit},
            )
            payload = self._payload(response, Provider.MICROSOFT)
            return ContextNoteCreate(
                source="microsoft-teams",
                title=f"Teams chat {request.resource_id}",
                content=json.dumps(
                    payload.get("value", []), indent=2, ensure_ascii=False
                )[:100_000],
            )
        raise IntegrationError(
            "Microsoft supports resource_type=calendar_event or teams_chat"
        )

    async def _zoom(
        self, request: ContextImportRequest, headers: dict[str, str]
    ) -> ContextNoteCreate:
        if request.resource_type != "meeting":
            raise IntegrationError("Zoom supports resource_type=meeting")
        resource_id = quote(request.resource_id, safe="")
        response = await self.oauth.requester.get(
            f"https://api.zoom.us/v2/past_meetings/{resource_id}", headers=headers
        )
        payload = self._payload(response, Provider.ZOOM)
        return ContextNoteCreate(
            source="zoom",
            title=str(payload.get("topic") or f"Zoom meeting {request.resource_id}"),
            content=json.dumps(payload, indent=2, ensure_ascii=False)[:100_000],
        )

    @staticmethod
    def _payload(response: httpx.Response, provider: Provider) -> dict[str, object]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise IntegrationError(
                f"{provider.value} returned an invalid API response"
            ) from exc
        if response.status_code >= 400 or not isinstance(payload, dict):
            raise IntegrationError(f"{provider.value} context import failed")
        return payload
