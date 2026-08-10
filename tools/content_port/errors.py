"""One public error type for every content-port contract violation."""


class ContentPortError(ValueError):
    """An authored policy, donor, or generated result violates the contract."""
