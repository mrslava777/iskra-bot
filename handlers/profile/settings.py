"""Настройки анкеты — активность, фильтры, удаление."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import repositories.user_repo as user_repo
from data.constants import Age, EMOJI, MenuText, Message, Format
from data.enums import CallbackPrefix, SettingsAction
from keyboards import confirm_delete_kb, settings_kb, MAIN_MENU
from services.profile_formatter import format_profile_async
from states import Edit

router = Router()


@router.message(F.text == MenuText.SETTINGS)
async def show_settings(message: Message) -> None:
    """Показывает меню настроек."""
    user = await user_repo.get_user(message.from_user.id)
    if not user:
        await message.answer(Message.CREATE_PROFILE_FIRST)
        return
    active = bool(user.get("active"))
    await message.answer(f"{EMOJI.SETTINGS} Настройки", reply_markup=settings_kb(active))


@router.callback_query(F.data == f"{CallbackPrefix.SETTINGS.value}:back")
async def on_settings_back(call: CallbackQuery) -> None:
    """Шаг назад — возврат в профиль из настроек."""
    user = await user_repo.get_user(call.from_user.id)
    caption = await format_profile_async(user, show_compat=False, show_badges=True)
    has_daily = bool(user.get("daily_a"))
    try:
        await call.message.edit_text(caption, reply_markup=profile_kb(has_daily=has_daily))
    except Exception:
        await call.message.answer(caption, reply_markup=profile_kb(has_daily=has_daily))
    await call.answer()


@router.callback_query(F.data == f"{CallbackPrefix.SETTINGS.value}:{SettingsAction.TOGGLE.value}")
async def on_toggle_active(call: CallbackQuery) -> None:
    """Переключает видимость анкеты — push + меню."""
    user = await user_repo.get_user(call.from_user.id)
    new_active = 0 if user.get("active") else 1
    await user_repo.upsert_user(call.from_user.id, active=new_active)
    status = f"{EMOJI.ACTIVE} Анкета активна" if new_active else f"{EMOJI.INACTIVE} Анкета скрыта"
    await call.answer(status, show_alert=True)
    await call.message.answer("Главное меню:", reply_markup=MAIN_MENU)


@router.callback_query(F.data == f"{CallbackPrefix.SETTINGS.value}:{SettingsAction.AGE_FILTER.value}")
async def on_set_age_filter(call: CallbackQuery, state: FSMContext) -> None:
    """Запрашивает фильтр по возрасту."""
    await call.message.edit_text(f"🎚 Введи диапазон возраста: мин макс (например: {Age.MIN} {Age.MAX})")
    await state.set_state(Edit.filters_age)
    await call.answer()


@router.message(Edit.filters_age, F.text)
async def save_age_filter(message: Message, state: FSMContext) -> None:
    """Сохраняет фильтр по возрасту — push + меню."""
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
    """Сохраняет предпочтение поиска — push + меню."""
    seeking = call.data.split(":")[1]
    await user_repo.upsert_user(call.from_user.id, seeking=seeking)
    await call.answer(Format.SEEKING_SAVED, show_alert=True)
    await call.message.answer("Главное меню:", reply_markup=MAIN_MENU)


@router.callback_query(F.data == f"{CallbackPrefix.SETTINGS.value}:{SettingsAction.DELETE.value}")
async def on_delete_account(call: CallbackQuery) -> None:
    """Запрашивает подтверждение удаления."""
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
    """Отменяет удаление — push + меню."""
    await call.answer("↩️ Удаление отменено", show_alert=True)
    await call.message.answer("Главное меню:", reply_markup=MAIN_MENU)
