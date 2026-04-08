import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (
    Flask,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "adoption.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('worker', 'buyer')),
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS animals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            image_path TEXT,
            status TEXT NOT NULL DEFAULT 'available' CHECK(status IN ('available', 'adopted')),
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS adoptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tree_id INTEGER NOT NULL UNIQUE,
            buyer_id INTEGER NOT NULL,
            adopted_at TEXT NOT NULL,
            FOREIGN KEY(tree_id) REFERENCES animals(id),
            FOREIGN KEY(buyer_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tree_id INTEGER NOT NULL,
            buyer_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            detail TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'processing', 'resolved')),
            response_note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(tree_id) REFERENCES animals(id),
            FOREIGN KEY(buyer_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS tree_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tree_id INTEGER NOT NULL,
            worker_id INTEGER NOT NULL,
            health_status TEXT NOT NULL CHECK(health_status IN ('excellent', 'good', 'warning', 'risk')),
            stage TEXT NOT NULL,
            note TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(tree_id) REFERENCES animals(id),
            FOREIGN KEY(worker_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS farm_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tree_id INTEGER NOT NULL,
            worker_id INTEGER NOT NULL,
            work_date TEXT NOT NULL,
            task_content TEXT NOT NULL,
            growth_progress TEXT NOT NULL,
            health_status TEXT NOT NULL CHECK(health_status IN ('excellent', 'good', 'warning', 'risk')),
            note TEXT NOT NULL,
            image_path TEXT,
            live_stream_url TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(tree_id) REFERENCES animals(id),
            FOREIGN KEY(worker_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tree_id INTEGER NOT NULL,
            buyer_id INTEGER NOT NULL,
            address TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'processing', 'shipped', 'completed')),
            created_at TEXT NOT NULL,
            FOREIGN KEY(tree_id) REFERENCES animals(id),
            FOREIGN KEY(buyer_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS picking_bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tree_id INTEGER NOT NULL,
            buyer_id INTEGER NOT NULL,
            visit_date TEXT NOT NULL,
            people_count INTEGER NOT NULL,
            note TEXT,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'confirmed', 'completed')),
            created_at TEXT NOT NULL,
            FOREIGN KEY(tree_id) REFERENCES animals(id),
            FOREIGN KEY(buyer_id) REFERENCES users(id)
        );
        """
    )
    db.commit()
    sync_db_schema(db)


def sync_db_schema(db):
    table_info = db.execute("PRAGMA table_info(adoptions)").fetchall()
    column_names = {row["name"] for row in table_info}
    if "tree_id" not in column_names and "animal_id" in column_names:
        db.execute("ALTER TABLE adoptions RENAME COLUMN animal_id TO tree_id")
        db.commit()
    animal_columns = {row["name"] for row in db.execute("PRAGMA table_info(animals)").fetchall()}
    if "is_mature" not in animal_columns:
        db.execute("ALTER TABLE animals ADD COLUMN is_mature INTEGER NOT NULL DEFAULT 0")
    if "live_stream_url" not in animal_columns:
        db.execute("ALTER TABLE animals ADD COLUMN live_stream_url TEXT")
    db.commit()


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("请先登录。", "warning")
            return redirect(url_for("login"))
        return func(*args, **kwargs)

    return wrapper


def role_required(role):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if session.get("role") != role:
                flash("没有权限访问该页面。", "danger")
                return redirect(url_for("index"))
            return func(*args, **kwargs)

        return wrapper

    return decorator


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "").strip()

        if not username or not password or role not in ("worker", "buyer"):
            flash("请完整填写信息。", "danger")
            return render_template("register.html")

        db = get_db()
        exists = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if exists:
            flash("用户名已存在。", "warning")
            return render_template("register.html")

        db.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (username, generate_password_hash(password), role, datetime.utcnow().isoformat()),
        )
        db.commit()
        flash("注册成功，请登录。", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        db = get_db()
        user = db.execute(
            "SELECT id, username, password_hash, role FROM users WHERE username = ?",
            (username,),
        ).fetchone()

        if not user or not check_password_hash(user["password_hash"], password):
            flash("用户名或密码错误。", "danger")
            return render_template("login.html")

        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user["role"]
        flash("登录成功。", "success")
        if user["role"] == "worker":
            return redirect(url_for("worker_dashboard"))
        return redirect(url_for("buyer_dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("已退出登录。", "info")
    return redirect(url_for("index"))


@app.route("/worker/dashboard")
@login_required
@role_required("worker")
def worker_dashboard():
    db = get_db()
    trees = db.execute(
        """
        SELECT id, name, category, status, created_at, is_mature, live_stream_url
        FROM animals
        WHERE created_by = ?
        ORDER BY id DESC
        """,
        (session["user_id"],),
    ).fetchall()
    issues = db.execute(
        """
        SELECT i.id, i.title, i.status, i.updated_at, i.response_note, a.name AS tree_name, u.username AS buyer_name
        FROM issues i
        JOIN animals a ON i.tree_id = a.id
        JOIN users u ON i.buyer_id = u.id
        ORDER BY i.id DESC
        """
    ).fetchall()
    orders = db.execute(
        """
        SELECT o.id, o.status, o.address, o.created_at, a.name AS tree_name, u.username AS buyer_name
        FROM orders o
        JOIN animals a ON o.tree_id = a.id
        JOIN users u ON o.buyer_id = u.id
        ORDER BY o.id DESC
        """
    ).fetchall()
    bookings = db.execute(
        """
        SELECT b.id, b.visit_date, b.people_count, b.status, b.note, a.name AS tree_name, u.username AS buyer_name
        FROM picking_bookings b
        JOIN animals a ON b.tree_id = a.id
        JOIN users u ON b.buyer_id = u.id
        ORDER BY b.id DESC
        """
    ).fetchall()
    return render_template("worker_dashboard.html", trees=trees, issues=issues, orders=orders, bookings=bookings)


@app.route("/worker/trees/create", methods=["GET", "POST"])
@login_required
@role_required("worker")
def create_tree():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        live_stream_url = request.form.get("live_stream_url", "").strip()
        image_file = request.files.get("image")

        if not name or not category or not description:
            flash("请完整填写葡萄树信息。", "danger")
            return render_template("create_tree.html")

        image_path = None
        if image_file and image_file.filename:
            if not allowed_file(image_file.filename):
                flash("图片格式不支持，请上传 png/jpg/jpeg/gif/webp。", "warning")
                return render_template("create_tree.html")

            filename = secure_filename(image_file.filename)
            unique_name = f"{int(datetime.utcnow().timestamp())}_{filename}"
            save_path = os.path.join(app.config["UPLOAD_FOLDER"], unique_name)
            image_file.save(save_path)
            image_path = f"uploads/{unique_name}"

        db = get_db()
        db.execute(
            """
            INSERT INTO animals (name, category, description, image_path, status, created_by, created_at, live_stream_url, is_mature)
            VALUES (?, ?, ?, ?, 'available', ?, ?, ?, 0)
            """,
            (name, category, description, image_path, session["user_id"], datetime.utcnow().isoformat(), live_stream_url),
        )
        db.commit()
        flash("葡萄树信息已发布。", "success")
        return redirect(url_for("worker_dashboard"))

    return render_template("create_tree.html")


@app.route("/buyer/dashboard")
@login_required
@role_required("buyer")
def buyer_dashboard():
    db = get_db()
    trees = db.execute(
        """
        SELECT a.id, a.name, a.category, a.description, a.image_path, a.status, a.is_mature, u.username AS worker_name
        FROM animals a
        JOIN users u ON a.created_by = u.id
        WHERE a.status = 'available'
        ORDER BY a.id DESC
        """
    ).fetchall()
    return render_template("buyer_dashboard.html", trees=trees)


@app.route("/adopt/<int:tree_id>", methods=["POST"])
@login_required
@role_required("buyer")
def adopt_tree(tree_id):
    db = get_db()
    tree = db.execute(
        "SELECT id, status FROM animals WHERE id = ?",
        (tree_id,),
    ).fetchone()
    if not tree:
        flash("葡萄树不存在。", "danger")
        return redirect(url_for("buyer_dashboard"))

    if tree["status"] != "available":
        flash("该葡萄树已被认养。", "warning")
        return redirect(url_for("buyer_dashboard"))

    db.execute(
        "UPDATE animals SET status = 'adopted' WHERE id = ?",
        (tree_id,),
    )
    db.execute(
        "INSERT INTO adoptions (tree_id, buyer_id, adopted_at) VALUES (?, ?, ?)",
        (tree_id, session["user_id"], datetime.utcnow().isoformat()),
    )
    db.commit()
    flash("认养成功。", "success")
    return redirect(url_for("my_adoptions"))


@app.route("/buyer/my-adoptions")
@login_required
@role_required("buyer")
def my_adoptions():
    db = get_db()
    rows = db.execute(
        """
        SELECT a.id, a.name, a.category, a.image_path, a.is_mature, a.live_stream_url, ad.adopted_at
        FROM adoptions ad
        JOIN animals a ON ad.tree_id = a.id
        WHERE ad.buyer_id = ?
        ORDER BY ad.id DESC
        """,
        (session["user_id"],),
    ).fetchall()
    latest_updates = db.execute(
        """
        SELECT tu.tree_id, tu.health_status, tu.stage, tu.note, tu.updated_at
        FROM tree_updates tu
        JOIN (
            SELECT tree_id, MAX(id) AS max_id
            FROM tree_updates
            GROUP BY tree_id
        ) latest ON latest.max_id = tu.id
        """
    ).fetchall()
    update_map = {row["tree_id"]: row for row in latest_updates}
    return render_template("my_adoptions.html", adoptions=rows, update_map=update_map)


@app.route("/worker/trees/<int:tree_id>/update", methods=["POST"])
@login_required
@role_required("worker")
def create_tree_update(tree_id):
    health_status = request.form.get("health_status", "").strip()
    stage = request.form.get("stage", "").strip()
    note = request.form.get("note", "").strip()
    work_date = request.form.get("work_date", "").strip() or datetime.utcnow().date().isoformat()
    task_content = request.form.get("task_content", "").strip()
    image_file = request.files.get("record_image")
    live_stream_url = request.form.get("live_stream_url", "").strip()
    is_mature = request.form.get("is_mature", "").strip() == "1"
    if health_status not in ("excellent", "good", "warning", "risk") or not stage or not note:
        flash("请完整填写树状态更新信息。", "warning")
        return redirect(url_for("worker_dashboard"))
    if not task_content:
        flash("请填写每日农事记录内容。", "warning")
        return redirect(url_for("worker_dashboard"))

    db = get_db()
    tree = db.execute("SELECT id FROM animals WHERE id = ?", (tree_id,)).fetchone()
    if not tree:
        flash("葡萄树不存在。", "danger")
        return redirect(url_for("worker_dashboard"))
    record_image_path = None
    if image_file and image_file.filename:
        if not allowed_file(image_file.filename):
            flash("记录图片格式不支持。", "warning")
            return redirect(url_for("worker_dashboard"))
        filename = secure_filename(image_file.filename)
        unique_name = f"record_{int(datetime.utcnow().timestamp())}_{filename}"
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], unique_name)
        image_file.save(save_path)
        record_image_path = f"uploads/{unique_name}"

    db.execute(
        """
        INSERT INTO tree_updates (tree_id, worker_id, health_status, stage, note, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (tree_id, session["user_id"], health_status, stage, note, datetime.utcnow().isoformat()),
    )
    db.execute(
        """
        INSERT INTO farm_records (tree_id, worker_id, work_date, task_content, growth_progress, health_status, note, image_path, live_stream_url, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tree_id,
            session["user_id"],
            work_date,
            task_content,
            stage,
            health_status,
            note,
            record_image_path,
            live_stream_url,
            datetime.utcnow().isoformat(),
        ),
    )
    if live_stream_url:
        db.execute("UPDATE animals SET live_stream_url = ? WHERE id = ?", (live_stream_url, tree_id))
    db.execute("UPDATE animals SET is_mature = ? WHERE id = ?", (1 if is_mature else 0, tree_id))
    db.commit()
    flash("每日农事记录和树状态已更新，买家可实时查看。", "success")
    return redirect(url_for("worker_dashboard"))


@app.route("/api/buyer/tree-status")
@login_required
@role_required("buyer")
def buyer_tree_status_api():
    db = get_db()
    rows = db.execute(
        """
        SELECT
            a.id AS tree_id,
            a.name AS tree_name,
            a.is_mature,
            COALESCE(fr.health_status, tu.health_status) AS health_status,
            COALESCE(fr.growth_progress, tu.stage) AS stage,
            COALESCE(fr.note, tu.note) AS note,
            COALESCE(fr.live_stream_url, a.live_stream_url) AS live_stream_url,
            fr.image_path AS image_path,
            COALESCE(fr.created_at, tu.updated_at) AS updated_at
        FROM adoptions ad
        JOIN animals a ON ad.tree_id = a.id
        LEFT JOIN (
            SELECT f1.*
            FROM farm_records f1
            JOIN (
                SELECT tree_id, MAX(id) AS max_id
                FROM farm_records
                GROUP BY tree_id
            ) f2 ON f1.id = f2.max_id
        ) fr ON fr.tree_id = a.id
        LEFT JOIN (
            SELECT t1.tree_id, t1.health_status, t1.stage, t1.note, t1.updated_at
            FROM tree_updates t1
            JOIN (
                SELECT tree_id, MAX(id) AS max_id
                FROM tree_updates
                GROUP BY tree_id
            ) t2 ON t1.id = t2.max_id
        ) tu ON tu.tree_id = a.id
        WHERE ad.buyer_id = ?
        ORDER BY a.id DESC
        """,
        (session["user_id"],),
    ).fetchall()
    result = []
    for row in rows:
        result.append(
            {
                "tree_id": row["tree_id"],
                "tree_name": row["tree_name"],
                "is_mature": row["is_mature"],
                "health_status": row["health_status"] or "pending",
                "stage": row["stage"] or "待更新",
                "note": row["note"] or "工作人员暂未上传最新巡检信息",
                "live_stream_url": row["live_stream_url"] or "",
                "image_path": row["image_path"] or "",
                "updated_at": row["updated_at"] or "",
            }
        )
    return jsonify(result)


@app.route("/buyer/commerce")
@login_required
@role_required("buyer")
def buyer_commerce():
    db = get_db()
    trees = db.execute(
        """
        SELECT a.id, a.name, a.category, a.is_mature
        FROM adoptions ad
        JOIN animals a ON a.id = ad.tree_id
        WHERE ad.buyer_id = ?
        ORDER BY ad.id DESC
        """,
        (session["user_id"],),
    ).fetchall()
    orders = db.execute(
        """
        SELECT o.id, o.address, o.status, o.created_at, a.name AS tree_name
        FROM orders o
        JOIN animals a ON o.tree_id = a.id
        WHERE o.buyer_id = ?
        ORDER BY o.id DESC
        """,
        (session["user_id"],),
    ).fetchall()
    bookings = db.execute(
        """
        SELECT b.id, b.visit_date, b.people_count, b.note, b.status, a.name AS tree_name
        FROM picking_bookings b
        JOIN animals a ON b.tree_id = a.id
        WHERE b.buyer_id = ?
        ORDER BY b.id DESC
        """,
        (session["user_id"],),
    ).fetchall()
    return render_template("buyer_commerce.html", trees=trees, orders=orders, bookings=bookings)


@app.route("/buyer/orders/create", methods=["POST"])
@login_required
@role_required("buyer")
def create_order():
    tree_id = request.form.get("tree_id", "").strip()
    address = request.form.get("address", "").strip()
    if not tree_id or not address:
        flash("请完整填写发货信息。", "warning")
        return redirect(url_for("buyer_commerce"))

    db = get_db()
    tree = db.execute(
        """
        SELECT a.id, a.is_mature
        FROM adoptions ad
        JOIN animals a ON ad.tree_id = a.id
        WHERE ad.buyer_id = ? AND ad.tree_id = ?
        """,
        (session["user_id"], tree_id),
    ).fetchone()
    if not tree:
        flash("只能为你已认养的葡萄树创建发货单。", "danger")
        return redirect(url_for("buyer_commerce"))
    if int(tree["is_mature"]) != 1:
        flash("葡萄尚未成熟，暂不可发货。", "warning")
        return redirect(url_for("buyer_commerce"))

    db.execute(
        "INSERT INTO orders (tree_id, buyer_id, address, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
        (tree_id, session["user_id"], address, datetime.utcnow().isoformat()),
    )
    db.commit()
    flash("发货申请已提交。", "success")
    return redirect(url_for("buyer_commerce"))


@app.route("/buyer/picking/create", methods=["POST"])
@login_required
@role_required("buyer")
def create_picking_booking():
    tree_id = request.form.get("tree_id", "").strip()
    visit_date = request.form.get("visit_date", "").strip()
    people_count = request.form.get("people_count", "").strip()
    note = request.form.get("note", "").strip()
    if not tree_id or not visit_date or not people_count:
        flash("请完整填写采摘预约信息。", "warning")
        return redirect(url_for("buyer_commerce"))

    db = get_db()
    owned = db.execute(
        "SELECT id FROM adoptions WHERE buyer_id = ? AND tree_id = ?",
        (session["user_id"], tree_id),
    ).fetchone()
    if not owned:
        flash("只能预约已认养葡萄树的线下采摘。", "danger")
        return redirect(url_for("buyer_commerce"))

    db.execute(
        """
        INSERT INTO picking_bookings (tree_id, buyer_id, visit_date, people_count, note, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'pending', ?)
        """,
        (tree_id, session["user_id"], visit_date, int(people_count), note, datetime.utcnow().isoformat()),
    )
    db.commit()
    flash("采摘预约已提交。", "success")
    return redirect(url_for("buyer_commerce"))


@app.route("/worker/orders/<int:order_id>/update", methods=["POST"])
@login_required
@role_required("worker")
def update_order(order_id):
    status = request.form.get("status", "").strip()
    if status not in ("pending", "processing", "shipped", "completed"):
        flash("订单状态无效。", "danger")
        return redirect(url_for("worker_dashboard"))

    db = get_db()
    db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    db.commit()
    flash("订单状态已更新。", "success")
    return redirect(url_for("worker_dashboard"))


@app.route("/worker/bookings/<int:booking_id>/update", methods=["POST"])
@login_required
@role_required("worker")
def update_booking(booking_id):
    status = request.form.get("status", "").strip()
    if status not in ("pending", "confirmed", "completed"):
        flash("预约状态无效。", "danger")
        return redirect(url_for("worker_dashboard"))

    db = get_db()
    db.execute("UPDATE picking_bookings SET status = ? WHERE id = ?", (status, booking_id))
    db.commit()
    flash("采摘预约状态已更新。", "success")
    return redirect(url_for("worker_dashboard"))


@app.route("/buyer/issues")
@login_required
@role_required("buyer")
def my_issues():
    db = get_db()
    issues = db.execute(
        """
        SELECT i.id, i.title, i.detail, i.status, i.response_note, i.created_at, i.updated_at, a.name AS tree_name
        FROM issues i
        JOIN animals a ON i.tree_id = a.id
        WHERE i.buyer_id = ?
        ORDER BY i.id DESC
        """,
        (session["user_id"],),
    ).fetchall()
    adopted_trees = db.execute(
        """
        SELECT a.id, a.name
        FROM adoptions ad
        JOIN animals a ON ad.tree_id = a.id
        WHERE ad.buyer_id = ?
        ORDER BY ad.id DESC
        """,
        (session["user_id"],),
    ).fetchall()
    return render_template("buyer_issues.html", issues=issues, adopted_trees=adopted_trees)


@app.route("/buyer/issues/create", methods=["POST"])
@login_required
@role_required("buyer")
def create_issue():
    tree_id = request.form.get("tree_id", "").strip()
    title = request.form.get("title", "").strip()
    detail = request.form.get("detail", "").strip()

    if not tree_id or not title or not detail:
        flash("请完整填写问题信息。", "warning")
        return redirect(url_for("my_issues"))

    db = get_db()
    owned_tree = db.execute(
        "SELECT id FROM adoptions WHERE tree_id = ? AND buyer_id = ?",
        (tree_id, session["user_id"]),
    ).fetchone()
    if not owned_tree:
        flash("只能提交你已认养葡萄树的问题。", "danger")
        return redirect(url_for("my_issues"))

    now = datetime.utcnow().isoformat()
    db.execute(
        """
        INSERT INTO issues (tree_id, buyer_id, title, detail, status, response_note, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'open', '', ?, ?)
        """,
        (tree_id, session["user_id"], title, detail, now, now),
    )
    db.commit()
    flash("问题已提交，等待工作人员处理。", "success")
    return redirect(url_for("my_issues"))


@app.route("/worker/issues/<int:issue_id>/update", methods=["POST"])
@login_required
@role_required("worker")
def update_issue(issue_id):
    status = request.form.get("status", "").strip()
    response_note = request.form.get("response_note", "").strip()
    if status not in ("open", "processing", "resolved"):
        flash("问题状态无效。", "danger")
        return redirect(url_for("worker_dashboard"))

    db = get_db()
    exists = db.execute("SELECT id FROM issues WHERE id = ?", (issue_id,)).fetchone()
    if not exists:
        flash("问题不存在。", "danger")
        return redirect(url_for("worker_dashboard"))

    db.execute(
        """
        UPDATE issues
        SET status = ?, response_note = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, response_note, datetime.utcnow().isoformat(), issue_id),
    )
    db.commit()
    flash("问题处理状态已更新。", "success")
    return redirect(url_for("worker_dashboard"))


@app.before_request
def ensure_db():
    init_db()


if __name__ == "__main__":
    app.run(debug=True)
