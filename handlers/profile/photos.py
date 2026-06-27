"""Управление фотографиями в анкете."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import repositories.photo_repo as photo_repo
import repositories.user_repo as user_repo
from data.constants import Photo, Message, Format
from data.enums import CallbackPrefix, PhotoAction
from keyboards import photos_manage_kb, profile_kb
from services.profile_formatter import format_profile_async
from services.message_utils import edit_or_caption
from states import Edit

router = Router()


@router.callback_query(F.data == f"{CallbackPrefix.EDIT.value}:photos")
async def on_photos_menu(call: CallbackQuery, state: FSMContext) -> None:
    """Показывает меню управления фото."""
    count = await photo_repo.photo_count(call.from_user.id)
    await edit_or_caption(
        call,
        f"🖼 Управление фото

Загружено: {count}/{Photo.MAX_TOTAL}",
        reply_markup=photos_manage_kb(count),
    )
    await state.set_state(Edit.photos)
    await call.answer()


@router.callback_query(Edit.photos, F.data == f"{CallbackPrefix.PHOTO.value}:{PhotoAction.ADD.value}")
async def on_photo_add(call: CallbackQuery, state: FSMContext) -> None:
    """Запрашивает новое фото."""
    await edit_or_caption(call, "📷 Пришли фото для добавления:")
    await state.update_data(photo_action=PhotoAction.ADD.value)
    await call.answer()


@router.callback_query(Edit.photos, F.data.startswith(f"{CallbackPrefix.PHOTO.value}:{PhotoAction.DELETE.value}:"))
async def on_photo_delete(call: CallbackQuery, state: FSMContext) -> None:
    """Удаляет фото по индексу."""
    idx = int(call.data.split(":")[2])
    photos = await photo_repo.get_photos(call.from_user.id)
    if 0 <= idx < len(photos):
        await photo_repo.remove_photo(call.from_user.id, idx)
        # Если удалили главное фото (поз. 0) — синхронизируем users.photo_id
        # с новым первым фото галереи (или очищаем, если фото не осталось).
        remaining = await photo_repo.get_photos(call.from_user.id)
        new_main = remaining[0]["photo_id"] if remaining else None
        await user_repo.upsert_user(call.from_user.id, photo_id=new_main)
        await call.answer("Фото удалено")
    else:
        await call.answer("Неверный индекс")
    count = await photo_repo.photo_count(call.from_user.id)
    await edit_or_caption(
        call,
        f"🖼 Управление фото

Загружено: {count}/{Photo.MAX_TOTAL}",
        reply_markup=photos_manage_kb(count),
    )


@router.callback_query(Edit.photos, F.data == f"{CallbackPrefix.PHOTO.value}:{PhotoAction.BACK.value}")
async def on_photos_back(call: CallbackQuery, state: FSMContext) -> None:
    """Возвращает к профилю."""
    await state.clear()
    user = await user_repo.get_user(call.from_user.id)
    caption = await format_profile_async(user, show_compat=False, show_badges=True)
    has_daily = bool(user.get("daily_a"))
    await edit_or_caption(call, caption, reply_markup=profile_kb(has_daily=has_daily))
    await call.answer()


@router.message(Edit.photos, F.photo)
async def on_photo_received(message: Message, state: FSMContext) -> None:
    """Сохраняет полученное фото."""
    data = await state.get_data()
    action = data.get("photo_action")

    if action == PhotoAction.ADD.value:
        count = await photo_repo.photo_count(message.from_user.id)
        if count >= Photo.MAX_TOTAL:
            await message.answer(Message.MAX_PHOTOS)
            await state.clear()
            return

        photo_id = message.photo[-1].file_id
        await photo_repo.add_photo(message.from_user.id, photo_id)

        # Обновляем главное фото если это первое
        if count == 0:
            await user_repo.upsert_user(message.from_user.id, photo_id=photo_id)

        count = await photo_repo.photo_count(message.from_user.id)
        await message.answer(
            Format.PHOTO_ADDED.format(count, Photo.MAX_TOTAL),
            reply_markup=photos_manage_kb(count),
        )
        await state.set_state(Edit.photos)
