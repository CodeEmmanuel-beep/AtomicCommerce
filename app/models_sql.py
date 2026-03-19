from app.database.d_base import Base
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
)
from enum import Enum
from sqlalchemy.orm import relationship, mapped_column, Mapped
from sqlalchemy import func
from datetime import datetime

store_staffs = Table(
    "store_staffs",
    Base.metadata,
    Column("users_id", ForeignKey("users.id"), primary_key=True, index=True),
    Column("stores_id", ForeignKey("stores.id"), primary_key=True, index=True),
)
store_owners = Table(
    "store_owners",
    Base.metadata,
    Column("users_id", ForeignKey("users.id"), primary_key=True, index=True),
    Column("stores_id", ForeignKey("stores.id"), primary_key=True, index=True),
)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    username = Column(String, index=True)
    password = Column(String)
    is_active = Column(Boolean, default=True)
    role = Column(String, default="user", index=True)
    email = Column(String)
    nationality = Column(String)
    profile_picture = Column(String, nullable=True)
    address = Column(String)

    payments = relationship("Payment", back_populates="user")
    membership = relationship("Membership", back_populates="user")
    reviews = relationship("Review", back_populates="user")
    replies = relationship("Reply", back_populates="user")
    orders = relationship("Order", back_populates="user")
    carts = relationship("Cart", back_populates="user")
    owners = relationship("Store", secondary=store_owners, back_populates="user_owners")
    staffs = relationship("Store", secondary=store_staffs, back_populates="user_staffs")


class Messaging(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    identifier = Column(Integer, index=True)
    customer_id = Column(Integer, index=True)
    message = Column(String, nullable=True)
    pics = Column(String, nullable=True)
    delivered = Column(Boolean, default=False)
    seen = Column(Boolean, default=False)
    sender_deleted = Column(Boolean, default=False, index=True)
    receiver_deleted = Column(Boolean, default=False, index=True)
    time_of_chat = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="messages")


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


class Store(Base):
    __tablename__ = "stores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    store_photo: Mapped[str] = mapped_column(String)
    store_name: Mapped[str] = mapped_column(String, unique=True)
    business_type: Mapped[BusinessType] = mapped_column(SQLEnum(BusinessType))
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id"), index=True
    )
    store_email: Mapped[str] = mapped_column(String, nullable=True)
    store_contact: Mapped[str] = mapped_column(String, nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    founded: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user_owners = relationship("User", secondary=store_owners, back_populates="owners")
    user_staffs = relationship("User", secondary=store_staffs, back_populates="staffs")
    category = relationship("Category", back_populates="stores")
    review = relationship("Review", back_populates="store")
    replies = relationship("Reply", back_populates="store")
    addresses = relationship("StoreAddress", back_populates="store")


class StoreAddress(Base):
    __tablename__ = "store_addresses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    address: Mapped[str] = mapped_column(String)

    store = relationship("Store", back_populates="addresses")


class Reply(Base):
    __tablename__ = "replies"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    edited = Column(Boolean, default=False)
    review_id = Column(
        Integer, ForeignKey("reviews.id", ondelete="CASCADE"), index=True
    )
    product_id = Column(Integer, ForeignKey("products.id"), index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), index=True)
    reply_text = Column(String)
    time_of_post = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="replies")
    review = relationship("Review", back_populates="replies")
    product = relationship("Product", back_populates="replies")
    store = relationship("Store", back_populates="replies")


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    product_name = Column(String)
    primary_image = Column(String, nullable=False)
    image = Column(String, nullable=True)
    product_price = Column(Numeric(precision=12, scale=2))
    category_id = Column(Integer, ForeignKey("categories.id"), index=True)
    product_availability = Column(String, default="available")
    stock_quantity = Column(Integer, default=0)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    review = relationship("Review", back_populates="product")
    replies = relationship("Reply", back_populates="product")
    cart = relationship("Cart", back_populates="product")
    category = relationship("Category", back_populates="products")
    orderitems = relationship("OrderItem", back_populates="product")


class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), index=True)
    payment_method = Column(String)
    amount_paid = Column(Float)
    payment_status = Column(String, default="pending", index=True)
    shipping_fee = Column(Float)
    discount = Column(Integer)
    tax = Column(Integer)
    transaction_id = Column(String)
    payment_date = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="payments")
    order = relationship("Order", back_populates="payment", uselist=False)


class Membership(Base):
    __tablename__ = "memberships"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True)
    membership_type = Column(String, index=True)
    is_active = Column(Boolean, default=False, index=True)
    is_deleted = Column(Boolean, default=False, index=True)
    is_pause = Column(Boolean, default=False, index=True)
    pause_date = Column(Date)
    delete_date = Column(Date)
    reactivation_date = Column(Date)
    start_date = Column(Date, server_default=func.now())

    user = relationship("User", back_populates="membership")
    orders = relationship(
        "Order", back_populates="membership", cascade="all, delete-orphan"
    )
    carts = relationship(
        "Cart", back_populates="membership", cascade="all, delete-orphan"
    )


class Review(Base):
    __tablename__ = "reviews"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    product_id = Column(Integer, ForeignKey("products.id"), index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), index=True)
    review_text = Column(String)
    ratings = Column(Integer)
    product_reply_count: Mapped[int] = mapped_column(Integer, default=0)
    store_reply_count: Mapped[int] = mapped_column(Integer, default=0)
    edited = Column(Boolean, default=False)
    date_of_review = Column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="user_product_review"),
    )
    __table_args__ = (
        UniqueConstraint("user_id", "store_id", name="user_store_review"),
    )
    user = relationship("User", back_populates="reviews")
    product = relationship("Product", back_populates="review")
    store = relationship("Store", back_populates="review")
    reply = relationship("Reply", back_populates="review", cascade="all, delete-orphan")


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True)

    products = relationship("Product", back_populates="category")
    stores = relationship("Store", back_populates="category")


class CartItem(Base):
    __tablename__ = "cartitems"
    id = Column(Integer, primary_key=True, index=True)
    cart_id = Column(Integer, ForeignKey("carts.id", ondelete="CASCADE"), index=True)
    quantity = Column(Float, default=1)
    product_id = Column(Integer, ForeignKey("products.id"), index=True)

    product = relationship("Product", back_populates="cart")
    cart = relationship("Cart", back_populates="cartitems")
    orderitems = relationship(
        "OrderItem", back_populates="cartitems", cascade="all, delete-orphan"
    )


class Cart(Base):
    __tablename__ = "carts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    member_id = Column(Integer, ForeignKey("memberships.id", ondelete="CASCADE"))
    check_out: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    total_quantity = Column(Float, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    user = relationship("User", back_populates="carts")
    cartitems = relationship(
        "CartItem", back_populates="cart", cascade="all, delete-orphan"
    )
    membership = relationship("Membership", back_populates="carts")


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    member = Column(
        Integer, ForeignKey("memberships.id", ondelete="CASCADE"), index=True
    )
    total_quantity = Column(Float, default=0)
    order_delete = Column(Boolean, default=False)
    status = Column(String, default="pending", index=True)
    total_amount = Column(Numeric(precision=12, scale=2), default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    payment = relationship("Payment", back_populates="order", uselist=False)
    user = relationship("User", back_populates="orders")
    orderitems = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )
    membership = relationship("Membership", back_populates="orders")


class OrderItem(Base):
    __tablename__ = "orderitems"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    cart_items = Column(
        Integer, ForeignKey("cartitems.id", ondelete="CASCADE"), index=True
    )
    quantity = Column(Float, default=1)
    price = Column(Numeric(precision=12, scale=2))

    order = relationship("Order", back_populates="orderitems")
    cartitems = relationship("CartItem", back_populates="orderitems")
