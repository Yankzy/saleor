from datetime import timedelta

import graphene
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django_countries.fields import Country

from ...core.exceptions import InsufficientStock
from ...reservation.error_codes import ReservationErrorCode
from ...reservation import models
from ...warehouse.availability import check_stock_quantity
from ...shipping.models import ShippingZone
from ..account.enums import CountryCodeEnum
from ..core.mutations import BaseMutation
from ..core.types.common import ReservationError
from ..product.types import ProductVariant
from .types import Reservation

RESERVATION_LENGTH = timedelta(minutes=10)
RESERVATION_SIZE_LIMIT = settings.MAX_CHECKOUT_LINE_QUANTITY


def _get_reservation_expiration() -> "datetime":
    return timezone.now() + RESERVATION_LENGTH


def check_reservation_quantity(user, product_variant, country_code, quantity):
    """Check if reservation for given quantity is allowed."""
    if quantity < 1:
        raise ValidationError(
            {
                "quantity": ValidationError(
                    "The quantity should be higher than zero.",
                    code=ReservationErrorCode.ZERO_QUANTITY,
                )
            }
        )
    if quantity > RESERVATION_SIZE_LIMIT:
        raise ValidationError(
            {
                "quantity": ValidationError(
                    "Cannot reserve more than %d times this item."
                    "" % RESERVATION_SIZE_LIMIT,
                    code=ReservationErrorCode.QUANTITY_GREATER_THAN_LIMIT,
                )
            }
        )

    try:
        check_stock_quantity(
            product_variant,
            country_code,
            quantity,
            user,
        )
    except InsufficientStock as e:
        remaining = e.context["available_quantity"]
        item_name = e.item.display_product()
        message = (
            f"Could not reserve item {item_name}. Only {remaining} remaining in stock."
        )
        raise ValidationError({"quantity": ValidationError(message, code=e.code)})


@transaction.atomic
def reserve_stock_for_user(user: "User", country_code: str, quantity: int, product_variant: "ProductVariant") -> "Reservation":
    """Reserve stock of given product variant for the user.

    Function lock for update all reservations for variant and user. Next, create or
    update quantity of existing reservation for the user.
    """
    reservation = (
        models.Reservation.objects.select_for_update(of=("self",))
        .filter(user=user, product_variant=product_variant)
        .first()
    )

    shipping_zone = ShippingZone.objects.filter(
        countries__contains=country_code
    ).values("pk")

    if reservation:
        reservation.shipping_zone = shipping_zone
        reservation.quantity = quantity
        reservation.expires = _get_reservation_expiration()
        reservation.save(update_fields=["shipping_zone", "quantity", "expires"])
    else:
        reservation = models.Reservation.objects.create(
            user=user,
            shipping_zone=shipping_zone,
            quantity=quantity,
            product_variant=product_variant,
            expires=_get_reservation_expiration(),
        )

    return reservation


class ReserveStock(BaseMutation):
    reservation = graphene.Field(
        Reservation, description="An reservation instance that was created or updated."
    )

    class Arguments:
        country_code = CountryCodeEnum(description="Country code.", required=True)
        quantity = graphene.Int(required=True, description="The number of items to reserve.")
        variant_id = graphene.ID(required=True, description="ID of the product variant.")

    class Meta:
        description = "Reserve the stock for authenticated user checkout."
        error_type_class = ReservationError
        error_type_field = "reservation_errors"

    @classmethod
    def check_permissions(cls, context):
        return context.user.is_authenticated

    @classmethod
    def perform_mutation(cls, root, info, **data):
        product_variant = cls.get_node_or_error(info, data["variant_id"], ProductVariant)
        check_reservation_quantity(info.context.user, product_variant, data["country_code"], data["quantity"])

        reservation = reserve_stock_for_user(
            info.context.user,
            data["country_code"],
            data["quantity"],
            product_variant
        )

        return ReserveStock(reservation=reservation)
