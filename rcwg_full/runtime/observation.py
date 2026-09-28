"""Trusted, versioned observation choices; never inferred from plan contents."""
PROFILE = {
    'revision': 'full001-observation-2',
    'journal': 'full001-block-events-2',
    'python_heap_inventory': 'NOT_MEASURED',
    'python_aliases': 'EXACT_REACHABLE_IDENTITY',
    'buffer_lifetime': 'ONLINE_TIMESTAMP_GROUPS',
    'cgroup_counters': 'PERIODIC_100MS',
    'timing': 'CONTROLLER_GO_TO_COMMITTED_RESULT_RECEIPT',
}


def validate_observation(profile):
    if profile is None:
        return None
    if profile != PROFILE:
        raise ValueError('OBSERVATION_PROFILE_UNKNOWN')
    return dict(PROFILE)


class Lifetime:
    """Online integral with releases before creates at equal timestamps."""
    def __init__(self):
        self.time = None
        self.live = self.peak = self.area = 0
        self.creates = self.releases = 0

    def change(self, ns, delta):
        if self.time is not None and ns < self.time:
            raise ValueError('LIFETIME_CLOCK')
        if self.time is not None and ns != self.time:
            self._commit()
            self.area += self.live * (ns - self.time)
        self.time = ns
        if delta >= 0: self.creates += delta
        else: self.releases += delta

    def _commit(self):
        self.live += self.releases
        self.peak = max(self.peak, self.live)
        self.live += self.creates
        self.peak = max(self.peak, self.live)
        self.creates = self.releases = 0

    def snapshot(self, ns):
        if self.time is not None and ns < self.time:
            raise ValueError('LIFETIME_CLOCK')
        live = self.live + self.releases + self.creates
        return {'peak_bytes': max(self.peak, self.live + self.releases, live),
                'byte_seconds': (self.area + live * (ns - self.time) if self.time is not None else 0) / 1e9}
