from datetime import datetime, timezone
import json

from ..extensions import db


class UserFavoriteProduct(db.Model):
    """Track which users have favorited which products."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    favorited_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("user_id", "product_id", name="unique_user_product_favorite"),
    )

    user = db.relationship("User", backref="favorite_products")
    product = db.relationship("Product", backref="favorited_by")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "product_id": self.product_id,
            "favorited_at": self.favorited_at.isoformat() if self.favorited_at else None,
        }


class Notification(db.Model):
    """In-app notification delivered to a user."""

    id = db.Column(db.Integer, primary_key=True)
    recipient_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    notification_type = db.Column(db.String(50), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    message = db.Column(db.Text, nullable=False)
    related_shop_id = db.Column(db.Integer, db.ForeignKey("shop.id"), nullable=True, index=True)
    related_product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=True, index=True)
    payload = db.Column(db.Text, nullable=True)
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False, index=True)
    read_at = db.Column(db.DateTime, nullable=True)

    recipient = db.relationship("User", foreign_keys=[recipient_user_id], backref="received_notifications")
    actor = db.relationship("User", foreign_keys=[actor_user_id], backref="sent_notifications")
    shop = db.relationship("Shop", backref="event_notifications")
    product = db.relationship("Product", backref="event_notifications")

    def set_payload(self, payload_dict):
        self.payload = json.dumps(payload_dict) if payload_dict is not None else None

    def get_payload(self):
        if not self.payload:
            return None
        try:
            return json.loads(self.payload)
        except Exception:
            return None

    def mark_read(self):
        self.is_read = True
        self.read_at = datetime.now(timezone.utc)

    def to_dict(self):
        return {
            "id": self.id,
            "recipient_user_id": self.recipient_user_id,
            "actor_user_id": self.actor_user_id,
            "notification_type": self.notification_type,
            "title": self.title,
            "message": self.message,
            "related_shop_id": self.related_shop_id,
            "related_product_id": self.related_product_id,
            "payload": self.get_payload(),
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "read_at": self.read_at.isoformat() if self.read_at else None,
        }

    @classmethod
    def create_for_users(
        cls,
        user_ids,
        notification_type,
        title,
        message,
        actor_user_id=None,
        related_shop_id=None,
        related_product_id=None,
        payload=None,
        exclude_user_id=None,
    ):
        notifications = []
        unique_user_ids = {int(user_id) for user_id in (user_ids or []) if user_id}

        if exclude_user_id is not None:
            unique_user_ids.discard(int(exclude_user_id))

        for user_id in unique_user_ids:
            notification = cls(
                recipient_user_id=user_id,
                actor_user_id=actor_user_id,
                notification_type=notification_type,
                title=title,
                message=message,
                related_shop_id=related_shop_id,
                related_product_id=related_product_id,
            )
            notification.set_payload(payload)
            db.session.add(notification)
            notifications.append(notification)

        return notifications
