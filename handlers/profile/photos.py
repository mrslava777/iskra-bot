"""Управление фотографиями в анкете.

FIX v9: устранены два бага UI управления фото:
  1) «Назад» оставлял текст-сироту без фото. Причина: меню фото открывается
     из карточки профиля (фото + caption). on_photos_back звал edit_text на
     фото-сообщении → TelegramBadRequest → fallback answer() слал НОВОЕ
     текстовое сообщение без фото. Теперь возврат перерисовывает профиль как
     полноценное фото-сообщение (удаляем старое, шлём свежее).
  2) После добавления фото показывался только счётчик «N/5», без самого фото.
     Теперь меню всегда рендерится как фото-сообщение, а после загрузки
     показывается именно добавленный кадр.

Паттерн: каждое действие удаляет своё сообщение и присылает свежее
фото-сообщение с актуальным счётчиком и клавиатурой. Никаких edit_caption,
которые оставляли устаревшие подписи и осиротевшие надписи.
"""
import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import repositories.photo_repo as photo_repo
import repositories.user_repo as user_repo
from data.constants import Photo, Message as Msg, Format, EMOJI
from data.enums import CallbackPrefix, PhotoAction
from keyboards import photos_manage_kb, profile_kb, MAIN_MENU
from services.profile_formatter import format_profile_async
from states import Edit

log = logging.getLogger("iskra." + __name__.split(".")[-1])

router = Router()


async def _safe_delete(message: Message) -> None:
    """Пытается удалить сообщение, не роняя обработчик если нельзя."""
    try:
        await message.delete()
    except Exception as e:
        log.debug("Could not delete message: %s", e)


async def _render_photos_menu(
    message: Message,
    tg_id: int,
    highlight_photo_id: str | None = None,
    note: str | None = None,
) -> None:
    """Отправляет меню управления фото как свежее фото-сообщение.

    highlight_photo_id — какой кадр показать (по умолчанию главное фото).
    note — необязательная строка сверху (например «✅ Фото добавлено»).
    """
    photos = await photo_repo.get_photos(tg_id)
    count = len(photos)

    header = f"🖼 Управление фото\n\nЗагружено: {count}/{Photo.MAX_TOTAL}"
    if note:
        header = f"{note}\n\n{header}"

    kb = photos_manage_kb(count)
    photo_to_show = highlight_photo_id or (photos[0]["photo_id"] if photos else None)

    if photo_to_show:
        try:
            await message.answer_photo(photo=photo_to_show, caption=header, reply_markup=kb)
            return
        except Exception as e:
            log.warning("Failed to send photos menu as photo for %d: %s", tg_id, e)
    # Фолбэк: нет фото или не удалось отправить кадр — текстовое меню.
    await message.answer(header, reply_markup=kb)


@router.callback_query(F.data == f"{CallbackPrefix.EDIT.value}:photos")
async def on_photos_menu(call: CallbackQuery, state: FSMContext) -> None:
    """Открывает меню управления фото свежим фото-сообщением."""
    try:
        await state.set_state(Edit.photos)
        await state.update_data(photo_action=None, prompt_msg_id=None)
        await _safe_delete(call.message)
        await _render_photos_menu(call.message, call.from_user.id)
    except Exception as e:
        log.error("Failed to open photos menu for %d: %s", call.from_user.id, e)
    finally:
        await call.answer()


@router.callback_query(Edit.photos, F.data == f"{CallbackPrefix.PHOTO.value}:{PhotoAction.ADD.value}")
async def on_photo_add(call: CallbackQuery, state: FSMContext) -> None:
    """Запрашивает новое фото. Убирает меню, шлёт текстовый промпт."""
    try:
        await _safe_delete(call.message)
        prompt = await call.message.answer("📷 Пришли фото для добавления:")
        await state.update_data(
            photo_action=PhotoAction.ADD.value,
            prompt_msg_id=prompt.message_id,
        )
    except Exception as e:
        log.error("Failed to request photo add for %d: %s", call.from_user.id, e)
    finally:
        await call.answer()


@router.callback_query(Edit.photos, F.data.startswith(f"{CallbackPrefix.PHOTO.value}:{PhotoAction.DELETE.value}:"))
async def on_photo_delete(call: CallbackQuery, state: FSMContext) -> None:
    """Удаляет фото по индексу и перерисовывает меню (без сирот)."""
    try:
        idx = int(call.data.split(":")[2])
        photos = await photo_repo.get_photos(call.from_user.id)
        if not (0 <= idx < len(photos)):
            await call.answer("Неверный индекс", show_alert=True)
            return

        await photo_repo.remove_photo(call.from_user.id, idx)
        remaining = await photo_repo.get_photos(call.from_user.id)
        new_main = remaining[0]["photo_id"] if remaining else None
        await user_repo.upsert_user(call.from_user.id, photo_id=new_main)

        await call.answer("🗑 Фото удалено")
        await _safe_delete(call.message)
        await _render_photos_menu(call.message, call.from_user.id, note="🗑 Фото удалено")
    except Exception as e:
        log.error("Failed to delete photo for %d: %s", call.from_user.id, e)
        await call.answer("Ошибка удаления 😕", show_alert=True)


@router.callback_query(Edit.photos, F.data == f"{CallbackPrefix.PHOTO.value}:{PhotoAction.BACK.value}")
async def on_photos_back(call: CallbackQuery, state: FSMContext) -> None:
    """Возврат в профиль. Перерисовывает карточку как фото-сообщение.

    FIX v9: раньше edit_text на фото-сообщении падал и fallback answer() слал
    текст-сироту без фото. Теперь удаляем меню и шлём профиль фото+подпись.
    """
    await state.clear()
    try:
        user = await user_repo.get_user(call.from_user.id)
        caption = await format_profile_async(user, show_compat=False, show_badges=True)
        await _safe_delete(call.message)

        main_photo = user.get("photo_id") if user else None
        if main_photo:
            try:
                await call.message.answer_photo(
                    photo=main_photo, caption=caption, reply_markup=profile_kb()
                )
            except Exception as e:
                log.warning("Failed to send profile photo on back for %d: %s", call.from_user.id, e)
                await call.message.answer(caption, reply_markup=profile_kb())
        else:
            await call.message.answer(caption, reply_markup=profile_kb())
    except Exception as e:
        log.error("Failed to go back from photos for %d: %s", call.from_user.id, e)
    finally:
        await call.answer()


@router.message(Edit.photos, F.photo)
async def on_photo_received(message: Message, state: FSMContext) -> None:
    """Сохраняет полученное фото и перерисовывает меню, показывая новый кадр.

    FIX v9: вместо голой строки «N/5» показываем сам добавленный кадр и
    остаёмся в меню (можно добавить ещё). NSFW-проверка сохранена.
    """
    from services.nsfw_moderation import moderate_profile_photo

    try:
        data = await state.get_data()
        action = data.get("photo_action")
        prompt_msg_id = data.get("prompt_msg_id")

        # Убираем текстовый промпт «Пришли фото», чтобы не копился мусор.
        if prompt_msg_id:
            try:
                await message.bot.delete_message(message.chat.id, prompt_msg_id)
            except Exception as e:
                log.debug("Could not delete prompt message: %s", e)
            await state.update_data(prompt_msg_id=None)

        if action != PhotoAction.ADD.value:
            await state.set_state(Edit.photos)
            await message.answer(Msg.SEND_PHOTO)
            await _render_photos_menu(message, message.from_user.id)
            return

        count = await photo_repo.photo_count(message.from_user.id)
        if count >= Photo.MAX_TOTAL:
            await message.answer(Msg.MAX_PHOTOS)
            await _render_photos_menu(message, message.from_user.id)
            await state.update_data(photo_action=None)
            return

        photo_id = message.photo[-1].file_id

        # NSFW-проверка перед сохранением.
        allowed, reason = await moderate_profile_photo(message.bot, message.from_user.id, photo_id)
        if not allowed:
            log.warning("Profile edit photo rejected for user %d: %s", message.from_user.id, reason)
            await message.answer(
                "⚠️ Это фото не подходит для анкеты\n\n"
                "Пожалуйста, загрузите другое фото, которое соответствует правилам.",
            )
            # Остаёмся в Edit.photos с тем же action — можно повторить.
            return

        ok, msg = await photo_repo.add_photo(message.from_user.id, photo_id)
        if not ok:
            log.warning("add_photo failed for %d: %s", message.from_user.id, msg)
            await message.answer(msg or "Не удалось сохранить фото 😕")
            await _render_photos_menu(message, message.from_user.id)
            await state.update_data(photo_action=None)
            return

        # Если это было первое фото — синхронизируем главное.
        if count == 0:
            await user_repo.upsert_user(message.from_user.id, photo_id=photo_id)

        # Остаёмся в меню, показываем именно добавленный кадр.
        await state.update_data(photo_action=None)
        new_count = await photo_repo.photo_count(message.from_user.id)
        note = Format.PHOTO_ADDED.format(new_count, Photo.MAX_TOTAL)
        await _render_photos_menu(
            message, message.from_user.id, highlight_photo_id=photo_id, note=note
        )
    except Exception as e:
        log.error("Failed to save photo for %d: %s", message.from_user.id, e)
        await message.answer("Не удалось сохранить фото 😕", reply_markup=MAIN_MENU)
        await state.clear()
