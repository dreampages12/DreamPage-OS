def __getattr__(name):
    # Planlegging og godkjenningskontroll skal ikke laste torch eller GPU.
    if name == "build_model":
        from .factory import build_model
        return build_model
    raise AttributeError(name)

__all__ = ["build_model"]
