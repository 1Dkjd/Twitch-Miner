"""Twitch protocol constants. Ported verbatim from reference/fireph-webui/constants.py
(fireph/TwitchDropsMiner @ 10706072, MIT). Update hashes here only."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClientInfo:
    client_url: str
    client_id: str
    user_agent: str


ANDROID_APP = ClientInfo(
    "https://www.twitch.tv",
    "kd1unb4b3q4t58fwlpcbzcbnm76a8fp",
    "Dalvik/2.1.0 (Linux; U; Android 16; SM-S911B Build/TP1A.220624.014) "
    "tv.twitch.android.app/25.3.0/2503006",
)
WEB = ClientInfo(
    "https://www.twitch.tv",
    "kimne78kx3ncx6brgo4mv6wki5h1ko",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36",
)

GQL_URL = "https://gql.twitch.tv/gql"
PUBSUB_URL = "wss://pubsub-edge.twitch.tv/v1"
WATCH_INTERVAL = 59  # spade minute-watched cadence
PLAY_INTERVAL = 10  # playlist poll cadence while simulating playback (JourneyDocker 870c8b5)
PING_INTERVAL = 180
PONG_TIMEOUT = 10
GQL_BATCH = 20

GQL_OPS: dict[str, tuple[str, str, dict]] = {
    "GetStreamInfo": ("VideoPlayerStreamInfoOverlayChannel",
                      "198492e0857f6aedead9665c81c5a06d67b25b58034649687124083ff288597d",
                      {"channel": None}),
    "ClaimCommunityPoints": ("ClaimCommunityPoints",
                             "46aaeebe02c99afdf4fc97c7c0cba964124bf6b0af229395f1f6d1feed05b3d0",
                             {"input": {"claimID": None, "channelID": None}}),
    "ClaimDrop": ("DropsPage_ClaimDropRewards",
                  "a455deea71bdc9015b78eb49f4acfbce8baa7ccbedd28e549bb025bd0f751930",
                  {"input": {"dropInstanceID": None}}),
    "Inventory": ("Inventory",
                  "8337eb8541b314040b0edde0c09c5c7a2783ba1960aa9edfbf3bac16d0fec404",
                  {"fetchRewardCampaigns": False}),
    "CurrentDrop": ("DropCurrentSessionContext",
                    "4d06b702d25d652afb9ef835d2a550031f1cf762b193523a92166f40ea3d142b",
                    {"channelID": None, "channelLogin": ""}),
    "Campaigns": ("ViewerDropsDashboard",
                  "c16bb890cc8ce7647a96ee69cd313d423a378a3dedadf630a1017cde18975feb",
                  {"fetchRewardCampaigns": False}),
    "CampaignDetails": ("DropCampaignDetails",
                        "039277bf98f3130929262cc7c6efd9c141ca3749cb6dca442fc8ead9a53f77c1",
                        {"channelLogin": None, "dropID": None}),
    "PlaybackAccessToken": ("PlaybackAccessToken",
                            "ed230aa1e33e07eebb8928504583da78a5173989fadfb1ac94be06a04f3cdbe9",
                            {"isLive": True, "isVod": False, "login": None, "platform": "web",
                             "playerType": "site", "vodID": ""}),
    "GameDirectory": ("DirectoryPage_Game",
                      "86bcceb4e8b1a51256ff8eed8bd8aae4acacf80d737efe904f84f3aeadf8cafd",
                      {"limit": 30, "slug": None, "imageWidth": 50, "includeCostreaming": False,
                       "options": {"broadcasterLanguages": [], "freeformTags": None,
                                   "includeRestricted": ["SUB_ONLY_LIVE"],
                                   "recommendationsContext": {"platform": "web"},
                                   "sort": "RELEVANCE", "systemFilters": [], "tags": [],
                                   "requestID": "JIRA-VXP-2397"},
                       "sortTypeIsRecency": False}),
}

TOPICS = {
    "user_drops": "user-drop-events",
    "user_notifications": "onsite-notifications",
    "user_points": "community-points-user-v1",
    "stream_state": "video-playback-by-id",
    "stream_update": "broadcast-settings-update",
}
