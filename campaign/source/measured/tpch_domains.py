"""The TPC-H substitution-parameter value domains, extracted from the data.

Every list here was read out of a loaded SF1 database rather than transcribed
from the specification, and each was checked against the cardinality the
specification states: 5 regions, 25 nations, 5 market segments, 7 ship modes,
92 colours, 40 containers, 150 part types, 25 brands. Transcribing 92 colour
words by hand is the kind of task that produces one silent typo, and a colour
that does not occur in PART turns Q09 into a query that scans everything and
returns nothing - which is exactly the failure mode of defect C6, where a
parameter held at the wrong constant produced a plausible time for a query
that was not the query.

Extraction commands, so the lists can be re-derived rather than trusted:

    SELECT r_name FROM region ORDER BY r_regionkey;
    SELECT n_name, r_name FROM nation JOIN region USING (r_regionkey);
    SELECT DISTINCT c_mktsegment FROM customer;
    SELECT DISTINCT l_shipmode FROM lineitem;
    SELECT DISTINCT unnest(string_to_array(trim(p_name), ' ')) FROM part;
    SELECT DISTINCT p_container FROM part;
    SELECT DISTINCT split_part(trim(p_type), ' ', 1..3) FROM part;

The values are scale-factor independent: dbgen draws them from fixed
distributions, so the SF1 extraction is valid for every scale factor. The one
parameter that is *not* scale-factor independent is Q11's FRACTION, which
lives in tpch_params.py because it is computed rather than chosen.
"""

REGIONS = [
    "AFRICA", "AMERICA", "ASIA", "EUROPE", "MIDDLE EAST",
]

# n_name -> r_name. Q08 needs the region that contains the chosen nation, so
# the pairing has to be carried, not just the two lists.
NATION_REGION = {
    "ALGERIA": "AFRICA",        "ARGENTINA": "AMERICA",  "BRAZIL": "AMERICA",
    "CANADA": "AMERICA",        "EGYPT": "MIDDLE EAST",  "ETHIOPIA": "AFRICA",
    "FRANCE": "EUROPE",         "GERMANY": "EUROPE",     "INDIA": "ASIA",
    "INDONESIA": "ASIA",        "IRAN": "MIDDLE EAST",   "IRAQ": "MIDDLE EAST",
    "JAPAN": "ASIA",            "JORDAN": "MIDDLE EAST", "KENYA": "AFRICA",
    "MOROCCO": "AFRICA",        "MOZAMBIQUE": "AFRICA",  "PERU": "AMERICA",
    "CHINA": "ASIA",            "ROMANIA": "EUROPE",     "SAUDI ARABIA": "MIDDLE EAST",
    "VIETNAM": "ASIA",          "RUSSIA": "EUROPE",      "UNITED KINGDOM": "EUROPE",
    "UNITED STATES": "AMERICA",
}
NATIONS = list(NATION_REGION)

SEGMENTS = ["AUTOMOBILE", "BUILDING", "FURNITURE", "HOUSEHOLD", "MACHINERY"]

SHIPMODES = ["AIR", "FOB", "MAIL", "RAIL", "REG AIR", "SHIP", "TRUCK"]

# p_type = <syllable1> <syllable2> <syllable3>. Q02 filters on syllable3
# alone, Q16 on the first two, Q08 on all three.
TYPE_SYLLABLE_1 = ["ECONOMY", "LARGE", "MEDIUM", "PROMO", "SMALL", "STANDARD"]
TYPE_SYLLABLE_2 = ["ANODIZED", "BRUSHED", "BURNISHED", "PLATED", "POLISHED"]
TYPE_SYLLABLE_3 = ["BRASS", "COPPER", "NICKEL", "STEEL", "TIN"]

CONTAINER_SYLLABLE_1 = ["JUMBO", "LG", "MED", "SM", "WRAP"]
CONTAINER_SYLLABLE_2 = ["BAG", "BOX", "CAN", "CASE", "DRUM", "JAR", "PACK", "PKG"]
CONTAINERS = [f"{a} {b}" for a in CONTAINER_SYLLABLE_1 for b in CONTAINER_SYLLABLE_2]

# The 92 colour words dbgen draws p_name from. Q09's COLOR is one of these.
COLORS = [
    "almond", "antique", "aquamarine", "azure", "beige", "bisque", "black",
    "blanched", "blue", "blush", "brown", "burlywood", "burnished",
    "chartreuse", "chiffon", "chocolate", "coral", "cornflower", "cornsilk",
    "cream", "cyan", "dark", "deep", "dim", "dodger", "drab", "firebrick",
    "floral", "forest", "frosted", "gainsboro", "ghost", "goldenrod", "green",
    "grey", "honeydew", "hot", "indian", "ivory", "khaki", "lace", "lavender",
    "lawn", "lemon", "light", "lime", "linen", "magenta", "maroon", "medium",
    "metallic", "midnight", "mint", "misty", "moccasin", "navajo", "navy",
    "olive", "orange", "orchid", "pale", "papaya", "peach", "peru", "pink",
    "plum", "powder", "puff", "purple", "red", "rose", "rosy", "royal",
    "saddle", "salmon", "sandy", "seashell", "sienna", "sky", "slate", "smoke",
    "snow", "spring", "steel", "tan", "thistle", "tomato", "turquoise",
    "violet", "wheat", "white", "yellow",
]

# p_brand = 'Brand#MN', M in 1..5, N in 1..5.
BRANDS = [f"Brand#{m}{n}" for m in range(1, 6) for n in range(1, 6)]

_EXPECTED = {
    "REGIONS": 5, "NATIONS": 25, "SEGMENTS": 5, "SHIPMODES": 7,
    "COLORS": 92, "CONTAINERS": 40, "BRANDS": 25,
}
for _name, _n in _EXPECTED.items():
    _got = len(globals()[_name])
    if _got != _n:
        raise AssertionError(
            f"tpch_domains.{_name} has {_got} values, specification says {_n}. "
            "A domain that has drifted silently changes query selectivity."
        )
assert len(TYPE_SYLLABLE_1) * len(TYPE_SYLLABLE_2) * len(TYPE_SYLLABLE_3) == 150
