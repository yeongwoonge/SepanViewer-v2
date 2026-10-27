"""Merge independent frame/input queues before applying reset boundaries."""
from queue import Empty


def drain_ordered(sources,limit=512):
    events=[]
    for source in sources:
        for _ in range(limit):
            try:events.append(source.get_nowait())
            except Empty:break
    timestamped={'frame','key','result_candidate','result_screen','inactive'}
    priority={'frame':0,'key':1,'result_candidate':2,'result_screen':3,'inactive':4}
    def key(item):
        index,event=item
        timed=event[0] in timestamped and len(event)>1
        return (float(event[1]) if timed else float('-inf'),priority.get(event[0],-1),index)
    return [event for _,event in sorted(enumerate(events),key=key)]
