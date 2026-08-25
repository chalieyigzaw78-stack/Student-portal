"""
app.py — Student Academic Result Portal
Waliya Primary School
Uses PostgreSQL (Neon.tech) for persistent data storage
"""

import os
import psycopg
from psycopg.rows import dict_row
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "waliya-primary-school-secret-key-2026")
DATABASE_URL = os.environ.get("DATABASE_URL")
SCHOOL_PHOTO_PATH = os.path.join("static", "school_photo.jpg")

ASSESSMENTS = [
    {"key": "quiz",       "label": "Quiz",       "max": 5},
    {"key": "test1",      "label": "Test 1",      "max": 10},
    {"key": "test2",      "label": "Test 2",      "max": 15},
    {"key": "assignment", "label": "Assignment",  "max": 10},
    {"key": "final",      "label": "Final Exam",  "max": 60},
]
GRADE_OPTIONS = ["A", "B+", "B", "C+", "C", "D", "F"]


def score_to_grade(score):
    if score >= 90: return "A",  4.0
    if score >= 85: return "B+", 3.5
    if score >= 80: return "B",  3.0
    if score >= 75: return "C+", 2.5
    if score >= 70: return "C",  2.0
    if score >= 60: return "D",  1.0
    return "F", 0.0


def grade_to_point(grade):
    return {"A":4.0,"B+":3.5,"B":3.0,"C+":2.5,"C":2.0,"D":1.0,"F":0.0}.get(grade, 0.0)


def calc_gpa(results):
    tp = tc = 0
    for r in results:
        tp += grade_to_point(r["confirmed_grade"]) * r["credit_hours"]
        tc += r["credit_hours"]
    return (round(tp/tc, 2), tc) if tc else (0.0, 0)


# ─── Database ──────────────────────────────────────────────────────────────

def get_db():
    conn = psycopg2.connect(DATABASE_URL, row_factory=dict_row)
    return conn


def init_db():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            SERIAL PRIMARY KEY,
            user_id       TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name     TEXT NOT NULL,
            role          TEXT NOT NULL CHECK(role IN ('admin','staff','student')),
            department    TEXT,
            year          INTEGER,
            section       TEXT,
            email         TEXT,
            phone         TEXT,
            created_at    TIMESTAMP NOT NULL DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subjects (
            id           SERIAL PRIMARY KEY,
            code         TEXT NOT NULL UNIQUE,
            name         TEXT NOT NULL,
            credit_hours INTEGER NOT NULL DEFAULT 3,
            department   TEXT,
            created_at   TIMESTAMP NOT NULL DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id              SERIAL PRIMARY KEY,
            student_id      INTEGER NOT NULL REFERENCES users(id),
            subject_id      INTEGER NOT NULL REFERENCES subjects(id),
            staff_id        INTEGER REFERENCES users(id),
            quiz            REAL NOT NULL DEFAULT 0,
            test1           REAL NOT NULL DEFAULT 0,
            test2           REAL NOT NULL DEFAULT 0,
            assignment      REAL NOT NULL DEFAULT 0,
            final           REAL NOT NULL DEFAULT 0,
            total_score     REAL NOT NULL DEFAULT 0,
            suggested_grade TEXT NOT NULL DEFAULT '',
            confirmed_grade TEXT NOT NULL DEFAULT '',
            is_released     INTEGER NOT NULL DEFAULT 0,
            semester        TEXT NOT NULL,
            academic_year   TEXT NOT NULL,
            note            TEXT,
            created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE(student_id, subject_id, semester, academic_year)
        );
    """)
    # Default admin
    cur.execute("SELECT id FROM users WHERE role='admin' LIMIT 1")
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users (user_id, password_hash, full_name, role) VALUES (%s,%s,%s,%s)",
            ("admin", generate_password_hash("admin123"), "System Administrator", "admin")
        )
        print("[db] Default admin: ID=admin, Password=admin123")
    conn.commit()
    cur.close()
    conn.close()


init_db()


# ─── Auth ──────────────────────────────────────────────────────────────────

def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if role:
                allowed = role if isinstance(role, (list, tuple)) else [role]
                if session.get("role") not in allowed:
                    flash("Access denied.", "error")
                    return redirect(url_for("login"))
            return f(*args, **kwargs)
        return decorated
    return decorator


def current_user():
    if "user_id" not in session: return None
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id=%s", (session["user_id"],))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user


# ─── Routes ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if "user_id" in session:
        r = session.get("role")
        if r == "student": return redirect(url_for("student_dashboard"))
        if r == "staff":   return redirect(url_for("staff_dashboard"))
        if r == "admin":   return redirect(url_for("admin_dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        uid = request.form.get("user_id","").strip()
        pw  = request.form.get("password","").strip()
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id=%s", (uid,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        if user and check_password_hash(user["password_hash"], pw):
            session["user_id"] = user["id"]
            session["role"]    = user["role"]
            session["name"]    = user["full_name"]
            if user["role"] == "student": return redirect(url_for("student_dashboard"))
            if user["role"] == "staff":   return redirect(url_for("staff_dashboard"))
            if user["role"] == "admin":   return redirect(url_for("admin_dashboard"))
        else:
            flash("Invalid ID or password.", "error")
    return render_template("login.html", school_photo=os.path.exists(SCHOOL_PHOTO_PATH))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ─── Student ───────────────────────────────────────────────────────────────

@app.route("/student")
@login_required(role="student")
def student_dashboard():
    user = current_user()
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT r.*, s.name as subject_name, s.code as subject_code, s.credit_hours
        FROM results r JOIN subjects s ON r.subject_id=s.id
        WHERE r.student_id=%s AND r.is_released=1
        ORDER BY r.academic_year DESC, r.semester DESC, s.name
    """, (user["id"],))
    results = cur.fetchall()
    cur.close()
    conn.close()
    semesters = {}
    for r in results:
        semesters.setdefault(f"{r['academic_year']} — Semester {r['semester']}", []).append(r)
    semester_gpas = {k: dict(zip(["gpa","credits"], calc_gpa(v))) for k,v in semesters.items()}
    cgpa, total_credits = calc_gpa(list(results))
    return render_template("student/dashboard.html",
        user=user, semesters=semesters, semester_gpas=semester_gpas,
        cgpa=cgpa, total_credits=total_credits,
        grade_to_point=grade_to_point, assessments=ASSESSMENTS)


@app.route("/student/profile")
@login_required(role="student")
def student_profile():
    return render_template("student/profile.html", user=current_user())


# ─── Staff ─────────────────────────────────────────────────────────────────

@app.route("/staff")
@login_required(role="staff")
def staff_dashboard():
    user = current_user()
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM users WHERE role='student' ORDER BY full_name")
    students = cur.fetchall()
    cur.execute("SELECT * FROM subjects ORDER BY name")
    subjects = cur.fetchall()
    cur.execute("""
        SELECT r.*, u.full_name, u.user_id as student_no,
               s.name as subject_name, s.code as subject_code
        FROM results r JOIN users u ON r.student_id=u.id
        JOIN subjects s ON r.subject_id=s.id
        WHERE r.staff_id=%s ORDER BY r.created_at DESC LIMIT 20
    """, (user["id"],))
    recent = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("staff/dashboard.html",
        user=user, students=students, subjects=subjects,
        recent=recent, assessments=ASSESSMENTS, grade_options=GRADE_OPTIONS)


@app.route("/staff/enter-result", methods=["POST"])
@login_required(role="staff")
def staff_enter_result():
    user = current_user()
    data = request.form
    student_id      = data.get("student_id")
    subject_id      = data.get("subject_id")
    semester        = data.get("semester")
    academic_year   = data.get("academic_year")
    confirmed_grade = data.get("confirmed_grade","").strip()
    is_released     = int(data.get("is_released", 0))
    note            = data.get("note","")

    if not all([student_id, subject_id, semester, academic_year, confirmed_grade]):
        flash("All fields including confirmed grade are required.", "error")
        return redirect(url_for("staff_dashboard"))
    if confirmed_grade not in GRADE_OPTIONS:
        flash("Invalid grade selected.", "error")
        return redirect(url_for("staff_dashboard"))

    scores = {}
    for a in ASSESSMENTS:
        try:
            val = float(data.get(a["key"], 0))
            if not 0 <= val <= a["max"]:
                flash(f"{a['label']} must be 0–{a['max']}.", "error")
                return redirect(url_for("staff_dashboard"))
            scores[a["key"]] = val
        except ValueError:
            flash(f"Invalid score for {a['label']}.", "error")
            return redirect(url_for("staff_dashboard"))

    total = sum(scores.values())
    suggested_grade, _ = score_to_grade(total)

    conn = get_db()
    cur  = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO results
              (student_id,subject_id,staff_id,quiz,test1,test2,assignment,final,
               total_score,suggested_grade,confirmed_grade,is_released,semester,academic_year,note)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(student_id,subject_id,semester,academic_year)
            DO UPDATE SET quiz=EXCLUDED.quiz,test1=EXCLUDED.test1,test2=EXCLUDED.test2,
              assignment=EXCLUDED.assignment,final=EXCLUDED.final,
              total_score=EXCLUDED.total_score,suggested_grade=EXCLUDED.suggested_grade,
              confirmed_grade=EXCLUDED.confirmed_grade,is_released=EXCLUDED.is_released,
              note=EXCLUDED.note,staff_id=EXCLUDED.staff_id,created_at=NOW()
        """, (student_id,subject_id,user["id"],
              scores["quiz"],scores["test1"],scores["test2"],
              scores["assignment"],scores["final"],
              total,suggested_grade,confirmed_grade,is_released,
              semester,academic_year,note))
        conn.commit()
        status = "Released" if is_released else "Draft"
        flash(f"Result saved as {status}. Total: {total:.1f}/100 — Grade: {confirmed_grade}", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "error")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("staff_dashboard"))


@app.route("/staff/release/<int:rid>", methods=["POST"])
@login_required(role="staff")
def staff_release(rid):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("UPDATE results SET is_released=1 WHERE id=%s", (rid,))
    conn.commit()
    cur.close()
    conn.close()
    flash("Result released to student.", "success")
    return redirect(url_for("staff_dashboard"))


@app.route("/staff/students")
@login_required(role="staff")
def staff_students():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM users WHERE role='student' ORDER BY full_name")
    students = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("staff/students.html", students=students)


@app.route("/staff/student/<int:sid>")
@login_required(role="staff")
def staff_view_student(sid):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id=%s AND role='student'", (sid,))
    student = cur.fetchone()
    if not student:
        flash("Student not found.","error")
        return redirect(url_for("staff_students"))
    cur.execute("""
        SELECT r.*, s.name as subject_name, s.code as subject_code, s.credit_hours
        FROM results r JOIN subjects s ON r.subject_id=s.id
        WHERE r.student_id=%s ORDER BY r.academic_year DESC, r.semester DESC, s.name
    """, (sid,))
    results = cur.fetchall()
    cur.close()
    conn.close()
    semesters = {}
    for r in results:
        semesters.setdefault(f"{r['academic_year']} — Semester {r['semester']}", []).append(r)
    cgpa, total_credits = calc_gpa(list(results))
    return render_template("staff/view_student.html",
        student=student, semesters=semesters,
        cgpa=cgpa, total_credits=total_credits,
        grade_to_point=grade_to_point, assessments=ASSESSMENTS)


# ─── Admin ─────────────────────────────────────────────────────────────────

@app.route("/admin")
@login_required(role="admin")
def admin_dashboard():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT COUNT(*) as c FROM users WHERE role='student'")
    students_count = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM users WHERE role='staff'")
    staff_count = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM subjects")
    subjects_count = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM results")
    results_count = cur.fetchone()["c"]
    stats = {"students": students_count, "staff": staff_count,
             "subjects": subjects_count, "results": results_count}
    cur.execute("""
        SELECT r.*, u.full_name, u.user_id as student_no,
               s.name as subject_name, st.full_name as staff_name
        FROM results r JOIN users u ON r.student_id=u.id
        JOIN subjects s ON r.subject_id=s.id
        LEFT JOIN users st ON r.staff_id=st.id
        ORDER BY r.created_at DESC LIMIT 10
    """)
    recent_results = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("admin/dashboard.html", stats=stats, recent_results=recent_results)


@app.route("/admin/upload-photo", methods=["POST"])
@login_required(role="admin")
def admin_upload_photo():
    if "photo" not in request.files or request.files["photo"].filename == "":
        flash("No file selected.", "error")
        return redirect(url_for("admin_dashboard"))
    os.makedirs("static", exist_ok=True)
    request.files["photo"].save(SCHOOL_PHOTO_PATH)
    flash("School photo updated.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/students")
@login_required(role="admin")
def admin_students():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM users WHERE role='student' ORDER BY full_name")
    students = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("admin/students.html", students=students)


@app.route("/admin/add-student", methods=["POST"])
@login_required(role="admin")
def admin_add_student():
    data = request.form
    conn = get_db()
    cur  = conn.cursor()
    try:
        cur.execute("""INSERT INTO users (user_id,password_hash,full_name,role,department,year,section,email,phone)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (data["user_id"].strip(), generate_password_hash(data["password"].strip()),
             data["full_name"].strip(), "student", data.get("department","").strip(),
             data.get("year",1), data.get("section","").strip(),
             data.get("email","").strip(), data.get("phone","").strip()))
        conn.commit()
        flash(f"Student '{data['full_name']}' added.", "success")
    except psycopg.errors.UniqueViolation:
        conn.rollback()
        flash(f"ID '{data['user_id']}' already exists.", "error")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("admin_students"))


@app.route("/admin/delete-student/<int:sid>", methods=["POST"])
@login_required(role="admin")
def admin_delete_student(sid):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("DELETE FROM results WHERE student_id=%s", (sid,))
    cur.execute("DELETE FROM users WHERE id=%s AND role='student'", (sid,))
    conn.commit()
    cur.close()
    conn.close()
    flash("Student deleted.", "success")
    return redirect(url_for("admin_students"))


@app.route("/admin/staff")
@login_required(role="admin")
def admin_staff():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM users WHERE role='staff' ORDER BY full_name")
    staff = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("admin/staff.html", staff=staff)


@app.route("/admin/add-staff", methods=["POST"])
@login_required(role="admin")
def admin_add_staff():
    data = request.form
    conn = get_db()
    cur  = conn.cursor()
    try:
        cur.execute("""INSERT INTO users (user_id,password_hash,full_name,role,department,email,phone)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (data["user_id"].strip(), generate_password_hash(data["password"].strip()),
             data["full_name"].strip(), "staff", data.get("department","").strip(),
             data.get("email","").strip(), data.get("phone","").strip()))
        conn.commit()
        flash(f"Staff '{data['full_name']}' added.", "success")
    except psycopg.errors.UniqueViolation:
        conn.rollback()
        flash(f"ID '{data['user_id']}' already exists.", "error")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("admin_staff"))


@app.route("/admin/delete-staff/<int:sid>", methods=["POST"])
@login_required(role="admin")
def admin_delete_staff(sid):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("DELETE FROM users WHERE id=%s AND role='staff'", (sid,))
    conn.commit()
    cur.close()
    conn.close()
    flash("Staff deleted.", "success")
    return redirect(url_for("admin_staff"))


@app.route("/admin/subjects")
@login_required(role="admin")
def admin_subjects():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM subjects ORDER BY name")
    subjects = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("admin/subjects.html", subjects=subjects)


@app.route("/admin/add-subject", methods=["POST"])
@login_required(role="admin")
def admin_add_subject():
    data = request.form
    conn = get_db()
    cur  = conn.cursor()
    try:
        cur.execute("INSERT INTO subjects (code,name,credit_hours,department) VALUES (%s,%s,%s,%s)",
            (data["code"].strip().upper(), data["name"].strip(),
             int(data.get("credit_hours",3)), data.get("department","").strip()))
        conn.commit()
        flash(f"Subject '{data['name']}' added.", "success")
    except psycopg.errors.UniqueViolation:
        conn.rollback()
        flash(f"Code '{data['code']}' already exists.", "error")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("admin_subjects"))


@app.route("/admin/delete-subject/<int:sid>", methods=["POST"])
@login_required(role="admin")
def admin_delete_subject(sid):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("DELETE FROM results WHERE subject_id=%s", (sid,))
    cur.execute("DELETE FROM subjects WHERE id=%s", (sid,))
    conn.commit()
    cur.close()
    conn.close()
    flash("Subject deleted.", "success")
    return redirect(url_for("admin_subjects"))


@app.route("/admin/results")
@login_required(role="admin")
def admin_results():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT r.*, u.full_name, u.user_id as student_no,
               s.name as subject_name, s.code, st.full_name as staff_name
        FROM results r JOIN users u ON r.student_id=u.id
        JOIN subjects s ON r.subject_id=s.id
        LEFT JOIN users st ON r.staff_id=st.id
        ORDER BY r.created_at DESC
    """)
    results = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("admin/results.html", results=results, assessments=ASSESSMENTS)


@app.route("/admin/student/<int:sid>")
@login_required(role="admin")
def admin_view_student(sid):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id=%s", (sid,))
    student = cur.fetchone()
    cur.execute("""
        SELECT r.*, s.name as subject_name, s.code as subject_code, s.credit_hours
        FROM results r JOIN subjects s ON r.subject_id=s.id
        WHERE r.student_id=%s ORDER BY r.academic_year DESC, r.semester DESC, s.name
    """, (sid,))
    results = cur.fetchall()
    cur.close()
    conn.close()
    semesters = {}
    for r in results:
        semesters.setdefault(f"{r['academic_year']} — Semester {r['semester']}", []).append(r)
    cgpa, total_credits = calc_gpa(list(results))
    return render_template("admin/view_student.html",
        student=student, semesters=semesters,
        cgpa=cgpa, total_credits=total_credits,
        grade_to_point=grade_to_point, assessments=ASSESSMENTS)


@app.route("/admin/reset-password/<int:uid>", methods=["POST"])
@login_required(role="admin")
def admin_reset_password(uid):
    new_pass = request.form.get("new_password","").strip()
    if not new_pass:
        flash("Password cannot be empty.", "error")
        return redirect(url_for("admin_students"))
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("UPDATE users SET password_hash=%s WHERE id=%s",
               (generate_password_hash(new_pass), uid))
    conn.commit()
    cur.close()
    conn.close()
    flash("Password reset.", "success")
    return redirect(url_for("admin_students"))


@app.route("/admin/release/<int:rid>", methods=["POST"])
@login_required(role="admin")
def admin_release(rid):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("UPDATE results SET is_released=1 WHERE id=%s", (rid,))
    conn.commit()
    cur.close()
    conn.close()
    flash("Result released.", "success")
    return redirect(url_for("admin_results"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
