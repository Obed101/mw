from datetime import datetime, timezone
from ..extensions import db

# Conversation Statuses
CONVERSATION_STATUS_OPEN = 'open'
CONVERSATION_STATUS_PENDING = 'pending'
CONVERSATION_STATUS_CLOSED = 'closed'

class SupportConversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    subject = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(50), nullable=False, default=CONVERSATION_STATUS_OPEN)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    last_message_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Relationships
    user = db.relationship("User", backref="support_conversations")
    messages = db.relationship("SupportMessage", back_populates="conversation", cascade="all, delete-orphan", order_by="SupportMessage.created_at")

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'subject': self.subject,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_message_at': self.last_message_at.isoformat() if self.last_message_at else None
        }


class SupportMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("support_conversation.id"), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    
    message = db.Column(db.Text, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Relationships
    conversation = db.relationship("SupportConversation", back_populates="messages")
    sender = db.relationship("User", backref="support_messages")

    def to_dict(self):
        return {
            'id': self.id,
            'conversation_id': self.conversation_id,
            'sender_id': self.sender_id,
            'message': "Deleted Message" if self.is_deleted else self.message,
            'is_admin': self.is_admin,
            'is_read': self.is_read,
            'is_deleted': self.is_deleted,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
