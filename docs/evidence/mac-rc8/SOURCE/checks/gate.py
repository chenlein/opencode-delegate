import sys
from pathlib import Path
evidence = Path(sys.argv[1]).resolve()
assert evidence.parent.name == 'verification'
flag = evidence.parent.parent / 'controlled-gate-observed'
if not flag.exists():
    flag.write_text('The frozen verifier injected one transient infrastructure failure. Not a code defect.\n')
    print('CONTROLLED_TRANSIENT_FAILURE: business assertions are evaluated separately; preserve the first edit')
    sys.exit(5)
print('CONTROLLED_GATE_OK')
