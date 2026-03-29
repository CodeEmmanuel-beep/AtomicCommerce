from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    model_validator,
    ValidationInfo,
)
from typing import Optional, List, TypeVar, Generic, Any
from datetime import datetime, date
from app.utils.supabase_url import get_public_url
from decimal import Decimal
import orjson
from enum import Enum

T = TypeVar("T")


class LoginResponse(BaseModel):
    username: str
    password: str

    model_config = ConfigDict(from_attributes=True)


class ProfileResponse(BaseModel):
    id: int
    role: str = Field(default="user")
    name: str
    profile_picture: str

    model_config = ConfigDict(from_attributes=True)


class UserResponse(BaseModel):
    id: int
    profile_picture: str
    name: str
    username: str
    email: str
    nationality: str
    address: str

    model_config = ConfigDict(from_attributes=True)


class BusinessType(str, Enum):
    beauty_and_hair = "beauty and hair"
    skincare = "skincare"
    hair = "hair"
    electronics = "electronics"
    fashion = "fashion"
    kitchen_wares = "kitchen wares"
    groceries = "groceries"
    fruits_and_vegetables = "fruits and vegetables"
    footwear = "footwear"
    bags = "bags"
    luggages = "luggages"
    games = "games"
    computers = "computers"


class StoreObj(BaseModel):
    store_name: str
    owners: List[int]
    business_type: BusinessType
    store_email: str | None = None
    store_contact: str | None = None


class StoreUpdate(BaseModel):
    store_id: int
    store_name: str | None
    motto: str | None
    business_type: BusinessType | None
    store_description: str | None
    store_email: str | None = None
    store_contact: str | None = None


class StoreResponse(BaseModel):
    id: int
    business_logo: str
    store_photo: str
    store_name: str
    motto: str
    business_type: BusinessType
    approved: bool = Field(default=False)

    @computed_field
    def photo_upload(self) -> str | None:
        return get_public_url(self.store_photo)

    def logo_upload(self) -> str | None:
        if self.business_logo:
            return get_public_url(self.business_logo)
        return None

    model_config = ConfigDict(from_attributes=True)


class StoreAccountDetail(BaseModel):
    account_name: str
    account_number: str
    tax_identification_number: str
    identification_number: str


class StoreAccountResponse(BaseModel):
    account_name: str
    account_number: str
    tax_identification_number: str
    identification_number: str

    @model_validator(mode="before")
    @classmethod
    def decryption(cls, data: Any, info: ValidationInfo) -> Any:
        context = info.context
        if not context:
            raise ValueError("Validation context is missing. Cannot decrypt data.")
        cipher = info.context.get("cipher")
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
                raise ValueError(f"{field} is missing in the data for decryption.")
            try:
                decrypted_field = cipher.decrypt(value).decode()
                if isinstance(data, dict):
                    data[field] = decrypted_field
                else:
                    setattr(data, field, decrypted_field)
            except Exception:
                raise ValueError({"error decrypting sensitive fields"})
        return data

    model_config = ConfigDict(from_attributes=True)


class StoreAddressDetail(BaseModel):
    street: str
    city: str
    state: str
    country: str


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
    reply_text: str
    time_of_post: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class Reply(BaseModel):
    id: int | None = None
    product_id: int
    review_id: int
    reply_text: str


class Chat(BaseModel):
    customer: List[str] = Field(default_factory=list)
    customer_support: List[str] = Field(default_factory=list)
    message: str | None = None
    pics: str | None = None
    delivered: bool = Field(default=False)
    seen: bool = Field(default=False)
    time_of_chat: Optional[datetime]
    conversation_id: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ProductObj(BaseModel):
    product_name: str
    primary_image: str
    image: str
    product_price: float
    category_id: int
    product_availability: str


class ProductRes(BaseModel):
    id: int
    product_name: str
    primary_image: str = Field(exclude=True)
    product_price: Decimal

    @computed_field
    def full_url(self) -> str | None:
        return get_public_url(self.primary_image)

    model_config = ConfigDict(from_attributes=True)


class ProductResponse(BaseModel):
    id: int
    product_name: str
    primary_image: str = Field(exclude=True)
    image: str | None = Field(exclude=True)
    product_price: Decimal
    product_availability: str

    @computed_field
    def primary_image_url(self) -> str | None:
        return get_public_url(self.primary_image)

    @computed_field
    def image_urls(self) -> list[str]:
        if self.image and len(self.image) > 2:
            try:
                filenames = orjson.loads(self.image)
                return [
                    url
                    for f in filenames
                    if f and (url := get_public_url(f)) is not None
                ]
            except Exception:
                return []
        return []

    model_config = ConfigDict(from_attributes=True)


class PaymentResponse(BaseModel):
    id: int
    name: List[str] = Field(default_factory=list)
    payment_method: str
    amount_paid: float
    payment_status: str
    shipping_fee: float
    discount: float
    tax: float
    transaction_id: str
    payment_date: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class ProductReviewResponse(BaseModel):
    id: int
    profile: ProfileResponse
    edited: bool = Field(default=False)
    review_text: str
    ratings: int
    product_reply_count: int = Field(default=0)
    date_of_review: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class StoreReviewResponse(BaseModel):
    id: int
    profile: ProfileResponse
    edited: bool = Field(default=False)
    review_text: str
    ratings: int
    store_reply_count: int = Field(default=0)
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


class CartItems(BaseModel):
    cart_id: int
    product_id: int
    product_name: str = Field(default_factory=str)
    image: str = Field(default_factory=str)
    product_availability: str = Field(default_factory=str)
    quantity: int


class CartItemReponse(BaseModel):
    id: int
    product: ProductRes
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


class OrderItemRes(BaseModel):
    product: ProductRes
    membership_type: str = Field(default_factory=str)
    quantity: float
    price: float

    model_config = ConfigDict(from_attributes=True)


class MemRes(BaseModel):
    membership_type: str

    model_config = ConfigDict(from_attributes=True)


class OrderResponse(BaseModel, Generic[T]):
    profile: ProfileResponse
    membership_type: List[MemRes] = Field(default_factory=list)
    items: List[OrderItemRes] = Field(default_factory=list)
    total_quantity: float
    total_amount: float
    status: str = Field(default="pending")
    receipt: List[PaymentResponse] = Field(default_factory=list)
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
        if ~self.is_active:
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
