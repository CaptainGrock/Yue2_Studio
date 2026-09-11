"""Turn native console progress into UI data without inventing generation totals."""
import re

LINE = re.compile(r'^\[YuE2\] (Starting|Running|Completed|Failed|Cancelled|Finished \(generation limit reached\)) (.+?): (.+)$')


def read_progress(log, status):
    stages = {}
    for line in log.replace('\r', '\n').splitlines():
        match = LINE.match(line)
        if not match:
            continue
        action, label, detail = match.groups()
        state = {'Starting':'running', 'Running':'running', 'Completed':'completed',
                 'Failed':'failed', 'Cancelled':'cancelled',
                 'Finished (generation limit reached)':'truncated'}[action]
        count = re.search(r'^(\d+)(?:/(\d+))? (tokens|steps|items)\b', detail)
        elapsed = re.search(r'elapsed ([\d.]+)s', detail)
        speed = re.search(r'([\d.]+) tokens/s', detail)
        stages[label] = {'label':label, 'status':state, 'detail':detail,
                         'completed':int(count[1]) if count else None,
                         'total':int(count[2]) if count and count[2] else None,
                         'unit':count[3] if count else None,
                         'elapsed':float(elapsed[1]) if elapsed else None,
                         'tokens_per_second':float(speed[1]) if speed else None}
    items = list(stages.values())
    if items and status in ('failed','cancelled','interrupted') and items[-1]['status']=='running':
        items[-1]['status']=status
    return {'stages':items, 'current':items[-1] if items else None,
            'status':status}
