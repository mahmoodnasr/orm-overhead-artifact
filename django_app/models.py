"""
TPC-H Database Schema as Django Models
Implements the 8-table TPC-H schema with proper relationships
"""

from django.db import models
from decimal import Decimal


class Region(models.Model):
    """TPC-H REGION table"""

    regionkey = models.IntegerField(primary_key=True, db_column="r_regionkey")
    name = models.CharField(max_length=25, db_column="r_name")
    comment = models.CharField(max_length=152, db_column="r_comment")

    class Meta:
        db_table = "region"
        managed = False  # Schema managed externally

    def __str__(self):
        return self.name


class Nation(models.Model):
    """TPC-H NATION table"""

    nationkey = models.IntegerField(primary_key=True, db_column="n_nationkey")
    name = models.CharField(max_length=25, db_column="n_name")
    regionkey = models.ForeignKey(
        Region,
        on_delete=models.DO_NOTHING,
        db_column="n_regionkey",
        related_name="nations",
    )
    comment = models.CharField(max_length=152, db_column="n_comment")

    class Meta:
        db_table = "nation"
        managed = False
        indexes = [
            models.Index(fields=["regionkey"], name="idx_nation_regionkey"),
        ]

    def __str__(self):
        return self.name


class Supplier(models.Model):
    """TPC-H SUPPLIER table"""

    suppkey = models.IntegerField(primary_key=True, db_column="s_suppkey")
    name = models.CharField(max_length=25, db_column="s_name")
    address = models.CharField(max_length=40, db_column="s_address")
    nationkey = models.ForeignKey(
        Nation,
        on_delete=models.DO_NOTHING,
        db_column="s_nationkey",
        related_name="suppliers",
    )
    phone = models.CharField(max_length=15, db_column="s_phone")
    acctbal = models.DecimalField(
        max_digits=15, decimal_places=2, db_column="s_acctbal"
    )
    comment = models.CharField(max_length=101, db_column="s_comment")

    class Meta:
        db_table = "supplier"
        managed = False
        indexes = [
            models.Index(fields=["nationkey"], name="idx_supplier_nationkey"),
        ]

    def __str__(self):
        return self.name


class Part(models.Model):
    """TPC-H PART table"""

    partkey = models.IntegerField(primary_key=True, db_column="p_partkey")
    name = models.CharField(max_length=55, db_column="p_name")
    mfgr = models.CharField(max_length=25, db_column="p_mfgr")
    brand = models.CharField(max_length=10, db_column="p_brand")
    type = models.CharField(max_length=25, db_column="p_type")
    size = models.IntegerField(db_column="p_size")
    container = models.CharField(max_length=10, db_column="p_container")
    retailprice = models.DecimalField(
        max_digits=15, decimal_places=2, db_column="p_retailprice"
    )
    comment = models.CharField(max_length=23, db_column="p_comment")

    class Meta:
        db_table = "part"
        managed = False
        indexes = [
            models.Index(fields=["brand"], name="idx_part_brand"),
            models.Index(fields=["type"], name="idx_part_type"),
            models.Index(fields=["size"], name="idx_part_size"),
        ]

    def __str__(self):
        return self.name


class PartSupp(models.Model):
    """TPC-H PARTSUPP table (composite key)"""

    partkey = models.ForeignKey(
        Part, on_delete=models.DO_NOTHING, db_column="ps_partkey"
    )
    suppkey = models.ForeignKey(
        Supplier, on_delete=models.DO_NOTHING, db_column="ps_suppkey"
    )
    availqty = models.IntegerField(db_column="ps_availqty")
    supplycost = models.DecimalField(
        max_digits=15, decimal_places=2, db_column="ps_supplycost"
    )
    comment = models.CharField(max_length=199, db_column="ps_comment")

    class Meta:
        db_table = "partsupp"
        managed = False
        unique_together = ("partkey", "suppkey")
        indexes = [
            models.Index(fields=["partkey"], name="idx_partsupp_partkey"),
            models.Index(fields=["suppkey"], name="idx_partsupp_suppkey"),
        ]

    def __str__(self):
        return f"PartSupp({self.partkey_id}, {self.suppkey_id})"


class Customer(models.Model):
    """TPC-H CUSTOMER table"""

    custkey = models.IntegerField(primary_key=True, db_column="c_custkey")
    name = models.CharField(max_length=25, db_column="c_name")
    address = models.CharField(max_length=40, db_column="c_address")
    nationkey = models.ForeignKey(
        Nation,
        on_delete=models.DO_NOTHING,
        db_column="c_nationkey",
        related_name="customers",
    )
    phone = models.CharField(max_length=15, db_column="c_phone")
    acctbal = models.DecimalField(
        max_digits=15, decimal_places=2, db_column="c_acctbal"
    )
    mktsegment = models.CharField(max_length=10, db_column="c_mktsegment")
    comment = models.CharField(max_length=117, db_column="c_comment")

    class Meta:
        db_table = "customer"
        managed = False
        indexes = [
            models.Index(fields=["nationkey"], name="idx_customer_nationkey"),
            models.Index(fields=["mktsegment"], name="idx_customer_mktsegment"),
        ]

    def __str__(self):
        return self.name


class Orders(models.Model):
    """TPC-H ORDERS table"""

    orderkey = models.IntegerField(primary_key=True, db_column="o_orderkey")
    custkey = models.ForeignKey(
        Customer,
        on_delete=models.DO_NOTHING,
        db_column="o_custkey",
        related_name="orders",
    )
    orderstatus = models.CharField(max_length=1, db_column="o_orderstatus")
    totalprice = models.DecimalField(
        max_digits=15, decimal_places=2, db_column="o_totalprice"
    )
    orderdate = models.DateField(db_column="o_orderdate")
    orderpriority = models.CharField(max_length=15, db_column="o_orderpriority")
    clerk = models.CharField(max_length=15, db_column="o_clerk")
    shippriority = models.IntegerField(db_column="o_shippriority")
    comment = models.CharField(max_length=79, db_column="o_comment")

    class Meta:
        db_table = "orders"
        managed = False
        indexes = [
            models.Index(fields=["custkey"], name="idx_orders_custkey"),
            models.Index(fields=["orderdate"], name="idx_orders_orderdate"),
            models.Index(fields=["orderstatus"], name="idx_orders_orderstatus"),
        ]

    def __str__(self):
        return f"Order {self.orderkey}"


class LineItem(models.Model):
    """TPC-H LINEITEM table (composite key)"""

    orderkey = models.ForeignKey(
        Orders, on_delete=models.DO_NOTHING, db_column="l_orderkey"
    )
    partkey = models.ForeignKey(
        Part,
        on_delete=models.DO_NOTHING,
        db_column="l_partkey",
        related_name="line_items",
    )
    suppkey = models.ForeignKey(
        Supplier,
        on_delete=models.DO_NOTHING,
        db_column="l_suppkey",
        related_name="line_items",
    )
    linenumber = models.IntegerField(db_column="l_linenumber")
    quantity = models.DecimalField(
        max_digits=15, decimal_places=2, db_column="l_quantity"
    )
    extendedprice = models.DecimalField(
        max_digits=15, decimal_places=2, db_column="l_extendedprice"
    )
    discount = models.DecimalField(
        max_digits=15, decimal_places=2, db_column="l_discount"
    )
    tax = models.DecimalField(max_digits=15, decimal_places=2, db_column="l_tax")
    returnflag = models.CharField(max_length=1, db_column="l_returnflag")
    linestatus = models.CharField(max_length=1, db_column="l_linestatus")
    shipdate = models.DateField(db_column="l_shipdate")
    commitdate = models.DateField(db_column="l_commitdate")
    receiptdate = models.DateField(db_column="l_receiptdate")
    shipinstruct = models.CharField(max_length=25, db_column="l_shipinstruct")
    shipmode = models.CharField(max_length=10, db_column="l_shipmode")
    comment = models.CharField(max_length=44, db_column="l_comment")

    class Meta:
        db_table = "lineitem"
        managed = False
        unique_together = ("orderkey", "linenumber")
        indexes = [
            models.Index(fields=["orderkey"], name="idx_lineitem_orderkey"),
            models.Index(fields=["partkey"], name="idx_lineitem_partkey"),
            models.Index(fields=["suppkey"], name="idx_lineitem_suppkey"),
            models.Index(fields=["shipdate"], name="idx_lineitem_shipdate"),
            models.Index(fields=["commitdate"], name="idx_lineitem_commitdate"),
            models.Index(fields=["receiptdate"], name="idx_lineitem_receiptdate"),
        ]

    def __str__(self):
        return f"LineItem({self.orderkey_id}, {self.linenumber})"
