"""Services package — business logic."""
from services.compatibility import compatibility, common_interests, compat_bar, gender_emoji, fire_level, interests_text
from services.profile_formatter import format_profile, format_profile_async
from services.badge_service import check_and_award, get_user_badges
from services.badge_formatter import format_badge_card, format_user_badges_inline
from services.relationship_service import RelationshipService, get_relationship, add_message_event, format_status
from services.notification import notify_liked, announce_match
from services.anon_rate_limiter import check_rate_limit
from services.admin_service import is_admin
from services.message_utils import edit_or_caption

__all__ = [
    "compatibility", "common_interests", "compat_bar", "gender_emoji", "fire_level", "interests_text",
    "format_profile", "format_profile_async",
    "check_and_award", "get_user_badges", "format_badge_card", "format_user_badges_inline",
    "RelationshipService", "get_relationship", "add_message_event", "format_status",
    "notify_liked", "announce_match",
    "check_rate_limit",
    "is_admin",
    "edit_or_caption",
]
