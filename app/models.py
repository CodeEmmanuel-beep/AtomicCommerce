from sqlalchemy import (
    Column,
    DateTime,
    String,
    Integer,
    Float,
    ForeignKey,
    Boolean,
    Date,
    Numeric,
    UniqueConstraint,
    Table,
    Enum as SQLEnum,
    LargeBinary,
    CheckConstraint,
    Text,
)
from typing import Optional
from sqlalchemy.dialects.postgresql import JSONB
from enum import Enum
from sqlalchemy.orm import relationship, mapped_column, Mapped, declarative_base
from sqlalchemy import func
from decimal import Decimal
from datetime import datetime

Base = declarative_base()

store_staffs = Table(
    "store_staffs",
    Base.metadata,
    Column("users_id", ForeignKey("user.id"), primary_key=True, index=True),
    Column("stores_id", ForeignKey("store.id"), primary_key=True, index=True),
)
store_owners = Table(
    "store_owners",
    Base.metadata,
    Column("users_id", ForeignKey("user.id"), primary_key=True, index=True),
    Column("stores_id", ForeignKey("store.id"), primary_key=True, index=True),
)


class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    first_name: Mapped[str] = mapped_column(String, index=True)
    middle_name: Mapped[str] = mapped_column(String, nullable=True)
    surname: Mapped[str] = mapped_column(String, index=True)
    username: Mapped[str] = mapped_column(String, index=True)
    password: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[str] = mapped_column(String, default="user", index=True)
    email: Mapped[str] = mapped_column(String)
    nationality: Mapped[str] = mapped_column(String)
    profile_picture: Mapped[str] = mapped_column(String, nullable=True)
    phone_number: Mapped[str] = mapped_column(String, nullable=True)
    address: Mapped[str] = mapped_column(String, nullable=True)

    payments = relationship("Payment", back_populates="user")
    membership = relationship("Membership", back_populates="user")
    reviews = relationship("Review", back_populates="user")
    replies = relationship("Reply", back_populates="user")
    orders = relationship("Order", back_populates="user")
    messages = relationship("Messaging", back_populates="user")
    carts = relationship("Cart", back_populates="user")
    owners = relationship("Store", secondary=store_owners, back_populates="user_owners")
    staffs = relationship("Store", secondary=store_staffs, back_populates="user_staffs")
    reacts = relationship("React", back_populates="user")
    refunds = relationship("Refund", back_populates="user")
    created_tickets = relationship(
        "Ticket", foreign_keys="[Ticket.user_id]", back_populates="creator"
    )
    assigned_tickets = relationship(
        "Ticket", foreign_keys="[Ticket.assigned_to]", back_populates="agent"
    )


class Messaging(Base):
    __tablename__ = "message"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user.id"), index=True)
    ticket_id = Column(Integer, ForeignKey("ticket.id"), index=True)
    support_id = Column(Integer, index=True)
    customer_id = Column(Integer, index=True)
    message = Column(String, nullable=True)
    pics = Column(String, nullable=True)
    delivered = Column(Boolean, default=False)
    seen = Column(Boolean, default=False)
    sender_deleted = Column(Boolean, default=False, index=True)
    receiver_deleted = Column(Boolean, default=False, index=True)
    time_of_chat = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="messages")
    ticket = relationship("Ticket", back_populates="messages")


class TicketStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    closed = "closed"


class Ticket(Base):
    __tablename__ = "ticket"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TicketStatus] = mapped_column(
        SQLEnum(TicketStatus), default=TicketStatus.open.value, index=True
    )
    assigned_to: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id"), nullable=True, index=True
    )
    updated_at = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    creator = relationship(
        "User", foreign_keys=[user_id], back_populates="created_tickets"
    )

    agent = relationship(
        "User", foreign_keys=[assigned_to], back_populates="assigned_tickets"
    )
    messages = relationship("Messaging", back_populates="ticket")


class Store(Base):
    __tablename__ = "store"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    business_logo: Mapped[str] = mapped_column(String, nullable=True)
    store_photo: Mapped[str] = mapped_column(String, nullable=False)
    store_name: Mapped[str] = mapped_column(String, unique=True, index=True)
    motto: Mapped[str] = mapped_column(String, nullable=True)
    edited_name: Mapped[bool] = mapped_column(Boolean, default=False)
    store_previous_name: Mapped[str] = mapped_column(String, nullable=True)
    store_description: Mapped[str] = mapped_column(String, nullable=True)
    slug: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    category_name: Mapped[str] = mapped_column(String, index=True)
    sub_category: Mapped[list] = mapped_column(JSONB, index=True)
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("category.id"), index=True
    )
    avg_rating: Mapped[Decimal] = mapped_column(
        Numeric(precision=3, scale=2), default=0
    )
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    store_email: Mapped[str] = mapped_column(String, nullable=True)
    shipping_fee: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=2), default=0
    )
    tax_rate: Mapped[float] = mapped_column(Float, default=0)
    store_contact: Mapped[str] = mapped_column(String, nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    founded: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    user_owners = relationship("User", secondary=store_owners, back_populates="owners")
    user_staffs = relationship("User", secondary=store_staffs, back_populates="staffs")
    category = relationship("Category", back_populates="stores")
    review = relationship("Review", back_populates="store")
    replies = relationship("Reply", back_populates="store")
    addresses = relationship("Address", back_populates="store")
    order = relationship("Order", back_populates="store", uselist=False)
    account = relationship("StoreAccount", back_populates="store")
    products = relationship("Product", back_populates="store")
    inventories = relationship("Inventory", back_populates="store")
    carts = relationship("Cart", back_populates="store")
    membership = relationship("Membership", back_populates="store")
    product_images = relationship("ProductImage", back_populates="store")


class Address(Base):
    __tablename__ = "address"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("store.id"), index=True)
    street: Mapped[str] = mapped_column(String, nullable=False)
    city: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    country: Mapped[str] = mapped_column(String, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    store = relationship("Store", back_populates="addresses")
    orders = relationship("Order", back_populates="address")


class IdType(str, Enum):
    voter_id = "voter_id"
    national_id = "national_id"
    driver_license = "driver_license"
    other_id = "other_id"


class AccountType(str, Enum):
    savings = "savings"
    current = "current"
    business = "business"


class AccountVerification(str, Enum):
    pending = "pending"
    verified = "verified"
    rejected = "rejected"


class StoreAccount(Base):
    __tablename__ = "store_account"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    store_id: Mapped[int] = mapped_column(Integer, ForeignKey("store.id"), index=True)
    bank_name: Mapped[str] = mapped_column(String, nullable=False)
    account_holder_name: Mapped[str] = mapped_column(String, nullable=False)
    account_type: Mapped[AccountType] = mapped_column(
        SQLEnum(AccountType), default=AccountType.savings, nullable=False
    )
    type_of_id: Mapped[IdType] = mapped_column(
        SQLEnum(IdType), default=IdType.national_id, nullable=False
    )
    account_number: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    tax_identification_number: Mapped[bytes] = mapped_column(LargeBinary, nullable=True)
    identification_number: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    verification_status: Mapped[AccountVerification] = mapped_column(
        SQLEnum(AccountVerification), default=AccountVerification.pending, index=True
    )
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_reason: Mapped[str] = mapped_column(String, nullable=True)
    previous_rejected_reason: Mapped[str] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("store_id", name="unique_store_account"),
        CheckConstraint(
            "(rejected_reason IS NULL) OR (verification_status = 'rejected')",
            name="rejection_reason_check",
        ),
        CheckConstraint(
            "(verification_status != 'verified') OR (verified_at IS NOT NULL)",
            name="verified_account_timestamp_check",
        ),
    )
    store = relationship("Store", back_populates="account")


class Reply(Base):
    __tablename__ = "reply"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user.id"), index=True)
    edited = Column(Boolean, default=False)
    review_id = Column(Integer, ForeignKey("review.id", ondelete="CASCADE"), index=True)
    product_id = Column(Integer, ForeignKey("product.id"), index=True)
    store_id = Column(Integer, ForeignKey("store.id"), index=True)
    reply_text = Column(String)
    product_reply_reaction_count: Mapped[int] = mapped_column(Integer, default=0)
    store_reply_reaction_count: Mapped[int] = mapped_column(Integer, default=0)
    time_of_post = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="replies")
    review = relationship("Review", back_populates="replies")
    product = relationship("Product", back_populates="replies")
    store = relationship("Store", back_populates="replies")
    react = relationship("React", back_populates="reply")


class ProductSize(str, Enum):
    small = "small"
    medium = "medium"
    large = "large"
    extra_large = "extra_large"


class Product(Base):
    __tablename__ = "product"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    store_id: Mapped[int] = mapped_column(Integer, ForeignKey("store.id"), index=True)
    product_name: Mapped[str] = mapped_column(String, index=True)
    primary_image: Mapped[str] = mapped_column(String, nullable=False)
    product_price: Mapped[Decimal] = mapped_column(Numeric(precision=12, scale=2))
    product_type: Mapped[str] = mapped_column(String)
    avg_rating: Mapped[Decimal] = mapped_column(
        Numeric(precision=3, scale=2), default=0
    )
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    product_description: Mapped[str] = mapped_column(Text)
    product_size: Mapped[ProductSize] = mapped_column(
        SQLEnum(ProductSize), default=ProductSize.small, index=True
    )
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("category.id"), index=True
    )
    sub_category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("subcategory.id"), index=True
    )
    product_availability: Mapped[str] = mapped_column(String, default="available")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    orderitem = relationship("OrderItem", back_populates="product", uselist=False)
    store = relationship("Store", back_populates="products")
    review = relationship("Review", back_populates="product")
    replies = relationship("Reply", back_populates="product")
    cartitems = relationship("CartItem", back_populates="product", uselist=False)
    category = relationship("Category", back_populates="products")
    inventory = relationship("Inventory", back_populates="product", uselist=False)
    sub_category = relationship("SubCategory", back_populates="products")
    product_images = relationship("ProductImage", back_populates="product")


class ProductImage(Base):
    __tablename__ = "product_image"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    store_id: Mapped[int] = mapped_column(Integer, ForeignKey("store.id"), index=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("product.id"), index=True
    )
    image: Mapped[str] = mapped_column(String, nullable=False)

    product = relationship("Product", back_populates="product_images")
    store = relationship("Store", back_populates="product_images")


class Inventory(Base):
    __tablename__ = "inventory"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("product.id"), index=True
    )
    store_id: Mapped[int] = mapped_column(Integer, ForeignKey("store.id"), index=True)
    stock_quantity: Mapped[int] = mapped_column(Integer, default=0)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("store_id", "product_id", name="store_product_inventory"),
        CheckConstraint("stock_quantity >= 0", name="positive_quantity"),
    )
    product = relationship("Product", back_populates="inventory")
    store = relationship("Store", back_populates="inventories")


class PaymentStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    REFUNDED = "refunded"


class Payment(Base):
    __tablename__ = "payment"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), index=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("order.id"), index=True)
    payment_method: Mapped[str] = mapped_column(String)
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(precision=10, scale=2))
    payment_status: Mapped[PaymentStatus] = mapped_column(
        SQLEnum(PaymentStatus), default=PaymentStatus.PENDING.value, index=True
    )
    reference_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    transaction_id: Mapped[str] = mapped_column(String, index=True)
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=2), default=0
    )
    shipping_fee: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=2), default=0
    )
    tax_rate: Mapped[float] = mapped_column(Float, default=0)
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=0
    )
    payment_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_event_id: Mapped[str] = mapped_column(String, index=True)

    user = relationship("User", back_populates="payments")
    order = relationship("Order", back_populates="payment", uselist=False)
    refunds = relationship("Refund", back_populates="payment")


class Refund(Base):
    __tablename__ = "refund"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), index=True)
    payment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("payment.id"), index=True
    )
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("order.id"), index=True)
    refund_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    refund_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=2), default=0
    )
    refund_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_event_id: Mapped[str] = mapped_column(String, index=True)

    user = relationship("User", back_populates="refunds")
    order = relationship("Order", back_populates="refunds")
    payment = relationship("Payment", back_populates="refunds")


class Membership(Base):
    __tablename__ = "membership"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user.id"), index=True)
    store_id = Column(Integer, ForeignKey("store.id"), index=True)
    membership_type = Column(String, index=True)
    is_active = Column(Boolean, default=False, index=True)
    is_deleted = Column(Boolean, default=False, index=True)
    is_pause = Column(Boolean, default=False, index=True)
    pause_date = Column(Date)
    delete_date = Column(Date)
    reactivation_date = Column(Date)
    start_date = Column(Date, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "store_id", name="user_store_membership"),
    )
    user = relationship("User", back_populates="membership")
    orders = relationship("Order", back_populates="membership")
    store = relationship("Store", back_populates="membership")
    carts = relationship(
        "Cart", back_populates="membership", cascade="all, delete-orphan"
    )
    subscriptions = relationship("Subscription", back_populates="membership")


class SubscriptionPlan(str, Enum):
    Standard = "Standard"
    Premium = "Premium"
    Regular = "Regular"


class Subscription(Base):
    __tablename__ = "subscription"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    membership_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("membership.id"), index=True
    )
    plan_name: Mapped[SubscriptionPlan] = mapped_column(
        SQLEnum(SubscriptionPlan),
        default=SubscriptionPlan.Standard,
        index=True,
    )
    price_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    plan_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=10, scale=2), nullable=True
    )
    status: Mapped[str] = mapped_column(String, index=True)
    customer_id: Mapped[str] = mapped_column(String)
    reference_id: Mapped[str] = mapped_column(String, index=True)
    last_event_id: Mapped[str] = mapped_column(String, index=True)
    last_event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    time_of_subscription: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    membership = relationship("Membership", back_populates="subscriptions")


class Notification(Base):
    __tablename__ = "notification"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    notification: Mapped[str] = mapped_column(String)
    from_user: Mapped[int] = mapped_column(Integer, index=True)
    notified_user: Mapped[int] = mapped_column(Integer, index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    time_of_op: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Review(Base):
    __tablename__ = "review"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user.id"), index=True)
    product_id = Column(Integer, ForeignKey("product.id"), index=True)
    store_id = Column(Integer, ForeignKey("store.id"), index=True)
    review_text = Column(String)
    ratings = Column(Integer)
    product_reply_count: Mapped[int] = mapped_column(Integer, default=0)
    store_reply_count: Mapped[int] = mapped_column(Integer, default=0)
    product_review_reaction_count: Mapped[int] = mapped_column(Integer, default=0)
    store_review_reaction_count: Mapped[int] = mapped_column(Integer, default=0)
    edited = Column(Boolean, default=False)
    time_of_post = Column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="user_product_review"),
        UniqueConstraint("user_id", "store_id", name="user_store_review"),
    )
    user = relationship("User", back_populates="reviews")
    product = relationship("Product", back_populates="review")
    store = relationship("Store", back_populates="review")
    replies = relationship(
        "Reply", back_populates="review", cascade="all, delete-orphan"
    )
    react = relationship("React", back_populates="review")


class ReactionType(str, Enum):
    like = "like"
    love = "love"
    wow = "wow"
    laugh = "laugh"
    sad = "sad"
    angry = "angry"


class React(Base):
    __tablename__ = "react"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    type: Mapped[ReactionType] = mapped_column(SQLEnum(ReactionType), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), index=True)
    reply_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("reply.id", ondelete="CASCADE"),
        index=True,
    )
    review_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("review.id", ondelete="CASCADE"),
        index=True,
    )
    time_of_reaction: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), index=True
    )

    __table_args__ = (
        UniqueConstraint("user_id", "reply_id", name="unique_reply_react"),
        UniqueConstraint("user_id", "review_id", name="unique_review_react"),
        CheckConstraint(
            "(reply_id IS NULL AND review_id IS NOT NULL) OR (reply_id IS NOT NULL AND review_id IS NULL)",
            name="exactly_one_parent",
        ),
    )
    reply = relationship("Reply", back_populates="react")
    review = relationship("Review", back_populates="react")
    user = relationship("User", back_populates="reacts")


class Category(Base):
    __tablename__ = "category"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    products = relationship("Product", back_populates="category")
    stores = relationship("Store", back_populates="category")
    sub_categories = relationship("SubCategory", back_populates="category")


class SubCategory(Base):
    __tablename__ = "subcategory"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("category.id"), index=True
    )
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    products = relationship("Product", back_populates="sub_category")
    category = relationship("Category", back_populates="sub_categories")


class CartItem(Base):
    __tablename__ = "cartitem"
    id = Column(Integer, primary_key=True, index=True)
    cart_id = Column(Integer, ForeignKey("cart.id", ondelete="CASCADE"), index=True)
    quantity = Column(Float, default=1)
    product_id = Column(Integer, ForeignKey("product.id"), index=True)

    product = relationship("Product", back_populates="cartitems")
    cart = relationship("Cart", back_populates="cartitems")
    orderitem = relationship("OrderItem", back_populates="cartitem", uselist=False)


class Cart(Base):
    __tablename__ = "cart"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user.id"), index=True)
    store_id = Column(Integer, ForeignKey("store.id"), index=True)
    member_id = Column(
        Integer, ForeignKey("membership.id", ondelete="CASCADE"), index=True
    )
    check_out: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    total_quantity = Column(Float, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    user = relationship("User", back_populates="carts")
    store = relationship("Store", back_populates="carts")
    cartitems = relationship(
        "CartItem", back_populates="cart", cascade="all, delete-orphan"
    )
    membership = relationship("Membership", back_populates="carts")


class OrderStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    shipped = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"


class Order(Base):
    __tablename__ = "order"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), index=True)
    store_id: Mapped[int] = mapped_column(Integer, ForeignKey("store.id"), index=True)
    delivery_address_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("address.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    member_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("membership.id"), index=True, nullable=True
    )
    total_quantity: Mapped[float] = mapped_column(Float, default=0)
    delivery_address: Mapped[dict] = mapped_column(JSONB, nullable=True)
    order_delete: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[OrderStatus] = mapped_column(
        SQLEnum(OrderStatus),
        default=OrderStatus.pending.value,
        nullable=False,
        index=True,
    )
    check_out: Mapped[bool] = mapped_column(Boolean, default=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(precision=12, scale=2), default=0)
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=0
    )
    tax_rate: Mapped[float] = mapped_column(Float, default=0)
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=0
    )
    shipping_fee: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=0
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=0
    )
    reference_id: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=True
    )
    re_order_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )

    payment = relationship("Payment", back_populates="order", uselist=False)
    refunds = relationship("Refund", back_populates="order")
    user = relationship("User", back_populates="orders")
    orderitems = relationship("OrderItem", back_populates="order")
    membership = relationship("Membership", back_populates="orders")
    store = relationship("Store", back_populates="order", uselist=False)
    address = relationship("Address", back_populates="orders")


class OrderItem(Base):
    __tablename__ = "orderitem"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("order.id"), index=True)
    cartitem_id = Column(Integer, ForeignKey("cartitem.id"), index=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("product.id"), index=True
    )
    quantity = Column(Float, default=1)
    price = Column(Numeric(precision=12, scale=2))

    product = relationship("Product", back_populates="orderitem")
    order = relationship("Order", back_populates="orderitems")
    cartitem = relationship("CartItem", back_populates="orderitem")
