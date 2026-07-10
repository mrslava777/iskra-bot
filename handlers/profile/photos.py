"""Управление фотографиями в анкете.

FIX v8: логирование ошибок вместо bare pass.
"""
import logging
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError

import repositories.photo_repo as photo_repo
import repositories.user_repo as user_repo
from data.constants import Photo, Message, Format, EMOJI
from data.enums import CallbackPrefix, PhotoAction
from keyboards import photos_manage_kb, profile_kb, MAIN_MENU
from services.profile_formatter import format_profile_async
from services.message_utils import edit_or_caption
from states import Edit
import asyncio


log = logging.getLogger("iskra." + __name__.split(".")[-1])

async def _safe_send(coro, fallback=None):
    """Safe wrapper for Telegram send operations."""
    try:
        return await coro
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        try:
            return await coro
        except Exception as e2:
            log.warning("Retry failed after TelegramRetryAfter: %s", e2)
    except TelegramForbiddenError:
        log.debug("User blocked bot, skipping send")
    except Exception as e:
        log.warning("Send failed: %s", e)
        if fallback:
            try:
                return await fallback
            except Exception as e2:
                log.warning("Fallback failed: %s", e2)
    return None

router = Router()


@router.callback_query(F.data == f"{CallbackPrefix.EDIT.value}:photos")
async def on_photos_menu(call: CallbackQuery, state: FSMContext) -> None:
    """Показывает меню управления фото."""
    try:
        count = await photo_repo.photo_count(call.from_user.id)
        text = "🖼 Управление фото\n\nЗагружено: " + str(count) + "/" + str(Photo.MAX_TOTAL)
        await edit_or_caption(
            call,
            text,
            reply_markup=photos_manage_kb(count),
        )
        await state.set_state(Edit.photos)
    except Exception as e:
        log.error("Failed to open photos menu for %d: %s", call.from_user.id, e)
    await call.answer()


@router.callback_query(Edit.photos, F.data == f"{CallbackPrefix.PHOTO.value}:{PhotoAction.ADD.value}")
async def on_photo_add(call: CallbackQuery, state: FSMContext) -> None:
    """Запрашивает новое фото."""
    try:
        await edit_or_caption(call, "📷 Пришли фото для добавления:")
        await state.update_data(photo_action=PhotoAction.ADD.value)
    except Exception as e:
        log.error("Failed to request photo add for %d: %s", call.from_user.id, e)
    await call.answer()


@router.callback_query(Edit.photos, F.data.startswith(f"{CallbackPrefix.PHOTO.value}:{PhotoAction.DELETE.value}:"))
async def on_photo_delete(call: CallbackQuery, state: FSMContext) -> None:
    """Удаляет фото по индексу — push + меню."""
    try:
        idx = int(call.data.split(":")[2])
        photos = await photo_repo.get_photos(call.from_user.id)
        if 0 <= idx < len(photos):
            await photo_repo.remove_photo(call.from_user.id, idx)
            remaining = await photo_repo.get_photos(call.from_user.id)
            new_main = remaining[0]["photo_id"] if remaining else None
            await user_repo.upsert_user(call.from_user.id, photo_id=new_main)
            await call.answer("🗑 Фото удалено", show_alert=True)
            await call.message.answer("Главное меню:", reply_markup=MAIN_MENU)
        else:
            await call.answer("Неверный индекс", show_alert=True)
    except Exception as e:
        log.error("Failed to delete photo for %d: %s", call.from_user.id, e)
        await call.answer("Ошибка удаления 😕", show_alert=True)


@router.callback_query(Edit.photos, F.data == f"{CallbackPrefix.PHOTO.value}:{PhotoAction.BACK.value}")
async def on_photos_back(call: CallbackQuery, state: FSMContext) -> None:
    """Шаг назад — возврат в профиль из управления фото."""
    await state.clear()
    try:
        user = await user_repo.get_user(call.from_user.id)
        caption = await format_profile_async(user, show_compat=False, show_badges=True)
        try:
            await call.message.edit_text(caption, reply_markup=profile_kb())
        except Exception as e:
            log.debug("edit_text failed, using answer: %s", e)
            await call.message.answer(caption, reply_markup=profile_kb())
    except Exception as e:
        log.error("Failed to go back from photos for %d: %s", call.from_user.id, e)
    await call.answer()


@router.message(Edit.photos, F.photo)
async def on_photo_received(message: Message, state: FSMContext) -> None:
    """Сохраняет полученное фото — push + меню."""
    try:
        data = await state.get_data()
        action = data.get("photo_action")

        if action == PhotoAction.ADD.value:
            count = await photo_repo.photo_count(message.from_user.id)
            if count >= Photo.MAX_TOTAL:
                await message.answer(Message.MAX_PHOTOS, reply_markup=MAIN_MENU)
                await state.clear()
                return

            photo_id = message.photo[-1].file_id
            await photo_repo.add_photo(message.from_user.id, photo_id)

            if count == 0:
                await user_repo.upsert_user(message.from_user.id, photo_id=photo_id)

            await state.clear()
            count = await photo_repo.photo_count(message.from_user.id)
            await message.answer(
                Format.PHOTO_ADDED.format(count, Photo.MAX_TOTAL),
                reply_markup=MAIN_MENU,
            )
        else:
            # Неизвестное действие — сбрасываем состояние
            await state.clear()
            await message.answer(Message.SEND_PHOTO, reply_markup=MAIN_MENU)
    except Exception as e:
        log.error("Failed to save photo for %d: %s", message.from_user.id, e)
        await message.answer("Не удалось сохранить фото 😕", reply_markup=MAIN_MENU)
        await state.clear()
