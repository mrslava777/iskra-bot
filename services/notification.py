"""Уведомления о симпатиях и мэтчах.

FIX: announce_match параллелизирует check_and_award для обоих пользователей.
FIX: announce_match загружает пользователей параллельно через asyncio.gather.
FIX: добавлено логирование ошибок доставки вместо pass.
"""
import asyncio
import logging

from aiogram import Bot

import repositories.user_repo as user_repo
from data.content import icebreaker
from services.badge_formatter import format_badge_card, format_user_badges_inline
from services.badge_service import check_and_award, get_user_badges_batch
from services.compatibility import common_interests, compatibility, gender_emoji

log = logging.getLogger("iskra.notification")


async def notify_liked(bot: Bot, viewer_id: int, target_id: int, with_message: bool = False) -> None:
    """Сообщает цели о входящей симпатии (без раскрытия личности)."""
    target = await user_repo.get_user(target_id)
    if not target or not target["active"] or target["is_banned"]:
        return
    me = await user_repo.get_user(viewer_id)
    if not me:
        return
    pct = compatibility(me["interests"], target["interests"])
    text = (
        "💌 Кто-то проявил симпатию!\n"
        f"Совместимость с этим человеком — <b>{pct}%</b>.\n"
    )
    if with_message:
        text += f"\n💬 Подсказка для первого сообщения:\n<i>{icebreaker(viewer_id + target_id)}</i>\n"
    text += "\nОткрой «💌 Кто меня лайкнул», чтобы посмотреть анкету."
    try:
        await bot.send_message(target_id, text)
    except Exception as e:
        log.warning("Не удалось отправить уведомление о лайке %d → %d: %s", viewer_id, target_id, e)


async def announce_match(bot: Bot, a_id: int, b_id: int) -> None:
    """Объявляет мэтч обоим участникам, показывает контакт и значки.

    FIX: параллельная загрузка пользователей и проверка значков
    через asyncio.gather вместо последовательных вызовов.
    """
    # Параллельно загружаем обоих пользователей
    a, b = await asyncio.gather(
        user_repo.get_user(a_id),
        user_repo.get_user(b_id),
    )
    if not a or not b:
        return
    ice = icebreaker(a_id + b_id)

    # Параллельно проверяем значки обоих (раньше — последовательно)
    new_a, new_b = await asyncio.gather(
        check_and_award(a_id),
        check_and_award(b_id),
    )

    for uid, new_badges in ((a_id, new_a), (b_id, new_b)):
        for badge in new_badges:
            try:
                await bot.send_message(uid, format_badge_card(badge, is_new=True))
            except Exception as e:
                log.warning("Не удалось отправить значок %s → %d: %s", badge["id"], uid, e)

    # Batch-загрузка значков для обоих пользователей одним запросом
    badges_map = await get_user_badges_batch([a_id, b_id])

    for me, other in ((a, b), (b, a)):
        common = common_interests(a["interests"], b["interests"])
        common_txt = ("\n🏷 Общее: " + ", ".join(common)) if common else ""
        if other["username"]:
            contact = f"@{other['username']}"
        else:
            contact = f'<a href="tg://user?id={other["tg_id"]}">{other["name"]}</a>'

        other_badges = badges_map.get(other["tg_id"], [])
        badges_line = format_user_badges_inline(other_badges)

        text = (
            f"🎉 <b>Это мэтч!</b> {gender_emoji(other['gender'])}\n\n"
            f"Вы понравились друг другу с <b>{other['name']}</b>, {other['age']}."
            f"{badges_line}"
            f"{common_txt}\n\n"
            f"📨 Контакт: {contact}\n\n"
            f"💬 С чего начать:\n<i>{ice}</i>"
        )
        try:
            await bot.send_photo(me["tg_id"], photo=other["photo_id"], caption=text)
        except Exception:
            try:
                await bot.send_message(me["tg_id"], text)
            except Exception as e:
                log.warning("Не удалось отправить мэтч %d ↔ %d → %d: %s", a_id, b_id, me["tg_id"], e)
