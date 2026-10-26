"""Keep only public HTTP(S) image URLs actually supplied by a POI source."""

import ipaddress
from urllib.parse import urlsplit


def poi_images(raw: dict) -> list[str]:
    found = []
    values = [raw.get("photo"), raw.get("photos"), raw.get("image_urls")]
    for value in values:
        entries = value if isinstance(value, list) else [value]
        for entry in entries[:10]:
            url = entry.get("url") if isinstance(entry, dict) else entry
            if not isinstance(url, str) or len(url) > 2048:
                continue
            try:
                url = url.strip()
                parsed = urlsplit(url)
                host = (parsed.hostname or "").lower()
                if (
                    parsed.scheme not in ("https", "http")
                    or parsed.username
                    or parsed.password
                    or not host
                    or "." not in host
                    or host.endswith((".local", ".localhost"))
                ):
                    continue
                try:
                    if not ipaddress.ip_address(host).is_global:
                        continue
                except ValueError:
                    pass
                if url not in found:
                    found.append(url.strip())
            except ValueError:
                continue
    return found[:3]
