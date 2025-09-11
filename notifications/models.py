from django.db import models
from django.conf import settings

# Create your models here.

class Notification(models.Model):
    """
    Persisted notifications for durability + replay.
    If `user` is null the notification is considered "global".
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"], name="idx_notifications_user_created"),
            models.Index(fields=["created_at"], name="idx_notifications_created"),
        ]
        ordering = ["id"]

    def __str__(self):
        return f"Notification(id={self.id}, user={self.user_id}, created_at={self.created_at})"