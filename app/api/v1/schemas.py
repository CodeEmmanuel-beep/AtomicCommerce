from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    model_validator,
    field_validator,
    ValidationInfo,
)
from typing import Optional, List, TypeVar, Generic, Any
from datetime import datetime, date
from app.utils.supabase_url import get_public_url
from decimal import Decimal
from enum import Enum

T = TypeVar("T")


class LoginResponse(BaseModel):
    username: str
    password: str

    model_config = ConfigDict(from_attributes=True)


class PersonnelResponse(BaseModel):
    id: int
    profile_picture: str | None = None
    first_name: str
    middle_name: str | None = None
    surname: str
    phone_number: str | None = None
    email: str | None = None

    @field_validator("profile_picture", mode="before")
    @classmethod
    def render_picture(cls, value) -> str | None:
        if value:
            return get_public_url(value)

    model_config = ConfigDict(from_attributes=True)


class ProfileResponse(BaseModel):
    id: int
    profile_picture: str | None = None
    role: str = Field(default="user")
    first_name: str
    middle_name: str | None = None
    surname: str

    @field_validator("profile_picture", mode="before")
    @classmethod
    def render_picture(cls, value) -> str | None:
        if value:
            return get_public_url(value)

    model_config = ConfigDict(from_attributes=True)


class UserResponse(BaseModel):
    id: int
    profile_picture: str | None = None
    first_name: str
    middle_name: str | None = None
    surname: str
    username: str
    role: str = Field(default="user")
    phone_number: str | None = None
    email: str
    nationality: str
    address: str | None = None
    membership: List = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class NotificationResponse(BaseModel):
    id: int
    notification: str
    is_read: bool = Field(default=False)
    time_of_op: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StoreAccountResponse(BaseModel):
    bank_name: str
    account_type: str
    account_holder_name: str
    account_number: str
    type_of_id: str
    identification_number: str
    tax_identification_number: str | None = None
    verification_status: str = Field(default="pending")
    rejected_reason: str | None = None

    @model_validator(mode="before")
    @classmethod
    def decryption(cls, data: Any, info: ValidationInfo) -> Any:
        context = info.context
        if not context:
            raise ValueError("Validation context is missing. Cannot decrypt data.")
        cipher = context.get("cipher")
        if not cipher:
            raise ValueError("cipher key not found")
        sensitive_fields = [
            "account_number",
            "tax_identification_number",
            "identification_number",
        ]
        for field in sensitive_fields:
            value = (
                data.get(field, None)
                if isinstance(data, dict)
                else getattr(data, field, None)
            )
            if value is None:
                continue
            try:
                decrypted_field = cipher.decrypt(value).decode()
                if isinstance(data, dict):
                    data[field] = decrypted_field
                else:
                    setattr(data, field, decrypted_field)
            except Exception:
                raise ValueError("error decrypting sensitive field: %s", field)
        return data

    model_config = ConfigDict(from_attributes=True)


class AddressDetails(BaseModel):
    street: str
    city: str
    state: str
    country: str


class AddressResponse(BaseModel):
    id: int
    street: str
    city: str
    state: str
    country: str

    model_config = ConfigDict(from_attributes=True)


class ReactionType(str, Enum):
    like = "like"
    love = "love"
    laugh = "laugh"
    wow = "wow"
    sad = "sad"
    angry = "angry"


class ReactionsSummary(BaseModel):
    like: int = 0
    love: int = 0
    laugh: int = 0
    wow: int = 0
    sad: int = 0
    angry: int = 0


class PaginatedResponse(BaseModel):
    page: int
    limit: int
    total: int


class PaginatedMetadata(BaseModel, Generic[T]):
    items: List[T]
    pagination: PaginatedResponse


class StandardResponse(BaseModel, Generic[T]):
    status: str
    message: str
    data: Optional[T]


class ReplyResponse(BaseModel):
    id: int
    role: List[str] = Field(default_factory=list)
    edited: bool = Field(default=False)
    profile: ProfileResponse
    reply_reaction_count: int
    reactions: ReactionsSummary = Field(default_factory=ReactionsSummary)
    reply_text: str
    time_of_post: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class Reply(BaseModel):
    id: int | None = None
    product_id: int
    review_id: int
    reply_text: str


class Chat(BaseModel):
    customer: Optional[str] = Field(default_factory=str)
    customer_support: Optional[str] = Field(default_factory=str)
    message: str | None = None
    pics: str | None = None
    delivered: bool = Field(default=False)
    seen: bool = Field(default=False)
    time_of_chat: Optional[datetime]
    conversation_id: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ProductSize(str, Enum):
    small = "small"
    medium = "medium"
    large = "large"
    extra_large = "extra large"


class InventoryObj(BaseModel):
    stock_quantity: int

    model_config = ConfigDict(from_attributes=True)


class ProductImageResponse(BaseModel):
    id: int
    image: str

    @model_validator(mode="before")
    @classmethod
    def render_urls(cls, value: Any) -> Any:
        file = "image"
        if isinstance(value, dict):
            v = value.get(file, None)
        else:
            v = getattr(value, file, None)
        try:
            rendered = get_public_url(v)
            if isinstance(value, dict):
                value[file] = rendered
            else:
                setattr(value, file, rendered)
        except Exception as e:
            raise ValueError(
                f"could not render image url for field '{file}' with value '{v}': {e}"
            )
        return value

    model_config = ConfigDict(from_attributes=True)


class ProductInventoryResponse(BaseModel):
    id: int
    primary_image: str
    product_name: str

    @field_validator("primary_image", mode="before")
    @classmethod
    def full_url(cls, value) -> str | None:
        return get_public_url(value)

    model_config = ConfigDict(from_attributes=True)


class InventoryResponse(BaseModel):
    id: int
    product: ProductInventoryResponse
    stock_quantity: int
    last_updated: datetime

    model_config = ConfigDict(from_attributes=True)


class Cart_OrderProductResponse(BaseModel):
    id: int
    product_name: str
    primary_image: str
    product_price: Decimal

    @field_validator("primary_image", mode="before")
    @classmethod
    def full_url(cls, value) -> str | None:
        return get_public_url(value)

    model_config = ConfigDict(from_attributes=True)


class ProductRes(BaseModel):
    id: int
    product_name: str
    primary_image: str
    product_price: Decimal
    product_availability: str
    avg_rating: Decimal = Field(default=Decimal(str("0.00")))
    inventory: InventoryObj

    @field_validator("primary_image", mode="before")
    @classmethod
    def full_url(cls, value) -> str | None:
        return get_public_url(value)

    model_config = ConfigDict(from_attributes=True)


class ProductResponse(BaseModel):
    id: int
    product_name: str
    primary_image: str
    product_type: str
    product_price: Decimal
    avg_rating: Decimal = Field(default=Decimal(str("0.00")))
    review_count: int = Field(default=0)
    product_size: str
    product_description: str
    product_availability: str
    inventory: InventoryObj

    @field_validator("primary_image", mode="before")
    @classmethod
    def full_url(cls, value) -> str | None:
        return get_public_url(value)

    model_config = ConfigDict(from_attributes=True)


class PersonalStoreResponse(BaseModel):
    id: int
    business_logo: str | None = None
    store_photo: str | None = None
    store_name: str
    category_name: str
    sub_category: List[str]
    store_previous_name: str | None = None
    store_contact: str | None = None
    store_email: str | None = None
    avg_rating: Decimal = Field(default=Decimal(0))
    review_count: int = Field(default=0)
    motto: str | None = None
    tax_rate: float = Field(default=0)
    shipping_fee: Decimal
    store_description: str | None = None
    approved: bool = Field(default=False)
    founded: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class StoreResponse(BaseModel):
    id: int
    business_logo: str | None = None
    store_photo: str
    store_name: str
    category_name: str
    sub_category: List[str]
    store_previous_name: str | None = None
    store_contact: str | None = None
    store_email: str | None = None
    avg_rating: Decimal = Field(default=Decimal(str(("0.00"))))
    review_count: int = Field(default=0)
    motto: str | None = None
    featured_product: List[ProductRes] | ProductRes = Field(default_factory=list)
    shipping_fee: Decimal
    store_description: str | None = None
    approved: bool = Field(default=False)
    founded: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PaymentResponse(BaseModel):
    id: int
    name: List[str] = Field(default_factory=list)
    payment_method: str
    currency: str
    amount_paid: Decimal
    payment_status: str
    shipping_fee: float
    discount_amount: Decimal
    tax_amount: Decimal
    reference_id: str
    transaction_id: str | None = None
    payment_date: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class SubscriptionResponse(BaseModel):
    id: int
    membership_id: int
    plan_name: str
    price_id: str
    plan_price: Decimal
    status: str
    expire_at: datetime
    time_of_subscription: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductReviewResponse(BaseModel):
    id: int
    profile: ProfileResponse
    edited: bool = Field(default=False)
    review_text: str
    ratings: int
    product_reply_count: int = Field(default=0)
    review_reaction_count: int
    reactions: ReactionsSummary = Field(default_factory=ReactionsSummary)
    date_of_review: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class StoreReviewResponse(BaseModel):
    id: int
    profile: ProfileResponse
    edited: bool = Field(default=False)
    review_text: str
    ratings: int
    store_reply_count: int = Field(default=0)
    review_reaction_count: int
    reactions: ReactionsSummary = Field(default_factory=ReactionsSummary)
    reply: List[ReplyResponse] = Field(default_factory=list)
    date_of_review: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class Review(BaseModel):
    id: int | None = None
    product_id: int
    store_id: int
    review_text: str
    ratings: int
    date_of_review: Optional[datetime]


class CategoryResponse(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class SubCategoryResponse(BaseModel):
    id: int
    category_id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class CartItemReponse(BaseModel):
    id: int
    product: Cart_OrderProductResponse
    quantity: int

    model_config = ConfigDict(from_attributes=True)


class CartResponse(BaseModel, Generic[T]):
    id: int
    items: List[CartItemReponse] = Field(default_factory=list)
    total_quantity: float
    check_out: bool = Field(default=False)
    created_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class Orders(BaseModel):
    order_id: int
    product_id: int
    quantity: float
    price: float


class MemRes(BaseModel):
    membership_type: str

    model_config = ConfigDict(from_attributes=True)


class OrderItemRes(BaseModel):
    product: Cart_OrderProductResponse
    membership_type: List[MemRes] = Field(default_factory=list)
    quantity: float
    price: Decimal

    model_config = ConfigDict(from_attributes=True)


class OrderResponse(BaseModel):
    user: ProfileResponse
    id: int
    membership_type: List[MemRes] = Field(default_factory=list)
    tax_rate: float
    tax_amount: Decimal
    shipping_fee: Decimal
    total_quantity: float
    subtotal: Decimal
    total_amount: Decimal
    status: str
    delivery_address: list | None = None
    created_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class MembershipResponse(BaseModel):
    id: int
    profile: ProfileResponse
    membership_type: str
    is_active: bool = Field(default=False)
    period_of_membership: str = Field(default_factory=str)
    start_date: Optional[date]

    @computed_field
    def offer_status(self) -> str:
        if not self.is_active:
            return "must be an active member to receive a membership discount"
        discounts = {"Regular": "3%", "Standard": "5%", "Premium": "10%"}
        rate = discounts.get(self.membership_type, "0%")
        return f"{rate} membership discound"

    model_config = ConfigDict(from_attributes=True)


class MembershipRes(BaseModel):
    profile: ProfileResponse
    membership_type: str
    period_of_membership: str = Field(default_factory=str)
    start_date: Optional[date]
    pause_date: Optional[date] = None
    reativation_data: Optional[date] = None
    delete_date: Optional[date] = None

    model_config = ConfigDict(from_attributes=True)
