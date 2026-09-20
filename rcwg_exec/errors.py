"""Machine-readable failures without data values, paths or provider messages."""
class ExecFault(Exception):
    def __init__(self, code: str, attribution: str = 'facility'):
        self.code, self.attribution = code, attribution
        super().__init__(code)
