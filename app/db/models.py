from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, unique=True)
    full_name = Column(String, nullable=True)
    phone_number = Column(String, nullable=True)
    organization = Column(String, nullable=True)
    office_number = Column(String, nullable=True)
    registered = Column(Boolean, default=False)
    role = Column(String, default="user")

    requests = relationship("Request", back_populates="creator")

    def __repr__(self) -> str:
        return f"<User(id={self.id}, full_name='{self.full_name}', registered={self.registered})>"


class Request(Base):
    __tablename__ = "requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    request_type = Column(String)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    subcategory_id = Column(Integer, ForeignKey("subcategories.id"), nullable=True)
    description = Column(String)
    urgency = Column(String)
    due_date = Column(String, nullable=True)
    photo_file_id = Column(String, nullable=True)
    status = Column(String, default="Принято")
    assigned_admin_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime, nullable=True)
    admin_message_id = Column(Integer, nullable=True)
    comment = Column(String, nullable=True)
    attachment_type = Column(String, nullable=True)
    car_start_at = Column(DateTime, nullable=True)
    car_end_at = Column(DateTime, nullable=True)
    car_location = Column(String, nullable=True)
    planned_date = Column(DateTime, nullable=True)

    creator = relationship("User", back_populates="requests")
    category = relationship("Category")
    subcategory = relationship("Subcategory")

    def __repr__(self) -> str:
        return f"<Request(id={self.id}, type='{self.request_type}', status='{self.status}')>"


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True)
    request_count = Column(Integer, default=0)

    subcategories = relationship("Subcategory", back_populates="category", cascade="all, delete")

    def __repr__(self) -> str:
        return f"<Category(id={self.id}, name='{self.name}', requests={self.request_count})>"


class Subcategory(Base):
    __tablename__ = "subcategories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String)
    category_id = Column(Integer, ForeignKey("categories.id"))
    request_count = Column(Integer, default=0)

    category = relationship("Category", back_populates="subcategories")

    def __repr__(self) -> str:
        return (
            f"<Subcategory(id={self.id}, name='{self.name}', category_id={self.category_id}, "
            f"requests={self.request_count})>"
        )


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, unique=True)
    admin_type = Column(String)

    def __repr__(self) -> str:
        return f"<Admin(id={self.id}, type='{self.admin_type}')>"