"""Настройки анкеты — активность, фильтры, поддержка, удаление.

FIX: добавлен обработчик callback set:support — раньше кнопка не работала.
FIX: единая логика меню — при входе в раздел показывается HIDE_MENU.
FIX: unterminated f-string literals (line 112).
FIX: "Моя анкета" перенесена в настройки.
FIX: "Моя анкета" из настроек теперь корректно показывает профиль пользователя
     (использует call.from_user.id вместо call.message.from_user.id, т.к.
     call.message — это сообщение бота, а не пользователя).
"""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import repositories.user_repo as user_repo
import repositories.photo_repo as photo_repo
from data.constants import Age, EMOJI, MenuText, Message, Format
from data.enums import CallbackPrefix, SettingsAction
from keyboards import confirm_delete_kb, settings_kb, MAIN_MENU, HIDE_MENU, profile_kb
from services.profile_formatter import format_profile_async
from services.badge_service import check_and_award
from services.badge_formatter import format_badge_card
from states import Edit
import asyncio

router = Router()


@router.message(F.text == MenuText.SETTINGS)
async def show_settings(message: Message) -> None:
    """Показывает меню настроек."""
    user = await user_repo.get_user(message.from_user.id)
    if not user:
        await message.answer(Message.CREATE_PROFILE_FIRST)
        return
    active = bool(user.get("active"))
    # FIX: показываем HIDE_MENU вместо полного меню
    await message.answer(f"{EMOJI.SETTINGS} Настройки", reply_markup=HIDE_MENU)
    # Отправляем inline-клавиатуру настроек отдельным сообщением
    await message.answer("Выбери действие:", reply_markup=settings_kb(active))


@router.callback_query(F.data == f"{CallbackPrefix.SETTINGS.value}:back")
async def on_settings_back(call: CallbackQuery) -> None:
    """Шаг назад — возврат в профиль из настроек."""
    user = await user_repo.get_user(call.from_user.id)
    caption = await format_profile_async(user, show_compat=False, show_badges=True)
    from keyboards import profile_kb
    try:
        await call.message.edit_text(caption, reply_markup=profile_kb())
    except Exception:
        await call.message.answer(caption, reply_markup=profile_kb())
    await call.answer()


@router.callback_query(F.data == f"{CallbackPrefix.EDIT.value}:profile")
async def on_settings_profile(call: CallbackQuery) -> None:
    """Показывает анкету пользователя из настроек (бывшая кнопка 'Моя анкета').

    FIX: используем call.from_user.id вместо call.message.from_user.id,
    т.к. call.message — это сообщение бота с inline-клавиатурой,
    и message.from_user.id = id бота, а не пользователя.
    """
    user = await user_repo.get_user(call.from_user.id)
    if not user or not user["name"]:
        await call.message.answer(Message.CREATE_PROFILE_FIRST)
        await call.answer()
        return

    # Параллельно: форматирование + счётчик фото + проверка значков
    caption, n_photos, new_badges = await asyncio.gather(
        format_profile_async(user, show_compat=False, show_badges=True),
        photo_repo.photo_count(call.from_user.id),
        check_and_award(call.from_user.id),
    )

    photo_note = Format.PHOTO_COUNT.format(n_photos) if n_photos > 1 else ""
    caption += photo_note
    kb = profile_kb()

    try:
        await call.message.answer_photo(photo=user["photo_id"], caption=caption, reply_markup=kb)
    except Exception:
        await call.message.answer(caption, reply_markup=kb)

    # Отправляем уведомления о новых значках
    for badge in new_badges:
        try:
            await call.message.answer(format_badge_card(badge, is_new=True))
        except Exception:
            pass

    await call.answer()


@router.callback_query(F.data == f"{CallbackPrefix.SETTINGS.value}:{SettingsAction.TOGGLE.value}")
async def on_toggle_active(call: CallbackQuery) -> None:
    """Переключает видимость анкеты."""
    user = await user_repo.get_user(call.from_user.id)
    new_active = 0 if user.get("active") else 1
    await user_repo.upsert_user(call.from_user.id, active=new_active)
    status = f"{EMOJI.ACTIVE} Анкета активна" if new_active else f"{EMOJI.INACTIVE} Анкета скрыта"
    await call.answer(status, show_alert=True)
    await call.message.answer("Главное меню:", reply_markup=MAIN_MENU)


@router.callback_query(F.data == f"{CallbackPrefix.SETTINGS.value}:{SettingsAction.AGE_FILTER.value}")
async def on_set_age_filter(call: CallbackQuery, state: FSMContext) -> None:
    """Запрашивает фильтр по возрасту."""
    await call.message.answer(f"🎚 Введи диапазон возраста: мин макс (например: {Age.MIN} {Age.MAX})")
    await state.set_state(Edit.filters_age)
    await call.answer()


@router.message(Edit.filters_age, F.text)
async def save_age_filter(message: Message, state: FSMContext) -> None:
    """Сохраняет фильтр по возрасту."""
    parts = message.text.strip().split()
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        await message.answer("Введи два числа через пробел: мин макс")
        return
    min_age, max_age = int(parts[0]), int(parts[1])
    if not (Age.MIN <= min_age < max_age <= Age.MAX):
        await message.answer(Message.AGE_RANGE_INVALID)
        return
    await user_repo.upsert_user(message.from_user.id, min_age=min_age, max_age=max_age)
    await state.clear()
    await message.answer(Format.AGE_FILTER_SAVED.format(min_age, max_age), reply_markup=MAIN_MENU)


@router.callback_query(F.data == f"{CallbackPrefix.SETTINGS.value}:{SettingsAction.SEEKING.value}")
async def on_set_seeking(call: CallbackQuery) -> None:
    """Показывает выбор кого искать."""
    from keyboards import seeking_kb
    await call.message.edit_text("👁 Кого показывать в ленте?", reply_markup=seeking_kb(CallbackPrefix.SETTINGS_SEEKING.value))
    await call.answer()


@router.callback_query(F.data.startswith(f"{CallbackPrefix.SETTINGS_SEEKING.value}:"))
async def on_seeking_chosen(call: CallbackQuery) -> None:
    """Сохраняет предпочтение поиска."""
    seeking = call.data.split(":")[1]
    await user_repo.upsert_user(call.from_user.id, seeking=seeking)
    await call.answer(Format.SEEKING_SAVED, show_alert=True)
    await call.message.answer("Главное меню:", reply_markup=MAIN_MENU)


@router.callback_query(F.data == f"{CallbackPrefix.SETTINGS.value}:{SettingsAction.SUPPORT.value}")
async def on_support_from_settings(call: CallbackQuery, state: FSMContext) -> None:
    """Переход в поддержку из настроек.

    FIX: раньше этот callback не обрабатывался — кнопка не работала.
    """
    await call.answer()
    # Импортируем и вызываем обработчик поддержки
    from handlers.support.ticket import cmd_support
    await cmd_support(call.message, state)


@router.callback_query(F.data == f"{CallbackPrefix.SETTINGS.value}:{SettingsAction.DELETE.value}")
async def on_delete_account(call: CallbackQuery) -> None:
    """Запрашивает подтверждение удаления."""
    # FIX: unterminated f-string — use \n instead of literal newlines
    await call.message.edit_text(
        f"{EMOJI.REPORT} <b>Удалить аккаунт?</b>\n\nВсе данные будут безвозвратно удалены.",
        reply_markup=confirm_delete_kb(),
    )
    await call.answer()


@router.callback_query(F.data == f"{CallbackPrefix.SETTINGS.value}:{SettingsAction.DELETE_CONFIRM.value}")
async def on_confirm_delete(call: CallbackQuery) -> None:
    """Удаляет аккаунт."""
    await user_repo.delete_user(call.from_user.id)
    await call.message.edit_text(Message.ACCOUNT_DELETED)
    await call.answer("Аккаунт удалён", show_alert=True)


@router.callback_query(F.data == f"{CallbackPrefix.SETTINGS.value}:{SettingsAction.DELETE_CANCEL.value}")
async def on_cancel_delete(call: CallbackQuery) -> None:
    """Отменяет удаление."""
    await call.answer("↩️ Удаление отменено", show_alert=True)
    await call.message.answer("Главное меню:", reply_markup=MAIN_MENU)
