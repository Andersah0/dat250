"""Provides all routes for the Social Insecurity application.

This file contains the routes for the application. It is imported by the social_insecurity package.
It also contains the SQL queries used for communicating with the database.
"""

from pathlib import Path

from flask import current_app as app
from flask import flash, redirect, render_template, send_from_directory, url_for, abort, session, request
from functools import wraps
from werkzeug.utils import secure_filename
import secrets

from social_insecurity import sqlite
from social_insecurity.forms import CommentsForm, FriendsForm, IndexForm, PostForm, ProfileForm


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in.", "warning")
            return redirect(url_for("index"))
        return view(*args, **kwargs)
    return wrapped

@app.route("/", methods=["GET", "POST"])
@app.route("/index", methods=["GET", "POST"])
def index():
    """Provides the index page for the application.

    It reads the composite IndexForm and based on which form was submitted,
    it either logs the user in or registers a new user.

    If no form was submitted, it simply renders the index page.
    """
    index_form = IndexForm()
    login_form = index_form.login
    register_form = index_form.register

    if login_form.validate_on_submit() and login_form.submit.data:
        user = sqlite.query(
            "SELECT * FROM Users WHERE username = ?",
            login_form.username.data,
            one=True,
        )

        if user is None:
            flash("Sorry, this user does not exist!", category="warning")
        elif user["password"] != login_form.password.data:
            flash("Sorry, wrong password!", category="warning")
        elif user["password"] == login_form.password.data:
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("stream", username=user["username"]))

    elif register_form.validate_on_submit() and register_form.submit.data:
        sqlite.query(
            "INSERT INTO Users (username, first_name, last_name, password) VALUES (?, ?, ?, ?)",
            register_form.username.data,
            register_form.first_name.data,
            register_form.last_name.data,
            register_form.password.data   
        )
        flash("User successfully created!", category="success")
        return redirect(url_for("index"))

    return render_template("index.html.j2", title="Welcome", form=index_form)

@app.route("/logout", methods=["POST", "GET"])
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("index"))


@app.route("/stream/<string:username>", methods=["GET", "POST"])
@login_required
def stream(username: str):
    """Provides the stream page for the application.

    If a form was submitted, it reads the form data and inserts a new post into the database.

    Otherwise, it reads the username from the URL and displays all posts from the user and their friends.
    """
    if username != session.get("username"):
        if request.method == "GET":
            return redirect(url_for("stream", username=session.get("username")))
        username = session.get("username")

    post_form = PostForm()
    user = sqlite.query(
        "SELECT * FROM Users WHERE id = ?",
        session["user_id"],
        one=True,
    )

    if post_form.validate_on_submit():
        filename = None
        fileobj = post_form.image.data

        if fileobj and getattr(fileobj, "filename", ""):
            raw = secure_filename(fileobj.filename)
            ext = raw.rsplit(".", 1)[-1].lower() if "." in raw else ""
            allowed = app.config.get("ALLOWED_EXTENSIONS", set())
            if ext not in allowed:
                flash("File type not allowed", "warning")
                return redirect(url_for("stream", username=username))

            unique = f"{secrets.token_hex(8)}_{raw}"
            upload_dir = Path(app.instance_path) / app.config["UPLOADS_FOLDER_PATH"]
            upload_dir.mkdir(parents=True, exist_ok=True)
            fileobj.save(upload_dir / unique)
            filename = unique

        sqlite.query(
            "INSERT INTO Posts (u_id, content, image, creation_time) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            user["id"],
            post_form.content.data,
            filename,
        )
        return redirect(url_for("stream", username=username))


    get_posts = """
        SELECT p.*, u.*, (SELECT COUNT(*) FROM Comments WHERE p_id = p.id) AS cc
        FROM Posts AS p JOIN Users AS u ON u.id = p.u_id
        WHERE p.u_id IN (SELECT u_id FROM Friends WHERE f_id = ?)
        OR p.u_id IN (SELECT f_id FROM Friends WHERE u_id = ?)
        OR p.u_id = ?
        ORDER BY p.creation_time DESC
    """
    posts = sqlite.query(get_posts, user["id"], user["id"], user["id"])

    return render_template("stream.html.j2", title="Stream", username=username, form=post_form, posts=posts)


@app.route("/comments/<string:username>/<int:post_id>", methods=["GET", "POST"])
@login_required
def comments(username: str, post_id: int):
    """Provides the comments page for the application.

    If a form was submitted, it reads the form data and inserts a new comment into the database.

    Otherwise, it reads the username and post id from the URL and displays all comments for the post.
    """
    if username != session.get("username"):
        if request.method == "GET":
            return redirect(url_for("comments", username=session.get("username"), post_id=post_id))
        username = session.get("username")

    comments_form = CommentsForm()
    user = sqlite.query(
        "SELECT * FROM Users WHERE id = ?",
        session["user_id"],
        one=True,
    )

    if comments_form.validate_on_submit():
        sqlite.query(
            "INSERT INTO Comments (p_id, u_id, comment, creation_time) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            post_id,
            user["id"],
            comments_form.comment.data
        )
    post = sqlite.query(
        "SELECT * FROM Posts AS p JOIN Users AS u ON p.u_id = u.id WHERE p.id = ?",
        post_id,
        one=True,
    )

    comments = sqlite.query(
        """
        SELECT DISTINCT *
        FROM Comments AS c JOIN Users AS u ON c.u_id = u.id
        WHERE c.p_id = ?
        ORDER BY c.creation_time DESC
        """,
        post_id
    )

    return render_template(
        "comments.html.j2", title="Comments", username=username, form=comments_form, post=post, comments=comments
    )


@app.route("/friends/<string:username>", methods=["GET", "POST"])
@login_required
def friends(username: str):
    """Provides the friends page for the application.

    If a form was submitted, it reads the form data and inserts a new friend into the database.

    Otherwise, it reads the username from the URL and displays all friends of the user.
    """
    if username != session.get("username"):
        if request.method == "GET":
            return redirect(url_for("friends", username=session.get("username")))
        username = session.get("username")

    friends_form = FriendsForm()
    user = sqlite.query(
        "SELECT * FROM Users WHERE id = ?",
        session["user_id"],
        one=True,
    )

    if friends_form.validate_on_submit():
        friend = sqlite.query(
            "SELECT * FROM Users WHERE username = ?",
            friends_form.username.data,
            one=True,
        )
        friends = sqlite.query(
            "SELECT f_id FROM Friends WHERE u_id = ?",
            user["id"],
        )

        if friend is None:
            flash("User does not exist!", category="warning")
        elif friend["id"] == user["id"]:
            flash("You cannot be friends with yourself!", category="warning")
        elif friend["id"] in [friend["f_id"] for friend in friends]:
            flash("You are already friends with this user!", category="warning")
        else:
            sqlite.query(
                "INSERT INTO Friends (u_id, f_id) VALUES (?, ?)",
                user["id"],
                friend["id"],
            )
            flash("Friend successfully added!", category="success")

    friends = sqlite.query(
        """
        SELECT *
        FROM Friends AS f JOIN Users AS u ON f.f_id = u.id
        WHERE f.u_id = ? AND f.f_id != ?
        """,
        user["id"],
        user["id"],
    )
    return render_template("friends.html.j2", title="Friends", username=username, friends=friends, form=friends_form)


@app.route("/profile/<string:username>", methods=["GET", "POST"])
@login_required
def profile(username: str):
    """Provides the profile page for the application.

    If a form was submitted, it reads the form data and updates the user's profile in the database.

    Otherwise, it reads the username from the URL and displays the user's profile.
    """
    if username != session.get("username"):
        if request.method == "GET":
            return redirect(url_for("profile", username=session.get("username")))
        username = session.get("username")

    profile_form = ProfileForm()
    user = sqlite.query(
        "SELECT * FROM Users WHERE id = ?",
        session["user_id"],
        one=True,
    )

    if profile_form.validate_on_submit():
        sqlite.query(
            """
            UPDATE Users
            SET education = ?, employment = ?, music = ?, movie = ?, nationality = ?, birthday = ?
            WHERE id = ?
            """,
            profile_form.education.data,
            profile_form.employment.data,
            profile_form.music.data,
            profile_form.movie.data,
            profile_form.nationality.data,
            profile_form.birthday.data,
            session["user_id"]
        )
        return redirect(url_for("profile", username=username))

    return render_template("profile.html.j2", title="Profile", username=username, user=user, form=profile_form)


@app.route("/uploads/<string:filename>")
def uploads(filename):
    """Provides an endpoint for serving uploaded files."""
    lower = filename.lower()

    # Blokker aktivt innhold
    if lower.endswith((".html", ".htm", ".js")):
        abort(403)

    # Tillater kun whitelistede endelser
    allowed = app.config.get("ALLOWED_EXTENSIONS", set())
    ext = lower.rsplit(".", 1)[-1] if "." in lower else ""
    if ext not in allowed:
        abort(403)

    return send_from_directory(
        Path(app.instance_path) / app.config["UPLOADS_FOLDER_PATH"],
        filename,
    )

