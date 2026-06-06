from ..models.service_keyword_model import ServiceKeyword

def is_service_name(name):
    """
    Detects if the shop name contains any active service keywords.
    Runs locally, fast, with no external API calls.
    """
    if not name:
        return False
        
    # Retrieve all active keywords
    active_keywords = [kw.keyword.lower() for kw in ServiceKeyword.query.filter_by(is_active=True).all()]
    if not active_keywords:
        return False
        
    normalized_name = name.lower()
    for keyword in active_keywords:
        if keyword in normalized_name:
            return True
            
    return False
