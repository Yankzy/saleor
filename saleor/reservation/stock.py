from collections import defaultdict
from typing import TYPE_CHECKING, Iterable, Optional

from .models import Reservation

if TYPE_CHECKING:
    from ..account.models import User
    from ..product.models import ProductVariant


def remove_user_reservations(
    user: "User", product_variants: Iterable["ProductVariant"]
):
    """Remove reservation of products for given user

    Function removes reservations of user and product variant combinations.
    """
    Reservation.objects.filter(user=user, product_variant__in=product_variants).delete()


def get_reserved_quantity_bulk(
    variants: Iterable["ProductVariant"],
    country_code: str,
    exclude_user: Optional["User"] = None
):
    reservations = (
        Reservation.objects
        .filter(product_variant__in=variants)
        .for_country(country_code)
        .exclude_user(exclude_user)
        .active()
        .order_by("product_variant_id")
        .values("product_variant_id")
        .annotate_total_quantity()
    )

    variant_reservations = defaultdict(int)
    for reservation in reservations:
        variant_reservations[reservation["product_variant_id"]] = reservation["total_quantity"]

    return variant_reservations


def get_reserved_quantity(
    product_variant: "ProductVariant",
    country_code: str,
    exclude_user: Optional["User"] = None
) -> int:
    reservations = (
        Reservation.objects
        .filter(product_variant=product_variant)
        .for_country(country_code)
        .exclude_user(exclude_user)
        .active()
        .values("product_variant_id")
        .annotate_total_quantity()
    )

    if not reservations:
        return 0

    return reservations[0]["total_quantity"]
