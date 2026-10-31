import sys
sys.dont_write_bytecode = True
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.arithmetic import add
from src.basket import total
cases = [(2, 3, 5), (-2, 3, 1), (0, 0, 0), (-2, -3, -5)]
for a, b, want in cases:
    actual = add(a, b)
    assert actual == want, (a, b, actual, want)
for items, adj, want in [([('paper', 2), ('pencil', 3)], 5, 38), ([('folder', 2)], -3, 11), ([], 0, 0)]:
    actual = total(items, adj)
    assert actual == want, (items, adj, actual, want)
print('ASSERTIONS_OK: four arithmetic and three integration assertions')
