"""Community Xiaohongshu adapter for clipsieve. See README.md for licence constraints."""

__all__ = ["XhsMediaCrawlerAdapter"]


def __getattr__(name: str):
    if name == "XhsMediaCrawlerAdapter":
        from clipsieve_xhs.adapter import XhsMediaCrawlerAdapter

        return XhsMediaCrawlerAdapter
    raise AttributeError(name)
