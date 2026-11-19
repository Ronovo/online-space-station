"""Flask web front end for Space Station Explorer."""

import functools
import hashlib
import os
import re
import secrets
import time

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from ronovo_portfolio_auth import portfolio_sso, security_questions
from ronovo_portfolio_auth.login_limiter import LockedOut, LoginLimiter
from werkzeug.security import check_password_hash, generate_password_hash

from space_online.game.character_methods.character_creation import (
    JOBS,
    NPC_NAMES,
    group_jobs_by_department,
    new_shift,
)
from space_online.game.helper_methods.career import (
    HEAD_JOB,
    REGULAR_JOBS,
    START_JOB,
    TOP_JOB,
    empty_save,
    finish_round,
    job_salary,
    locked_regular_jobs,
    new_career,
    revive_cost,
    start_career_shift,
    unlock_job,
    unlocked_jobs,
)
from space_online.game.helper_methods.rounds import ANTAGONIST, CAREER, MODE_DESCRIPTIONS, PEACEFUL, round_over
from space_online.game.helper_methods.ui_panels import default_ui_state
from space_online.game.main import SpaceStationGame
from space_online.webapp import db
from space_online.webapp.wiki import wiki

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_PASSWORD_LENGTH = 6
MAX_PASSWORD_LENGTH = 128
PORTFOLIO_CHOICE_SECONDS = 600
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COVERAGE_DIR = os.path.join(ROOT, "coverage")


def _load_secret_key(instance_path):
    """SPACE_ONLINE_SECRET_KEY env var, else a key generated once into the instance folder."""
    env_key = os.environ.get("SPACE_ONLINE_SECRET_KEY")
    if env_key:
        return env_key
    os.makedirs(instance_path, exist_ok=True)
    key_path = os.path.join(instance_path, "secret_key")
    if not os.path.exists(key_path):
        with open(key_path, "w", encoding="utf-8") as f:
            f.write(secrets.token_hex(32))
    with open(key_path, encoding="utf-8") as f:
        return f.read().strip()


def create_app(test_config=None):
    app = Flask(__name__, instance_path=os.path.join(ROOT, "instance"))
    app.config.update(
        DATABASE=os.path.join(app.instance_path, "space_online.sqlite3"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SECURE_COOKIES") == "1",
    )
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _load_secret_key(app.instance_path)

    app.teardown_appcontext(db.close_db)
    os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)
    db.init_db(app)
    _register_routes(app)
    app.register_blueprint(wiki)
    return app


def _csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


def _check_csrf():
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    if not sent or not secrets.compare_digest(sent.encode("utf-8"), session.get("csrf_token", "").encode("utf-8")):
        abort(400, description="Invalid or missing CSRF token. Reload the page and try again.")


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        user = db.get_user(session["user_id"]) if session.get("user_id") is not None else None
        if user is None or not secrets.compare_digest(session.get("session_key", ""), _session_key(user)):
            session.clear()
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def _run_game(user_id, action=None, args=None):
    """Tick the round's clock, apply one action, save, and return the view.

    Returns None when no round is in progress, and a bare redirect to the summary when this ended it.
    """
    def run(save, ui_state):
        if not save["shift"]:
            return None, save, ui_state
        game = SpaceStationGame(save["shift"], ui_state)
        game.tick()
        if action:
            game.perform(action, args or {})
        view = game.view()
        save["shift"] = game.to_save_data()
        if round_over(save["shift"]):
            finish_round(save)
            return {"redirect": "round_summary"}, save, default_ui_state()
        return view, save, game.ui
    return db.update_character(user_id, run)


def _session_key(user):
    """Changes whenever the password does, so a login session stored with it ends when the password is reset."""
    return hashlib.sha256(user["password_hash"].encode("utf-8")).hexdigest()[:16]


def _log_in(user):
    session.clear()
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["session_key"] = _session_key(user)


def _login_error(logins, username, user, password):
    """Why this username and password can't log in, or None when they can. Wrong passwords count toward a lockout."""
    try:
        if logins.attempt(username, lambda: user is not None and check_password_hash(user["password_hash"], password)):
            return None
    except LockedOut as locked:
        return str(locked)
    return "Incorrect username or password."


def _password_error(password, confirm):
    """Why a new password can't be used, or None."""
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        return f"Passwords must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters."
    if password != confirm:
        return "Passwords do not match."
    return None


def _portfolio_user(account):
    """A new account linked to a portfolio account and named after it. Its password is random and never shown,
    so logging in with the portfolio account is the only way in."""
    user = db.get_user_by_portfolio(account["sub"])
    base = account["username"] if USERNAME_PATTERN.match(account["username"]) else "player"
    n = 1
    while user is None:
        name = base if n == 1 else f"{base[:32 - len(str(n))]}{n}"
        # None when the name is taken, or when a second login for this portfolio account got there first.
        if db.create_user(name, generate_password_hash(secrets.token_urlsafe(32)), account["sub"]) is None:
            n += 1
        user = db.get_user_by_portfolio(account["sub"])
    return user


def _answer_hash(answer):
    return generate_password_hash(security_questions.normalize_answer(answer))


def _render_screen(view):
    """The screen's HTML, and the JSON the page script reads: its hash, title and any open choice."""
    html = render_template("game/screen.html", view=view)
    screen_hash = hashlib.sha1(html.encode("utf-8")).hexdigest()[:16]
    return html, {"hash": screen_hash, "title": view["title"], "choice": view["choice"]}


def _register_routes(app):
    logins = LoginLimiter()

    @app.context_processor
    def inject_globals():
        return {"csrf_token": _csrf_token, "current_user": session.get("username"), "portfolio": portfolio_sso.enabled(),
                "portfolio_url": portfolio_sso.portfolio_url() if portfolio_sso.enabled() else ""}

    # The portfolio login callback is posted by the portfolio, so it carries no CSRF token. Its signed login token
    # and the state cookie set by /sso/login are what prove it.
    @app.before_request
    def protect_posts():
        if request.method == "POST" and request.endpoint != "sso_callback":
            _check_csrf()

    def _enter(user, next_path=None):
        _log_in(user)
        return redirect(next_path or url_for("home"))

    # The first portfolio login here asks whether to link an account the player already has or make a new one,
    # so it waits in the session until they choose.
    def portfolio_login(account, next_path):
        user = db.get_user_by_portfolio(account["sub"])
        if user is not None:
            return _enter(user, next_path)
        session.clear()
        session["portfolio_pending"] = {**account, "expires": time.time() + PORTFOLIO_CHOICE_SECONDS}
        return redirect(url_for("link_account"))

    def portfolio_error(reason):
        flash(portfolio_sso.LOGIN_MESSAGES[reason], "error")
        return redirect(url_for("login"))

    portfolio_sso.add_flask_routes(app, "space-online", portfolio_login, portfolio_error)

    @app.route("/link-account", methods=["GET", "POST"])
    def link_account():
        pending = session.get("portfolio_pending")
        if not pending or pending["expires"] < time.time():
            session.pop("portfolio_pending", None)
            flash("Log in with your portfolio account again.", "error")
            return redirect(url_for("login"))
        username = request.form.get("username", pending["username"]).strip()
        action = request.form.get("action")
        if action == "cancel":
            session.clear()
            return redirect(url_for("login"))
        if action == "new":
            return _enter(_portfolio_user(pending))
        if action == "link":
            user = db.get_user_by_name(username)
            error = _login_error(logins, username, user, request.form.get("password", ""))
            if error:
                flash(error, "error")
            elif not db.link_portfolio(user["id"], pending["sub"]):
                flash("That account is already linked to another portfolio account.", "error")
            else:
                return _enter(user)
        return render_template("link_account.html", name=pending["username"], username=username)

    @app.route("/register", methods=["GET", "POST"])
    def register():
        username = request.form.get("username", "").strip()
        question = request.form.get("question", "")
        if request.method == "POST":
            password = request.form.get("password", "")
            answer = request.form.get("answer", "")
            if not USERNAME_PATTERN.match(username):
                error = "Usernames are 3-32 characters: letters, numbers, dot, dash, or underscore."
            else:
                error = (_password_error(password, request.form.get("confirm_password", ""))
                         or security_questions.problem(question, answer))
            if error is None:
                user_id = db.create_user(username, generate_password_hash(password))
                if user_id is None:
                    error = "That username is already taken."
                else:
                    db.set_security_question(user_id, question, _answer_hash(answer))
                    _log_in(db.get_user(user_id))
                    return redirect(url_for("home"))
            flash(error, "error")
        return render_template("register.html", username=username, question=question,
                               questions=security_questions.QUESTIONS)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            user = db.get_user_by_name(username)
            error = _login_error(logins, username, user, request.form.get("password", ""))
            if error:
                flash(error, "error")
                return render_template("login.html", username=username)
            return _enter(user)
        return render_template("login.html", username="")

    # Two steps: the username brings up its security question, then the answer and a new password change it.
    # Too many wrong answers lock resets for a while. Usernames are public (registering says when one is taken),
    # so the first step says plainly when there is no such account.
    @app.route("/reset-password", methods=["GET", "POST"])
    def reset_password():
        username = request.form.get("username", "").strip()
        if request.method == "GET" or not username:
            return render_template("reset_password.html", username="", question=None)
        user = db.get_reset_user(username)
        if user is None:
            flash("That account logs in with the portfolio and has no security question."
                  if db.get_user_by_name(username) else "There is no account with that username.", "error")
            return render_template("reset_password.html", username="", question=None)
        question = user["security_question"]
        if "answer" in request.form:
            password = request.form.get("password", "")
            error = _password_error(password, request.form.get("confirm_password", ""))
            if error is None:
                tries = db.count_reset_try(user["id"], time.time())
                if tries is None or tries > security_questions.MAX_RESET_FAILURES:
                    error = (f"Too many wrong answers. Try again in "
                             f"{security_questions.RESET_LOCK_SECONDS // 60} minutes.")
                elif not check_password_hash(
                        user["security_answer_hash"], security_questions.normalize_answer(request.form["answer"])):
                    error = "That answer is wrong."
                    if tries == security_questions.MAX_RESET_FAILURES:
                        db.lock_resets(user["id"], time.time() + security_questions.RESET_LOCK_SECONDS)
                else:
                    db.set_password(user["id"], generate_password_hash(password))
                    flash("Password changed. Log in with your new password.", "info")
                    return redirect(url_for("login"))
            flash(error, "error")
        return render_template("reset_password.html", username=username, question=question)

    @app.get("/coverage/", defaults={"path": ""})
    @app.get("/coverage/<path:path>")
    def coverage(path):
        if not path or path.endswith("/"):
            path += "index.html"
        return send_from_directory(COVERAGE_DIR, path)

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def home():
        save, updated_at = db.load_save(session["user_id"])
        save = save or empty_save()
        career = save["career"]
        return render_template(
            "home.html",
            career=career,
            shift=save["shift"],
            career_over=save["summary"] if not career and save["summary"] and save["summary"]["career_over"] else None,
            open_panel=request.args.get("panel"),
            updated_at=updated_at,
            unlocked=unlocked_jobs(career) if career else [],
            pick_from=locked_regular_jobs(career) if career and career["pick_owed"] else [],
            revive_cost=revive_cost(career) if career else None,
            ladder=[START_JOB, *REGULAR_JOBS, HEAD_JOB, TOP_JOB],
            departments=group_jobs_by_department(),
            jobs=JOBS,
            job_salary=job_salary,
            mode_descriptions=MODE_DESCRIPTIONS,
            npc_names=NPC_NAMES,
        )

    def _change_save(change):
        """Apply change(save) to the account's save, making the save first if there isn't one.

        change returns an error message, or None when it went through.
        """
        def run(save, ui_state):
            error = change(save)
            return (error, save, default_ui_state() if error is None else ui_state)

        db.ensure_save(session["user_id"], empty_save(), default_ui_state())
        error = db.update_character(session["user_id"], run)
        if error:
            flash(error, "error")
        return error is None

    @app.route("/career/new", methods=["POST"])
    @login_required
    def new_career_route():
        def change(save):
            if save["career"]:
                return "You already have a career."
            try:
                save["career"] = new_career(request.form.get("name", ""))
            except ValueError as error:
                return str(error)
            save["summary"] = None
            return None

        if _change_save(change):
            flash("Career started. Pick a job and start your first shift.", "info")
            return redirect(url_for("home", panel="career"))
        return redirect(url_for("home"))

    @app.route("/career/unlock", methods=["POST"])
    @login_required
    def unlock_job_route():
        def change(save):
            if not save["career"]:
                return "Start a career first."
            try:
                unlock_job(save["career"], request.form.get("job", ""))
            except ValueError as error:
                return str(error)
            return None

        _change_save(change)
        return redirect(url_for("home"))

    @app.route("/round/start", methods=["POST"])
    @login_required
    def start_round():
        mode = request.form.get("mode")
        job = request.form.get("job", "")

        def change(save):
            if save["shift"]:
                return "You already have a round in progress."
            try:
                if mode == CAREER:
                    if not save["career"]:
                        return "Start a career first."
                    save["shift"] = start_career_shift(save["career"], job)
                elif mode in (PEACEFUL, ANTAGONIST):
                    save["shift"] = new_shift(request.form.get("name", ""), job, mode=mode)
                else:
                    return "Choose a kind of round."
            except ValueError as error:
                return str(error)
            save["summary"] = None
            return None

        return redirect(url_for("play" if _change_save(change) else "home"))

    @app.route("/round/abandon", methods=["POST"])
    @login_required
    def abandon_round():
        def change(save):
            if not save["shift"]:
                return "You have no round in progress."
            if save["shift"]["round"]["mode"] == CAREER:
                return "A career shift can't be abandoned. See it through to the shuttle."
            save["shift"] = None
            return None

        _change_save(change)
        return redirect(url_for("home"))

    @app.route("/round/summary")
    @login_required
    def round_summary():
        save, _ = db.load_save(session["user_id"])
        if not save or not save["summary"]:
            return redirect(url_for("home"))
        career = save["career"]
        return render_template("round_summary.html", summary=save["summary"], career=career, job_salary=job_salary,
                               pick_from=locked_regular_jobs(career) if career and career["pick_owed"] else [])

    @app.route("/character/delete", methods=["POST"])
    @login_required
    def delete_character():
        if request.form.get("confirm") != "yes":
            flash("Tick the confirmation box to delete your career.", "error")
            return redirect(url_for("home"))
        db.delete_character(session["user_id"])
        flash("Your career and any round in progress have been deleted.", "info")
        return redirect(url_for("home"))

    @app.route("/play")
    @login_required
    def play():
        view = _run_game(session["user_id"])
        if view is None:
            return redirect(url_for("home"))
        if view["redirect"]:
            return redirect(url_for(view["redirect"]))
        html, initial = _render_screen(view)
        return render_template("play.html", screen_html=html, initial_state=initial)

    @app.route("/api/act", methods=["POST"])
    @login_required
    def act():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            payload = {}
        action = payload.get("action")
        view = _run_game(
            session["user_id"],
            None if action == "tick" else action,
            payload.get("args"),
        )
        if view is None:
            return jsonify({"redirect": url_for("home")})
        if view["redirect"]:
            return jsonify({"redirect": url_for(view["redirect"])})

        html, response = _render_screen(view)
        if response["hash"] != payload.get("hash"):
            response["html"] = html
        return jsonify(response)
