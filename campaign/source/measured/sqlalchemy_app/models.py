"""
TPC-H Database Schema as SQLAlchemy Models
Implements the 8-table TPC-H schema with proper relationships
"""
from sqlalchemy import Column, Integer, String, Date, Numeric, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Region(Base):
    """TPC-H REGION table"""
    __tablename__ = 'region'
    
    regionkey = Column('r_regionkey', Integer, primary_key=True)
    name = Column('r_name', String(25))
    comment = Column('r_comment', String(152))
    
    # Relationships
    nations = relationship('Nation', back_populates='region')
    
    def __repr__(self):
        return f"<Region({self.name})>"


class Nation(Base):
    """TPC-H NATION table"""
    __tablename__ = 'nation'
    
    nationkey = Column('n_nationkey', Integer, primary_key=True)
    name = Column('n_name', String(25))
    regionkey_id = Column('n_regionkey', Integer, ForeignKey('region.r_regionkey'))
    comment = Column('n_comment', String(152))
    
    # Relationships
    region = relationship('Region', back_populates='nations')
    suppliers = relationship('Supplier', back_populates='nation')
    customers = relationship('Customer', back_populates='nation')
    
    def __repr__(self):
        return f"<Nation({self.name})>"


class Supplier(Base):
    """TPC-H SUPPLIER table"""
    __tablename__ = 'supplier'
    
    suppkey = Column('s_suppkey', Integer, primary_key=True)
    name = Column('s_name', String(25))
    address = Column('s_address', String(40))
    nationkey_id = Column('s_nationkey', Integer, ForeignKey('nation.n_nationkey'))
    phone = Column('s_phone', String(15))
    acctbal = Column('s_acctbal', Numeric(15, 2))
    comment = Column('s_comment', String(101))
    
    # Relationships
    nation = relationship('Nation', back_populates='suppliers')
    partsupps = relationship('PartSupp', back_populates='supplier')
    line_items = relationship('LineItem', back_populates='supplier')
    
    def __repr__(self):
        return f"<Supplier({self.name})>"


class Part(Base):
    """TPC-H PART table"""
    __tablename__ = 'part'
    
    partkey = Column('p_partkey', Integer, primary_key=True)
    name = Column('p_name', String(55))
    mfgr = Column('p_mfgr', String(25))
    brand = Column('p_brand', String(10))
    type = Column('p_type', String(25))
    size = Column('p_size', Integer)
    container = Column('p_container', String(10))
    retailprice = Column('p_retailprice', Numeric(15, 2))
    comment = Column('p_comment', String(23))
    
    # Relationships
    partsupps = relationship('PartSupp', back_populates='part')
    line_items = relationship('LineItem', back_populates='part')
    
    def __repr__(self):
        return f"<Part({self.name})>"


class PartSupp(Base):
    """TPC-H PARTSUPP table (composite key)"""
    __tablename__ = 'partsupp'
    
    partkey_id = Column('ps_partkey', Integer, ForeignKey('part.p_partkey'), primary_key=True)
    suppkey_id = Column('ps_suppkey', Integer, ForeignKey('supplier.s_suppkey'), primary_key=True)
    availqty = Column('ps_availqty', Integer)
    supplycost = Column('ps_supplycost', Numeric(15, 2))
    comment = Column('ps_comment', String(199))
    
    # Relationships
    part = relationship('Part', back_populates='partsupps')
    supplier = relationship('Supplier', back_populates='partsupps')
    
    def __repr__(self):
        return f"<PartSupp({self.partkey_id}, {self.suppkey_id})>"


class Customer(Base):
    """TPC-H CUSTOMER table"""
    __tablename__ = 'customer'
    
    custkey = Column('c_custkey', Integer, primary_key=True)
    name = Column('c_name', String(25))
    address = Column('c_address', String(40))
    nationkey_id = Column('c_nationkey', Integer, ForeignKey('nation.n_nationkey'))
    phone = Column('c_phone', String(15))
    acctbal = Column('c_acctbal', Numeric(15, 2))
    mktsegment = Column('c_mktsegment', String(10))
    comment = Column('c_comment', String(117))
    
    # Relationships
    nation = relationship('Nation', back_populates='customers')
    orders = relationship('Orders', back_populates='customer')
    
    def __repr__(self):
        return f"<Customer({self.name})>"


class Orders(Base):
    """TPC-H ORDERS table"""
    __tablename__ = 'orders'
    
    orderkey = Column('o_orderkey', Integer, primary_key=True)
    custkey_id = Column('o_custkey', Integer, ForeignKey('customer.c_custkey'))
    orderstatus = Column('o_orderstatus', String(1))
    totalprice = Column('o_totalprice', Numeric(15, 2))
    orderdate = Column('o_orderdate', Date)
    orderpriority = Column('o_orderpriority', String(15))
    clerk = Column('o_clerk', String(15))
    shippriority = Column('o_shippriority', Integer)
    comment = Column('o_comment', String(79))
    
    # Relationships
    customer = relationship('Customer', back_populates='orders')
    line_items = relationship('LineItem', back_populates='order')
    
    def __repr__(self):
        return f"<Order({self.orderkey})>"


class LineItem(Base):
    """TPC-H LINEITEM table (composite key)"""
    __tablename__ = 'lineitem'
    
    orderkey_id = Column('l_orderkey', Integer, ForeignKey('orders.o_orderkey'), primary_key=True)
    linenumber = Column('l_linenumber', Integer, primary_key=True)
    partkey_id = Column('l_partkey', Integer, ForeignKey('part.p_partkey'))
    suppkey_id = Column('l_suppkey', Integer, ForeignKey('supplier.s_suppkey'))
    quantity = Column('l_quantity', Numeric(15, 2))
    extendedprice = Column('l_extendedprice', Numeric(15, 2))
    discount = Column('l_discount', Numeric(15, 2))
    tax = Column('l_tax', Numeric(15, 2))
    returnflag = Column('l_returnflag', String(1))
    linestatus = Column('l_linestatus', String(1))
    shipdate = Column('l_shipdate', Date)
    commitdate = Column('l_commitdate', Date)
    receiptdate = Column('l_receiptdate', Date)
    shipinstruct = Column('l_shipinstruct', String(25))
    shipmode = Column('l_shipmode', String(10))
    comment = Column('l_comment', String(44))
    
    # Relationships
    order = relationship('Orders', back_populates='line_items')
    part = relationship('Part', back_populates='line_items')
    supplier = relationship('Supplier', back_populates='line_items')
    
    def __repr__(self):
        return f"<LineItem({self.orderkey_id}, {self.linenumber})>"

