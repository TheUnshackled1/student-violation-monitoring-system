import json
from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone
from .models import ChatMessage


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
    self.room_name = room_name
    self.room_group_name = f"chat_{room_name}"
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        # Send recent history (last 50 messages) directly to the connecting socket
        try:
            msgs = await sync_to_async(list)(
                ChatMessage.objects.filter(room=room_name).order_by('created_at').values('sender__username', 'content', 'created_at')[:50]
            )
            history = [
                {"user": m['sender__username'], "message": m['content'], "ts": m['created_at'].isoformat()}
                for m in msgs
            ]
            await self.send(text_data=json.dumps({"kind": "history", "messages": history}))
        except Exception:
            # Non-fatal: if DB access fails, continue without history
            pass

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

        # Persist message to DB (best-effort)
        try:
            await sync_to_async(ChatMessage.objects.create)(sender=user, room=self.room_name, content=content)
        except Exception:
            # Don't block delivery if DB write fails
            pass

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
