"""User-facing lane names; stable internal IDs keep existing records readable."""
def lane_label(lane):
    return {'A':'LS','B':'RS','L':'LT','R':'RT'}.get(lane,lane)
