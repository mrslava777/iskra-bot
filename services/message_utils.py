"""Утилиты для работы с сообщениями — редактирование текста/подписи."""
from aiogram.types import CallbackQuery


async def edit_or_caption(call: CallbackQuery, text: str, reply_markup=None, parse_mode="HTML") -> None:
    """Редактирует сообщение: использует edit_caption для фото, edit_text для текста.

    Профиль отправляется как фото с подписью (caption), поэтому обычный edit_text
    вызывает TelegramBadRequest. Эта функция автоматически выбирает правильный метод.
    """
    if call.message.photo:
        await call.message.edit_caption(
            caption=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    else:
        await call.message.edit_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
