
from statistics import median

CONDITION_FACTORS = {
    "like_new": 1.10,
    "good": 1.00,
    "fair": 0.80,
    "poor": 0.60,
}


def estimate_resale_price(
    original_price,
    age_years,
    condition,
    comparable_prices=None,
):
    """Estimate a resale price using comparable listings or depreciation."""

    condition = condition.strip().lower()

    if condition not in CONDITION_FACTORS:
        raise ValueError("Please select a valid product condition.")

    if original_price is None or original_price <= 0:
        raise ValueError("Original price must be greater than zero.")

    if age_years < 0 or age_years > 50:
        raise ValueError("Product age must be between 0 and 50 years.")

    prices = [
        float(price)
        for price in (comparable_prices or [])
        if price is not None and float(price) > 0
    ]

    if len(prices) >= 3:
        base_price = median(prices)
        estimated_price = base_price * CONDITION_FACTORS[condition]
        method = "Comparable listings"
    else:
        age_factor = 0.85 ** age_years
        condition_factor = CONDITION_FACTORS[condition]

        estimated_price = (
            original_price * age_factor * condition_factor
        )
        method = "Depreciation estimate"

    estimated_price = max(0, round(estimated_price / 100) * 100)

    return {
        "estimated_price": estimated_price,
        "method": method,
    }