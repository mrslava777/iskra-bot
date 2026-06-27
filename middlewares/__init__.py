"""Middleware-слой бота (анти-флуд и пр.)."""
from middlewares.throttling import ThrottlingMiddleware

__all__ = ["ThrottlingMiddleware"]
