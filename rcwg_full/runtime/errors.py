"""Structured failures shared by Python scheduling and the native translator."""


class ExecutionFault(RuntimeError):
    def __init__(self, code, attribution='plan', *, stage=None, node_instance=None, origin='python'):
        super().__init__(code)
        self.code = code
        self.attribution = attribution
        self.stage = stage
        self.node_instance = node_instance
        self.origin = origin

    def record(self):
        return {'code': self.code, 'attribution': self.attribution, 'detail': str(self),
                'stage': self.stage, 'node_instance': self.node_instance, 'origin': self.origin}
