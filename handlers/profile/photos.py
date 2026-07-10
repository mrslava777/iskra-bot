"""Управление фотографиями в анкете.

FIX v11 (скорость): навигация меню фото снова мгновенная. Вместо
 «удалить сообщение → отправить новое» (2 round-trip на каждый тык)
 редактируем ОДНО сообщение через edit_media / edit_caption (1 запрос).
 При этом баг с «надписью-сиротой» не возвращается: мы не используем
 edit_text на фото-сообщении (он падал и слал текст без фото), а всегда
 работаем с медиа-сообщением.

Идея: меню фото живёт в ОДНОМ фото-сообщении. Мы его редактируем:
  - открытие меню: показать главное фото + подпись-счётчик + клавиатуру;
  - «добавить»: сменить подпись на «Пришли фото» (то же сообщение);
  - фото получено: edit_media → новый кадр + счётчик + клавиатура;
  - удаление: edit_media → оставшийся кадр + счётчик;
  - «назад»: edit_media → профиль (главное фото + анкета).
message_id меню храним в FSM, чтобы редактировать его после присланного фото.
"""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InputMediaPhoto

import repositories.photo_repo as photo_repo
import repositories.user_repo as user_repo
from data.constants import Photo, Message as Msg, Format, EMOJI
from data.enums import CallbackPrefix, PhotoAction
from keyboards import photos_manage_kb, profile_kb, MAIN_MENU
from services.profile_formatter import format_profile_async
from states import Edit

log = logging.getLogger("iskra." + __name__.split(".")[-1])

router = Router()


def _menu_caption(count: int, note: str | None = None) -> str:
    header = f"🖼 Управление фото\n\nЗагружено: {count}/{Photo.MAX_TOTAL}"
    return f"{note}\n\n{header}" if note else header


async def _show_menu_via_edit(
    call: CallbackQuery,
    tg_id: int,
    photo_id: str | None = None,
    note: str | None = None,
) -> int | None:
    """Редактирует сообщение call.message в меню фото за один запрос.

    Возвращает message_id меню (для последующего редактирования) или None.
    """
    photos = await photo_repo.get_photos(tg_id)
    count = len(photos)
    caption = _menu_caption(count, note)
    kb = photos_manage_kb(count)
    show = photo_id or (photos[0]["photo_id"] if photos else None)

    msg = call.message
    try:
        if show and msg.photo:
            # И картинка, и подпись, и клавиатура — одним запросом.
            await msg.edit_media(
                media=InputMediaPhoto(media=show, caption=caption),
                reply_markup=kb,
            )
            return msg.message_id
        if show and not msg.photo:
            # Текущее сообщение текстовое — заменить на фото нельзя редактом,
            # поэтому один раз пересоздаём (дальше уже будет фото-сообщение).
            await _safe_delete(msg)
            sent = await msg.answer_photo(photo=show, caption=caption, reply_markup=kb)
            return sent.message_id
        # Фото нет вообще — текстовое меню.
        if msg.photo:
            await _safe_delete(msg)
            sent = await msg.answer(caption, reply_markup=kb)
            return sent.message_id
        await msg.edit_text(caption, reply_markup=kb)
        return msg.message_id
    except Exception as e:
        log.debug("menu edit failed, recreating: %s", e)
        await _safe_delete(msg)
        if show:
            sent = await msg.answer_photo(photo=show, caption=caption, reply_markup=kb)
        else:
            sent = await msg.answer(caption, reply_markup=kb)
        return sent.message_id


async def _safe_delete(message: Message) -> None:
    try:
        await message.delete()
    except Exception as e:
        log.debug("Could not delete message: %s", e)


@router.callback_query(F.data == f"{CallbackPrefix.EDIT.value}:photos")
async def on_photos_menu(call: CallbackQuery, state: FSMContext) -> None:
    """Открывает меню управления фото (редактом текущей карточки профиля)."""
    try:
        await state.set_state(Edit.photos)
        menu_id = await _show_menu_via_edit(call, call.from_user.id)
        await state.update_data(photo_action=None, menu_msg_id=menu_id)
    except Exception as e:
        log.error("Failed to open photos menu for %d: %s", call.from_user.id, e)
    finally:
        await call.answer()


@router.callback_query(Edit.photos, F.data == f"{CallbackPrefix.PHOTO.value}:{PhotoAction.ADD.value}")
async def on_photo_add(call: CallbackQuery, state: FSMContext) -> None:
    """Просит фото. Меняем ТОЛЬКО подпись того же сообщения — мгновенно."""
    try:
        prompt = f"📷 Пришли фото для добавления\n\n(или нажми {EMOJI.BACK} Назад)"
        try:
            if call.message.photo:
                await call.message.edit_caption(caption=prompt, reply_markup=photos_manage_kb(
                    await photo_repo.photo_count(call.from_user.id)
                ))
            else:
                await call.message.edit_text(prompt)
        except Exception as e:
            log.debug("add-prompt edit failed: %s", e)
        await state.update_data(
            photo_action=PhotoAction.ADD.value,
            menu_msg_id=call.message.message_id,
        )
    except Exception as e:
        log.error("Failed to request photo add for %d: %s", call.from_user.id, e)
    finally:
        await call.answer()


@router.callback_query(Edit.photos, F.data.startswith(f"{CallbackPrefix.PHOTO.value}:{PhotoAction.DELETE.value}:"))
async def on_photo_delete(call: CallbackQuery, state: FSMContext) -> None:
    """Удаляет фото по индексу и перерисовывает меню тем же сообщением."""
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
        menu_id = await _show_menu_via_edit(call, call.from_user.id, note="🗑 Фото удалено")
        await state.update_data(menu_msg_id=menu_id)
    except Exception as e:
        log.error("Failed to delete photo for %d: %s", call.from_user.id, e)
        await call.answer("Ошибка удаления 😕", show_alert=True)


@router.callback_query(Edit.photos, F.data == f"{CallbackPrefix.PHOTO.value}:{PhotoAction.BACK.value}")
async def on_photos_back(call: CallbackQuery, state: FSMContext) -> None:
    """Возврат в профиль — edit_media текущего сообщения (без сирот, 1 запрос)."""
    await state.clear()
    try:
        user = await user_repo.get_user(call.from_user.id)
        caption = await format_profile_async(user, show_compat=False, show_badges=True)
        main_photo = user.get("photo_id") if user else None

        msg = call.message
        try:
            if main_photo and msg.photo:
                await msg.edit_media(
                    media=InputMediaPhoto(media=main_photo, caption=caption),
                    reply_markup=profile_kb(),
                )
            elif main_photo:
                await _safe_delete(msg)
                await msg.answer_photo(photo=main_photo, caption=caption, reply_markup=profile_kb())
            else:
                if msg.photo:
                    await _safe_delete(msg)
                    await msg.answer(caption, reply_markup=profile_kb())
                else:
                    await msg.edit_text(caption, reply_markup=profile_kb())
        except Exception as e:
            log.debug("back edit failed, recreating: %s", e)
            await _safe_delete(msg)
            if main_photo:
                await msg.answer_photo(photo=main_photo, caption=caption, reply_markup=profile_kb())
            else:
                await msg.answer(caption, reply_markup=profile_kb())
    except Exception as e:
        log.error("Failed to go back from photos for %d: %s", call.from_user.id, e)
    finally:
        await call.answer()


@router.message(Edit.photos, F.photo)
async def on_photo_received(message: Message, state: FSMContext) -> None:
    """Сохраняет фото и обновляет меню-сообщение (одним edit_media)."""
    from services.nsfw_moderation import moderate_profile_photo

    try:
        data = await state.get_data()
        action = data.get("photo_action")
        menu_msg_id = data.get("menu_msg_id")

        if action != PhotoAction.ADD.value:
            await state.set_state(Edit.photos)
            menu_id = await _recreate_menu(message, message.from_user.id)
            await state.update_data(menu_msg_id=menu_id, photo_action=None)
            return

        count = await photo_repo.photo_count(message.from_user.id)
        if count >= Photo.MAX_TOTAL:
            await message.answer(Msg.MAX_PHOTOS)
            return

        photo_id = message.photo[-1].file_id

        allowed, reason = await moderate_profile_photo(message.bot, message.from_user.id, photo_id)
        if not allowed:
            log.warning("Profile edit photo rejected for user %d: %s", message.from_user.id, reason)
            await message.answer("⚠️ Это фото не подходит для анкеты. Загрузите другое.")
            return

        ok, msg = await photo_repo.add_photo(message.from_user.id, photo_id)
        if not ok:
            log.warning("add_photo failed for %d: %s", message.from_user.id, msg)
            await message.answer(msg or "Не удалось сохранить фото 😕")
            return

        if count == 0:
            await user_repo.upsert_user(message.from_user.id, photo_id=photo_id)

        new_count = await photo_repo.photo_count(message.from_user.id)
        note = Format.PHOTO_ADDED.format(new_count, Photo.MAX_TOTAL)
        caption = _menu_caption(new_count, note)
        kb = photos_manage_kb(new_count)

        # Обновляем существующее меню-сообщение новым кадром — один запрос.
        # Присланное пользователем фото удаляем, чтобы не дублировать ленту.
        await _safe_delete(message)
        edited = False
        if menu_msg_id:
            try:
                await message.bot.edit_message_media(
                    chat_id=message.chat.id,
                    message_id=menu_msg_id,
                    media=InputMediaPhoto(media=photo_id, caption=caption),
                    reply_markup=kb,
                )
                edited = True
            except Exception as e:
                log.debug("menu edit_media after add failed: %s", e)

        if not edited:
            sent = await message.answer_photo(photo=photo_id, caption=caption, reply_markup=kb)
            await state.update_data(menu_msg_id=sent.message_id)

        await state.update_data(photo_action=None)
    except Exception as e:
        log.error("Failed to save photo for %d: %s", message.from_user.id, e)
        await message.answer("Не удалось сохранить фото 😕", reply_markup=MAIN_MENU)
        await state.clear()


async def _recreate_menu(message: Message, tg_id: int, note: str | None = None) -> int | None:
    """Присылает меню новым фото-сообщением (fallback, когда нет что редактировать)."""
    photos = await photo_repo.get_photos(tg_id)
    count = len(photos)
    caption = _menu_caption(count, note)
    kb = photos_manage_kb(count)
    show = photos[0]["photo_id"] if photos else None
    if show:
        try:
            sent = await message.answer_photo(photo=show, caption=caption, reply_markup=kb)
            return sent.message_id
        except Exception as e:
            log.warning("recreate menu photo failed: %s", e)
    sent = await message.answer(caption, reply_markup=kb)
    return sent.message_id
