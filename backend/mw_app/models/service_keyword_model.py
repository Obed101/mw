from ..extensions import db

class ServiceKeyword(db.Model):
    __tablename__ = "service_keyword"

    id = db.Column(db.Integer, primary_key=True)
    keyword = db.Column(db.String(100), unique=True, nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f'<ServiceKeyword {self.keyword}>'

    def to_dict(self):
        return {
            'id': self.id,
            'keyword': self.keyword,
            'is_active': self.is_active
        }
