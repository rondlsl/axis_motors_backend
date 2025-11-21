from datetime import datetime, timedelta


ALMATY_OFFSET = timedelta(hours=5)


def get_local_time() -> datetime:
    """
    Return naive datetime shifted to GMT+5 (Almaty time).
    """
    return datetime.utcnow() + ALMATY_OFFSET

