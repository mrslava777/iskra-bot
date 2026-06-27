"""Форматирование значков — только презентация, без бизнес-логики выдачи."""
from data.constants import BadgeDisplay, Format, Message
from data.enums import Rarity
from badges import BADGE_BY_ID, RARITY_EMOJI, rarity_label


def format_badge_card(badge: dict, is_new: bool = False) -> str:
    rarity_emoji = RARITY_EMOJI.get(badge["rarity"], Rarity.COMMON.emoji)
    label = rarity_label(badge["rarity"])
    new_mark = Message.BADGE_NEW if is_new else ""
    return (
        f"{new_mark}"
        f"{badge['icon']} <b>{badge['name']}</b> {rarity_emoji}\n"
        f"<i>{badge['description']}</i>\n"
        f"{Message.BADGE_RARITY_LABEL.format(label)}"
    )


def format_user_badges_inline(badges: list[dict], max_show: int = BadgeDisplay.INLINE_MAX) -> str:
    if not badges:
        return ""
    shown = badges[:max_show]
    icons = " ".join(b["icon"] for b in shown)
    extra = Format.BADGE_EXTRA.format(len(badges) - max_show) if len(badges) > max_show else ""
    return Format.BADGE_INLINE.format(icons, extra)


async def get_user_badges_inline(tg_id: int) -> str:
    """Подгружает значки пользователя и форматирует строку."""
    from repositories.badge_repo import get_user_badge_ids
    badge_ids = await get_user_badge_ids(tg_id)
    badges = [BADGE_BY_ID[bid] for bid in badge_ids if bid in BADGE_BY_ID]
    return format_user_badges_inline(badges)
