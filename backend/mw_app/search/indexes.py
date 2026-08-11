SEARCH_INDEXES = {
    "products": {
        "uid": "products",
        "primary_key": "id",
        "searchable_attributes": ["name", "description"],
        "filterable_attributes": ["shop_id", "category_id", "item_type", "is_hidden"],
        "typo_tolerance": {
            "enabled": True,
            "minWordSizeForTypos": {"oneTypo": 3, "twoTypos": 7},
        },
    },
    "shops": {
        "uid": "shops",
        "primary_key": "id",
        "searchable_attributes": ["name", "google_category", "description", "location"],
        "filterable_attributes": ["business_type", "is_verified", "is_active"],
        "typo_tolerance": {
            "enabled": True,
            "minWordSizeForTypos": {"oneTypo": 3, "twoTypos": 7},
        },
    },
    "categories": {
        "uid": "categories",
        "primary_key": "id",
        "searchable_attributes": ["name", "description"],
        "filterable_attributes": [],
        "typo_tolerance": {
            "enabled": True,
            "minWordSizeForTypos": {"oneTypo": 3, "twoTypos": 7},
        },
    },
}
