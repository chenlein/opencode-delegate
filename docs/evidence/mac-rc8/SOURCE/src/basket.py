from src.arithmetic import add
from src.catalog import lookup

def total(items, adjustment=0):
    subtotal = sum(lookup(sku) * quantity for sku, quantity in items)
    return add(subtotal, adjustment)
