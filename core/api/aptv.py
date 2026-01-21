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

# core/api/aptv.py (patched)
# - Add targetId/targetType support for clip URLs
# - Add diagnostics for non-JSON responses (status/content-type/body snippet)
# - Add playables fallback when clips endpoint fails


class AppleTVPlus:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers = HEADERS

        # URL context (filled by __get_url)
        self.id = None
        self.kind = None
        self.targetId = None
        self.targetType = None

        self.__get_access_token()

    def __get_access_token(self):
        logger.info("Fetching access-token from web...")

        try:
            r = requests.get("https://tv.apple.com/us")
        except Exception:
            logger.warning("SSL failed! Trying without SSL...")
            r = requests.get("https://tv.apple.com/us", verify=False)

        if r.status_code != 200:
            logger.error("Failed to get https://tv.apple.com/. Try-again...", 1)

        c = BeautifulSoup(r.text, "html.parser")
        m = c.find(
            "script",
            attrs={
                "type": "application/json",
                "id": "serialized-server-data",
            },
        )

        accessToken = json.loads(m.text)
        accessToken = accessToken[0]["data"]["configureParams"]["developerToken"]
        self.session.headers.update({"authorization": f"Bearer {accessToken}"})

    def __get_url(self, url):
        logger.info("Checking and parsing url...")

        def check(_url):
            try:
                try:
                    rr = requests.get(_url)
                except Exception:
                    logger.warning("SSL failed! Trying without SSL...")
                    rr = requests.get(_url, verify=False)
                if rr.status_code == 200:
                    return True
            except Exception:
                return False

        u = urlparse(url)

        if not u.scheme:
            url = f"https://{url}"
            u = urlparse(url)

        if u.netloc != "tv.apple.com":
            logger.error("URL is invalid! Host should be tv.apple.com!", 1)

        if not check(url):
            logger.error("URL is invalid! Please check the URL!", 1)

        # Parse path parts: /<storefront>/<kind>/<slug>/<id>
        s = u.path.split("/")

        # Reset context
        self.targetId = None
        self.targetType = None

        # Parse query for context (important for /clip/ URLs)
        q = parse_qs(u.query or "")
        self.targetId = (q.get("targetId") or [None])[0]
        self.targetType = (q.get("targetType") or [None])[0]

        # Default parsing
        self.id = s[-1]
        self.kind = s[2] if len(s) > 2 else None

        # Existing special-case logic for episodes/seasons -> show with showId query
        if self.kind in ["episode", "season"]:
            self.kind = "show"
            if "showId" in q and q["showId"]:
                self.id = q["showId"][0]
            else:
                # old logic used u.query.replace('showId=', '')
                # keep a compatible fallback
                if "showId=" in (u.query or ""):
                    self.id = (u.query or "").replace("showId=", "")
                else:
                    logger.error("Unable to parse showId from URL!", 1)

        if not self.kind or not self.id:
            logger.error("Unable to parse kind/id from URL path!", 1)

    def __base_params(self):
        # Keep original params; clip/playable requests may need extra context params.
        return {
            "caller": "web",
            "locale": "en-US",
            "pfm": "appletv",
            "sf": "143441",
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

        # Provide clip context params if present (important for /clip/... urls)
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
            coverImage = (
                data["data"]["content"]["backgroundVideo"]["images"]["contentImage"]["url"].format(
                    w=data["data"]["content"]["backgroundVideo"]["images"]["contentImage"]["width"],
                    h=data["data"]["content"]["backgroundVideo"]["images"]["contentImage"]["height"],
                    f="jpg",
                )
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

        # Extract a playable-like object
        playable = None
        if isinstance(d.get("playable"), dict):
            playable = d.get("playable")
        elif isinstance(d.get("playables"), list) and d.get("playables"):
            playable = d.get("playables")[0]
        elif isinstance(d.get("content"), dict):
            # Some endpoints may put playable-ish structure under content
            playable = d.get("content")

        # Pull hlsUrl
        hlsUrl = None
        if isinstance(playable, dict):
            hlsUrl = (playable.get("assets") or {}).get("hlsUrl")

        # Fallback: deep-ish search for first hlsUrl
        if not hlsUrl:
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

        # Clip title + cover (best-effort)
        videoTitle = ""
        coverImage = None
        if isinstance(playable, dict):
            videoTitle = playable.get("title") or ""

            cm = playable.get("canonicalMetadata") or {}
            img = (cm.get("images") or {}).get("contentImage") or None
            if isinstance(img, dict):
                coverImage = img_from_obj(img)

            # Some responses may have images at top-level
            if not coverImage:
                img2 = (playable.get("images") or {}).get("contentImage") or None
                if isinstance(img2, dict):
                    coverImage = img_from_obj(img2)

        if not videoTitle:
            videoTitle = "Clip"

        # Base meta (fallback)
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
            # Try some local metadata fields if present
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
