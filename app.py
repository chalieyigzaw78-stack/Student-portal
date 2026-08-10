"""
app.py — Student Academic Result Portal
Three roles: Admin, Staff, Student
"""

import os
import sqlite3
from functools import wraps
from datetime import datetime
from flask import (
    Flask, render_template, request, jsonify,
    redirect, url_for, session, flash
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key-in-production")
DB_PATH = os.environ.get("DB_PATH", "portal.db")


# ─── Grading System ────────────────────────────────────────────────────────

def score_to_grade(score):
    if score >= 90: return "A",  4.0
    if score >= 85: return "B+", 3.5
    if score >= 80: return "B",  3.0
    if score >= 75: return "C+", 2.5
    if score >= 70: return "C",  2.0
    if score >= 60: return "D",  1.0
    return "F", 0.0


def calc_gpa(results):
    """Calculate GPA from a list of result rows."""
    total_points = 0
    total_credits = 0
    for r in results:
        grade_letter, grade_point = score_to_grade(r["score"])
        total_points  += grade_point * r["credit_hours"]
        total_credits += r["credit_hours"]
    if total_credits == 0:
        return 0.0, 0
    return round(total_points / total_credits, 2), total_credits


# ─── Database ──────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name     TEXT NOT NULL,
            role          TEXT NOT NULL CHECK(role IN ('admin','staff','student')),
            department    TEXT,
            year          INTEGER,
            section       TEXT,
            email         TEXT,
            phone         TEXT,
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS subjects (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            code         TEXT NOT NULL UNIQUE,
            name         TEXT NOT NULL,
            credit_hours INTEGER NOT NULL DEFAULT 3,
            department   TEXT,
            created_at   TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS results (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id   INTEGER NOT NULL REFERENCES users(id),
            subject_id   INTEGER NOT NULL REFERENCES subjects(id),
            staff_id     INTEGER REFERENCES users(id),
            score        REAL NOT NULL,
            semester     TEXT NOT NULL,
            academic_year TEXT NOT NULL,
            note         TEXT,
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(student_id, subject_id, semester, academic_year)
        );
    """)

    # Create default admin if not exists
    admin = conn.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
    if not admin:
        conn.execute(
            "INSERT INTO users (user_id, password_hash, full_name, role) VALUES (?,?,?,?)",
            ("admin", generate_password_hash("admin123"), "System Administrator", "admin")
        )
        print("[db] Default admin created: ID=admin, Password=admin123")

    conn.commit()
    conn.close()


init_db()


# ─── Auth helpers ──────────────────────────────────────────────────────────

def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                if isinstance(role, (list, tuple)):
                    if session.get("role") not in role:
                        flash("Access denied.", "error")
                        return redirect(url_for("login"))
                else:
                    flash("Access denied.", "error")
                    return redirect(url_for("login"))
            return f(*args, **kwargs)
        return decorated
    return decorator


def current_user():
    if "user_id" not in session:
        return None
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    db.close()
    return user


# ─── Auth routes ───────────────────────────────────────────────────────────

@app.route("/")
def index():
    if "user_id" in session:
        role = session.get("role")
        if role == "student": return redirect(url_for("student_dashboard"))
        if role == "staff":   return redirect(url_for("staff_dashboard"))
        if role == "admin":   return redirect(url_for("admin_dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user_id  = request.form.get("user_id", "").strip()
        password = request.form.get("password", "").strip()

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        db.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["role"]    = user["role"]
            session["name"]    = user["full_name"]

            if user["role"] == "student": return redirect(url_for("student_dashboard"))
            if user["role"] == "staff":   return redirect(url_for("staff_dashboard"))
            if user["role"] == "admin":   return redirect(url_for("admin_dashboard"))
        else:
            flash("Invalid ID or password.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ─── Student routes ────────────────────────────────────────────────────────

@app.route("/student")
@login_required(role="student")
def student_dashboard():
    user = current_user()
    db   = get_db()

    # Get all results grouped by semester
    results = db.execute("""
        SELECT r.*, s.name as subject_name, s.code as subject_code,
               s.credit_hours, r.semester, r.academic_year
        FROM results r
        JOIN subjects s ON r.subject_id = s.id
        WHERE r.student_id = ?
        ORDER BY r.academic_year DESC, r.semester DESC, s.name
    """, (user["id"],)).fetchall()

    db.close()

    # Group by academic_year + semester
    semesters = {}
    for r in results:
        key = f"{r['academic_year']} — Semester {r['semester']}"
        if key not in semesters:
            semesters[key] = []
        semesters[key].append(r)

    # Calculate GPA per semester and CGPA
    semester_gpas = {}
    all_results   = list(results)

    for key, rows in semesters.items():
        gpa, credits = calc_gpa(rows)
        semester_gpas[key] = {"gpa": gpa, "credits": credits}

    cgpa, total_credits = calc_gpa(all_results)

    return render_template(
        "student/dashboard.html",
        user=user,
        semesters=semesters,
        semester_gpas=semester_gpas,
        cgpa=cgpa,
        total_credits=total_credits,
        score_to_grade=score_to_grade
    )


@app.route("/student/profile")
@login_required(role="student")
def student_profile():
    user = current_user()
    return render_template("student/profile.html", user=user)


# ─── Staff routes ──────────────────────────────────────────────────────────

@app.route("/staff")
@login_required(role="staff")
def staff_dashboard():
    user = current_user()
    db   = get_db()
    students = db.execute(
        "SELECT * FROM users WHERE role='student' ORDER BY full_name"
    ).fetchall()
    subjects = db.execute("SELECT * FROM subjects ORDER BY name").fetchall()
    recent   = db.execute("""
        SELECT r.*, u.full_name, u.user_id as student_no,
               s.name as subject_name, s.code as subject_code
        FROM results r
        JOIN users u ON r.student_id = u.id
        JOIN subjects s ON r.subject_id = s.id
        WHERE r.staff_id = ?
        ORDER BY r.created_at DESC LIMIT 20
    """, (user["id"],)).fetchall()
    db.close()
    return render_template(
        "staff/dashboard.html",
        user=user, students=students,
        subjects=subjects, recent=recent
    )


@app.route("/staff/enter-result", methods=["POST"])
@login_required(role="staff")
def staff_enter_result():
    user = current_user()
    data = request.form

    student_id    = data.get("student_id")
    subject_id    = data.get("subject_id")
    score         = data.get("score")
    semester      = data.get("semester")
    academic_year = data.get("academic_year")
    note          = data.get("note", "")

    if not all([student_id, subject_id, score, semester, academic_year]):
        flash("All fields are required.", "error")
        return redirect(url_for("staff_dashboard"))

    try:
        score = float(score)
        if not 0 <= score <= 100:
            raise ValueError
    except ValueError:
        flash("Score must be a number between 0 and 100.", "error")
        return redirect(url_for("staff_dashboard"))

    db = get_db()
    try:
        db.execute("""
            INSERT INTO results
              (student_id, subject_id, staff_id, score, semester, academic_year, note)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(student_id, subject_id, semester, academic_year)
            DO UPDATE SET score=excluded.score, note=excluded.note,
                          staff_id=excluded.staff_id, created_at=datetime('now')
        """, (student_id, subject_id, user["id"], score, semester, academic_year, note))
        db.commit()
        flash("Result saved successfully.", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    finally:
        db.close()

    return redirect(url_for("staff_dashboard"))


@app.route("/staff/students")
@login_required(role="staff")
def staff_students():
    db = get_db()
    students = db.execute(
        "SELECT * FROM users WHERE role='student' ORDER BY full_name"
    ).fetchall()
    db.close()
    return render_template("staff/students.html", students=students)


@app.route("/staff/student/<int:sid>")
@login_required(role="staff")
def staff_view_student(sid):
    db = get_db()
    student = db.execute("SELECT * FROM users WHERE id=? AND role='student'", (sid,)).fetchone()
    if not student:
        flash("Student not found.", "error")
        return redirect(url_for("staff_students"))
    results = db.execute("""
        SELECT r.*, s.name as subject_name, s.code as subject_code, s.credit_hours
        FROM results r JOIN subjects s ON r.subject_id=s.id
        WHERE r.student_id=?
        ORDER BY r.academic_year DESC, r.semester DESC, s.name
    """, (sid,)).fetchall()
    db.close()

    semesters = {}
    for r in results:
        key = f"{r['academic_year']} — Semester {r['semester']}"
        if key not in semesters:
            semesters[key] = []
        semesters[key].append(r)

    cgpa, total_credits = calc_gpa(list(results))
    return render_template(
        "staff/view_student.html",
        student=student, semesters=semesters,
        cgpa=cgpa, total_credits=total_credits,
        score_to_grade=score_to_grade
    )


# ─── Admin routes ──────────────────────────────────────────────────────────

@app.route("/admin")
@login_required(role="admin")
def admin_dashboard():
    db = get_db()
    stats = {
        "students": db.execute("SELECT COUNT(*) FROM users WHERE role='student'").fetchone()[0],
        "staff":    db.execute("SELECT COUNT(*) FROM users WHERE role='staff'").fetchone()[0],
        "subjects": db.execute("SELECT COUNT(*) FROM subjects").fetchone()[0],
        "results":  db.execute("SELECT COUNT(*) FROM results").fetchone()[0],
    }
    recent_results = db.execute("""
        SELECT r.*, u.full_name, u.user_id as student_no,
               s.name as subject_name, st.full_name as staff_name
        FROM results r
        JOIN users u  ON r.student_id = u.id
        JOIN subjects s ON r.subject_id = s.id
        LEFT JOIN users st ON r.staff_id = st.id
        ORDER BY r.created_at DESC LIMIT 10
    """).fetchall()
    db.close()
    return render_template("admin/dashboard.html", stats=stats, recent_results=recent_results)


@app.route("/admin/students")
@login_required(role="admin")
def admin_students():
    db = get_db()
    students = db.execute(
        "SELECT * FROM users WHERE role='student' ORDER BY full_name"
    ).fetchall()
    db.close()
    return render_template("admin/students.html", students=students)


@app.route("/admin/add-student", methods=["POST"])
@login_required(role="admin")
def admin_add_student():
    data = request.form
    db   = get_db()
    try:
        db.execute("""
            INSERT INTO users (user_id, password_hash, full_name, role, department, year, section, email, phone)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            data["user_id"].strip(),
            generate_password_hash(data["password"].strip()),
            data["full_name"].strip(),
            "student",
            data.get("department","").strip(),
            data.get("year", 1),
            data.get("section","").strip(),
            data.get("email","").strip(),
            data.get("phone","").strip(),
        ))
        db.commit()
        flash(f"Student '{data['full_name']}' added successfully.", "success")
    except sqlite3.IntegrityError:
        flash(f"ID '{data['user_id']}' already exists.", "error")
    finally:
        db.close()
    return redirect(url_for("admin_students"))


@app.route("/admin/delete-student/<int:sid>", methods=["POST"])
@login_required(role="admin")
def admin_delete_student(sid):
    db = get_db()
    db.execute("DELETE FROM results WHERE student_id=?", (sid,))
    db.execute("DELETE FROM users WHERE id=? AND role='student'", (sid,))
    db.commit()
    db.close()
    flash("Student deleted.", "success")
    return redirect(url_for("admin_students"))


@app.route("/admin/staff")
@login_required(role="admin")
def admin_staff():
    db = get_db()
    staff = db.execute(
        "SELECT * FROM users WHERE role='staff' ORDER BY full_name"
    ).fetchall()
    db.close()
    return render_template("admin/staff.html", staff=staff)


@app.route("/admin/add-staff", methods=["POST"])
@login_required(role="admin")
def admin_add_staff():
    data = request.form
    db   = get_db()
    try:
        db.execute("""
            INSERT INTO users (user_id, password_hash, full_name, role, department, email, phone)
            VALUES (?,?,?,?,?,?,?)
        """, (
            data["user_id"].strip(),
            generate_password_hash(data["password"].strip()),
            data["full_name"].strip(),
            "staff",
            data.get("department","").strip(),
            data.get("email","").strip(),
            data.get("phone","").strip(),
        ))
        db.commit()
        flash(f"Staff '{data['full_name']}' added successfully.", "success")
    except sqlite3.IntegrityError:
        flash(f"ID '{data['user_id']}' already exists.", "error")
    finally:
        db.close()
    return redirect(url_for("admin_staff"))


@app.route("/admin/delete-staff/<int:sid>", methods=["POST"])
@login_required(role="admin")
def admin_delete_staff(sid):
    db = get_db()
    db.execute("DELETE FROM users WHERE id=? AND role='staff'", (sid,))
    db.commit()
    db.close()
    flash("Staff deleted.", "success")
    return redirect(url_for("admin_staff"))


@app.route("/admin/subjects")
@login_required(role="admin")
def admin_subjects():
    db = get_db()
    subjects = db.execute("SELECT * FROM subjects ORDER BY name").fetchall()
    db.close()
    return render_template("admin/subjects.html", subjects=subjects)


@app.route("/admin/add-subject", methods=["POST"])
@login_required(role="admin")
def admin_add_subject():
    data = request.form
    db   = get_db()
    try:
        db.execute("""
            INSERT INTO subjects (code, name, credit_hours, department)
            VALUES (?,?,?,?)
        """, (
            data["code"].strip().upper(),
            data["name"].strip(),
            int(data.get("credit_hours", 3)),
            data.get("department","").strip(),
        ))
        db.commit()
        flash(f"Subject '{data['name']}' added.", "success")
    except sqlite3.IntegrityError:
        flash(f"Subject code '{data['code']}' already exists.", "error")
    finally:
        db.close()
    return redirect(url_for("admin_subjects"))


@app.route("/admin/delete-subject/<int:sid>", methods=["POST"])
@login_required(role="admin")
def admin_delete_subject(sid):
    db = get_db()
    db.execute("DELETE FROM results WHERE subject_id=?", (sid,))
    db.execute("DELETE FROM subjects WHERE id=?", (sid,))
    db.commit()
    db.close()
    flash("Subject deleted.", "success")
    return redirect(url_for("admin_subjects"))


@app.route("/admin/results")
@login_required(role="admin")
def admin_results():
    db = get_db()
    results = db.execute("""
        SELECT r.*, u.full_name, u.user_id as student_no,
               s.name as subject_name, s.code,
               st.full_name as staff_name
        FROM results r
        JOIN users u ON r.student_id=u.id
        JOIN subjects s ON r.subject_id=s.id
        LEFT JOIN users st ON r.staff_id=st.id
        ORDER BY r.created_at DESC
    """).fetchall()
    db.close()
    return render_template("admin/results.html", results=results, score_to_grade=score_to_grade)


@app.route("/admin/student/<int:sid>")
@login_required(role="admin")
def admin_view_student(sid):
    db = get_db()
    student = db.execute("SELECT * FROM users WHERE id=?", (sid,)).fetchone()
    results = db.execute("""
        SELECT r.*, s.name as subject_name, s.code as subject_code, s.credit_hours
        FROM results r JOIN subjects s ON r.subject_id=s.id
        WHERE r.student_id=?
        ORDER BY r.academic_year DESC, r.semester DESC, s.name
    """, (sid,)).fetchall()
    db.close()

    semesters = {}
    for r in results:
        key = f"{r['academic_year']} — Semester {r['semester']}"
        if key not in semesters:
            semesters[key] = []
        semesters[key].append(r)

    cgpa, total_credits = calc_gpa(list(results))
    return render_template(
        "admin/view_student.html",
        student=student, semesters=semesters,
        cgpa=cgpa, total_credits=total_credits,
        score_to_grade=score_to_grade
    )


@app.route("/admin/reset-password/<int:uid>", methods=["POST"])
@login_required(role="admin")
def admin_reset_password(uid):
    new_pass = request.form.get("new_password", "").strip()
    if not new_pass:
        flash("Password cannot be empty.", "error")
        return redirect(url_for("admin_students"))
    db = get_db()
    db.execute("UPDATE users SET password_hash=? WHERE id=?",
               (generate_password_hash(new_pass), uid))
    db.commit()
    db.close()
    flash("Password reset successfully.", "success")
    return redirect(url_for("admin_students"))


# ─── API ───────────────────────────────────────────────────────────────────

@app.route("/api/student-results/<int:sid>")
@login_required(role=["admin","staff"])
def api_student_results(sid):
    db = get_db()
    results = db.execute("""
        SELECT r.*, s.name as subject_name, s.code, s.credit_hours
        FROM results r JOIN subjects s ON r.subject_id=s.id
        WHERE r.student_id=?
        ORDER BY r.academic_year DESC, r.semester DESC
    """, (sid,)).fetchall()
    db.close()
    data = []
    for r in results:
        grade, point = score_to_grade(r["score"])
        data.append({**dict(r), "grade": grade, "grade_point": point})
    return jsonify(data)


# ─── Run ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
