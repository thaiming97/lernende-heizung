"""Attrappe für Windows – nur damit die HA-Testumgebung importierbar ist (HA läuft sonst nur unter Linux)."""
LOCK_EX = LOCK_NB = LOCK_UN = LOCK_SH = 0
F_GETFL = F_SETFL = 0


def flock(*_a, **_k):
    return None


def lockf(*_a, **_k):
    return None


def fcntl(*_a, **_k):
    return 0


def ioctl(*_a, **_k):
    return 0
