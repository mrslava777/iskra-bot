"""Раздел «Артефакты» — коллекция значков и прогресс."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import repositories.badge_repo as badge_repo
import repositories.user_repo as user_repo
from badges import BADGES, RARITY_EMOJI, RARITY_ORDER, get_badge_progress, rarity_label
from data.constants import EMOJI, MenuText, Message as Msg, ProgressBar
from data.enums import BadgeAction, CallbackPrefix, Command as Cmd
from keyboards import HIDE_MENU, MAIN_MENU, badges_kb, badge_progress_kb
from services.badge_formatter import format_badge_card
from services.badge_service import check_and_award, get_user_badges, get_user_stats

router = Router()

TOTAL_BADGES = len(BADGES)
_BADGE_PAGE_SIZE = 10


def _mini_bar(pct: int) -> str:
    """Компактный прогресс-бар."""
    filled = min(10, pct // 10)
    return ProgressBar.FILLED * filled + ProgressBar.EMPTY * (10 - filled)


def _format_collection(badges: list[dict]) -> str:
    """Текст коллекции значков пользователя."""
    if not badges:
        return Msg.NO_BADGES
    ordered = sorted(badges, key=lambda b: RARITY_ORDER.get(b["rarity"], 0), reverse=True)
    lines = [Msg.BADGE_COLLECTION_TITLE.format(len(badges)), ""]
    for b in ordered:
        emoji = RARITY_EMOJI.get(b["rarity"], "⚪")
        lines.append(f"{b['icon']} <b>{b['name']}</b> {emoji}
<i>{b['description']}</i>")

    # Прогресс-бар в коллекции
    pct = int(len(badges) / TOTAL_BADGES * 100)
    bar = _mini_bar(pct)
    lines.append(f"
📊 Собрано: <b>{len(badges)}</b> / {TOTAL_BADGES} ({pct}%)")
    lines.append(f"{bar}")
    return "
".join(lines)


def _format_progress(locked: list[dict], user: dict, stats: dict, page: int = 0) -> str:
    """Форматирует страницу прогресса (недостающих артефактов) с прогрессом под каждым."""
    if not locked:
        return "🎉 <b>Все артефакты собраны!</b>

Ты настоящий легенда Искры!"

    start = page * _BADGE_PAGE_SIZE
    end = start + _BADGE_PAGE_SIZE
    page_badges = locked[start:end]
    total_pages = (len(locked) + _BADGE_PAGE_SIZE - 1) // _BADGE_PAGE_SIZE

    lines = ["📈 <b>Прогресс Артефактов</b>", ""]
    lines.append(f"🔒 Осталось собрать: <b>{len(locked)}</b> / {TOTAL_BADGES}")
    lines.append("")

    for b in page_badges:
        emoji = RARITY_EMOJI.get(b["rarity"], "⚪")
        lines.append(f"{b['icon']} <b>{b['name']}</b> {emoji} ({rarity_label(b['rarity'])})")
        lines.append(f"<i>└ {b['description']}</i>")

        # ⬇️ ПРОГРЕСС ПОД КАЖДЫМ АРТЕФАКТОМ
        progress_line = get_badge_progress(b, user, stats)
        if progress_line:
            lines.append(f"<code>  {progress_line}</code>")
        else:
            # Бинарные (да/нет) — показываем статус
            if b["condition"](user, stats):
                lines.append(f"<code>  ✅ Условие выполнено!</code>")
            else:
                lines.append(f"<code>  ⏳ Ещё не выполнено</code>")
        lines.append("")  # отступ между артефактами

    if total_pages > 1:
        lines.append(f"📄 Страница {page + 1} / {total_pages}")

    return "
".join(lines)


@router.message(Command(Cmd.BADGES.value[1:]))
@router.message(F.text == MenuText.BADGES)
async def cmd_badges(message: Message) -> None:
    """Показывает коллекцию артефактов. Скрывает меню."""
    user = await user_repo.get_user(message.from_user.id)
    if not user or not user["name"]:
        await message.answer(Msg.CREATE_PROFILE_FIRST)
        return

    new_badges = await check_and_award(message.from_user.id)
    for badge in new_badges:
        await message.answer(format_badge_card(badge, is_new=True))

    badges = await get_user_badges(message.from_user.id)
    await message.answer(_format_collection(badges), reply_markup=badges_kb(len(badges)))
    # Скрываем полное меню
    await message.answer("👆 Артефакты", reply_markup=HIDE_MENU)


@router.callback_query(F.data == f"{CallbackPrefix.BADGE.value}:{BadgeAction.COLLECTION.value}")
async def cb_collection(call: CallbackQuery) -> None:
    """Обновляет коллекцию."""
    await check_and_award(call.from_user.id)
    badges = await get_user_badges(call.from_user.id)
    try:
        await call.message.edit_text(_format_collection(badges), reply_markup=badges_kb(len(badges)))
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data.startswith(f"{CallbackPrefix.BADGE.value}:{BadgeAction.PROGRESS.value}"))
async def cb_progress(call: CallbackQuery) -> None:
    """Показывает прогресс (недостающие значки) с пагинацией.

    Фикс: используем startswith вместо == чтобы ловить bdg:progress:0, bdg:progress:1 и т.д.
    """
    earned = await badge_repo.get_user_badge_ids(call.from_user.id)
    locked = [b for b in BADGES if b["id"] not in earned]

    # Определяем страницу из callback_data
    parts = call.data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 0

    total_pages = max(1, (len(locked) + _BADGE_PAGE_SIZE - 1) // _BADGE_PAGE_SIZE) if locked else 1
    page = max(0, min(page, total_pages - 1))

    # ⬇️ ОПТИМИЗАЦИЯ: собираем статистику один раз
    user, stats = await get_user_stats(call.from_user.id)

    text = _format_progress(locked, user, stats, page)
    kb = badge_progress_kb(page=page, total_pages=total_pages)

    try:
        await call.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data == f"{CallbackPrefix.BADGE.value}:{BadgeAction.BACK.value}")
async def cb_back_to_menu(call: CallbackQuery) -> None:
    """Возврат в главное меню из артефактов."""
    await call.message.answer("Главное меню:", reply_markup=MAIN_MENU)
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.answer()
