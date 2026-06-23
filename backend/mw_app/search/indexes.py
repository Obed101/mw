SEARCH_INDEXES = {
    "products": {
        "uid": "products",
        "primary_key": "id",
        "searchable_attributes": ["name", "description"],
        "filterable_attributes": ["shop_id", "category_id", "item_type", "is_hidden"]
    },
    "shops": {
        "uid": "shops",
        "primary_key": "id",
        "searchable_attributes": ["name", "location", "description"],
        "filterable_attributes": ["business_type", "is_verified", "is_active"]
    }
}
