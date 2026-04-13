import os
import requests
from datetime import datetime, timezone
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import praw
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder="public", static_url_path="")
CORS(app)

# --- Reddit client (read-only, no user login required) ---
reddit = praw.Reddit(
    client_id=os.environ["REDDIT_CLIENT_ID"],
    client_secret=os.environ["REDDIT_CLIENT_SECRET"],
    user_agent=os.environ.get("REDDIT_USER_AGENT", "web:PlotArmor:1.0"),
)

TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
TMDB_BASE = "https://api.themoviedb.org/3"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def comment_to_dict(comment, depth=0):
    """Recursively convert a PRAW Comment to a plain dict."""
    return {
        "id": comment.id,
        "author": str(comment.author) if comment.author else "[deleted]",
        "body": comment.body,
        "score": comment.score,
        "created_utc": comment.created_utc,
        "depth": depth,
        "replies": [
            comment_to_dict(reply, depth + 1)
            for reply in comment.replies
            if hasattr(reply, "body")  # skip MoreComments stubs
        ],
    }


def tmdb_search_show(query):
    resp = requests.get(
        f"{TMDB_BASE}/search/tv",
        params={"api_key": TMDB_API_KEY, "query": query},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if not results:
        return None
    return results[0]  # best match


def tmdb_episode_air_date(show_id, season, episode):
    resp = requests.get(
        f"{TMDB_BASE}/tv/{show_id}/season/{season}/episode/{episode}",
        params={"api_key": TMDB_API_KEY},
        timeout=10,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json().get("air_date")  # "YYYY-MM-DD"


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
        submission = reddit.submission(url=url)
        # Expand all "load more" comment stubs (up to 512 extra API calls max)
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

        comments = [comment_to_dict(c) for c in submission.comments if hasattr(c, "body")]

        return jsonify({"post": post, "comments": comments})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/episode")
def get_episode():
    """
    Look up the air date of the NEXT episode after what the user has watched.
    Params: show, season (int), episode (int)
    Returns: { cutoffDate, nextEpisode, showName }
    """
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

        # Try next episode in same season first
        next_ep = episode + 1
        next_season = season
        air_date = tmdb_episode_air_date(show_id, next_season, next_ep)

        # If not found, try first episode of next season
        if air_date is None:
            next_season = season + 1
            next_ep = 1
            air_date = tmdb_episode_air_date(show_id, next_season, next_ep)

        if air_date is None:
            # User is on the series finale — no spoilers possible
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
    """Return top TMDB matches for a show name (for autocomplete / confirmation)."""
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
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
