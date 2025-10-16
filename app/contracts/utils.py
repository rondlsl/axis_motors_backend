from __future__ import annotations

import base64
from typing import Tuple


def decode_file_content_and_extension(file_content_str: str) -> Tuple[bytes, str]:
    """
    Decode given data URL or raw base64 string to bytes and infer a suitable file extension.

    Supported extensions: .pdf, .docx, .txt, .jpg, .png, .gif
    Defaults to .pdf if content type is unknown or missing.
    """
    default_ext = ".pdf"

    if not isinstance(file_content_str, str) or not file_content_str:
        raise ValueError("file_content must be a non-empty base64 or data URL string")

    # data URL: data:<mime>;base64,<data>
    if file_content_str.startswith("data:"):
        try:
            header, base64_data = file_content_str.split(",", 1)
        except ValueError:
            raise ValueError("Invalid data URL format")

        # Infer extension from MIME
        if "application/pdf" in header:
            ext = ".pdf"
        elif (
            "application/msword" in header
            or "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in header
        ):
            ext = ".docx"
        elif "text/plain" in header:
            ext = ".txt"
        elif "image/jpeg" in header:
            ext = ".jpg"
        elif "image/png" in header:
            ext = ".png"
        elif "image/gif" in header:
            ext = ".gif"
        else:
            ext = default_ext

        try:
            file_bytes = base64.b64decode(base64_data)
        except Exception as exc:
            raise ValueError(f"Failed to decode base64 data: {exc}")

        return file_bytes, ext

    # Plain base64 without header
    try:
        file_bytes = base64.b64decode(file_content_str)
    except Exception as exc:
        raise ValueError(f"Failed to decode base64 data: {exc}")

    return file_bytes, default_ext


