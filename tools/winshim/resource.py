"""Attrappe für Windows (nur Tests)."""
RLIMIT_NOFILE = 7


def getrlimit(_r):
    return (4096, 4096)


def setrlimit(_r, _v):
    return None
