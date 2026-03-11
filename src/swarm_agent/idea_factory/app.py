"""Idea Factory web app — a single text box behind basic auth that creates GitHub issues."""

from __future__ import annotations

import functools
import logging
import os
import subprocess

from flask import Flask, flash, redirect, render_template, request, url_for
from werkzeug.exceptions import Unauthorized

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("IDEA_FACTORY_SECRET_KEY", os.urandom(32).hex())

    username = os.environ.get("IDEA_FACTORY_USERNAME", "")
    password = os.environ.get("IDEA_FACTORY_PASSWORD", "")
    repo = os.environ.get("SWARM_REPO", "")
    gh_token = os.environ.get("GITHUB_TOKEN", "")

    if not username or not password:
        raise RuntimeError("IDEA_FACTORY_USERNAME and IDEA_FACTORY_PASSWORD must be set")
    if not repo:
        raise RuntimeError("SWARM_REPO must be set")
    if not gh_token:
        raise RuntimeError("GITHUB_TOKEN must be set")

    def require_auth(f):
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            auth = request.authorization
            if not auth or auth.username != username or auth.password != password:
                raise Unauthorized()
            return f(*args, **kwargs)
        return decorated

    @app.errorhandler(Unauthorized)
    def handle_unauthorized(_):
        return (
            "Unauthorized",
            401,
            {"WWW-Authenticate": 'Basic realm="Idea Factory"'},
        )

    @app.route("/", methods=["GET"])
    @require_auth
    def index():
        return render_template("index.html")

    @app.route("/submit", methods=["POST"])
    @require_auth
    def submit():
        title = request.form.get("title", "").strip()
        body = request.form.get("body", "").strip()

        if not title:
            flash("Title is required.", "error")
            return redirect(url_for("index"))

        try:
            result = subprocess.run(
                [
                    "gh", "issue", "create",
                    "--repo", repo,
                    "--title", title,
                    "--body", body or "(No description provided)",
                    "--label", "idea",
                ],
                capture_output=True,
                text=True,
                check=True,
                env={**os.environ, "GH_TOKEN": gh_token},
                timeout=30,
            )
            issue_url = result.stdout.strip()
            logger.info("Created issue: %s", issue_url)
            flash(f"Idea submitted! {issue_url}", "success")
        except subprocess.CalledProcessError as e:
            logger.error("Failed to create issue: %s", e.stderr)
            flash("Failed to create issue. Please try again.", "error")
        except subprocess.TimeoutExpired:
            logger.error("Timed out creating issue")
            flash("Request timed out. Please try again.", "error")

        return redirect(url_for("index"))

    @app.route("/healthz")
    def healthz():
        return "ok", 200

    return app
