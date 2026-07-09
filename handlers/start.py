"""Registration (FSM) and /start handler.

PERF: _finish_registration parallelizes user + photo_count + badges loading.

FIX v7: safe dict access (user.get() instead of direct indexing).
        Fixed bare except -- CancelledError is now re-raised.
        FIX v7.1: removed emoji from f-strings (Unicode BMP copy issue).
"""
import asyncio
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import repositories.photo_repo as photo_repo
import repositories.user_repo as user_repo
from data.constants import EMOJI, Format, Interest, Length, Message, Photo
from data.enums import CallbackPrefix, Command as Cmd
from keyboards import MAIN_MENU, extra_photos_kb, gender_kb, interests_kb, seeking_kb
from services.badge_formatter import format_badge_card
from services.badge_service import check_and_award
from services.profile_formatter import format_profile
from states import Reg

router = Router()
log = logging.getLogger("iskra.start")


async def _safe_touch(tg_id: int) -> None:
    """Fire-and-forget touch_activity with error handling."""
    try:
        await user_repo.touch_activity(tg_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        pass


# FIX v7.1: use string concatenation instead of f-string with emoji
WELCOME = (
    EMOJI.FIRE_MID + " <b>Moment</b> - dating bot where looks are not everything.\n\n"
    "Here we calculate <b>interest compatibility</b>, suggest "
    "conversation starters, and give unique artifacts for activity.\n\n"
    "Let's create your profile in a minute. What's your name?"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await user_repo.get_user(message.from_user.id)
    # FIX v7: safe field access
    if user is not None and user.get("name") and user.get("photo_id"):
        asyncio.create_task(_safe_touch(message.from_user.id))
        await message.answer(Message.WELCOME_BACK, reply_markup=MAIN_MENU)
        return
    await message.answer(WELCOME)
    await state.set_state(Reg.name)


@router.message(Reg.name, F.text)
async def reg_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if len(name) > Length.NAME:
        await message.answer(Message.NAME_TOO_LONG)
        return
    await state.update_data(name=name)
    await message.answer("How old are you?")
    await state.set_state(Reg.age)


@router.message(Reg.age, F.text)
async def reg_age(message: Message, state: FSMContext) -> None:
    txt = message.text.strip()
    if not txt.isdigit() or not (14 <= int(txt) <= 99):
        await message.answer(Message.AGE_INVALID)
        return
    await state.update_data(age=int(txt))
    await message.answer("Your gender?", reply_markup=gender_kb(CallbackPrefix.REG_GENDER.value))
    await state.set_state(Reg.gender)


@router.callback_query(Reg.gender, F.data.startswith(f"{CallbackPrefix.REG_GENDER.value}:"))
async def reg_gender(call: CallbackQuery, state: FSMContext) -> None:
    g = call.data.split(":")[1]
    await state.update_data(gender=g)
    await call.message.edit_text("Who do you want to see in the feed?")
    await call.message.answer(
        "Choose:", reply_markup=seeking_kb(CallbackPrefix.REG_SEEKING.value)
    )
    await state.set_state(Reg.seeking)
    await call.answer()


@router.callback_query(Reg.seeking, F.data.startswith(f"{CallbackPrefix.REG_SEEKING.value}:"))
async def reg_seeking(call: CallbackQuery, state: FSMContext) -> None:
    s = call.data.split(":")[1]
    await state.update_data(seeking=s)
    await call.message.edit_text("What city are you from?")
    await state.set_state(Reg.city)
    await call.answer()


@router.message(Reg.city, F.text)
async def reg_city(message: Message, state: FSMContext) -> None:
    await state.update_data(city=message.text.strip()[: Length.CITY])
    await state.update_data(sel_interests=[])
    await message.answer(
        "Choose interests (up to " + str(Interest.MAX_SELECTED) + ") - compatibility is calculated by them " + EMOJI.COMPAT,
        reply_markup=interests_kb([], CallbackPrefix.REG_INTEREST.value),
    )
    await state.set_state(Reg.interests)


@router.callback_query(Reg.interests, F.data.startswith(f"{CallbackPrefix.REG_INTEREST.value}:"))
async def reg_interests(call: CallbackQuery, state: FSMContext) -> None:
    payload = call.data.split(":")[1]
    data = await state.get_data()
    sel = data.get("sel_interests", [])

    if payload == "done":
        await call.message.edit_text(
            "Write a few words about yourself (or send '-' to skip)."
        )
        await state.set_state(Reg.bio)
        await call.answer()
        return

    idx = int(payload)
    if idx in sel:
        sel.remove(idx)
    elif len(sel) < Interest.MAX_SELECTED:
        sel.append(idx)
    else:
        await call.answer(Message.MAX_INTERESTS, show_alert=True)
        return
    await state.update_data(sel_interests=sel)
    await call.message.edit_reply_markup(
        reply_markup=interests_kb(sel, CallbackPrefix.REG_INTEREST.value)
    )
    await call.answer()


@router.message(Reg.bio, F.text)
async def reg_bio(message: Message, state: FSMContext) -> None:
    bio = "" if message.text.strip() == "-" else message.text.strip()[: Length.BIO]
    await state.update_data(bio=bio)
    await message.answer("Last step - send your photo.")
    await state.set_state(Reg.photo)


@router.message(Reg.photo, F.photo)
async def reg_photo(message: Message, state: FSMContext) -> None:
    photo_id = message.photo[-1].file_id
    data = await state.get_data()
    interests = ",".join(str(i) for i in data.get("sel_interests", []))
    await user_repo.upsert_user(
        message.from_user.id,
        username=message.from_user.username,
        name=data.get("name"),
        age=data.get("age"),
        gender=data.get("gender"),
        seeking=data.get("seeking"),
        city=data.get("city"),
        bio=data.get("bio", ""),
        interests=interests,
        photo_id=photo_id,
        active=1,
    )
    await photo_repo.sync_photos_to_gallery(message.from_user.id)
    await user_repo.touch_activity(message.from_user.id)

    await state.update_data(extra_count=0)
    await state.set_state(Reg.extra_photos)
    await message.answer(
        "Want to add more photos? (up to " + str(Photo.MAX_EXTRA) + " extra)\n"
        "Just send a photo or click 'Skip'.",
        reply_markup=extra_photos_kb(),
    )


@router.callback_query(Reg.extra_photos, F.data == f"{CallbackPrefix.REG_PHOTO.value}:skip")
async def reg_skip_extra(call: CallbackQuery, state: FSMContext) -> None:
    await _finish_registration(call.message, call.from_user.id, state)
    await call.answer("Profile ready!", show_alert=True)


@router.message(Reg.extra_photos, F.photo)
async def reg_extra_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    count = data.get("extra_count", 0)
    if count >= Photo.MAX_EXTRA:
        await message.answer(Message.MAX_PHOTOS + " Saving profile!")
        await _finish_registration(message, message.from_user.id, state)
        return
    photo_id = message.photo[-1].file_id
    await photo_repo.add_photo(message.from_user.id, photo_id)
    count += 1
    await state.update_data(extra_count=count)
    remaining = Photo.MAX_EXTRA - count
    if remaining > 0:
        await message.answer(
            Format.PHOTO_ADDED.format(count + 1, Photo.MAX_TOTAL)
            + "\n" + Format.PHOTOS_REMAINING.format(remaining),
            reply_markup=extra_photos_kb(),
        )
    else:
        await message.answer("All 5 photos uploaded!")
        await _finish_registration(message, message.from_user.id, state)


async def _finish_registration(message: Message, user_id: int, state: FSMContext) -> None:
    await state.clear()

    # Parallel: user + photo_count + badges
    user, n_photos, new_badges = await asyncio.gather(
        user_repo.get_user(user_id),
        photo_repo.photo_count(user_id),
        check_and_award(user_id),
    )

    # FIX v7: safe access
    if user is None:
        log.error("User %s not found after registration", user_id)
        await message.answer("Registration error. Try /start", reply_markup=MAIN_MENU)
        return

    photo_note = Format.PHOTO_COUNT.format(n_photos) if n_photos > 1 else ""

    try:
        await message.answer_photo(
            photo=user.get("photo_id"),
            caption=Message.PROFILE_COMPLETE + format_profile(user) + photo_note,
        )
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        await message.answer_photo(
            photo=user.get("photo_id"),
            caption=Message.PROFILE_COMPLETE + format_profile(user) + photo_note,
        )
    except TelegramForbiddenError:
        log.debug("User %s blocked bot during registration", user_id)
    except Exception:
        log.exception("Failed to send profile photo to %s", user_id)
        # Fallback to text
        await message.answer(
            Message.PROFILE_COMPLETE + format_profile(user) + photo_note
        )

    for badge in new_badges:
        try:
            await message.answer(format_badge_card(badge, is_new=True))
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    await message.answer(Message.LETS_GO, reply_markup=MAIN_MENU)


@router.message(Reg.extra_photos)
async def reg_extra_invalid(message: Message) -> None:
    await message.answer(Message.SEND_PHOTO_OR_SKIP, reply_markup=extra_photos_kb())


@router.message(Reg.photo)
async def reg_photo_invalid(message: Message) -> None:
    await message.answer(Message.SEND_PHOTO)
