"""
Comprehensive Test Data Sets for E2E Testing.

Contains predefined data sets for ALL channels with 20-50 records each:
- Shopify: purchases, refunds, cancellations
- Ad Platforms: Meta, Google, TikTok, Snapchat
- Email Marketing: Klaviyo campaigns and events
- SMS Marketing: Attentive, SMSBump, Postscript

All data is designed to flow through APIs for realistic E2E testing.
"""

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import uuid
import random

# Seed for reproducible random data
random.seed(42)

# =============================================================================
# Base Configuration
# =============================================================================

BASE_DATE = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

# Product catalog for realistic order data
PRODUCTS = [
    {"id": "prod_001", "title": "Premium Widget", "price": 49.99, "sku": "PWD-001"},
    {"id": "prod_002", "title": "Basic Widget", "price": 24.99, "sku": "BWD-002"},
    {"id": "prod_003", "title": "Widget Pro Bundle", "price": 99.99, "sku": "WPB-003"},
    {"id": "prod_004", "title": "Widget Starter Kit", "price": 34.99, "sku": "WSK-004"},
    {"id": "prod_005", "title": "Widget Accessories Pack", "price": 19.99, "sku": "WAP-005"},
    {"id": "prod_006", "title": "Premium Widget XL", "price": 79.99, "sku": "PWX-006"},
    {"id": "prod_007", "title": "Widget Mini", "price": 14.99, "sku": "WMN-007"},
    {"id": "prod_008", "title": "Widget Deluxe", "price": 149.99, "sku": "WDX-008"},
    {"id": "prod_009", "title": "Widget Essential", "price": 29.99, "sku": "WES-009"},
    {"id": "prod_010", "title": "Widget Ultimate", "price": 199.99, "sku": "WUL-010"},
]

# Campaign names for realistic ad data
AD_CAMPAIGNS = {
    "meta": [
        "Winter Sale 2024", "New Arrivals", "Retargeting - Cart Abandoners",
        "Lookalike - High Value", "Brand Awareness", "Product Launch",
        "Holiday Special", "Flash Sale", "VIP Exclusive", "Clearance Event"
    ],
    "google": [
        "Brand Search", "Generic Keywords", "Shopping - All Products",
        "Display Remarketing", "Performance Max", "YouTube Pre-roll",
        "Discovery Ads", "Local Campaigns", "Smart Shopping", "Search - Competitors"
    ],
    "tiktok": [
        "Viral Challenge", "Influencer Collab", "Product Showcase",
        "UGC Campaign", "Spark Ads", "Brand Takeover", "Hashtag Challenge",
        "In-Feed Native", "TopView", "Branded Effects"
    ],
    "snapchat": [
        "Story Ads", "Collection Ads", "AR Lens", "Commercials",
        "Dynamic Ads", "Snap Ads", "Filter Campaign", "Spotlight",
        "Discover Ads", "Promoted Stories"
    ],
}


# =============================================================================
# Shopify Data Generators
# =============================================================================

def create_shopify_order(
    order_id: Optional[str] = None,
    order_number: Optional[int] = None,
    total_price: Optional[float] = None,
    financial_status: str = "paid",
    fulfillment_status: str = "fulfilled",
    created_at: Optional[str] = None,
    currency: str = "USD",
    customer_email: Optional[str] = None,
    refunds: Optional[List[Dict]] = None,
    cancelled_at: Optional[str] = None,
    products: Optional[List[Dict]] = None,
) -> Dict:
    """Create a realistic Shopify order."""
    order_id = order_id or f"gid://shopify/Order/{uuid.uuid4().hex[:12]}"
    customer_id = f"gid://shopify/Customer/{uuid.uuid4().hex[:12]}"

    # Random product selection if not specified
    if products is None:
        num_items = random.randint(1, 3)
        selected_products = random.sample(PRODUCTS, num_items)
        total_price = sum(p["price"] * random.randint(1, 2) for p in selected_products)
    else:
        selected_products = products
        total_price = total_price or sum(p.get("price", 50) for p in products)

    total_price = total_price or random.uniform(25, 250)

    line_items = [
        {
            "id": f"gid://shopify/LineItem/{uuid.uuid4().hex[:12]}",
            "product_id": f"gid://shopify/Product/{p['id']}",
            "variant_id": f"gid://shopify/ProductVariant/{p['id']}_v1",
            "title": p["title"],
            "sku": p["sku"],
            "quantity": random.randint(1, 2),
            "price": str(p["price"]),
        }
        for p in selected_products
    ]

    return {
        "id": order_id,
        "order_number": order_number or (1000 + abs(hash(order_id)) % 9000),
        "total_price": str(round(total_price, 2)),
        "subtotal_price": str(round(total_price * 0.9, 2)),
        "total_tax": str(round(total_price * 0.1, 2)),
        "total_discounts": str(round(random.uniform(0, total_price * 0.1), 2)),
        "currency": currency,
        "financial_status": financial_status,
        "fulfillment_status": fulfillment_status,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "processed_at": created_at or datetime.now(timezone.utc).isoformat(),
        "cancelled_at": cancelled_at,
        "cancel_reason": "customer" if cancelled_at else None,
        "customer": {
            "id": customer_id,
            "email": customer_email or f"customer-{uuid.uuid4().hex[:8]}@example.com",
            "first_name": random.choice(["John", "Jane", "Bob", "Alice", "Charlie", "Diana"]),
            "last_name": random.choice(["Smith", "Johnson", "Williams", "Brown", "Jones", "Davis"]),
            "orders_count": random.randint(1, 10),
            "total_spent": str(round(total_price * random.randint(1, 5), 2)),
        },
        "line_items": line_items,
        "shipping_address": {
            "first_name": "Test",
            "last_name": "Customer",
            "address1": f"{random.randint(100, 9999)} Main St",
            "city": random.choice(["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"]),
            "province": random.choice(["NY", "CA", "IL", "TX", "AZ"]),
            "province_code": random.choice(["NY", "CA", "IL", "TX", "AZ"]),
            "country": "United States",
            "country_code": "US",
            "zip": f"{random.randint(10000, 99999)}",
        },
        "billing_address": {
            "first_name": "Test",
            "last_name": "Customer",
            "address1": f"{random.randint(100, 9999)} Main St",
            "city": random.choice(["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"]),
            "province_code": random.choice(["NY", "CA", "IL", "TX", "AZ"]),
            "country_code": "US",
            "zip": f"{random.randint(10000, 99999)}",
        },
        "refunds": refunds or [],
        "tags": random.choice(["", "vip", "wholesale", "returning", "new_customer"]),
        "source_name": random.choice(["web", "shopify_draft_order", "pos", "iphone", "android"]),
        "referring_site": random.choice(["", "https://google.com", "https://facebook.com", "https://instagram.com"]),
        "landing_site": f"/products/{random.choice(PRODUCTS)['sku']}",
    }


def create_shopify_customer(
    customer_id: Optional[str] = None,
    email: Optional[str] = None,
    orders_count: int = 1,
    total_spent: float = 99.99,
) -> Dict:
    """Create a realistic Shopify customer."""
    customer_id = customer_id or f"gid://shopify/Customer/{uuid.uuid4().hex[:12]}"
    first_name = random.choice(["John", "Jane", "Bob", "Alice", "Charlie", "Diana", "Eve", "Frank"])
    last_name = random.choice(["Smith", "Johnson", "Williams", "Brown", "Jones", "Davis", "Miller", "Wilson"])

    return {
        "id": customer_id,
        "email": email or f"{first_name.lower()}.{last_name.lower()}.{uuid.uuid4().hex[:4]}@example.com",
        "first_name": first_name,
        "last_name": last_name,
        "orders_count": orders_count,
        "total_spent": str(total_spent),
        "created_at": (BASE_DATE - timedelta(days=random.randint(1, 365))).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "verified_email": True,
        "accepts_marketing": random.choice([True, False]),
        "accepts_marketing_updated_at": datetime.now(timezone.utc).isoformat(),
        "marketing_opt_in_level": random.choice(["single_opt_in", "confirmed_opt_in", None]),
        "state": "enabled",
        "tags": random.choice(["", "vip", "wholesale", "newsletter"]),
        "currency": "USD",
        "default_address": {
            "address1": f"{random.randint(100, 9999)} Main St",
            "city": random.choice(["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"]),
            "province_code": random.choice(["NY", "CA", "IL", "TX", "AZ"]),
            "country_code": "US",
            "zip": f"{random.randint(10000, 99999)}",
        },
    }


def generate_shopify_purchases(count: int = 30) -> List[Dict]:
    """Generate successful purchase orders."""
    orders = []
    for i in range(count):
        created_at = BASE_DATE + timedelta(days=i // 3, hours=random.randint(0, 23), minutes=random.randint(0, 59))
        orders.append(create_shopify_order(
            order_id=f"gid://shopify/Order/PUR{i:04d}",
            order_number=1000 + i,
            financial_status="paid",
            fulfillment_status="fulfilled",
            created_at=created_at.isoformat(),
        ))
    return orders


def generate_shopify_refunds(count: int = 25) -> List[Dict]:
    """Generate refunded orders."""
    orders = []
    for i in range(count):
        created_at = BASE_DATE + timedelta(days=i // 2, hours=random.randint(0, 23))
        refund_at = created_at + timedelta(days=random.randint(1, 14))
        total_price = round(random.uniform(30, 200), 2)

        # Mix of full and partial refunds
        is_full_refund = random.choice([True, True, False])  # 2/3 full refunds
        refund_amount = total_price if is_full_refund else round(total_price * random.uniform(0.3, 0.7), 2)

        orders.append(create_shopify_order(
            order_id=f"gid://shopify/Order/REF{i:04d}",
            order_number=2000 + i,
            total_price=total_price,
            financial_status="refunded" if is_full_refund else "partially_refunded",
            fulfillment_status="fulfilled",
            created_at=created_at.isoformat(),
            refunds=[{
                "id": f"gid://shopify/Refund/R{i:04d}",
                "created_at": refund_at.isoformat(),
                "processed_at": refund_at.isoformat(),
                "note": random.choice(["Customer request", "Defective product", "Wrong item shipped", "Changed mind"]),
                "restock": random.choice([True, False]),
                "transactions": [{
                    "amount": str(refund_amount),
                    "kind": "refund",
                    "status": "success",
                }],
                "refund_line_items": [{
                    "quantity": 1,
                    "subtotal": str(refund_amount),
                    "total_tax": "0.00",
                }],
            }],
        ))
    return orders


def generate_shopify_cancellations(count: int = 20) -> List[Dict]:
    """Generate cancelled orders."""
    orders = []
    cancel_reasons = ["customer", "fraud", "inventory", "declined", "other"]

    for i in range(count):
        created_at = BASE_DATE + timedelta(days=i // 2, hours=random.randint(0, 23))
        cancelled_at = created_at + timedelta(hours=random.randint(1, 48))

        orders.append(create_shopify_order(
            order_id=f"gid://shopify/Order/CAN{i:04d}",
            order_number=3000 + i,
            financial_status=random.choice(["voided", "refunded", "pending"]),
            fulfillment_status=None,
            created_at=created_at.isoformat(),
            cancelled_at=cancelled_at.isoformat(),
        ))
    return orders


# =============================================================================
# Ad Platform Data Generators
# =============================================================================

def create_meta_ad_record(
    campaign_id: Optional[str] = None,
    campaign_name: Optional[str] = None,
    date: Optional[str] = None,
    spend: Optional[float] = None,
) -> Dict:
    """Create a Meta (Facebook/Instagram) ads record."""
    campaign_id = campaign_id or f"meta_camp_{uuid.uuid4().hex[:12]}"
    campaign_name = campaign_name or random.choice(AD_CAMPAIGNS["meta"])

    impressions = random.randint(5000, 100000)
    clicks = int(impressions * random.uniform(0.01, 0.05))  # 1-5% CTR
    spend = spend or round(random.uniform(50, 500), 2)
    conversions = int(clicks * random.uniform(0.02, 0.10))  # 2-10% conversion rate
    revenue = round(conversions * random.uniform(50, 150), 2)

    return {
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "adset_id": f"meta_adset_{uuid.uuid4().hex[:8]}",
        "adset_name": f"{campaign_name} - Adset {random.randint(1, 5)}",
        "ad_id": f"meta_ad_{uuid.uuid4().hex[:8]}",
        "ad_name": f"Ad Creative {random.randint(1, 10)}",
        "date": date or (BASE_DATE + timedelta(days=random.randint(0, 30))).strftime("%Y-%m-%d"),
        "impressions": impressions,
        "clicks": clicks,
        "spend": spend,
        "reach": int(impressions * random.uniform(0.6, 0.9)),
        "frequency": round(random.uniform(1.0, 3.0), 2),
        "cpm": round(spend / impressions * 1000, 2),
        "cpc": round(spend / max(clicks, 1), 2),
        "ctr": round(clicks / impressions * 100, 2),
        "conversions": conversions,
        "conversion_value": revenue,
        "roas": round(revenue / max(spend, 1), 2),
        "actions": [
            {"action_type": "link_click", "value": clicks},
            {"action_type": "purchase", "value": conversions},
            {"action_type": "add_to_cart", "value": int(conversions * random.uniform(2, 4))},
            {"action_type": "view_content", "value": int(clicks * random.uniform(0.5, 0.9))},
        ],
        "objective": random.choice(["CONVERSIONS", "TRAFFIC", "BRAND_AWARENESS", "REACH"]),
        "platform": random.choice(["facebook", "instagram", "audience_network"]),
        "placement": random.choice(["feed", "stories", "reels", "right_column"]),
        "account_id": "act_123456789",
        "account_name": "Test Ad Account",
    }


def create_google_ad_record(
    campaign_id: Optional[str] = None,
    campaign_name: Optional[str] = None,
    date: Optional[str] = None,
    cost: Optional[float] = None,
) -> Dict:
    """Create a Google Ads record."""
    campaign_id = campaign_id or f"google_camp_{random.randint(1000000, 9999999)}"
    campaign_name = campaign_name or random.choice(AD_CAMPAIGNS["google"])

    impressions = random.randint(3000, 80000)
    clicks = int(impressions * random.uniform(0.02, 0.08))  # 2-8% CTR for Google
    cost = cost or round(random.uniform(30, 400), 2)
    conversions = int(clicks * random.uniform(0.03, 0.12))  # 3-12% conversion rate
    conversion_value = round(conversions * random.uniform(40, 120), 2)

    return {
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "campaign_type": random.choice(["SEARCH", "SHOPPING", "DISPLAY", "VIDEO", "PERFORMANCE_MAX"]),
        "ad_group_id": f"adgroup_{random.randint(100000, 999999)}",
        "ad_group_name": f"{campaign_name} - Ad Group {random.randint(1, 5)}",
        "date": date or (BASE_DATE + timedelta(days=random.randint(0, 30))).strftime("%Y-%m-%d"),
        "impressions": impressions,
        "clicks": clicks,
        "cost": cost,  # Google uses 'cost' instead of 'spend'
        "cost_micros": int(cost * 1000000),
        "conversions": conversions,
        "conversions_value": conversion_value,
        "all_conversions": conversions + random.randint(0, 5),
        "view_through_conversions": random.randint(0, int(conversions * 0.3)),
        "average_cpc": round(cost / max(clicks, 1), 2),
        "average_cpm": round(cost / impressions * 1000, 2),
        "ctr": round(clicks / impressions * 100, 4),
        "conversion_rate": round(conversions / max(clicks, 1) * 100, 2),
        "cost_per_conversion": round(cost / max(conversions, 1), 2),
        "search_impression_share": round(random.uniform(0.3, 0.9), 2),
        "quality_score": random.randint(5, 10),
        "customer_id": "123-456-7890",
        "account_name": "Test Google Ads Account",
        "network": random.choice(["SEARCH", "SEARCH_PARTNERS", "CONTENT", "YOUTUBE_SEARCH", "YOUTUBE_WATCH"]),
        "device": random.choice(["MOBILE", "DESKTOP", "TABLET"]),
    }


def create_tiktok_ad_record(
    campaign_id: Optional[str] = None,
    campaign_name: Optional[str] = None,
    date: Optional[str] = None,
    spend: Optional[float] = None,
) -> Dict:
    """Create a TikTok Ads record."""
    campaign_id = campaign_id or f"tiktok_camp_{uuid.uuid4().hex[:12]}"
    campaign_name = campaign_name or random.choice(AD_CAMPAIGNS["tiktok"])

    impressions = random.randint(10000, 200000)  # TikTok tends to have high impressions
    clicks = int(impressions * random.uniform(0.005, 0.025))  # 0.5-2.5% CTR
    spend = spend or round(random.uniform(40, 350), 2)
    conversions = int(clicks * random.uniform(0.01, 0.08))
    video_views = int(impressions * random.uniform(0.3, 0.7))

    return {
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "adgroup_id": f"tiktok_adgroup_{uuid.uuid4().hex[:8]}",
        "adgroup_name": f"{campaign_name} - Adgroup {random.randint(1, 5)}",
        "ad_id": f"tiktok_ad_{uuid.uuid4().hex[:8]}",
        "ad_name": f"TikTok Creative {random.randint(1, 10)}",
        "date": date or (BASE_DATE + timedelta(days=random.randint(0, 30))).strftime("%Y-%m-%d"),
        "impressions": impressions,
        "clicks": clicks,
        "spend": spend,
        "reach": int(impressions * random.uniform(0.5, 0.8)),
        "video_views": video_views,
        "video_watched_2s": int(video_views * random.uniform(0.6, 0.9)),
        "video_watched_6s": int(video_views * random.uniform(0.3, 0.6)),
        "average_video_play": round(random.uniform(3, 15), 1),
        "average_video_play_per_user": round(random.uniform(5, 20), 1),
        "profile_visits": random.randint(100, 2000),
        "likes": random.randint(50, 5000),
        "comments": random.randint(10, 500),
        "shares": random.randint(5, 200),
        "follows": random.randint(0, 100),
        "conversions": conversions,
        "conversion_rate": round(conversions / max(clicks, 1) * 100, 2),
        "cost_per_conversion": round(spend / max(conversions, 1), 2),
        "cpm": round(spend / impressions * 1000, 2),
        "cpc": round(spend / max(clicks, 1), 2),
        "ctr": round(clicks / impressions * 100, 4),
        "objective": random.choice(["CONVERSIONS", "TRAFFIC", "VIDEO_VIEWS", "REACH", "APP_INSTALLS"]),
        "placement": random.choice(["TikTok", "Pangle", "News Feed App Series"]),
        "advertiser_id": "tiktok_adv_123456",
    }


def create_snapchat_ad_record(
    campaign_id: Optional[str] = None,
    campaign_name: Optional[str] = None,
    date: Optional[str] = None,
    spend: Optional[float] = None,
) -> Dict:
    """Create a Snapchat Ads record."""
    campaign_id = campaign_id or f"snap_camp_{uuid.uuid4().hex[:12]}"
    campaign_name = campaign_name or random.choice(AD_CAMPAIGNS["snapchat"])

    impressions = random.randint(8000, 150000)
    swipe_ups = int(impressions * random.uniform(0.01, 0.04))  # 1-4% swipe rate
    spend = spend or round(random.uniform(35, 300), 2)
    conversions = int(swipe_ups * random.uniform(0.02, 0.10))

    return {
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "ad_squad_id": f"snap_squad_{uuid.uuid4().hex[:8]}",
        "ad_squad_name": f"{campaign_name} - Squad {random.randint(1, 5)}",
        "ad_id": f"snap_ad_{uuid.uuid4().hex[:8]}",
        "ad_name": f"Snap Creative {random.randint(1, 10)}",
        "date": date or (BASE_DATE + timedelta(days=random.randint(0, 30))).strftime("%Y-%m-%d"),
        "impressions": impressions,
        "swipes": swipe_ups,
        "spend": spend,
        "reach": int(impressions * random.uniform(0.55, 0.85)),
        "frequency": round(random.uniform(1.2, 4.0), 2),
        "video_views": int(impressions * random.uniform(0.4, 0.75)),
        "video_views_time_based": int(impressions * random.uniform(0.25, 0.5)),
        "screen_time_millis": random.randint(1000, 15000),
        "quartile_1": int(impressions * random.uniform(0.5, 0.8)),
        "quartile_2": int(impressions * random.uniform(0.3, 0.6)),
        "quartile_3": int(impressions * random.uniform(0.2, 0.4)),
        "view_completion": int(impressions * random.uniform(0.1, 0.3)),
        "shares": random.randint(5, 100),
        "saves": random.randint(10, 200),
        "conversions": conversions,
        "conversion_purchases": conversions,
        "conversion_purchases_value": round(conversions * random.uniform(45, 130), 2),
        "ecpm": round(spend / impressions * 1000, 2),
        "ecpsu": round(spend / max(swipe_ups, 1), 2),
        "swipe_up_rate": round(swipe_ups / impressions * 100, 4),
        "objective": random.choice(["WEB_CONVERSIONS", "SWIPES", "APP_INSTALLS", "VIDEO_VIEWS", "AWARENESS"]),
        "ad_account_id": "snap_account_123456",
    }


def generate_meta_ads(count: int = 30) -> List[Dict]:
    """Generate Meta ads records."""
    records = []
    for i in range(count):
        date = (BASE_DATE + timedelta(days=i % 30)).strftime("%Y-%m-%d")
        records.append(create_meta_ad_record(
            campaign_id=f"meta_camp_{i:04d}",
            campaign_name=AD_CAMPAIGNS["meta"][i % len(AD_CAMPAIGNS["meta"])],
            date=date,
        ))
    return records


def generate_google_ads(count: int = 30) -> List[Dict]:
    """Generate Google Ads records."""
    records = []
    for i in range(count):
        date = (BASE_DATE + timedelta(days=i % 30)).strftime("%Y-%m-%d")
        records.append(create_google_ad_record(
            campaign_id=f"google_camp_{i:04d}",
            campaign_name=AD_CAMPAIGNS["google"][i % len(AD_CAMPAIGNS["google"])],
            date=date,
        ))
    return records


def generate_tiktok_ads(count: int = 25) -> List[Dict]:
    """Generate TikTok Ads records."""
    records = []
    for i in range(count):
        date = (BASE_DATE + timedelta(days=i % 30)).strftime("%Y-%m-%d")
        records.append(create_tiktok_ad_record(
            campaign_id=f"tiktok_camp_{i:04d}",
            campaign_name=AD_CAMPAIGNS["tiktok"][i % len(AD_CAMPAIGNS["tiktok"])],
            date=date,
        ))
    return records


def generate_snapchat_ads(count: int = 25) -> List[Dict]:
    """Generate Snapchat Ads records."""
    records = []
    for i in range(count):
        date = (BASE_DATE + timedelta(days=i % 30)).strftime("%Y-%m-%d")
        records.append(create_snapchat_ad_record(
            campaign_id=f"snap_camp_{i:04d}",
            campaign_name=AD_CAMPAIGNS["snapchat"][i % len(AD_CAMPAIGNS["snapchat"])],
            date=date,
        ))
    return records


# =============================================================================
# Email Marketing Data Generators (Klaviyo)
# =============================================================================

def create_klaviyo_campaign(
    campaign_id: Optional[str] = None,
    name: Optional[str] = None,
    sent_at: Optional[str] = None,
) -> Dict:
    """Create a Klaviyo email campaign record."""
    campaign_id = campaign_id or f"klaviyo_camp_{uuid.uuid4().hex[:12]}"

    campaign_names = [
        "Welcome Series - Email 1", "Welcome Series - Email 2", "Welcome Series - Email 3",
        "Abandoned Cart Reminder", "Abandoned Cart - Final Chance",
        "Weekly Newsletter", "Monthly Digest",
        "Flash Sale Announcement", "New Product Launch",
        "Customer Win-Back", "VIP Early Access",
        "Holiday Gift Guide", "End of Season Sale",
        "Thank You - First Purchase", "Review Request",
        "Birthday Special", "Anniversary Offer",
        "Back in Stock Alert", "Price Drop Alert",
        "Loyalty Rewards Update", "Referral Program"
    ]

    name = name or random.choice(campaign_names)
    sent_count = random.randint(5000, 50000)
    open_count = int(sent_count * random.uniform(0.15, 0.45))  # 15-45% open rate
    click_count = int(open_count * random.uniform(0.10, 0.35))  # 10-35% click-to-open rate
    conversion_count = int(click_count * random.uniform(0.05, 0.20))
    unsubscribe_count = int(sent_count * random.uniform(0.001, 0.005))
    bounce_count = int(sent_count * random.uniform(0.01, 0.03))

    revenue = round(conversion_count * random.uniform(50, 150), 2)

    return {
        "id": campaign_id,
        "name": name,
        "status": "sent",
        "campaign_type": random.choice(["campaign", "flow"]),
        "subject_line": f"{name} - Don't miss out!",
        "preview_text": "Check out our latest offers...",
        "from_email": "hello@teststore.com",
        "from_name": "Test Store",
        "send_time": sent_at or (BASE_DATE + timedelta(days=random.randint(0, 30))).isoformat(),
        "created_at": (BASE_DATE - timedelta(days=random.randint(1, 7))).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "sent_at": sent_at or (BASE_DATE + timedelta(days=random.randint(0, 30))).isoformat(),
        "statistics": {
            "sent": sent_count,
            "delivered": sent_count - bounce_count,
            "opens": open_count,
            "unique_opens": int(open_count * 0.85),
            "clicks": click_count,
            "unique_clicks": int(click_count * 0.75),
            "unsubscribes": unsubscribe_count,
            "spam_complaints": random.randint(0, max(1, int(sent_count * 0.0001))),
            "bounces": bounce_count,
            "soft_bounces": int(bounce_count * 0.3),
            "hard_bounces": int(bounce_count * 0.7),
        },
        "conversions": {
            "count": conversion_count,
            "revenue": revenue,
            "average_order_value": round(revenue / max(conversion_count, 1), 2),
        },
        "metrics": {
            "open_rate": round(open_count / sent_count * 100, 2),
            "click_rate": round(click_count / sent_count * 100, 2),
            "click_to_open_rate": round(click_count / max(open_count, 1) * 100, 2),
            "unsubscribe_rate": round(unsubscribe_count / sent_count * 100, 4),
            "bounce_rate": round(bounce_count / sent_count * 100, 2),
            "revenue_per_recipient": round(revenue / sent_count, 4),
        },
        "lists": [{"id": f"list_{random.randint(1, 5)}", "name": f"List {random.randint(1, 5)}"}],
        "tags": random.sample(["promotional", "transactional", "newsletter", "automated", "seasonal"], random.randint(1, 3)),
    }


def create_klaviyo_event(
    event_id: Optional[str] = None,
    event_type: str = "Opened Email",
    timestamp: Optional[str] = None,
) -> Dict:
    """Create a Klaviyo event record."""
    event_id = event_id or f"klaviyo_evt_{uuid.uuid4().hex[:12]}"

    event_types = [
        "Opened Email", "Clicked Email", "Received Email",
        "Unsubscribed", "Marked as Spam", "Bounced",
        "Placed Order", "Started Checkout", "Added to Cart",
        "Viewed Product", "Subscribed to List"
    ]

    return {
        "id": event_id,
        "type": event_type,
        "timestamp": timestamp or (BASE_DATE + timedelta(days=random.randint(0, 30), hours=random.randint(0, 23))).isoformat(),
        "datetime": timestamp or (BASE_DATE + timedelta(days=random.randint(0, 30), hours=random.randint(0, 23))).isoformat(),
        "uuid": str(uuid.uuid4()),
        "event_properties": {
            "campaign_id": f"klaviyo_camp_{random.randint(1, 50):04d}",
            "campaign_name": random.choice(["Welcome Series", "Flash Sale", "Newsletter"]),
            "subject": "Your exclusive offer inside!",
            "url": f"https://teststore.com/products/{random.choice(PRODUCTS)['sku']}" if event_type == "Clicked Email" else None,
        },
        "person": {
            "id": f"klaviyo_person_{uuid.uuid4().hex[:8]}",
            "email": f"customer-{uuid.uuid4().hex[:8]}@example.com",
            "first_name": random.choice(["John", "Jane", "Bob", "Alice"]),
            "last_name": random.choice(["Smith", "Johnson", "Williams", "Brown"]),
        },
        "attribution": {
            "flow_id": f"flow_{random.randint(1, 10)}" if random.choice([True, False]) else None,
            "campaign_id": f"camp_{random.randint(1, 50)}",
            "message_id": f"msg_{uuid.uuid4().hex[:8]}",
        },
    }


def generate_klaviyo_campaigns(count: int = 30) -> List[Dict]:
    """Generate Klaviyo campaign records."""
    records = []
    for i in range(count):
        sent_at = (BASE_DATE + timedelta(days=i % 30)).isoformat()
        records.append(create_klaviyo_campaign(
            campaign_id=f"klaviyo_camp_{i:04d}",
            sent_at=sent_at,
        ))
    return records


def generate_klaviyo_events(count: int = 50) -> List[Dict]:
    """Generate Klaviyo event records."""
    records = []
    event_types = ["Opened Email", "Clicked Email", "Received Email", "Placed Order", "Added to Cart"]
    weights = [0.35, 0.20, 0.30, 0.05, 0.10]  # Relative frequency

    for i in range(count):
        event_type = random.choices(event_types, weights=weights)[0]
        timestamp = (BASE_DATE + timedelta(days=i % 30, hours=random.randint(0, 23))).isoformat()
        records.append(create_klaviyo_event(
            event_id=f"klaviyo_evt_{i:04d}",
            event_type=event_type,
            timestamp=timestamp,
        ))
    return records


# =============================================================================
# SMS Marketing Data Generators
# =============================================================================

def create_sms_event(
    platform: str,  # "attentive", "smsbump", or "postscript"
    event_id: Optional[str] = None,
    event_type: str = "delivered",
    timestamp: Optional[str] = None,
) -> Dict:
    """Create an SMS event record for any platform."""
    event_id = event_id or f"{platform}_evt_{uuid.uuid4().hex[:12]}"

    sms_campaign_names = [
        "Welcome SMS", "Cart Recovery", "Order Shipped",
        "Flash Sale Alert", "VIP Early Access", "Back in Stock",
        "Birthday Offer", "Review Request", "Loyalty Update",
        "Abandoned Browse", "Win-back Campaign"
    ]

    base_record = {
        "id": event_id,
        "event_type": event_type,
        "timestamp": timestamp or (BASE_DATE + timedelta(days=random.randint(0, 30), hours=random.randint(0, 23))).isoformat(),
        "campaign_id": f"{platform}_camp_{random.randint(1, 20):04d}",
        "campaign_name": random.choice(sms_campaign_names),
        "message_id": f"{platform}_msg_{uuid.uuid4().hex[:8]}",
        "phone_number": f"+1{random.randint(2000000000, 9999999999)}",
        "subscriber_id": f"{platform}_sub_{uuid.uuid4().hex[:8]}",
    }

    # Platform-specific fields
    if platform == "attentive":
        base_record.update({
            "company_id": "attentive_company_123",
            "subscriber": {
                "id": base_record["subscriber_id"],
                "phone": base_record["phone_number"],
                "email": f"customer-{uuid.uuid4().hex[:6]}@example.com",
                "created_at": (BASE_DATE - timedelta(days=random.randint(1, 90))).isoformat(),
            },
            "message": {
                "id": base_record["message_id"],
                "body": "Your exclusive offer is waiting! Shop now: https://shop.link/abc",
                "type": random.choice(["campaign", "journey", "transactional"]),
            },
            "links_clicked": random.randint(0, 3) if event_type == "clicked" else 0,
            "revenue_attributed": round(random.uniform(0, 150), 2) if event_type in ["clicked", "converted"] else 0,
        })

    elif platform == "smsbump":
        base_record.update({
            "shop_id": "smsbump_shop_123",
            "automation_id": f"auto_{random.randint(1, 10)}" if random.choice([True, False]) else None,
            "text": {
                "id": base_record["message_id"],
                "body": "Don't miss out! Use code SMS10 for 10% off. Shop: https://shop.link/xyz",
                "segments": random.randint(1, 3),
            },
            "cost": round(random.uniform(0.01, 0.05), 4),
            "country_code": "US",
            "carrier": random.choice(["verizon", "att", "tmobile", "sprint"]),
            "conversion": {
                "order_id": f"order_{random.randint(1000, 9999)}" if event_type == "converted" else None,
                "revenue": round(random.uniform(50, 200), 2) if event_type == "converted" else 0,
            } if event_type == "converted" else None,
        })

    elif platform == "postscript":
        base_record.update({
            "shop_id": "postscript_shop_123",
            "keyword_id": f"kw_{random.randint(1, 5)}" if random.choice([True, False]) else None,
            "automation_id": f"ps_auto_{random.randint(1, 15)}" if random.choice([True, False]) else None,
            "message": {
                "id": base_record["message_id"],
                "body": "Hey! Your cart is waiting. Complete your order: https://shop.link/cart",
                "media_url": None,
            },
            "cost_in_cents": random.randint(1, 5),
            "subscriber": {
                "id": base_record["subscriber_id"],
                "phone_number": base_record["phone_number"],
                "opted_in_at": (BASE_DATE - timedelta(days=random.randint(1, 180))).isoformat(),
                "source": random.choice(["checkout", "popup", "keyword", "import"]),
            },
            "attribution": {
                "order_id": f"ps_order_{random.randint(1000, 9999)}" if event_type == "converted" else None,
                "revenue": round(random.uniform(40, 180), 2) if event_type == "converted" else 0,
                "attributed_at": timestamp if event_type == "converted" else None,
            } if event_type == "converted" else None,
        })

    return base_record


def generate_attentive_events(count: int = 30) -> List[Dict]:
    """Generate Attentive SMS event records."""
    records = []
    event_types = ["sent", "delivered", "clicked", "converted", "unsubscribed", "failed"]
    weights = [0.25, 0.35, 0.20, 0.10, 0.05, 0.05]

    for i in range(count):
        event_type = random.choices(event_types, weights=weights)[0]
        timestamp = (BASE_DATE + timedelta(days=i % 30, hours=random.randint(0, 23))).isoformat()
        records.append(create_sms_event(
            platform="attentive",
            event_id=f"attentive_evt_{i:04d}",
            event_type=event_type,
            timestamp=timestamp,
        ))
    return records


def generate_smsbump_events(count: int = 30) -> List[Dict]:
    """Generate SMSBump event records."""
    records = []
    event_types = ["sent", "delivered", "clicked", "converted", "unsubscribed", "bounced"]
    weights = [0.25, 0.35, 0.18, 0.12, 0.05, 0.05]

    for i in range(count):
        event_type = random.choices(event_types, weights=weights)[0]
        timestamp = (BASE_DATE + timedelta(days=i % 30, hours=random.randint(0, 23))).isoformat()
        records.append(create_sms_event(
            platform="smsbump",
            event_id=f"smsbump_evt_{i:04d}",
            event_type=event_type,
            timestamp=timestamp,
        ))
    return records


def generate_postscript_events(count: int = 30) -> List[Dict]:
    """Generate Postscript SMS event records."""
    records = []
    event_types = ["sent", "delivered", "clicked", "converted", "opted_out", "failed"]
    weights = [0.25, 0.35, 0.20, 0.10, 0.05, 0.05]

    for i in range(count):
        event_type = random.choices(event_types, weights=weights)[0]
        timestamp = (BASE_DATE + timedelta(days=i % 30, hours=random.randint(0, 23))).isoformat()
        records.append(create_sms_event(
            platform="postscript",
            event_id=f"postscript_evt_{i:04d}",
            event_type=event_type,
            timestamp=timestamp,
        ))
    return records


# =============================================================================
# Complete Test Data Sets
# =============================================================================

# Generate all test data
SHOPIFY_PURCHASES = generate_shopify_purchases(30)
SHOPIFY_REFUNDS = generate_shopify_refunds(25)
SHOPIFY_CANCELLATIONS = generate_shopify_cancellations(20)

META_ADS = generate_meta_ads(30)
GOOGLE_ADS = generate_google_ads(30)
TIKTOK_ADS = generate_tiktok_ads(25)
SNAPCHAT_ADS = generate_snapchat_ads(25)

KLAVIYO_CAMPAIGNS = generate_klaviyo_campaigns(30)
KLAVIYO_EVENTS = generate_klaviyo_events(50)

ATTENTIVE_EVENTS = generate_attentive_events(30)
SMSBUMP_EVENTS = generate_smsbump_events(30)
POSTSCRIPT_EVENTS = generate_postscript_events(30)


TEST_DATA_SETS: Dict[str, Dict[str, List[Dict]]] = {
    # =========================================================================
    # Complete Shopify Test Data
    # =========================================================================
    "shopify_complete": {
        "_airbyte_raw_shopify_orders": SHOPIFY_PURCHASES + SHOPIFY_REFUNDS + SHOPIFY_CANCELLATIONS,
        "_airbyte_raw_shopify_customers": [
            create_shopify_customer(
                customer_id=f"gid://shopify/Customer/C{i:04d}",
                email=f"customer-{i:04d}@example.com",
                orders_count=random.randint(1, 10),
                total_spent=round(random.uniform(50, 1000), 2),
            )
            for i in range(50)
        ],
    },

    "shopify_purchases_only": {
        "_airbyte_raw_shopify_orders": SHOPIFY_PURCHASES,
        "_airbyte_raw_shopify_customers": [],
    },

    "shopify_refunds_only": {
        "_airbyte_raw_shopify_orders": SHOPIFY_REFUNDS,
        "_airbyte_raw_shopify_customers": [],
    },

    "shopify_cancellations_only": {
        "_airbyte_raw_shopify_orders": SHOPIFY_CANCELLATIONS,
        "_airbyte_raw_shopify_customers": [],
    },

    # =========================================================================
    # Ad Platform Test Data
    # =========================================================================
    "meta_ads_complete": {
        "_airbyte_raw_meta_ads": META_ADS,
    },

    "google_ads_complete": {
        "_airbyte_raw_google_ads": GOOGLE_ADS,
    },

    "tiktok_ads_complete": {
        "_airbyte_raw_tiktok_ads": TIKTOK_ADS,
    },

    "snapchat_ads_complete": {
        "_airbyte_raw_snapchat_ads": SNAPCHAT_ADS,
    },

    "all_ads_platforms": {
        "_airbyte_raw_meta_ads": META_ADS,
        "_airbyte_raw_google_ads": GOOGLE_ADS,
        "_airbyte_raw_tiktok_ads": TIKTOK_ADS,
        "_airbyte_raw_snapchat_ads": SNAPCHAT_ADS,
    },

    # =========================================================================
    # Email Marketing Test Data
    # =========================================================================
    "klaviyo_complete": {
        "_airbyte_raw_klaviyo_campaigns": KLAVIYO_CAMPAIGNS,
        "_airbyte_raw_klaviyo_events": KLAVIYO_EVENTS,
    },

    # =========================================================================
    # SMS Marketing Test Data
    # =========================================================================
    "attentive_complete": {
        "_airbyte_raw_attentive_events": ATTENTIVE_EVENTS,
    },

    "smsbump_complete": {
        "_airbyte_raw_smsbump_events": SMSBUMP_EVENTS,
    },

    "postscript_complete": {
        "_airbyte_raw_postscript_events": POSTSCRIPT_EVENTS,
    },

    "all_sms_platforms": {
        "_airbyte_raw_attentive_events": ATTENTIVE_EVENTS,
        "_airbyte_raw_smsbump_events": SMSBUMP_EVENTS,
        "_airbyte_raw_postscript_events": POSTSCRIPT_EVENTS,
    },

    # =========================================================================
    # Full E2E Test Data (All Channels)
    # =========================================================================
    "full_e2e_all_channels": {
        # Shopify
        "_airbyte_raw_shopify_orders": SHOPIFY_PURCHASES + SHOPIFY_REFUNDS + SHOPIFY_CANCELLATIONS,
        "_airbyte_raw_shopify_customers": [
            create_shopify_customer(
                customer_id=f"gid://shopify/Customer/C{i:04d}",
                email=f"customer-{i:04d}@example.com",
            )
            for i in range(50)
        ],
        # Ads
        "_airbyte_raw_meta_ads": META_ADS,
        "_airbyte_raw_google_ads": GOOGLE_ADS,
        "_airbyte_raw_tiktok_ads": TIKTOK_ADS,
        "_airbyte_raw_snapchat_ads": SNAPCHAT_ADS,
        # Email
        "_airbyte_raw_klaviyo_campaigns": KLAVIYO_CAMPAIGNS,
        "_airbyte_raw_klaviyo_events": KLAVIYO_EVENTS,
        # SMS
        "_airbyte_raw_attentive_events": ATTENTIVE_EVENTS,
        "_airbyte_raw_smsbump_events": SMSBUMP_EVENTS,
        "_airbyte_raw_postscript_events": POSTSCRIPT_EVENTS,
    },

    # =========================================================================
    # Empty Data (Edge Case)
    # =========================================================================
    "empty_store": {
        "_airbyte_raw_shopify_orders": [],
        "_airbyte_raw_shopify_customers": [],
    },
}


# =============================================================================
# Expected Outcomes for Test Validation
# =============================================================================

EXPECTED_OUTCOMES: Dict[str, Dict[str, Any]] = {
    "shopify_complete": {
        "total_orders": 75,  # 30 purchases + 25 refunds + 20 cancellations
        "purchase_count": 30,
        "refund_count": 25,
        "cancellation_count": 20,
        "customer_count": 50,
    },
    "shopify_purchases_only": {
        "order_count": 30,
        "financial_status_paid": 30,
    },
    "shopify_refunds_only": {
        "order_count": 25,
        "has_refunds": True,
    },
    "shopify_cancellations_only": {
        "order_count": 20,
        "has_cancellations": True,
    },
    "meta_ads_complete": {
        "record_count": 30,
        "has_spend": True,
        "has_conversions": True,
    },
    "google_ads_complete": {
        "record_count": 30,
        "has_cost": True,
        "has_conversions": True,
    },
    "tiktok_ads_complete": {
        "record_count": 25,
        "has_video_views": True,
    },
    "snapchat_ads_complete": {
        "record_count": 25,
        "has_swipes": True,
    },
    "klaviyo_complete": {
        "campaign_count": 30,
        "event_count": 50,
    },
    "attentive_complete": {
        "event_count": 30,
    },
    "smsbump_complete": {
        "event_count": 30,
    },
    "postscript_complete": {
        "event_count": 30,
    },
    "full_e2e_all_channels": {
        "shopify_orders": 75,
        "shopify_customers": 50,
        "meta_ads": 30,
        "google_ads": 30,
        "tiktok_ads": 25,
        "snapchat_ads": 25,
        "klaviyo_campaigns": 30,
        "klaviyo_events": 50,
        "attentive_events": 30,
        "smsbump_events": 30,
        "postscript_events": 30,
    },
}


# =============================================================================
# Test Data Provider Class
# =============================================================================

class TestDataProvider:
    """
    Provides test data for E2E testing with methods to access and customize.

    Usage:
        provider = TestDataProvider()

        # Get all Shopify data
        shopify_data = provider.get_scenario("shopify_complete")

        # Get specific channel data
        meta_ads = provider.get_channel_data("meta_ads")

        # Get data for API injection
        api_payload = provider.get_api_payload("shopify_ingestion", scenario="shopify_complete")
    """

    def __init__(self):
        self._custom_data: Dict[str, Dict] = {}

    def get_scenario(self, scenario: str) -> Dict[str, List[Dict]]:
        """Get all data for a specific test scenario."""
        if scenario in self._custom_data:
            return self._custom_data[scenario]
        return TEST_DATA_SETS.get(scenario, {})

    def get_channel_data(self, channel: str) -> List[Dict]:
        """Get data for a specific channel."""
        channel_mapping = {
            "shopify_orders": SHOPIFY_PURCHASES + SHOPIFY_REFUNDS + SHOPIFY_CANCELLATIONS,
            "shopify_purchases": SHOPIFY_PURCHASES,
            "shopify_refunds": SHOPIFY_REFUNDS,
            "shopify_cancellations": SHOPIFY_CANCELLATIONS,
            "meta_ads": META_ADS,
            "google_ads": GOOGLE_ADS,
            "tiktok_ads": TIKTOK_ADS,
            "snapchat_ads": SNAPCHAT_ADS,
            "klaviyo_campaigns": KLAVIYO_CAMPAIGNS,
            "klaviyo_events": KLAVIYO_EVENTS,
            "attentive": ATTENTIVE_EVENTS,
            "smsbump": SMSBUMP_EVENTS,
            "postscript": POSTSCRIPT_EVENTS,
        }
        return channel_mapping.get(channel, [])

    def get_expected_outcomes(self, scenario: str) -> Dict[str, Any]:
        """Get expected outcomes for a scenario (for assertions)."""
        return EXPECTED_OUTCOMES.get(scenario, {})

    def set_custom_scenario(self, scenario: str, data: Dict[str, List[Dict]]) -> None:
        """Set custom data for a scenario."""
        self._custom_data[scenario] = data

    def get_webhook_payloads(self, event_type: str, count: int = 5) -> List[Dict]:
        """
        Get webhook payloads for testing webhook endpoints.

        Args:
            event_type: Type of webhook (orders/create, orders/updated, app/uninstalled, etc.)
            count: Number of payloads to generate
        """
        if event_type == "orders/create":
            return [create_shopify_order() for _ in range(count)]
        elif event_type == "orders/updated":
            return [create_shopify_order(financial_status=random.choice(["paid", "refunded", "partially_refunded"])) for _ in range(count)]
        elif event_type == "app_subscriptions/update":
            return [
                {
                    "app_subscription": {
                        "admin_graphql_api_id": f"gid://shopify/AppSubscription/{uuid.uuid4().hex[:12]}",
                        "status": random.choice(["ACTIVE", "CANCELLED", "FROZEN"]),
                        "name": random.choice(["Free", "Growth", "Pro"]),
                        "current_period_end": (BASE_DATE + timedelta(days=30)).isoformat(),
                    }
                }
                for _ in range(count)
            ]
        return []

    @staticmethod
    def get_all_channels() -> List[str]:
        """Get list of all supported channels."""
        return [
            "shopify", "meta_ads", "google_ads", "tiktok_ads", "snapchat_ads",
            "klaviyo", "attentive", "smsbump", "postscript"
        ]
