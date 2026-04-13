import os
import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder="public", static_url_path="")
CORS(app)

TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
TMDB_BASE = "https://api.themoviedb.org/3"

REDDIT_BACKEND = os.environ.get("REDDIT_BACKEND", "json").lower()  # "json" or "praw"
REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "web:PlotArmor:1.0")

# ---------------------------------------------------------------------------
# Reddit backend: PRAW
# ---------------------------------------------------------------------------
_reddit = None

def get_praw_client():
    global _reddit
    if _reddit is None:
        import praw
        _reddit = praw.Reddit(
            client_id=os.environ["REDDIT_CLIENT_ID"],
            client_secret=os.environ["REDDIT_CLIENT_SECRET"],
            user_agent=REDDIT_USER_AGENT,
        )
    return _reddit


def fetch_thread_praw(url):
    reddit = get_praw_client()
    submission = reddit.submission(url=url)
    submission.comments.replace_more(limit=32)

    post = {
        "title": submission.title,
        "author": str(submission.author) if submission.author else "[deleted]",
        "subreddit": submission.subreddit.display_name,
        "score": submission.score,
        "created_utc": submission.created_utc,
        "selftext": submission.selftext,
        "url": submission.url,
        "num_comments": submission.num_comments,
    }
    comments = [_praw_comment_to_dict(c) for c in submission.comments if hasattr(c, "body")]
    return post, comments


def _praw_comment_to_dict(comment, depth=0):
    return {
        "id": comment.id,
        "author": str(comment.author) if comment.author else "[deleted]",
        "body": comment.body,
        "score": comment.score,
        "created_utc": comment.created_utc,
        "depth": depth,
        "replies": [
            _praw_comment_to_dict(r, depth + 1)
            for r in comment.replies
            if hasattr(r, "body")
        ],
    }


# ---------------------------------------------------------------------------
# Reddit backend: .json
# ---------------------------------------------------------------------------

def fetch_thread_json(url):
    json_url = url.split("?")[0].rstrip("/") + ".json"
    resp = requests.get(
        json_url,
        headers={"User-Agent": REDDIT_USER_AGENT},
        params={"limit": 500, "depth": 10, "sort": "top"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    p = data[0]["data"]["children"][0]["data"]
    post = {
        "title": p["title"],
        "author": p.get("author") or "[deleted]",
        "subreddit": p["subreddit"],
        "score": p["score"],
        "created_utc": p["created_utc"],
        "selftext": p.get("selftext", ""),
        "url": p.get("url", ""),
        "num_comments": p.get("num_comments", 0),
    }
    comments = _parse_json_comments(data[1]["data"]["children"])
    return post, comments


def _parse_json_comments(children, depth=0):
    result = []
    for child in children:
        if child["kind"] != "t1":
            continue
        d = child["data"]
        replies_raw = d.get("replies")
        replies = (
            _parse_json_comments(replies_raw["data"]["children"], depth + 1)
            if isinstance(replies_raw, dict)
            else []
        )
        result.append({
            "id": d["id"],
            "author": d.get("author") or "[deleted]",
            "body": d.get("body", ""),
            "score": d.get("score", 0),
            "created_utc": d["created_utc"],
            "depth": depth,
            "replies": replies,
        })
    return result


# ---------------------------------------------------------------------------
# Shared fetch dispatcher
# ---------------------------------------------------------------------------

def fetch_thread(url):
    if REDDIT_BACKEND == "praw":
        return fetch_thread_praw(url)
    return fetch_thread_json(url)


# ---------------------------------------------------------------------------
# TMDB helpers
# ---------------------------------------------------------------------------

def tmdb_search_show(query):
    resp = requests.get(
        f"{TMDB_BASE}/search/tv",
        params={"api_key": TMDB_API_KEY, "query": query},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    return results[0] if results else None


def tmdb_episode_air_date(show_id, season, episode):
    resp = requests.get(
        f"{TMDB_BASE}/tv/{show_id}/season/{season}/episode/{episode}",
        params={"api_key": TMDB_API_KEY},
        timeout=10,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json().get("air_date")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory("public", "index.html")


@app.route("/api/thread")
def get_thread():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "Missing url parameter"}), 400
    try:
        post, comments = fetch_thread(url)
        return jsonify({"post": post, "comments": comments, "backend": REDDIT_BACKEND})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/episode")
def get_episode():
    show = request.args.get("show", "").strip()
    try:
        season = int(request.args.get("season", 0))
        episode = int(request.args.get("episode", 0))
    except ValueError:
        return jsonify({"error": "season and episode must be integers"}), 400

    if not show or not season or not episode:
        return jsonify({"error": "Missing show, season, or episode"}), 400

    try:
        show_result = tmdb_search_show(show)
        if not show_result:
            return jsonify({"error": f"Show '{show}' not found on TMDB"}), 404

        show_id = show_result["id"]
        show_name = show_result["name"]

        # Try next episode in same season, then first of next season
        air_date = tmdb_episode_air_date(show_id, season, episode + 1)
        next_season, next_ep = season, episode + 1
        if air_date is None:
            next_season, next_ep = season + 1, 1
            air_date = tmdb_episode_air_date(show_id, next_season, next_ep)

        if air_date is None:
            return jsonify({
                "cutoffDate": None,
                "nextEpisode": None,
                "showName": show_name,
                "message": "No further episodes found — you're all caught up!",
            })

        return jsonify({
            "cutoffDate": air_date,
            "nextEpisode": f"S{next_season:02d}E{next_ep:02d}",
            "showName": show_name,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/search-show")
def search_show():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])
    try:
        resp = requests.get(
            f"{TMDB_BASE}/search/tv",
            params={"api_key": TMDB_API_KEY, "query": query},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])[:5]
        return jsonify([
            {"id": r["id"], "name": r["name"], "firstAired": r.get("first_air_date", "")}
            for r in results
        ])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
