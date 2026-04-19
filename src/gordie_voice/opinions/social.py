"""Social media publishing for approved opinion recordings.

This module is called from the admin panel (not from the Pi device itself).
When an admin approves an opinion and enables social push, this module:
1. Downloads the video from Supabase Storage
2. Generates a caption from the transcript + category
3. Publishes to configured platforms (Twitter/X, YouTube Shorts, TikTok, Instagram)
4. Updates the opinion row with post URLs

Platform adapters are pluggable — each implements SocialAdapter ABC.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    pass

log = structlog.get_logger()


@dataclass
class SocialPost:
    platform: str
    post_url: str
    post_id: str


@dataclass
class OpinionMedia:
    video_url: str
    thumbnail_url: str | None
    transcript: str
    category: str
    duration_s: int
    user_display_name: str | None = None


class SocialAdapter(abc.ABC):
    """Base class for social media platform adapters."""

    @property
    @abc.abstractmethod
    def platform_name(self) -> str: ...

    @abc.abstractmethod
    def publish(self, media: OpinionMedia, caption: str) -> SocialPost:
        """Upload video and publish. Returns the post details."""

    def generate_caption(self, media: OpinionMedia) -> str:
        """Generate a default caption. Can be overridden per platform."""
        category_label = media.category.replace("_", " ").title()
        name = media.user_display_name or "A Canadian"
        caption = (
            f"{name} shares their opinion on {category_label}.\n\n"
            f"Recorded on a CanadaGPT Gordie appliance — "
            f"sovereign Canadian civic AI.\n\n"
            f"#CanadaGPT #CivicAI #CanadianVoices #{category_label.replace(' ', '')}"
        )
        return caption


class TwitterAdapter(SocialAdapter):
    """Publish opinion clips to Twitter/X."""

    platform_name = "twitter"

    def __init__(self, bearer_token: str) -> None:
        self._token = bearer_token

    def publish(self, media: OpinionMedia, caption: str) -> SocialPost:
        # Twitter v2 API media upload + tweet creation
        # This is a stub — full implementation requires chunked media upload
        log.info("twitter_publish", category=media.category)

        # 1. Upload media via v1.1 chunked upload endpoint
        # 2. Create tweet with media_id via v2 endpoint
        # Placeholder for actual implementation:
        raise NotImplementedError(
            "Twitter publishing requires OAuth 1.0a media upload + v2 tweet creation. "
            "See https://developer.twitter.com/en/docs/twitter-api/tweets/manage-tweets"
        )


class YouTubeAdapter(SocialAdapter):
    """Publish opinion clips as YouTube Shorts."""

    platform_name = "youtube"

    def __init__(self, credentials_path: str) -> None:
        self._credentials_path = credentials_path

    def publish(self, media: OpinionMedia, caption: str) -> SocialPost:
        log.info("youtube_publish", category=media.category)
        raise NotImplementedError(
            "YouTube publishing requires Google OAuth + YouTube Data API v3. "
            "See https://developers.google.com/youtube/v3/guides/uploading_a_video"
        )


class TikTokAdapter(SocialAdapter):
    """Publish opinion clips to TikTok."""

    platform_name = "tiktok"

    def __init__(self, access_token: str) -> None:
        self._token = access_token

    def publish(self, media: OpinionMedia, caption: str) -> SocialPost:
        log.info("tiktok_publish", category=media.category)
        raise NotImplementedError(
            "TikTok publishing requires TikTok Content Posting API. "
            "See https://developers.tiktok.com/doc/content-posting-api-get-started"
        )


class SocialPublisher:
    """Orchestrates publishing an opinion to multiple platforms."""

    def __init__(self, supabase_url: str, supabase_key: str) -> None:
        self._supabase_url = supabase_url
        self._supabase_key = supabase_key
        self._adapters: dict[str, SocialAdapter] = {}
        self._client = httpx.Client(
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
            },
            timeout=120.0,
        )

    def register_adapter(self, adapter: SocialAdapter) -> None:
        self._adapters[adapter.platform_name] = adapter

    def publish_opinion(self, opinion_id: str, platforms: list[str]) -> dict[str, str]:
        """Publish an approved opinion to the specified platforms.

        Returns dict of platform -> post_url for successful publishes.
        """
        # Fetch opinion metadata
        opinion = self._fetch_opinion(opinion_id)
        if not opinion:
            raise ValueError(f"Opinion {opinion_id} not found")

        if opinion["status"] not in ("approved", "published"):
            raise ValueError(f"Opinion {opinion_id} is not approved (status: {opinion['status']})")

        # Get signed URL for the video
        video_url = self._get_signed_url(opinion["storage_path"])

        media = OpinionMedia(
            video_url=video_url,
            thumbnail_url=self._get_signed_url(opinion["thumbnail_path"]) if opinion.get("thumbnail_path") else None,
            transcript=opinion.get("transcript", ""),
            category=opinion["category"],
            duration_s=opinion["duration_s"],
        )

        results: dict[str, str] = {}
        for platform in platforms:
            adapter = self._adapters.get(platform)
            if not adapter:
                log.warning("social_adapter_not_found", platform=platform)
                continue
            try:
                caption = adapter.generate_caption(media)
                post = adapter.publish(media, caption)
                results[platform] = post.post_url
                log.info("social_published", platform=platform, url=post.post_url)
            except NotImplementedError as e:
                log.warning("social_not_implemented", platform=platform, detail=str(e))
            except Exception:
                log.exception("social_publish_failed", platform=platform)

        # Update opinion row with results
        if results:
            self._update_opinion_social(opinion_id, results)

        return results

    def _fetch_opinion(self, opinion_id: str) -> dict | None:
        url = f"{self._supabase_url}/rest/v1/opinions?id=eq.{opinion_id}&select=*"
        response = self._client.get(url)
        response.raise_for_status()
        rows = response.json()
        return rows[0] if rows else None

    def _get_signed_url(self, storage_path: str) -> str:
        url = f"{self._supabase_url}/storage/v1/object/sign/opinions/{storage_path}"
        response = self._client.post(url, json={"expiresIn": 3600})
        response.raise_for_status()
        return f"{self._supabase_url}/storage/v1{response.json()['signedURL']}"

    def _update_opinion_social(self, opinion_id: str, post_urls: dict[str, str]) -> None:
        from datetime import datetime, timezone
        url = f"{self._supabase_url}/rest/v1/opinions?id=eq.{opinion_id}"
        self._client.patch(
            url,
            json={
                "status": "published",
                "social_post_urls": post_urls,
                "social_published_at": datetime.now(timezone.utc).isoformat(),
            },
            headers={"Content-Type": "application/json", "Prefer": "return=minimal"},
        ).raise_for_status()
