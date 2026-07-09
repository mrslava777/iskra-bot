"""Уведомления о симпатиях и мэтчах.

PERF: notify_liked загружает обоих пользователей параллельно.
PERF: announce_match параллелизирует все DB-операции.

FIX v7: добавлена обработка TelegramRetryAfter и TelegramForbiddenError.
        CancelledError теперь пробрасывается, а не ловится.
        Безопасный .get() доступ к полям dict.
"""
import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

import repositories.user_repo as user_repo
from data.content import icebreaker
from services.badge_formatter import format_badge_card, format_user_badges_inline
from services.badge_service import check_and_award, get_user_badges_batch
from services.compatibility import common_interests, compatibility, gender_emoji

log = logging.getLogger("iskra.notification")


async def notify_liked(
    bot: Bot, viewer_id: int, target_id: int, with_message: bool = False
) -> None:
    """Сообщает цели о входящей симпатии (без раскрытия личности).

    PERF: загружает обоих пользователей параллельно через asyncio.gather.
    """
    try:
        target, me = await asyncio.gather(
            user_repo.get_user(target_id),
            user_repo.get_user(viewer_id),
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Failed to load users for like notification")
        return

    # FIX v7: безопасный доступ к полям
    if target is None or not target.get("active") or target.get("is_banned"):
        return
    if me is None:
        return

    pct = compatibility(me.get("interests"), target.get("interests"))
    text = (
        "💌 Кто-то проявил симпатию!
"
        f"Совместимость с этим человеком — <b>{pct}%</b>.
"
    )
    if with_message:
        text += f"
💬 Подсказка для первого сообщения:
<i>{icebreaker(viewer_id + target_id)}</i>
"
    text += "
Открой «💌 Кто меня лайкнул», чтобы посмотреть анкету."

    try:
        await bot.send_message(target_id, text)
    except TelegramRetryAfter as e:
        log.warning("Rate limit notifying like, retry after %s", e.retry_after)
        await asyncio.sleep(e.retry_after)
        try:
            await bot.send_message(target_id, text)
        except Exception:
            log.warning("Failed to send like notification to %s after retry", target_id)
    except TelegramForbiddenError:
        log.debug("User %s blocked bot, skipping like notification", target_id)
    except Exception as e:
        log.warning(
            "Не удалось отправить уведомление о лайке %d → %d: %s",
            viewer_id,
            target_id,
            e,
        )


async def announce_match(bot: Bot, a_id: int, b_id: int) -> None:
    """Объявляет мэтч обоим участникам, показывает контакт и значки.

    PERF: все DB-операции параллелизированы — загрузка пользователей,
    проверка значков и batch-загрузка значков в одном asyncio.gather.
    """
    # Параллельно: оба пользователя + значки обоих + batch-загрузка значков
    try:
        a, b, new_a, new_b, badges_map = await asyncio.gather(
            user_repo.get_user(a_id),
            user_repo.get_user(b_id),
            check_and_award(a_id),
            check_and_award(b_id),
            get_user_badges_batch([a_id, b_id]),
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Failed to load data for match announcement")
        return

    if a is None or b is None:
        return
    ice = icebreaker(a_id + b_id)

    for uid, new_badges in ((a_id, new_a), (b_id, new_b)):
        for badge in new_badges:
            try:
                await bot.send_message(uid, format_badge_card(badge, is_new=True))
            except TelegramForbiddenError:
                log.debug("User %s blocked bot, skipping badge", uid)
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
                try:
                    await bot.send_message(uid, format_badge_card(badge, is_new=True))
                except Exception:
                    pass
            except Exception as e:
                log.warning(
                    "Не удалось отправить значок %s → %d: %s", badge["id"], uid, e
                )

    for me, other in ((a, b), (b, a)):
        # FIX v7: безопасный доступ к полям
        common = common_interests(a.get("interests"), b.get("interests"))
        common_txt = ("
🏷 Общее: " + ", ".join(common)) if common else ""
        if other.get("username"):
            contact = f"@{other['username']}"
        else:
            tg_id = other.get("tg_id", "?")
            name = other.get("name", "?")
            contact = f'<a href="tg://user?id={tg_id}">{name}</a>'

        other_badges = badges_map.get(other.get("tg_id"), [])
        badges_line = format_user_badges_inline(other_badges)

        text = (
            f"🎉 <b>Это мэтч!</b> {gender_emoji(other.get('gender'))}

"
            f"Вы понравились друг другу с <b>{other.get('name', '?')}</b>, {other.get('age', '?')}."
            f"{badges_line}"
            f"{common_txt}

"
            f"📨 Контакт: {contact}

"
            f"💬 С чего начать:
<i>{ice}</i>"
        )
        try:
            await bot.send_photo(me.get("tg_id"), photo=other.get("photo_id"), caption=text)
        except TelegramForbiddenError:
            log.debug("User %s blocked bot, skipping match photo", me.get("tg_id"))
        except Exception:
            try:
                await bot.send_message(me.get("tg_id"), text)
            except TelegramForbiddenError:
                log.debug(
                    "User %s blocked bot, skipping match text", me.get("tg_id")
                )
            except Exception as e:
                log.warning(
                    "Не удалось отправить мэтч %d ↔ %d → %d: %s",
                    a_id,
                    b_id,
                    me.get("tg_id"),
                    e,
                )
