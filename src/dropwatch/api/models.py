"""Request/response models. Field names are the contract phase 3's UI types are generated from."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class RewardOut(BaseModel):
    name: str
    image_url: str


class DropOut(BaseModel):
    id: str
    name: str
    required_minutes: int
    current_minutes: int
    claimed: bool
    starts_at: datetime
    ends_at: datetime
    rewards: list[RewardOut]


class CampaignOut(BaseModel):
    id: str
    name: str
    game: str
    box_art_url: str
    ends_at: datetime
    linked: bool | None
    maybe_unlinked: bool = False
    link_url: str
    allowed_channels: list[str]
    minutes_needed: int
    verdict: str | None
    drops: list[DropOut]


class ChannelOut(BaseModel):
    login: str
    viewers: int
    favourite: bool


class CurrentOut(BaseModel):
    campaign: CampaignOut
    channel: ChannelOut
    reason: str
    channel_reason: str
    also_credited: list[str]
    channels: list[ChannelOut] = []  # other live channels that qualify (the "change" picker)


class SwitchOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from")
    to: str
    at: datetime


class CatalogOut(BaseModel):
    status: str  # ok | stale | unreachable
    since: datetime | None


class StateOut(BaseModel):
    state: str
    signed_in: bool
    login: str | None
    paused_until: datetime | None
    last_refresh: datetime | None
    current: CurrentOut | None
    needs_you: list[CampaignOut]
    up_next: list[CampaignOut]
    done: list[CampaignOut]
    catalog: CatalogOut | None = None  # set when campaigns come from the public catalogue (TV login)
    last_switch: SwitchOut | None = None  # for 10 minutes after the channel changed
    next_check_at: datetime | None = None  # the runner's next Twitch refresh (or retry)


class ListsIn(BaseModel):
    priority: list[str] = Field(default_factory=list, max_length=200)
    never: list[str] = Field(default_factory=list, max_length=200)
    favourites: list[str] = Field(default_factory=list, max_length=200)


class ListsOut(BaseModel):
    priority: list[str]
    never: list[str]
    favourites: list[str]


class SettingsIn(BaseModel):
    # StrictBool: pydantic's lax mode would turn "yes" or 1 into True
    mine_badges: StrictBool | None = None
    claim_points: StrictBool | None = None
    notify_target: str | None = Field(default=None, max_length=500)
    notify_claimed: StrictBool | None = None
    notify_needs_you: StrictBool | None = None
    notify_signin: StrictBool | None = None


class SettingsOut(BaseModel):
    mine_badges: bool
    claim_points: bool
    notify_target: str
    notify_claimed: bool
    notify_needs_you: bool
    notify_signin: bool


class PasswordIn(BaseModel):
    password: str = Field(max_length=200)


class PauseIn(BaseModel):
    minutes: int | None = Field(default=None, ge=1, le=1440)


class MineNowIn(BaseModel):
    campaign_id: str = Field(min_length=1, max_length=100)


class ChannelIn(BaseModel):
    login: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_]+$")


class ClaimOut(BaseModel):
    at: datetime
    campaign_id: str
    campaign: str
    game: str
    rewards: list[RewardOut]


class HistoryOut(BaseModel):
    total_rewards: int
    claims: list[ClaimOut]  # newest first; the page groups by the viewer's local day


class SignInStatus(BaseModel):
    status: str  # idle | waiting | done | expired | failed
    message: str = ""
    code: str | None = None  # the 8 letters to enter at verification_uri
    verification_uri: str | None = None
    expires_at: datetime | None = None


class MeOut(BaseModel):
    authenticated: bool
    setup_required: bool


class ChannelSuggestion(BaseModel):
    login: str
    live: bool  # live now with drops on, as of the last refresh
    game: str | None  # what it is (or was last) streaming
    last_seen: datetime | None  # last seen live; None if never seen (a favourite added by name)


class SuggestionsOut(BaseModel):
    games: list[str]
    channels: list[ChannelSuggestion]  # live first, then most recently seen, then never-seen favourites
