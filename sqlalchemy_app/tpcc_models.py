"""
TPC-C Database Schema as SQLAlchemy Models
Implements the 9-table TPC-C schema with proper relationships
"""

from sqlalchemy import Column, Integer, String, DateTime, Numeric, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy import MetaData

# Configure naming convention to uppercase table names for Oracle
# This ensures table names match Oracle's uppercase storage
metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

Base = declarative_base(metadata=metadata)


class Warehouse(Base):
    """TPC-C WAREHOUSE table"""

    __tablename__ = "warehouse"

    w_id = Column("w_id", Integer, primary_key=True)
    w_name = Column("w_name", String(10))
    w_street_1 = Column("w_street_1", String(20))
    w_street_2 = Column("w_street_2", String(20))
    w_city = Column("w_city", String(20))
    w_state = Column("w_state", String(2))
    w_zip = Column("w_zip", String(9))
    w_tax = Column("w_tax", Numeric(4, 4))
    w_ytd = Column("w_ytd", Numeric(12, 2))

    # Relationships
    districts = relationship("District", back_populates="warehouse")
    customers = relationship("Customer", back_populates="warehouse")
    new_orders = relationship("NewOrder", back_populates="warehouse")
    orders = relationship("Order", back_populates="warehouse")
    order_lines = relationship("OrderLine", back_populates="warehouse")
    stocks = relationship("Stock", back_populates="warehouse")

    def __repr__(self):
        return f"<Warehouse({self.w_name})>"


class District(Base):
    """TPC-C DISTRICT table"""

    __tablename__ = "district"

    d_id = Column("d_id", Integer, primary_key=True)
    d_w_id = Column("d_w_id", Integer, ForeignKey("warehouse.w_id"), primary_key=True)
    d_name = Column("d_name", String(10))
    d_street_1 = Column("d_street_1", String(20))
    d_street_2 = Column("d_street_2", String(20))
    d_city = Column("d_city", String(20))
    d_state = Column("d_state", String(2))
    d_zip = Column("d_zip", String(9))
    d_tax = Column("d_tax", Numeric(4, 4))
    d_ytd = Column("d_ytd", Numeric(12, 2))
    d_next_o_id = Column("d_next_o_id", Integer)

    # Relationships
    warehouse = relationship("Warehouse", back_populates="districts")

    def __repr__(self):
        return f"<District({self.d_id})>"


class Customer(Base):
    """TPC-C CUSTOMER table"""

    __tablename__ = "customer"

    c_id = Column("c_id", Integer, primary_key=True)
    c_d_id = Column("c_d_id", Integer, primary_key=True)
    c_w_id = Column("c_w_id", Integer, ForeignKey("warehouse.w_id"), primary_key=True)
    c_first = Column("c_first", String(16))
    c_middle = Column("c_middle", String(2))
    c_last = Column("c_last", String(16))
    c_street_1 = Column("c_street_1", String(20))
    c_street_2 = Column("c_street_2", String(20))
    c_city = Column("c_city", String(20))
    c_state = Column("c_state", String(2))
    c_zip = Column("c_zip", String(9))
    c_phone = Column("c_phone", String(16))
    c_since = Column("c_since", DateTime)
    c_credit = Column("c_credit", String(2))
    c_credit_lim = Column("c_credit_lim", Numeric(12, 2))
    c_discount = Column("c_discount", Numeric(4, 4))
    c_balance = Column("c_balance", Numeric(12, 2))
    c_ytd_payment = Column("c_ytd_payment", Numeric(12, 2))
    c_payment_cnt = Column("c_payment_cnt", Integer)
    c_delivery_cnt = Column("c_delivery_cnt", Integer)
    c_data = Column("c_data", String(500))

    # Relationships
    warehouse = relationship("Warehouse", back_populates="customers")

    def __repr__(self):
        return f"<Customer({self.c_id})>"


class History(Base):
    """TPC-C HISTORY table"""

    __tablename__ = "history"

    h_c_id = Column("h_c_id", Integer, primary_key=True)
    h_c_d_id = Column("h_c_d_id", Integer, primary_key=True)
    h_c_w_id = Column("h_c_w_id", Integer, primary_key=True)
    h_d_id = Column("h_d_id", Integer)
    h_w_id = Column("h_w_id", Integer)
    h_date = Column("h_date", DateTime, primary_key=True)
    h_amount = Column("h_amount", Numeric(6, 2))
    h_data = Column("h_data", String(24))

    def __repr__(self):
        return f"<History({self.h_c_id})>"


class NewOrder(Base):
    """TPC-C NEW_ORDER table"""

    __tablename__ = "new_order"

    no_o_id = Column("no_o_id", Integer, primary_key=True)
    no_d_id = Column("no_d_id", Integer, primary_key=True)
    no_w_id = Column("no_w_id", Integer, ForeignKey("warehouse.w_id"), primary_key=True)

    # Relationships
    warehouse = relationship("Warehouse", back_populates="new_orders")

    def __repr__(self):
        return f"<NewOrder({self.no_o_id})>"


class Order(Base):
    """TPC-C ORDER table"""

    __tablename__ = "order"

    o_id = Column("o_id", Integer, primary_key=True)
    o_d_id = Column("o_d_id", Integer, primary_key=True)
    o_w_id = Column("o_w_id", Integer, ForeignKey("warehouse.w_id"), primary_key=True)
    o_c_id = Column("o_c_id", Integer)
    o_entry_d = Column("o_entry_d", DateTime)
    o_carrier_id = Column("o_carrier_id", Integer)
    o_ol_cnt = Column("o_ol_cnt", Integer)
    o_all_local = Column("o_all_local", Integer)

    # Relationships
    warehouse = relationship("Warehouse", back_populates="orders")

    def __repr__(self):
        return f"<Order({self.o_id})>"


class OrderLine(Base):
    """TPC-C ORDER_LINE table"""

    __tablename__ = "order_line"

    ol_o_id = Column("ol_o_id", Integer, primary_key=True)
    ol_d_id = Column("ol_d_id", Integer, primary_key=True)
    ol_w_id = Column("ol_w_id", Integer, ForeignKey("warehouse.w_id"), primary_key=True)
    ol_number = Column("ol_number", Integer, primary_key=True)
    ol_i_id = Column("ol_i_id", Integer)
    ol_supply_w_id = Column("ol_supply_w_id", Integer)
    ol_delivery_d = Column("ol_delivery_d", DateTime)
    ol_quantity = Column("ol_quantity", Integer)
    ol_amount = Column("ol_amount", Numeric(6, 2))
    ol_dist_info = Column("ol_dist_info", String(24))

    # Relationships
    warehouse = relationship("Warehouse", back_populates="order_lines")

    def __repr__(self):
        return f"<OrderLine({self.ol_o_id}-{self.ol_number})>"


class Item(Base):
    """TPC-C ITEM table"""

    __tablename__ = "item"

    i_id = Column("i_id", Integer, primary_key=True)
    i_im_id = Column("i_im_id", Integer)
    i_name = Column("i_name", String(24))
    i_price = Column("i_price", Numeric(5, 2))
    i_data = Column("i_data", String(50))

    # Relationships
    stocks = relationship("Stock", back_populates="item")

    def __repr__(self):
        return f"<Item({self.i_name})>"


class Stock(Base):
    """TPC-C STOCK table"""

    __tablename__ = "stock"

    s_i_id = Column("s_i_id", Integer, ForeignKey("item.i_id"), primary_key=True)
    s_w_id = Column("s_w_id", Integer, ForeignKey("warehouse.w_id"), primary_key=True)
    s_quantity = Column("s_quantity", Integer)
    s_dist_01 = Column("s_dist_01", String(24))
    s_dist_02 = Column("s_dist_02", String(24))
    s_dist_03 = Column("s_dist_03", String(24))
    s_dist_04 = Column("s_dist_04", String(24))
    s_dist_05 = Column("s_dist_05", String(24))
    s_dist_06 = Column("s_dist_06", String(24))
    s_dist_07 = Column("s_dist_07", String(24))
    s_dist_08 = Column("s_dist_08", String(24))
    s_dist_09 = Column("s_dist_09", String(24))
    s_dist_10 = Column("s_dist_10", String(24))
    s_ytd = Column("s_ytd", Integer)
    s_order_cnt = Column("s_order_cnt", Integer)
    s_remote_cnt = Column("s_remote_cnt", Integer)
    s_data = Column("s_data", String(50))

    # Relationships
    item = relationship("Item", back_populates="stocks")
    warehouse = relationship("Warehouse", back_populates="stocks")

    def __repr__(self):
        return f"<Stock({self.s_i_id}@{self.s_w_id})>"
