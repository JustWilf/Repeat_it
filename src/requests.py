# Literally requests to telegram API with its own data formating
from httpx import AsyncClient, HTTPError, Timeout
from dotenv import load_dotenv, get_key, set_key
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from orjson import dumps as json_dumps
from json import JSONDecodeError
from sys import exit
from typing import Any, Literal
from rich.console import Console


type default_dict = dict[str, Any]
type Updates = list[default_dict]
type not_return = str | HTTPError | JSONDecodeError | None


class Requests:
    def __init__(self) -> None:
        self.ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
        load_dotenv(self.ENV_PATH)

        self.TOKEN: str | None = get_key(self.ENV_PATH, "TOKEN")
        self.BASE_URL: str = f"https://api.telegram.org/bot{self.TOKEN}"
        self.ERR_CONSOLE: Console = Console(force_terminal=True, stderr=True)
        if not self.TOKEN:
            self.ERR_CONSOLE.print(
                "[bold red]Env error:[/] [underline]There isn't token in .env\n"
            )
            exit(1)
        self.FILE_PATH: str = Path(__file__).name
        self.METHODS: dict[str, str] = {
            "text": "sendMessage",
            "photo": "sendPhoto",
            "document": "sendDocument",
        }
        self._client: AsyncClient = AsyncClient(timeout=Timeout(100))

    async def _api_request(self, method: str, data: default_dict, timeout: int) -> Any:
        if self._client.is_closed:
            self._client = AsyncClient(timeout=Timeout(timeout))
        try:
            response = (
                await self._client.post(
                    f"{self.BASE_URL}/{method}", json=data, timeout=timeout + 10
                )
            ).json()

        except (HTTPError, JSONDecodeError) as e:
            self.ERR_CONSOLE.print(
                f"[bold red]Request error:[/] [underline]{e}\nCheck your internet connection or telegram services status\n"
            )
            return e
        if not response["ok"]:
            self.ERR_CONSOLE.print(
                f"\n[bold red]Request error {response['error_code']}:[/] [underline]{response['description']}[/] [italic]({self.FILE_PATH})[/]\n"
            )
            return f"{response['error_code']}: {response['description']}"

        if not self._client.is_closed:
            await self._client.aclose()
        return response["result"]

    async def get_updates(self, timeout: int) -> Updates | not_return:
        if not self._client:
            self._client = AsyncClient(timeout=Timeout(timeout))

        last_update_id: str | int | None = get_key(self.ENV_PATH, "LAST_UPDATE_ID")
        last_update_id = int(last_update_id) if last_update_id else -2

        result: Updates | str | None = await self._api_request(
            "getUpdates",
            {
                "offset": last_update_id + 1,
                "timeout": timeout,
                "allowed_updates": json_dumps(
                    ["message", "edited_message", "callback_query"]
                ).decode(),
            },
            timeout,
        )
        if not result or isinstance(result, str):
            return result

        set_key(self.ENV_PATH, "LAST_UPDATE_ID", str(result[-1]["update_id"]))

        updates: Updates = []
        for update in result:
            is_button_callback: bool = "callback_query" in update
            update = (
                update["callback_query"]
                if is_button_callback
                else update["edited_message"]
                if "edited_message" in update
                else update["message"]
            )
            update_from: default_dict = update["from"]

            if not update_from["is_bot"]:
                updates.append(
                    {
                        "chat_id": update["chat"]["id"],
                        "user": {
                            "first_name": update_from["first_name"],
                            "last_name": update_from.get("last_name"),
                            "username": update_from.get("username"),
                            "is_premium": update_from.get("is_premium"),
                        },
                    }
                )
                if is_button_callback:
                    updates[-1]["data"] = {
                        "content_type": "button_callback",
                        "button_id": update["id"],
                        "message_id": update["message"]["message_id"],
                        "action": update["data"],
                        "date": datetime.now(ZoneInfo("Europe/Moscow")).strftime(
                            "%d.%m.%Y %H:%M"
                        ),
                    }
                else:
                    updates[-1]["data"] = {
                        "message_id": update["message_id"],
                        "language_code": update_from.get("language_code"),
                        "date": datetime.fromtimestamp(
                            update["date"], ZoneInfo("Europe/Moscow")
                        ).strftime("%d.%m.%Y %H:%M"),
                    }

                    base: list[str] = ["file_id", "file_unique_id", "file_size"]
                    duration: list[str] = base + ["duration"]
                    keys: dict[str, list[str]] = {
                        "video": duration,
                        "animation": ["file_id", "file_unique_id", "duration"],
                        "document": base + ["file_name", "mime_type"],
                        "sticker": ["file_id", "emoji", "set_name"],
                        "checklist": [
                            "title",
                            "tasks",
                            "others_can_add_tasks",
                            "others_can_mark_tasks_as_done",
                        ],
                        "poll": [
                            "id",
                            "question",
                            "options",
                            "is_closed",
                            "is_anonymous",
                            "allows_multiple_answers",
                            "allows_revoting",
                        ],
                        "video_note": duration,
                        "voice": ["file_id", "file_unique_id", "duration"],
                        "audio": duration,
                        "contact": [
                            "phone_number",
                            "first_name",
                            "last_name",
                            "user_id",
                        ],
                    }
                    photo_keys: list[str] = base
                    updates[-1]["content"] = {
                        "media_group_id": update.get("media_group_id")
                    }
                    updates[-1]["data"]["content_type"] = None
                    content = updates[-1]["content"]

                    if "text" in update:
                        updates[-1]["content"] = {"text": update["text"]}
                        updates[-1]["content_type"] = "text"
                    elif "photo" in update:
                        photo: default_dict = update["photo"][-1]
                        place: default_dict = content
                        updates[-1]["data"]["content_type"] = "photo"
                        for field in photo_keys:
                            place[field] = photo.get(field)
                    else:
                        for field in keys:
                            if field in update:
                                place: default_dict = content
                                content: default_dict = update[field]
                                updates[-1]["data"]["content_type"] = field
                                for k in keys[field]:
                                    place[k] = content.get(k)
                                break
                    if "caption" in update:
                        updates[-1]["content"]["caption"] = update["caption"]

        return updates

    async def send_text(
        self,
        chat_id: int | str,
        text: str,
        disable_notification: bool = False,
        protect_content: bool = False,
        enable_link_preview: bool = False,
        timeout: int = 10,
    ) -> default_dict | not_return:
        return await self._api_request(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_notification": disable_notification,
                "protect_content": protect_content,
                "link_preview_options": {"is_disabled": not enable_link_preview},
            },
            timeout,
        )

    async def send_reply_text(
        self,
        chat_id: int | str,
        text: str,
        reply_message_id: int,
        disable_notification: bool = False,
        protect_content: bool = False,
        enable_link_preview: bool = False,
        quote: str | None = None,
        timeout: int = 10,
    ) -> default_dict | not_return:
        data: default_dict = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_notification": disable_notification,
            "protect_content": protect_content,
            "link_preview_options": {"is_disabled": not enable_link_preview},
        }

        if quote:
            data["reply_parameters"] = {
                "message_id": reply_message_id,
                "quote": quote,
            }
        else:
            data["reply_parameters"] = {"message_id": reply_message_id}

        return await self._api_request("sendMessage", data, timeout)

    async def send_photo(
        self,
        chat_id: int | str,
        photo: str,
        disable_notification: bool = False,
        protect_content: bool = False,
        caption: str | None = None,
        show_caption_above_media: bool = False,
        has_spoiler: bool = False,
        timeout: int = 10,
    ) -> default_dict | not_return:
        data: default_dict = {
            "chat_id": chat_id,
            "photo": photo,
            "disable_notification": disable_notification,
            "protect_content": protect_content,
            "parse_mode": "HTML",
            "caption": caption,
            "has_spoiler": has_spoiler,
        }

        if caption:
            data["show_caption_above_media"] = show_caption_above_media

        return await self._api_request("sendPhoto", data, timeout)

    async def send_reply_photo(
        self,
        chat_id: int | str,
        photo: str,
        reply_message_id: int,
        disable_notification: bool = False,
        protect_content: bool = False,
        caption: str | None = None,
        show_caption_above_media: bool = False,
        has_spoiler: bool = False,
        quote: str | None = None,
        timeout: int = 10,
    ) -> default_dict | not_return:
        data: default_dict = {
            "chat_id": chat_id,
            "photo": photo,
            "disable_notification": disable_notification,
            "protect_content": protect_content,
            "parse_mode": "HTML",
            "has_spoiler": has_spoiler,
        }

        if caption:
            data["caption"] = caption
            data["show_caption_above_media"] = show_caption_above_media
        if quote:
            data["reply_parameters"] = {
                "message_id": reply_message_id,
                "quote": quote,
            }
        else:
            data["reply_parameters"] = {"message_id": reply_message_id}

        return await self._api_request("sendPhoto", data, timeout)

    async def send_document(
        self,
        chat_id: int | str,
        document: str,
        disable_notification: bool = False,
        protect_content: bool = False,
        caption: str | None = None,
        content_type_detection: bool = False,
        timeout: int = 10,
    ) -> default_dict | not_return:
        data: default_dict = {
            "chat_id": chat_id,
            "document": document,
            "disable_notification": disable_notification,
            "protect_content": protect_content,
            "parse_mode": "HTML",
            "disable_content_type_detection": not content_type_detection,
        }

        if caption:
            data["caption"] = caption

        return await self._api_request("sendDocument", data, timeout)

    async def send_reply_document(
        self,
        chat_id: int | str,
        document: str,
        reply_message_id: int,
        disable_notification: bool = False,
        protect_content: bool = False,
        content_type_detection: bool = False,
        caption: str | None = None,
        quote: str | None = None,
        timeout: int = 10,
    ) -> default_dict | not_return:
        data: default_dict = {
            "chat_id": chat_id,
            "document": document,
            "disable_notification": disable_notification,
            "protect_content": protect_content,
            "parse_mode": "HTML",
            "disable_content_type_detection": not content_type_detection,
        }

        if caption:
            data["caption"] = caption
        if quote:
            data["reply_parameters"] = {
                "message_id": reply_message_id,
                "quote": quote,
            }
        else:
            data["reply_parameters"] = {"message_id": reply_message_id}

        return await self._api_request("sendDocument", data, timeout)

    async def send_buttons(
        self,
        chat_id: int | str,
        content_type: Literal["text", "photo", "document"],
        content: str,
        buttons: list[list[tuple[str, str]]],
        disable_notification: bool = False,
        protect_content: bool = False,
        caption: str | None = None,
        show_caption_above_media: bool = False,
        has_spoiler: bool = False,
        content_type_detection: bool = False,
        timeout: int = 10,
    ) -> default_dict | not_return:
        if content_type not in self.METHODS:
            self.ERR_CONSOLE.print(
                "[bold red]Request error:[/] [underline]Unknown content type in buttons sending[/]"
            )
            exit(1)

        data: default_dict = {
            "chat_id": chat_id,
            content_type: content,
            "disable_notification": disable_notification,
            "protect_content": protect_content,
            "parse_mode": "HTML",
        }

        if content_type != "text" and caption:
            data["caption"] = caption
        match content_type:
            case "photo":
                if caption:
                    data["show_caption_above_media"] = show_caption_above_media
                data["has_spoiler"] = has_spoiler
            case "document":
                data["disable_content_type_detection"] = not content_type_detection

        final_buttons: list[list[dict[str, str]]] = []
        for i in buttons:
            final_buttons.append([])
            for j in i:
                final_buttons[-1].append({"text": j[0], "callback_data": j[1]})
        data["reply_markup"] = {"inline_keyboard": final_buttons}

        return await self._api_request(self.METHODS[content_type], data, timeout)

    async def send_reply_buttons(
        self,
        chat_id: int | str,
        content_type: Literal["text", "photo", "document"],
        content: str,
        reply_message_id: int,
        buttons: list[list[tuple[str, str]]],
        disable_notification: bool = False,
        protect_content: bool = False,
        caption: str | None = None,
        quote: str | None = None,
        show_caption_above_media: bool = False,
        has_spoiler: bool = False,
        content_type_detection: bool = False,
        timeout: int = 10,
    ) -> default_dict | not_return:
        if content_type not in self.METHODS:
            self.ERR_CONSOLE.print(
                "[bold red]Request error:[/] [underline]Unknown content type in buttons sending[/]"
            )
            exit(1)

        data: default_dict = {
            "chat_id": chat_id,
            content_type: content,
            "disable_notification": disable_notification,
            "protect_content": protect_content,
            "parse_mode": "HTML",
        }

        if content_type != "text" and caption:
            data["caption"] = caption
        if quote:
            data["reply_parameters"] = {
                "message_id": reply_message_id,
                "quote": quote,
            }
        else:
            data["reply_parameters"] = {"message_id": reply_message_id}
        match content_type:
            case "photo":
                if caption:
                    data["show_caption_above_media"] = show_caption_above_media
                data["has_spoiler"] = has_spoiler
            case "document":
                data["disable_content_type_detection"] = not content_type_detection

        final_buttons: list[list[dict[str, str]]] = []
        for i in buttons:
            final_buttons.append([])
            for j in i:
                final_buttons[-1].append({"text": j[0], "callback_data": j[1]})
        data["reply_markup"] = {"inline_keyboard": final_buttons}

        return await self._api_request(self.METHODS[content_type], data, timeout)

    async def forward_message(
        self,
        chat_id: str,
        from_chat_id: str,
        message_id: int,
        disable_notification: bool = False,
        protect_content: bool = False,
        caption: str | None = None,
        timeout: int = 10,
    ) -> default_dict | not_return:
        data: default_dict = {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_id": message_id,
            "disable_notification": disable_notification,
            "protect_content": protect_content,
            "parse_mode": "HTML",
        }

        if caption:
            data["caption"] = caption

        return await self._api_request("copyMessage", data, timeout)

    async def edit_text(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        enable_link_preview: bool = False,
        timeout: int = 10,
    ) -> default_dict | not_return:
        return await self._api_request(
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": not enable_link_preview},
            },
            timeout,
        )

    async def edit_caption(
        self,
        chat_id: int | str,
        message_id: int,
        caption: str,
        show_caption_above_media: bool = False,
        timeout: int = 10,
    ) -> default_dict | not_return:
        return await self._api_request(
            "editMessageCaption",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "caption": caption,
                "parse_mode": "HTML",
                "show_caption_above_media": show_caption_above_media,
            },
            timeout,
        )

    async def edit_media(
        self,
        chat_id: int | str,
        message_id: int,
        media_type: str,
        media: str,
        has_spoiler: bool,
        timeout: int = 10,
    ) -> default_dict | not_return:
        return await self._api_request(
            "editMessageMedia",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "media": {
                    "type": media_type,
                    "media": media,
                    "has_spoiler": has_spoiler,
                },
            },
            timeout,
        )

    async def edit_buttons(
        self,
        chat_id: int | str,
        message_id: int,
        buttons: list[list[tuple[str, str]]],
        timeout: int = 10,
    ) -> default_dict | not_return:

        data: default_dict = {
            "chat_id": chat_id,
            "message_id": message_id,
        }

        final_buttons: list[list[dict[str, str]]] = []
        for i in buttons:
            final_buttons.append([])
            for j in i:
                final_buttons[-1].append({"text": j[0], "callback_data": j[1]})
        data["reply_markup"] = {"inline_keyboard": final_buttons}

        return await self._api_request(
            "editMessageReplyMarkup",
            data,
            timeout,
        )

    async def delete_message(
        self,
        chat_id: int | str,
        message_id: int,
        timeout: int = 10,
    ) -> default_dict | not_return:
        return await self._api_request(
            "deleteMessage",
            {"chat_id": chat_id, "message_id": message_id},
            timeout,
        )

    async def delete_messages(
        self,
        chat_id: int | str,
        message_ids: list[int],
        timeout: int = 10,
    ) -> default_dict | not_return:
        return await self._api_request(
            "deleteMessages",
            {"chat_id": chat_id, "message_ids": message_ids},
            timeout,
        )
