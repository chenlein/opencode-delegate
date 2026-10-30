#!/usr/bin/env python3
"""Summarize controlled manual runs. Unknown usage never becomes zero."""
import argparse
import json
import math
from pathlib import Path
import statistics


def summarize(rows):
    groups, seen = {}, set()
    for row in rows:
        for field in ('run_id','case_id','route','passed','elapsed_seconds'):
            if field not in row:
                raise ValueError('Missing ' + field)
        if row['run_id'] in seen:
            raise ValueError('Duplicate run_id')
        seen.add(row['run_id'])
        if type(row['passed']) is not bool:
            raise ValueError('passed must be boolean')
        value = row['elapsed_seconds']
        if type(value) not in (int,float) or not math.isfinite(value) or value < 0:
            raise ValueError('Invalid elapsed_seconds')
        groups.setdefault(row['route'], []).append(row)
    result = {}
    for route, group in groups.items():
        totals = []
        for row in group:
            a, b = row.get('coordinator_tokens'), row.get('worker_tokens')
            totals.append(a+b if type(a) is int and type(b) is int and a >= 0 and b >= 0 else None)
        complete = all(v is not None for v in totals)
        result[route] = {'runs':len(group), 'accepted':sum(r['passed'] for r in group),
            'acceptance_rate':sum(r['passed'] for r in group)/len(group),
            'median_elapsed_seconds':statistics.median(r['elapsed_seconds'] for r in group),
            'total_tokens':sum(totals) if complete else None,
            'usage_completeness':'complete' if complete else 'unknown_or_partial',
            'cases':sorted({r['case_id'] for r in group})}
    return {'routes':result, 'note':'Compare identical baselines and acceptance in independent sessions. This does not prove causality or billed cost.'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('jsonl'); a = p.parse_args()
    print(json.dumps(summarize([json.loads(x) for x in Path(a.jsonl).read_text().splitlines() if x.strip()]), indent=2))
