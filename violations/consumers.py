import json
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone


"""Realtime chat consumer.

Currently allows faculty admin + staff. Extend to normal faculty role so that
regular faculty accounts (whose template uses body class `role-faculty`) can join.
In production you may want to tighten further or move role logic into a
permission helper.
"""

ALLOWED_ROLES = {"faculty_admin", "faculty", "staff"}
ROOM_NAME = "staff-faculty"  # default shared room


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        # Only authenticated staff & faculty (admin) + superusers
        if not user or not user.is_authenticated:
            await self.close()
            return
        role = getattr(user, "role", None)
        if not (getattr(user, "is_superuser", False) or role in ALLOWED_ROLES):
            await self.close()
            return
        room_name = self.scope["url_route"]["kwargs"].get("room_name") or ROOM_NAME
        self.room_group_name = f"chat_{room_name}"
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat.system",
                "message": f"{user.username} joined the chat",
                "ts": timezone.now().isoformat(),
            },
        )

    async def disconnect(self, code):
        user = self.scope.get("user")
        if hasattr(self, "room_group_name"):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
            if user and user.is_authenticated:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "chat.system",
                        "message": f"{user.username} left the chat",
                        "ts": timezone.now().isoformat(),
                    },
                )

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return
        user = self.scope.get("user")
        content = (data.get("message") or "").strip()
        if not content:
            return
        # Broadcast to group
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat.message",
                "user": user.username,
                "role": getattr(user, "role", ""),
                "message": content,
                "ts": timezone.now().isoformat(),
            },
        )

    async def chat_message(self, event):  # type: ignore
        await self.send(text_data=json.dumps({
            "kind": "message",
            "user": event.get("user"),
            "role": event.get("role"),
            "message": event.get("message"),
            "ts": event.get("ts"),
        }))

    async def chat_system(self, event):  # type: ignore
        await self.send(text_data=json.dumps({
            "kind": "system",
            "message": event.get("message"),
            "ts": event.get("ts"),
        }))
