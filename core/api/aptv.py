import json
import requests
import datetime
import warnings

from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs

from utils import logger

warnings.filterwarnings("ignore")

HEADERS = {
    "content-type": "application/json",
    "accept-encoding": "gzip, deflate, br",
    "accept-language": "en-US,en;q=0.9",
    "origin": "https://tv.apple.com",
    "referer": "https://tv.apple.com/",
    "user-agent": "AppleTV6,2/11.1",
}

# core/api/aptv.py @ v0.2.1
#
# Goals:
# - Storefront-aware developerToken and API context:
#   - Extract storefront from input URL path (e.g. /be/movie/... -> "be")
#   - Fetch developerToken from https://tv.apple.com/<storefront>
#   - Try to derive sf (storeFrontId) and locale from serialized-server-data / HTML
#   - Use derived sf/locale for UTS requests (instead of always US context)
#
# - Keep v0.2.0 improvements:
#   - targetId/targetType support for clip URLs
#   - diagnostics for non-JSON responses (status/content-type/body snippet)
#   - playables fallback when clips endpoint fails


def _deep_find_first(obj, predicate):
    """
    Recursively search nested dict/list and return first value where predicate(key, value) is True.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            try:
                if predicate(k, v):
                    return v
            except Exception:
                pass
            r = _deep_find_first(v, predicate)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for it in obj:
            r = _deep_find_first(it, predicate)
            if r is not None:
                return r
    return None


def _as_int(x):
    try:
        return int(x)
    except Exception:
        return None


class AppleTVPlus:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers = dict(HEADERS)

        # URL context (filled by __get_url)
        self.id = None
        self.kind = None
        self.targetId = None
        self.targetType = None
        self.storefront = None

        # Storefront-configured API context (best-effort)
        self.sf = None
        self.locale = None

        # Track which storefront the token/context was fetched from
        self._token_storefront = None

        # Default init (US), may be replaced once a URL is parsed
        self.__get_access_token(storefront="us")

    def __get_access_token(self, storefront: str):
        """
        Fetch developerToken from https://tv.apple.com/<storefront> (NOT fixed to /us).
        Also tries to derive sf/locale from the page JSON/HTML.
        """
        storefront = (storefront or "us").strip().lower()
        home_url = f"https://tv.apple.com/{storefront}"

        logger.info(f"Fetching access-token from web... (storefront={storefront})")

        try:
            r = requests.get(home_url, timeout=30)
        except Exception:
            logger.warning("SSL failed! Trying without SSL...")
            r = requests.get(home_url, timeout=30, verify=False)

        if r.status_code != 200:
            snippet = (r.text or "").replace("\n", " ")[:120]
            logger.error(
                f"Failed to get {home_url} (status={r.status_code}) body[:120]={snippet}. Try-again...",
                1,
            )

        html = r.text
        soup = BeautifulSoup(html, "html.parser")

        # Try derive locale from <html lang="...">
        try:
            lang = (soup.html.get("lang") or "").strip()
        except Exception:
            lang = ""

        # Find serialized-server-data
        m = soup.find("script", attrs={"type": "application/json", "id": "serialized-server-data"})
        if not m or not m.text:
            logger.error('Unable to locate "serialized-server-data" on Apple TV home page.', 1)

        try:
            server_data = json.loads(m.text)
        except Exception as e:
            logger.error(f"Unable to parse serialized-server-data JSON: {e}", 1)

        # developerToken location (same as original)
        try:
            accessToken = server_data[0]["data"]["configureParams"]["developerToken"]
        except Exception:
            logger.error("Unable to extract developerToken from serialized-server-data.", 1)

        self.session.headers.update({"authorization": f"Bearer {accessToken}"})
        self._token_storefront = storefront

        # Try derive storeFrontId (sf) from JSON
        sf_val = _deep_find_first(
            server_data,
            lambda k, v: str(k).lower() in ("storefrontid", "storefrontid", "storefront", "storefront-id", "sf")
            and _as_int(v) is not None
            and 100000 <= int(v) <= 999999,
        )
        sf_int = _as_int(sf_val)

        # Known fallback mapping (best-effort)
        sf_fallback_map = {
            "us": 143441,
            "be": 143446,  # common iTunes storefront id for Belgium
            "gb": 143444,  # (best-effort; may vary)
            "fr": 143442,  # (best-effort; may vary)
            "de": 143443,  # (best-effort; may vary)
        }

        if sf_int:
            self.sf = sf_int
        else:
            # fallback by storefront code, else default to US sf
            self.sf = sf_fallback_map.get(storefront, 143441)

        # Locale: prefer html lang if it looks like xx-YY, else keep en-US
        if lang and ("-" in lang) and (len(lang) >= 4):
            self.locale = lang
        else:
            # Try to find a locale-like value in JSON
            loc_val = _deep_find_first(
                server_data,
                lambda k, v: str(k).lower() == "locale" and isinstance(v, str) and "-" in v and len(v) >= 4,
            )
            self.locale = str(loc_val) if isinstance(loc_val, str) else "en-US"

        logger.info(f"Storefront context: storefront={storefront} sf={self.sf} locale={self.locale}")

    def __check_url_reachable(self, url: str) -> bool:
        try:
            rr = requests.get(url, timeout=20)
        except Exception:
            logger.warning("SSL failed! Trying without SSL...")
            rr = requests.get(url, timeout=20, verify=False)

        if rr.status_code == 200:
            return True

        snippet = (rr.text or "").replace("\n", " ")[:120]
        logger.error(
            f"URL is invalid or not reachable (status={rr.status_code}). Please check the URL! body[:120]={snippet}",
            1,
        )
        return False

    def __get_url(self, url):
        logger.info("Checking and parsing url...")

        u = urlparse(url)

        if not u.scheme:
            url = f"https://{url}"
            u = urlparse(url)

        if u.netloc != "tv.apple.com":
            logger.error("URL is invalid! Host should be tv.apple.com!", 1)

        # Quick reachability check (keeps old behavior, but with status diagnostics)
        self.__check_url_reachable(url)

        # Path parts: /<storefront>/<kind>/<slug>/<id>
        parts = u.path.split("/")
        # parts example: ["", "be", "movie", "tron-legacy", "umc.cmc.xxxxx"]
        sf_code = parts[1].strip().lower() if len(parts) > 1 and parts[1] else "us"
        kind = parts[2].strip().lower() if len(parts) > 2 and parts[2] else None
        cid = parts[-1].strip() if parts and parts[-1] else None

        # Parse query for context (important for /clip/ URLs)
        q = parse_qs(u.query or "")
        self.targetId = (q.get("targetId") or [None])[0]
        self.targetType = (q.get("targetType") or [None])[0]

        # Handle episodes/seasons -> show, via showId query
        if kind in ("episode", "season"):
            kind = "show"
            show_ids = q.get("showId") or []
            if show_ids:
                cid = show_ids[0]
            else:
                # compatible fallback
                if "showId=" in (u.query or ""):
                    cid = (u.query or "").replace("showId=", "")
                else:
                    logger.error("Unable to parse showId from URL!", 1)

        if not kind or not cid:
            logger.error("Unable to parse kind/id from URL path!", 1)

        self.storefront = sf_code
        self.kind = kind
        self.id = cid

        # Ensure token/context matches storefront
        if self._token_storefront != self.storefront:
            self.__get_access_token(storefront=self.storefront)

    def __base_params(self):
        # Keep original params but make sf/locale dynamic (storefront aware)
        return {
            "caller": "web",
            "locale": self.locale or "en-US",
            "pfm": "appletv",
            "sf": str(self.sf or 143441),
            "utscf": "OjAAAAAAAAA~",
            "utsk": "6e3013c6d6fae3c2::::::235656c069bb0efb",
            "v": "68",
        }

    def __request_json(self, collection: str, content_id: str, extra_params: dict | None = None):
        """
        collection: already plural, e.g. "movies", "shows", "clips", "playables"
        Returns: dict on success, None on non-JSON / non-200 response.
        """
        apiUrl = f"https://tv.apple.com/api/uts/v3/{collection}/{content_id}"
        params = self.__base_params()
        if extra_params:
            params.update(extra_params)

        try:
            r = self.session.get(url=apiUrl, params=params)
        except Exception:
            logger.warning("SSL failed! Trying without SSL...")
            r = self.session.get(url=apiUrl, params=params, verify=False)

        ct = (r.headers.get("content-type") or "").lower()
        if r.status_code != 200:
            snippet = (r.text or "").replace("\n", " ")[:200]
            logger.warning(
                f"API request failed (status={r.status_code}) "
                f"url={getattr(r, 'url', apiUrl)} ct={ct} body[:200]={snippet}"
            )
            return None

        try:
            return r.json()
        except Exception:
            snippet = (r.text or "").replace("\n", " ")[:200]
            logger.warning(
                f"API response is not JSON "
                f"url={getattr(r, 'url', apiUrl)} ct={ct} body[:200]={snippet}"
            )
            return None

    def __get_json(self):
        logger.info("Fetching API response...")

        # Provide clip context params if present
        extra = {}
        if self.targetId:
            extra["targetId"] = self.targetId
        if self.targetType:
            extra["targetType"] = self.targetType

        # Normal kinds (movie/show) keep old behavior
        if self.kind != "clip":
            data = self.__request_json(f"{self.kind}s", self.id, extra_params=None)
            if data is None:
                logger.error("Failed to fetch API JSON response.", 1)
            return data

        # Clip kind: try /clips/<id> first, then fallback to /playables/<id>
        data = self.__request_json("clips", self.id, extra_params=extra or None)
        if data is not None:
            return data

        logger.warning("clips endpoint failed; trying playables endpoint fallback...")
        data = self.__request_json("playables", self.id, extra_params=extra or None)
        if data is not None:
            return data

        logger.error("Failed to fetch clip/playable API JSON response.", 1)

    def __get_default(self):
        def genres(genre):
            if not isinstance(genre, list):
                genre = [genre]
            return [g.get("name") for g in genre if isinstance(g, dict) and g.get("name")]

        def fixdate(date_ms):
            try:
                return datetime.datetime.utcfromtimestamp(date_ms / 1000.0).strftime("%Y-%m-%d")
            except Exception:
                return "0000-00-00"

        data = self.__get_json()

        try:
            coverImage = data["data"]["content"]["backgroundVideo"]["images"]["contentImage"]["url"].format(
                w=data["data"]["content"]["backgroundVideo"]["images"]["contentImage"]["width"],
                h=data["data"]["content"]["backgroundVideo"]["images"]["contentImage"]["height"],
                f="jpg",
            )
        except Exception:
            coverImage = None

        return {
            "hlsUrl": data["data"]["content"]["backgroundVideo"]["assets"]["hlsUrl"],
            "cover": coverImage,
            "videoTitle": data["data"]["content"]["backgroundVideo"].get("title") or "",
            "title": data["data"]["content"].get("title") or "Unknown Title",
            "releaseDate": fixdate(data["data"]["content"].get("releaseDate")),
            "description": data["data"]["content"].get("description") or "",
            "genres": genres(data["data"]["content"].get("genres") or []),
        }

    def __get_trailers(self):
        def genres(genre):
            if not isinstance(genre, list):
                genre = [genre]
            return [g.get("name") for g in genre if isinstance(g, dict) and g.get("name")]

        def fixdate(date_ms):
            try:
                return datetime.datetime.utcfromtimestamp(date_ms / 1000.0).strftime("%Y-%m-%d")
            except Exception:
                return "0000-00-00"

        data = self.__get_json()

        backgroundVideos = next(
            (shelve.get("items") for shelve in data["data"]["canvas"]["shelves"] if shelve.get("title") == "Trailers"),
            None,
        )

        dataList = []

        if backgroundVideos:
            for item in backgroundVideos:
                try:
                    coverImage = item["playables"][0]["canonicalMetadata"]["images"]["contentImage"]["url"].format(
                        w=item["playables"][0]["canonicalMetadata"]["images"]["contentImage"]["width"],
                        h=item["playables"][0]["canonicalMetadata"]["images"]["contentImage"]["height"],
                        f="jpg",
                    )
                except Exception:
                    coverImage = None

                dataList.append(
                    {
                        "hlsUrl": item["playables"][0]["assets"]["hlsUrl"],
                        "cover": coverImage,
                        "videoTitle": item["playables"][0].get("title") or "",
                        "title": data["data"]["content"].get("title") or "Unknown Title",
                        "releaseDate": fixdate(data["data"]["content"].get("releaseDate")),
                        "description": data["data"]["content"].get("description") or "",
                        "genres": genres(data["data"]["content"].get("genres") or []),
                    }
                )

            return dataList
        else:
            return [self.__get_default()]

    def __get_clip(self):
        """
        Best-effort clip/playable parser. Returns a single item with an hlsUrl.
        Also tries to enrich title/releaseDate/genres/description from targetId (Movie) when present.
        """

        def fixdate(date_ms):
            try:
                return datetime.datetime.utcfromtimestamp(date_ms / 1000.0).strftime("%Y-%m-%d")
            except Exception:
                return "0000-00-00"

        def genres(genre):
            if not isinstance(genre, list):
                genre = [genre]
            return [g.get("name") for g in genre if isinstance(g, dict) and g.get("name")]

        def img_from_obj(img_obj):
            try:
                return img_obj["url"].format(w=img_obj["width"], h=img_obj["height"], f="jpg")
            except Exception:
                return None

        data = self.__get_json()
        d = data.get("data") or {}

        playable = None
        if isinstance(d.get("playable"), dict):
            playable = d.get("playable")
        elif isinstance(d.get("playables"), list) and d.get("playables"):
            playable = d.get("playables")[0]
        elif isinstance(d.get("content"), dict):
            playable = d.get("content")

        hlsUrl = None
        if isinstance(playable, dict):
            hlsUrl = (playable.get("assets") or {}).get("hlsUrl")

        if not hlsUrl:
            # Deep search fallback for hlsUrl
            def find_hls(obj):
                if isinstance(obj, dict):
                    if isinstance(obj.get("hlsUrl"), str) and obj.get("hlsUrl"):
                        return obj.get("hlsUrl")
                    for v in obj.values():
                        r = find_hls(v)
                        if r:
                            return r
                elif isinstance(obj, list):
                    for v in obj:
                        r = find_hls(v)
                        if r:
                            return r
                return None

            hlsUrl = find_hls(data)

        if not hlsUrl:
            logger.error("Clip/playable JSON parsed, but no hlsUrl found.", 1)

        videoTitle = ""
        coverImage = None
        if isinstance(playable, dict):
            videoTitle = playable.get("title") or ""

            cm = playable.get("canonicalMetadata") or {}
            img = (cm.get("images") or {}).get("contentImage") or None
            if isinstance(img, dict):
                coverImage = img_from_obj(img)

            if not coverImage:
                img2 = (playable.get("images") or {}).get("contentImage") or None
                if isinstance(img2, dict):
                    coverImage = img_from_obj(img2)

        if not videoTitle:
            videoTitle = "Clip"

        # Base meta
        title = "Unknown Title"
        releaseDate = "0000-00-00"
        description = ""
        genres_list = []

        # Enrich from target movie if available
        if self.targetType == "Movie" and self.targetId:
            logger.info("Fetching target movie metadata for clip (targetId)...")
            movie_data = self.__request_json("movies", self.targetId, extra_params=None)
            if movie_data and movie_data.get("data", {}).get("content"):
                c = movie_data["data"]["content"]
                title = c.get("title") or title
                releaseDate = fixdate(c.get("releaseDate"))
                description = c.get("description") or ""
                genres_list = genres(c.get("genres") or [])
        else:
            content = d.get("content") if isinstance(d.get("content"), dict) else None
            if content:
                title = content.get("title") or title
                releaseDate = fixdate(content.get("releaseDate"))
                description = content.get("description") or description
                genres_list = genres(content.get("genres") or [])

        return {
            "hlsUrl": hlsUrl,
            "cover": coverImage,
            "videoTitle": videoTitle,
            "title": title,
            "releaseDate": releaseDate,
            "description": description,
            "genres": genres_list,
        }

    def get_info(self, url, default):
        self.__get_url(url)

        # If it's a clip page, treat it as a single playable item.
        if self.kind == "clip":
            return [self.__get_clip()]

        if default:
            return [self.__get_default()]
        else:
            return self.__get_trailers()
