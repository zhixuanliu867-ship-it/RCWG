"""Explicit diagnostic scheduling limits; public resource budgets are unchanged."""
from copy import deepcopy


def validate_profile(task,profile):
    if profile is None:return None
    if type(profile) is not dict or set(profile)!={'revision','cpu_kernel_concurrency','map_parallelism'} or profile['revision']!='FULL001_SCHEDULE_1':raise ValueError('SCHEDULING_PROFILE')
    for field in ['cpu_kernel_concurrency','map_parallelism']:
        if type(profile[field]) is not int or not 1<=profile[field]<=task['resources']['cpu_slots']:raise ValueError('SCHEDULING_PROFILE_RANGE')
    return deepcopy(profile)
