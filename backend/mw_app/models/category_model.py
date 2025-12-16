from datetime import datetime, timezone
from ..extensions import db

# Category level constants
CATEGORY_LEVEL_TRUNK = 0
CATEGORY_LEVEL_BRANCH = 1
CATEGORY_LEVEL_LEAF = 2
VALID_CATEGORY_LEVELS = {CATEGORY_LEVEL_TRUNK, CATEGORY_LEVEL_BRANCH, CATEGORY_LEVEL_LEAF}

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    level = db.Column(db.Integer, nullable=False, default=CATEGORY_LEVEL_LEAF)
    parent_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    
    # Self-referential relationships
    parent = db.relationship('Category', remote_side=[id], backref='children')
    products = db.relationship('Product', backref='category', lazy=True)
    
    # Ensure unique names within the same parent and level
    __table_args__ = (
        db.UniqueConstraint('name', 'parent_id', 'level', name='unique_category_name'),
    )
    
    def __repr__(self):
        level_names = {0: 'Trunk', 1: 'Branch', 2: 'Leaf'}
        return f'<Category {self.name} ({level_names.get(self.level, "Unknown")})>'
    
    def to_dict(self, include_children=False):
        """Convert category to dictionary for JSON serialization"""
        level_names = {0: 'trunk', 1: 'branch', 2: 'leaf'}
        result = {
            'id': self.id,
            'name': self.name,
            'level': self.level,
            'level_name': level_names.get(self.level, 'unknown'),
            'parent_id': self.parent_id,
            'description': self.description,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'product_count': len(self.products) if self.level == CATEGORY_LEVEL_LEAF else 0
        }
        
        if include_children and self.children:
            result['children'] = [child.to_dict() for child in self.children]
        
        return result
    
    def get_leaf_descendants(self):
        """Get all leaf categories under this category (works for Trunk and Branch)"""
        if self.level == CATEGORY_LEVEL_LEAF:
            return [self]
        
        leaf_categories = []
        for child in self.children:
            if child.level == CATEGORY_LEVEL_LEAF:
                leaf_categories.append(child)
            elif child.level == CATEGORY_LEVEL_BRANCH:
                leaf_categories.extend(child.get_leaf_descendants())
        
        return leaf_categories
    
    def get_all_products(self):
        """Get all products under this category and its descendants"""
        if self.level == CATEGORY_LEVEL_LEAF:
            return self.products
        
        all_products = []
        for leaf in self.get_leaf_descendants():
            all_products.extend(leaf.products)
        
        return all_products
    
    @staticmethod
    def get_trunk_categories():
        """Get all trunk (top-level) categories"""
        return Category.query.filter_by(level=CATEGORY_LEVEL_TRUNK, is_active=True).all()
    
    @staticmethod
    def get_branches_for_trunk(trunk_id):
        """Get all branches under a trunk"""
        return Category.query.filter_by(parent_id=trunk_id, level=CATEGORY_LEVEL_BRANCH, is_active=True).all()
    
    @staticmethod
    def get_leaves_for_branch(branch_id):
        """Get all leaves under a branch"""
        return Category.query.filter_by(parent_id=branch_id, level=CATEGORY_LEVEL_LEAF, is_active=True).all()
    
    def can_add_products(self):
        """Check if products can be added to this category (only Leaf categories)"""
        return self.level == CATEGORY_LEVEL_LEAF and self.is_active

