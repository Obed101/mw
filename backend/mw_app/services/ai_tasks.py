import logging
import hashlib
import json
from ..extensions import db
from ..models import Shop, Product, Category, CATEGORY_LEVEL_LEAF, CATEGORY_LEVEL_BRANCH, CATEGORY_LEVEL_TRUNK
from .ai_service import AIService, AIServiceError
from ..utils.threading_utils import run_in_background

logger = logging.getLogger(__name__)

def background_generate_shop_description(shop_id):
    """Background task to generate shop description"""
    # This function is called from a thread, so it should handle its own context
    # But we'll use the decorator at the call site or wrap it here.
    # For simplicity, I'll define the logic here and use the utility to call it.
    
    shop = Shop.query.get(shop_id)
    if not shop:
        logger.error(f"Shop {shop_id} not found for AI description generation")
        return

    try:
        shop.ai_job_status = 'running'
        db.session.commit()

        # Collect data for prompt
        products = product_names = [p.name for p in shop.products[:10]]  # Limit to 10 products
        products_text = ", ".join(products) if products else "various products"
        
        prompt = (
            f"Generate a short, compelling description (max 40 words) for a shop named '{shop.name}' "
            f"located in {shop.town or 'our town'}. The shop sells: {products_text}. "
            f"Make it persuasive, human-like, and professional."
        )

        ai_service = AIService()
        description = ai_service.generate_text(prompt)

        shop.description = description
        shop.ai_description_generated = True
        shop.ai_job_status = 'idle'
        db.session.commit()
        logger.info(f"Successfully generated AI description for shop {shop_id}")

    except Exception as e:
        logger.error(f"Error in background_generate_shop_description for shop {shop_id}: {str(e)}")
        shop.ai_job_status = 'failed'
        db.session.commit()

def background_auto_tag_product(product_id):
    """Background task to auto-tag a product"""
    product = Product.query.get(product_id)
    if not product:
        logger.error(f"Product {product_id} not found for AI auto-tagging")
        return

    try:
        product.ai_job_status = 'running'
        db.session.commit()

        ai_service = AIService()
        
        # Hash current state to detect changes
        content_to_hash = f"{product.name}|{product.description or ''}"
        current_hash = hashlib.md5(content_to_hash.encode()).hexdigest()
        
        if product.ai_tag_hash == current_hash:
            logger.info(f"Product {product_id} content hasn't changed. Skipping AI tagging.")
            product.ai_job_status = 'idle'
            db.session.commit()
            return

        prompt = (
            f"Analyze this product: Name: '{product.name}', Description: '{product.description or 'N/A'}'.\n"
            "Identify the most appropriate category and relevant search tags.\n"
            "Return a JSON object with 'category' (string) and 'tags' (list of strings).\n"
            "Tags should be short, lowercase, and relevant for search indexing."
        )

        data = ai_service.generate_json(prompt)
        
        category_name = data.get('category')
        tags = data.get('tags', [])

        if category_name:
            # Category logic: find existing or create new
            category = Category.query.filter(Category.name.ilike(category_name)).first()
            if not category:
                # Create new category as a Leaf under a generic "AI Generated" branch if possible
                # For now, let's just create it at the top level or find a default branch.
                # Requirement: "If not create new category."
                # We'll create it as a Leaf with no parent for now, or look for 'Uncategorized'
                uncategorized_branch = Category.query.filter(Category.name.ilike('Uncategorized')).first()
                category = Category(
                    name=category_name,
                    level=CATEGORY_LEVEL_LEAF,
                    parent_id=uncategorized_branch.id if uncategorized_branch else None
                )
                db.session.add(category)
                db.session.flush() # Get ID
            
            product.category_id = category.id

        if tags:
            product.tags = ", ".join(tags)

        product.ai_tag_hash = current_hash
        product.ai_job_status = 'idle'
        db.session.commit()
        logger.info(f"Successfully auto-tagged product {product_id}")

    except Exception as e:
        logger.error(f"Error in background_auto_tag_product for product {product_id}: {str(e)}")
        product.ai_job_status = 'failed'
        db.session.commit()
