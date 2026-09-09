"""Django models for the TPC-C tables.

**Every composite key here is declared as a single-column primary key, and that
is a compromise with a sharp edge.**

TPC-C keys are composite - district is (d_w_id, d_id), order_line is
(ol_w_id, ol_d_id, ol_o_id, ol_number) - and Django 4.2 cannot express that.
`CompositePrimaryKey` arrived in Django 5.2. Without a declared primary key
Django invents `id = AutoField(primary_key=True)` and every query it builds
selects a column the TPC-C schema does not have, which is exactly what happened:
the first execution of T1 died on `column district.id does not exist`.

Declaring one column of each key `primary_key=True` stops Django inventing the
column. It also makes Django believe that column is unique, which it is not:
`d_id` 5 exists in all ten warehouses.

So these models are safe only for queries that filter on the *whole* key, and
every transaction module here does:

    District.objects.get(d_w_id=w_id, d_id=d_id)                   # safe
    District.objects.filter(d_w_id=w_id, d_id=d_id).update(...)    # safe
    Order.objects.create(o_id=..., o_d_id=..., o_w_id=...)         # safe

These are not, and must not be used:

    District.objects.get(pk=5)          # matches ten rows, returns one
    instance.save()                     # UPDATE ... WHERE d_id = 5, ten rows
    instance.delete()                   # DELETE ... WHERE d_id = 5, ten rows
    instance.refresh_from_db()          # SELECT ... WHERE c_id = 1208, 100 rows

Two of these were present. `t4_delivery.py` called `new_order.delete()`, which
would have deleted that order number from every warehouse and district rather
than the one row it had just delivered. `t2_payment.py` called
`customer.refresh_from_db()`, which re-reads by primary key and raised
MultipleObjectsReturned across the 100 rows sharing that `c_id` - loudly, which
is the one piece of luck in it. Both now go through a filter on the whole key.

Note for anyone adding to these modules: the unsafe operations are the ones that
*imply* the key rather than state it, so they do not grep as a group. `save`,
`delete`, `refresh_from_db`, `get(pk=)`, `in_bulk` and `.pk` are the ones to
avoid; an audit that looked only for the first three missed `refresh_from_db`
and the defect survived into the first execution.

The SQLAlchemy models have no such limitation - SQLAlchemy has supported
composite primary keys since long before this study - so the two frameworks
differ here in what the mapper can express, not in what the benchmark asks of
them. Worth a sentence in the write-up: it is the same class of finding as C17,
where Django's lack of a derived-table construct made Q13 inexpressible.
"""

from django.db import models
from decimal import Decimal


class Warehouse(models.Model):
    """TPC-C WAREHOUSE table"""

    w_id = models.IntegerField(primary_key=True, db_column="w_id")
    w_name = models.CharField(max_length=10, db_column="w_name")
    w_street_1 = models.CharField(max_length=20, db_column="w_street_1")
    w_street_2 = models.CharField(max_length=20, db_column="w_street_2")
    w_city = models.CharField(max_length=20, db_column="w_city")
    w_state = models.CharField(max_length=2, db_column="w_state")
    w_zip = models.CharField(max_length=9, db_column="w_zip")
    w_tax = models.DecimalField(max_digits=4, decimal_places=4, db_column="w_tax")
    w_ytd = models.DecimalField(max_digits=12, decimal_places=2, db_column="w_ytd")

    class Meta:
        db_table = "warehouse"
        managed = False
        app_label = "django_app"
        # Use a different app_label to avoid conflicts with TPC-H models
        # This is a workaround - Django doesn't allow same model names in same app

    def __str__(self):
        return self.w_name


class District(models.Model):
    """TPC-C DISTRICT table"""

    d_id = models.IntegerField(primary_key=True, db_column="d_id")
    d_w_id = models.ForeignKey(
        Warehouse,
        on_delete=models.DO_NOTHING,
        db_column="d_w_id",
        related_name="districts",
    )
    d_name = models.CharField(max_length=10, db_column="d_name")
    d_street_1 = models.CharField(max_length=20, db_column="d_street_1")
    d_street_2 = models.CharField(max_length=20, db_column="d_street_2")
    d_city = models.CharField(max_length=20, db_column="d_city")
    d_state = models.CharField(max_length=2, db_column="d_state")
    d_zip = models.CharField(max_length=9, db_column="d_zip")
    d_tax = models.DecimalField(max_digits=4, decimal_places=4, db_column="d_tax")
    d_ytd = models.DecimalField(max_digits=12, decimal_places=2, db_column="d_ytd")
    d_next_o_id = models.IntegerField(db_column="d_next_o_id")

    class Meta:
        db_table = "district"
        managed = False
        unique_together = ("d_w_id", "d_id")
        indexes = [
            models.Index(fields=["d_w_id"], name="idx_district_w_id"),
        ]

    def __str__(self):
        return f"District {self.d_id}"


class TpccCustomer(models.Model):
    """TPC-C CUSTOMER table"""

    c_id = models.IntegerField(primary_key=True, db_column="c_id")
    c_d_id = models.IntegerField(db_column="c_d_id")
    c_w_id = models.ForeignKey(
        Warehouse,
        on_delete=models.DO_NOTHING,
        db_column="c_w_id",
        related_name="tpcc_customers",
    )
    c_first = models.CharField(max_length=16, db_column="c_first")
    c_middle = models.CharField(max_length=2, db_column="c_middle")
    c_last = models.CharField(max_length=16, db_column="c_last")
    c_street_1 = models.CharField(max_length=20, db_column="c_street_1")
    c_street_2 = models.CharField(max_length=20, db_column="c_street_2")
    c_city = models.CharField(max_length=20, db_column="c_city")
    c_state = models.CharField(max_length=2, db_column="c_state")
    c_zip = models.CharField(max_length=9, db_column="c_zip")
    c_phone = models.CharField(max_length=16, db_column="c_phone")
    c_since = models.DateTimeField(db_column="c_since")
    c_credit = models.CharField(max_length=2, db_column="c_credit")
    c_credit_lim = models.DecimalField(
        max_digits=12, decimal_places=2, db_column="c_credit_lim"
    )
    c_discount = models.DecimalField(
        max_digits=4, decimal_places=4, db_column="c_discount"
    )
    c_balance = models.DecimalField(
        max_digits=12, decimal_places=2, db_column="c_balance"
    )
    c_ytd_payment = models.DecimalField(
        max_digits=12, decimal_places=2, db_column="c_ytd_payment"
    )
    c_payment_cnt = models.IntegerField(db_column="c_payment_cnt")
    c_delivery_cnt = models.IntegerField(db_column="c_delivery_cnt")
    c_data = models.CharField(max_length=500, db_column="c_data")

    class Meta:
        db_table = "customer"
        managed = False
        unique_together = ("c_w_id", "c_d_id", "c_id")
        # Note: This will conflict with TPC-H Customer model
        # Solution: Use db_table to differentiate, but Django still registers by class name
        indexes = [
            models.Index(fields=["c_w_id", "c_d_id"], name="idx_customer_wd"),
            models.Index(
                fields=["c_w_id", "c_d_id", "c_last"], name="idx_customer_wdl"
            ),
        ]

    def __str__(self):
        return f"Customer {self.c_id}"


class History(models.Model):
    """TPC-C HISTORY table"""

    h_c_id = models.IntegerField(primary_key=True, db_column="h_c_id")
    h_c_d_id = models.IntegerField(db_column="h_c_d_id")
    h_c_w_id = models.IntegerField(db_column="h_c_w_id")
    h_d_id = models.IntegerField(db_column="h_d_id")
    h_w_id = models.IntegerField(db_column="h_w_id")
    h_date = models.DateTimeField(db_column="h_date")
    h_amount = models.DecimalField(max_digits=6, decimal_places=2, db_column="h_amount")
    h_data = models.CharField(max_length=24, db_column="h_data")

    class Meta:
        db_table = "history"
        managed = False
        indexes = [
            models.Index(
                fields=["h_c_w_id", "h_c_d_id", "h_c_id"], name="idx_history_customer"
            ),
        ]

    def __str__(self):
        return f"History {self.h_c_id}"


class NewOrder(models.Model):
    """TPC-C NEW_ORDER table"""

    no_o_id = models.IntegerField(primary_key=True, db_column="no_o_id")
    no_d_id = models.IntegerField(db_column="no_d_id")
    no_w_id = models.ForeignKey(
        Warehouse,
        on_delete=models.DO_NOTHING,
        db_column="no_w_id",
        related_name="new_orders",
    )

    class Meta:
        db_table = "new_order"
        managed = False
        unique_together = ("no_w_id", "no_d_id", "no_o_id")
        indexes = [
            models.Index(fields=["no_w_id", "no_d_id"], name="idx_neworder_wd"),
        ]

    def __str__(self):
        return f"NewOrder {self.no_o_id}"


class TpccOrder(models.Model):
    """TPC-C ORDER table"""

    o_id = models.IntegerField(primary_key=True, db_column="o_id")
    o_d_id = models.IntegerField(db_column="o_d_id")
    o_w_id = models.ForeignKey(
        Warehouse,
        on_delete=models.DO_NOTHING,
        db_column="o_w_id",
        related_name="orders",
    )
    o_c_id = models.IntegerField(db_column="o_c_id")
    o_entry_d = models.DateTimeField(db_column="o_entry_d")
    o_carrier_id = models.IntegerField(null=True, db_column="o_carrier_id")
    o_ol_cnt = models.IntegerField(db_column="o_ol_cnt")
    o_all_local = models.IntegerField(db_column="o_all_local")

    class Meta:
        db_table = "order"
        managed = False
        unique_together = ("o_w_id", "o_d_id", "o_id")
        indexes = [
            models.Index(
                fields=["o_w_id", "o_d_id", "o_c_id"], name="idx_order_customer"
            ),
        ]

    def __str__(self):
        return f"Order {self.o_id}"


class OrderLine(models.Model):
    """TPC-C ORDER_LINE table"""

    ol_o_id = models.IntegerField(db_column="ol_o_id")
    ol_d_id = models.IntegerField(db_column="ol_d_id")
    ol_w_id = models.ForeignKey(
        Warehouse,
        on_delete=models.DO_NOTHING,
        db_column="ol_w_id",
        related_name="order_lines",
    )
    ol_number = models.IntegerField(primary_key=True, db_column="ol_number")
    ol_i_id = models.IntegerField(db_column="ol_i_id")
    ol_supply_w_id = models.IntegerField(db_column="ol_supply_w_id")
    ol_delivery_d = models.DateTimeField(null=True, db_column="ol_delivery_d")
    ol_quantity = models.IntegerField(db_column="ol_quantity")
    ol_amount = models.DecimalField(
        max_digits=6, decimal_places=2, db_column="ol_amount"
    )
    ol_dist_info = models.CharField(max_length=24, db_column="ol_dist_info")

    class Meta:
        db_table = "order_line"
        managed = False
        unique_together = ("ol_w_id", "ol_d_id", "ol_o_id", "ol_number")
        indexes = [
            models.Index(
                fields=["ol_w_id", "ol_d_id", "ol_o_id"], name="idx_orderline_order"
            ),
        ]

    def __str__(self):
        return f"OrderLine {self.ol_o_id}-{self.ol_number}"


class Item(models.Model):
    """TPC-C ITEM table"""

    i_id = models.IntegerField(primary_key=True, db_column="i_id")
    i_im_id = models.IntegerField(db_column="i_im_id")
    i_name = models.CharField(max_length=24, db_column="i_name")
    i_price = models.DecimalField(max_digits=5, decimal_places=2, db_column="i_price")
    i_data = models.CharField(max_length=50, db_column="i_data")

    class Meta:
        db_table = "item"
        managed = False

    def __str__(self):
        return self.i_name


class Stock(models.Model):
    """TPC-C STOCK table"""

    s_i_id = models.ForeignKey(
        Item,
        on_delete=models.DO_NOTHING,
        db_column="s_i_id",
        related_name="stocks",
        primary_key=True,
    )
    s_w_id = models.ForeignKey(
        Warehouse,
        on_delete=models.DO_NOTHING,
        db_column="s_w_id",
        related_name="stocks",
    )
    s_quantity = models.IntegerField(db_column="s_quantity")
    s_dist_01 = models.CharField(max_length=24, db_column="s_dist_01")
    s_dist_02 = models.CharField(max_length=24, db_column="s_dist_02")
    s_dist_03 = models.CharField(max_length=24, db_column="s_dist_03")
    s_dist_04 = models.CharField(max_length=24, db_column="s_dist_04")
    s_dist_05 = models.CharField(max_length=24, db_column="s_dist_05")
    s_dist_06 = models.CharField(max_length=24, db_column="s_dist_06")
    s_dist_07 = models.CharField(max_length=24, db_column="s_dist_07")
    s_dist_08 = models.CharField(max_length=24, db_column="s_dist_08")
    s_dist_09 = models.CharField(max_length=24, db_column="s_dist_09")
    s_dist_10 = models.CharField(max_length=24, db_column="s_dist_10")
    s_ytd = models.IntegerField(db_column="s_ytd")
    s_order_cnt = models.IntegerField(db_column="s_order_cnt")
    s_remote_cnt = models.IntegerField(db_column="s_remote_cnt")
    s_data = models.CharField(max_length=50, db_column="s_data")

    class Meta:
        db_table = "stock"
        managed = False
        unique_together = ("s_w_id", "s_i_id")
        indexes = [
            models.Index(fields=["s_w_id"], name="idx_stock_w_id"),
            models.Index(fields=["s_i_id"], name="idx_stock_i_id"),
        ]

    def __str__(self):
        return f"Stock {self.s_i_id_id}@{self.s_w_id_id}"


# Aliases for backward compatibility with query files
# These allow imports like "from django_app.tpcc_models import Customer, Order"
Customer = TpccCustomer
Order = TpccOrder
