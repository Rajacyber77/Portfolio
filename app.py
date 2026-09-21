from flask import Flask, render_template, request, redirect, url_for, send_from_directory, send_file, session
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from io import BytesIO
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import redirect, url_for
import mysql.connector
import pandas as pd
import re
import os
import traceback
import time
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)
app.secret_key = "hall_allotment_secret_key"

# ==================================================
# ADMIN LOGIN DETAILS
# ==================================================

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

FACULTY_COMMON_PASSWORD = "Faculty@123"
FACULTY_PASSWORD_CHANGED_COLUMN = "faculty_password_changed"


# ==================================================
# UPLOAD FOLDER
# ==================================================

UPLOAD_FOLDER = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "uploads"
)

os.makedirs(
    UPLOAD_FOLDER,
    exist_ok=True
)


# ==================================================
# MYSQL DATABASE CONNECTION
# ==================================================
def get_db_connection():
    db = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        ssl_disabled=False
    )

    print("DATABASE:", db.database)

    return db


# ==================================================
# ROLE-BASED ACCESS CONTROL
# ==================================================
# Keep the existing application logic unchanged. This single
# middleware layer protects the routes according to the login role.

ADMIN_ROUTES = {
    "/admin-hall", "/students", "/student-upload", "/students-upload",
    "/delete-all-students", "/faculty-upload", "/hall-management",
    "/hall-allotment", "/delete-total-hall-allotment",
    "/admin-hall-allotment-pdf", "/hall-student-signature-pdf",
    "/hall-faculty-signature-pdf", "/admin-seating-arrangement-pdf",
    "/generate-hall-allotment", "/admin-timetable-upload",
    "/admin-attendance", "/admin-attendance-pdf",
    "/admin-attendance-summary-pdf",
    "/admin-attendance-close-all",
    "/admin-dashboard", "/admin-question-management", "/test-db", "/change-admin-password",
    "/arrear-hall-allotment",
    "/delete-arrear-timetable", "/delete-arrear-student-database",
    "/delete-total-arrear-hall-allotment", "/arrear-hall-allotment-pdf",
    "/arrear-student-seating-pdf", "/arrear-hall-faculty-signature-pdf",
}

ADMIN_PREFIXES = (
    "/delete-hall/",
    "/delete-hall-allotment/",
    "/hall-allotment-pdf/",
    "/hall-student-signature-pdf/",
    "/hall-faculty-signature-pdf/",
    "/delete-question-paper/",
    "/delete-exam-timetable/",
    "/admin-attendance-close/",
    "/admin-attendance-open/",
    "/faculty-edit/",
    "/faculty-delete/",
    "/faculty-file-delete/",
    "/view-hall-file/",
    "/delete-hall-file/",
)

FACULTY_ROUTES = {
    "/faculty-dashboard", "/faculty-timetables", "/faculty-view-timetables",
    "/faculty-attendance", "/faculty-attendance-submitted",
    "/faculty-change-password",
    "/question-paper-upload", "/question-papers",
}

FACULTY_PREFIXES = (
    "/download-faculty-timetables/",
    "/delete-faculty-timetables/",
)

STUDENT_ROUTES = {
    "/student-dashboard", "/student-timetable", "/student-hall-pdf",
}

SHARED_AUTH_ROUTES = {
    "/download-question-paper",
}


def _route_matches(path, exact_routes, prefixes):
    return path in exact_routes or any(path.startswith(p) for p in prefixes)


@app.before_request
def enforce_role_access():
    path = request.path

    # Public routes: home + login/register/logout + health/status pages.
    public_paths = {
        "/", "/admin-login", "/admin-logout",
        "/student-login", "/faculty-login", "/faculty-register",
        "/faculty-logout", "/status",
    }

    if path in public_paths or path.startswith("/static/"):
        return None

    # Admin-only routes.
    if _route_matches(path, ADMIN_ROUTES, ADMIN_PREFIXES):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return None

    # Faculty-only routes.
    if _route_matches(path, FACULTY_ROUTES, FACULTY_PREFIXES):
        if not session.get("faculty_logged_in"):
            return redirect(url_for("faculty_login"))
        return None

    # Student-only routes.
    if _route_matches(path, STUDENT_ROUTES, ()):
        if not session.get("student_register_number"):
            return redirect(url_for("student_login"))
        return None

    # Files that can be used by more than one logged-in role.
    if path.startswith("/uploads/") or _route_matches(path, SHARED_AUTH_ROUTES, ()):
        if not (
            session.get("admin_logged_in")
            or session.get("faculty_logged_in")
            or session.get("student_register_number")
        ):
            return redirect(url_for("student_login"))
        return None

    return None

# ==================================================
# HOME
# ==================================================

@app.route("/")
def home():

    return render_template("index.html")

# ==================================================
# EDIT FACULTY DETAILS
# ==================================================

# ==================================================
# FACULTY EDIT
# ==================================================

@app.route("/faculty-edit/<int:faculty_id>", methods=["GET", "POST"])
def faculty_edit(faculty_id):

    db = None
    cursor = None

    try:

        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        # ==================================================
        # GET DEPARTMENT + COURSE
        # ==================================================

        cursor.execute("""
            SELECT
                department_name,
                course_name
            FROM departments
            ORDER BY
                department_name,
                course_name
        """)

        departments = cursor.fetchall()

        # ==================================================
        # GET FACULTY DETAILS
        # ==================================================

        cursor.execute("""
            SELECT
                id,
                faculty_name,
                department,
                course
            FROM faculty_details
            WHERE id = %s
        """, (faculty_id,))

        faculty = cursor.fetchone()

        if not faculty:

            return (
                "Faculty details not found.",
                404
            )

        # ==================================================
        # UPDATE
        # ==================================================

        if request.method == "POST":

            faculty_name = (
                request.form.get(
                    "faculty_name"
                ) or ""
            ).strip()

            department = (
                request.form.get(
                    "department"
                ) or ""
            ).strip()

            course = (
                request.form.get(
                    "course"
                ) or ""
            ).strip()

            # ==================================================
            # VALIDATION
            # ==================================================

            if not all([
                faculty_name,
                department,
                course
            ]):

                return render_template(
                    "faculty_edit.html",
                    faculty=faculty,
                    departments=departments,
                    error=(
                        "Please fill all fields."
                    )
                )

            # ==================================================
            # UPDATE DATABASE
            # ==================================================

            cursor.execute("""
                UPDATE faculty_details
                SET
                    faculty_name = %s,
                    department = %s,
                    course = %s
                WHERE id = %s
            """, (
                faculty_name,
                department,
                course,
                faculty_id
            ))

            db.commit()

            return redirect(
                url_for(
                    "faculty_upload"
                )
            )

        # ==================================================
        # GET PAGE
        # ==================================================

        return render_template(
            "faculty_edit.html",
            faculty=faculty,
            departments=departments
        )

    except Exception as e:

        if db:
            db.rollback()

        return (
            "Error: " + str(e)
        )

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()


# ==================================================
# DELETE FACULTY DETAILS
# ==================================================

@app.route(
    "/faculty-delete/<int:faculty_id>",
    methods=["POST"]
)
def faculty_delete(faculty_id):

    db = None
    cursor = None

    try:

        db = get_db_connection()
        cursor = db.cursor()

        cursor.execute("""
            DELETE FROM faculty_details
            WHERE id = %s
        """, (faculty_id,))

        db.commit()

        return redirect(
            url_for("faculty_upload")
        )

    except Exception as e:

        if db:
            db.rollback()

        return "Delete Error: " + str(e)

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()
# ==================================================
# ADMIN ACCOUNT / LOGIN
# ==================================================
def ensure_admin_account():
    db = None; cursor = None
    try:
        db = get_db_connection(); cursor = db.cursor(dictionary=True)
        cursor.execute("""CREATE TABLE IF NOT EXISTS admin_credentials (id INT PRIMARY KEY AUTO_INCREMENT, username VARCHAR(100) NOT NULL UNIQUE, password_hash VARCHAR(255) NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)""")
        cursor.execute("SELECT id FROM admin_credentials WHERE username=%s LIMIT 1", (ADMIN_USERNAME,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO admin_credentials (username,password_hash) VALUES (%s,%s)", (ADMIN_USERNAME, generate_password_hash(ADMIN_PASSWORD)))
        db.commit()
    finally:
        if cursor: cursor.close()
        if db: db.close()

@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    error = None
    try:
        ensure_admin_account()
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            db = get_db_connection(); cursor = db.cursor(dictionary=True)
            cursor.execute("SELECT id,username,password_hash FROM admin_credentials WHERE username=%s LIMIT 1", (username,))
            admin = cursor.fetchone(); cursor.close(); db.close()
            if admin and check_password_hash(admin["password_hash"], password):
                session["admin_logged_in"] = True
                session["admin_username"] = admin["username"]
                return redirect(url_for("admin_dashboard"))
            error = "Invalid username or password"
    except Exception as e:
        error = "Login Error: " + str(e)
    return render_template("admin_login.html", error=error)

@app.route("/change-admin-password", methods=["GET", "POST"])
def change_admin_password():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    error = None; success = None
    if request.method == "POST":
        current = request.form.get("current_password") or ""
        new = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""
        if len(new) < 6: error = "New password must be at least 6 characters."
        elif new != confirm: error = "New passwords do not match."
        else:
            db=None; cursor=None
            try:
                db=get_db_connection(); cursor=db.cursor(dictionary=True)
                username=session.get("admin_username", ADMIN_USERNAME)
                cursor.execute("SELECT id,password_hash FROM admin_credentials WHERE username=%s LIMIT 1", (username,))
                admin=cursor.fetchone()
                if not admin or not check_password_hash(admin["password_hash"], current):
                    error="Current password is incorrect."
                else:
                    cursor.execute("UPDATE admin_credentials SET password_hash=%s WHERE id=%s", (generate_password_hash(new), admin["id"]))
                    db.commit(); success="Admin password changed successfully."
            except Exception as e:
                if db: db.rollback()
                error="Password change error: "+str(e)
            finally:
                if cursor: cursor.close()
                if db: db.close()
    return render_template("change_admin_password.html", error=error, success=success)

@app.route("/admin-logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))
      # ==================================================
# ADMIN HALL DETAILS - EXCEL UPLOAD
# ==================================================

@app.route("/admin-hall", methods=["GET", "POST"])
def admin_hall():

    success = None
    error = None

    db = None
    cursor = None

    try:

        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        # ==================================================
        # ENSURE FLOOR COLUMN EXISTS
        # ==================================================
        # MySQL versions that do not support
        # "ADD COLUMN IF NOT EXISTS" are handled safely here.
        # Existing hall-allotment logic is not changed.
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'halls'
              AND COLUMN_NAME = 'floor'
        """)

        floor_column = cursor.fetchone()

        if floor_column["total"] == 0:
            cursor.execute("""
                ALTER TABLE halls
                ADD COLUMN floor VARCHAR(100) NULL
            """)

        # ==================================================
        # UPLOAD HALL EXCEL
        # ==================================================

        if request.method == "POST":

            hall_file = request.files.get("hall_file")

            # --------------------------------------------------
            # VALIDATION
            # --------------------------------------------------

            if not hall_file:

                error = "Please select HALLS Excel file."

            elif hall_file.filename == "":

                error = "Please select HALLS Excel file."

            else:

                filename = hall_file.filename

                # --------------------------------------------------
                # CHECK FILE TYPE
                # --------------------------------------------------

                if not (
                    filename.lower().endswith(".xlsx")
                    or filename.lower().endswith(".xls")
                ):

                    error = "Please upload only Excel files."

                else:

                    # --------------------------------------------------
                    # CREATE UPLOAD FOLDER
                    # --------------------------------------------------

                    if not os.path.exists(UPLOAD_FOLDER):

                        os.makedirs(UPLOAD_FOLDER)

                    # --------------------------------------------------
                    # SAVE FILE
                    # --------------------------------------------------

                    upload_path = os.path.join(
                        UPLOAD_FOLDER,
                        filename
                    )

                    hall_file.save(upload_path)

                    # --------------------------------------------------
                    # READ EXCEL
                    # --------------------------------------------------

                    df = pd.read_excel(
                        upload_path,
                        header=0
                    )

                    # --------------------------------------------------
                    # CHECK REQUIRED COLUMNS
                    # --------------------------------------------------

                    required_columns = [
                        "HALL NAME",
                        "CAPACITY",
                        "ROWS",
                        "FLOOR"
                    ]

                    missing_columns = [
                        column
                        for column in required_columns
                        if column not in df.columns
                    ]

                    if missing_columns:

                        raise Exception(
                            "Invalid HALLS.xlsx format. "
                            "Required columns: "
                            "HALL NAME, CAPACITY, ROWS, FLOOR"
                        )

                    # --------------------------------------------------
                    # CREATE UPLOADED FILE RECORD
                    # --------------------------------------------------

                    cursor.execute(
                        """
                        INSERT INTO uploaded_hall_files
                        (
                            file_name,
                            file_path
                        )
                        VALUES
                        (
                            %s,
                            %s
                        )
                        """,
                        (
                            filename,
                            upload_path
                        )
                    )

                    upload_id = cursor.lastrowid

                    total_halls = 0

                    # ==================================================
                    # PROCESS EACH HALL
                    # ==================================================

                    for _, row in df.iterrows():

                        hall_name = str(
                            row["HALL NAME"]
                        ).strip()

                        # --------------------------------------------------
                        # SKIP EMPTY HALL NAME
                        # --------------------------------------------------

                        if (
                            hall_name == ""
                            or hall_name.lower() == "nan"
                        ):

                            continue

                        # --------------------------------------------------
                        # CAPACITY
                        # --------------------------------------------------

                        if pd.isna(row["CAPACITY"]):

                            raise Exception(
                                f"Capacity missing for hall {hall_name}."
                            )

                        seating_capacity = int(
                            row["CAPACITY"]
                        )

                        # --------------------------------------------------
                        # ROWS
                        # --------------------------------------------------

                        if pd.isna(row["ROWS"]):

                            raise Exception(
                                f"Rows missing for hall {hall_name}."
                            )

                        hall_rows = int(
                            row["ROWS"]
                        )

                        # --------------------------------------------------
                        # FLOOR
                        # --------------------------------------------------

                        if pd.isna(row["FLOOR"]):
                            raise Exception(
                                f"Floor missing for hall {hall_name}."
                            )

                        floor_name = str(row["FLOOR"]).strip()

                        if floor_name == "" or floor_name.lower() == "nan":
                            raise Exception(
                                f"Floor missing for hall {hall_name}."
                            )

                        # --------------------------------------------------
                        # VALIDATION
                        # --------------------------------------------------

                        if seating_capacity <= 0:

                            raise Exception(
                                f"Invalid capacity for hall {hall_name}."
                            )

                        if hall_rows <= 0:

                            raise Exception(
                                f"Invalid rows for hall {hall_name}."
                            )

                        # --------------------------------------------------
                        # DUPLICATE HALL CHECK
                        # --------------------------------------------------

                        cursor.execute(
                            """
                            SELECT id
                            FROM halls
                            WHERE LOWER(TRIM(hall_name))
                                  =
                                  LOWER(TRIM(%s))
                            LIMIT 1
                            """,
                            (
                                hall_name,
                            )
                        )

                        existing_hall = cursor.fetchone()

                        # --------------------------------------------------
                        # IF HALL ALREADY EXISTS
                        # --------------------------------------------------

                        if existing_hall:

                            cursor.execute(
                                """
                                UPDATE halls
                                SET
                                    seating_capacity = %s,
                                    hall_rows = %s,
                                    floor = %s,
                                    upload_id = %s
                                WHERE id = %s
                                """,
                                (
                                    seating_capacity,
                                    hall_rows,
                                    floor_name,
                                    upload_id,
                                    existing_hall["id"]
                                )
                            )

                        # --------------------------------------------------
                        # NEW HALL
                        # --------------------------------------------------

                        else:

                            cursor.execute(
                                """
                                INSERT INTO halls
                                (
                                    hall_name,
                                    seating_capacity,
                                    hall_rows,
                                    floor,
                                    upload_id
                                )
                                VALUES
                                (
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    %s
                                )
                                """,
                                (
                                    hall_name,
                                    seating_capacity,
                                    hall_rows,
                                    floor_name,
                                    upload_id
                                )
                            )

                        total_halls += 1

                    # ==================================================
                    # COMMIT
                    # ==================================================

                    db.commit()

                    success = (
                        f"{total_halls} hall(s) uploaded "
                        f"successfully."
                    )

        # ==================================================
        # GET ALL HALLS
        # ==================================================

        cursor.execute(
            """
            SELECT
                id,
                hall_name,
                seating_capacity,
                hall_rows,
                floor,
                upload_id
            FROM halls
            ORDER BY id
            """
        )

        halls = cursor.fetchall()

        # ==================================================
        # GET UPLOADED HALL FILES
        # ==================================================

        cursor.execute(
            """
            SELECT
                id,
                file_name,
                file_path,
                uploaded_at
            FROM uploaded_hall_files
            ORDER BY uploaded_at DESC
            """
        )

        uploaded_hall_files = cursor.fetchall()

        # ==================================================
        # DISPLAY PAGE
        # ==================================================

        return render_template(
            "admin_hall.html",
            success=success,
            error=error,
            halls=halls,
            uploaded_hall_files=uploaded_hall_files
        )

    except Exception as e:

        if db:
            db.rollback()

        error = "Error: " + str(e)

        return render_template(
            "admin_hall.html",
            success=None,
            error=error,
            halls=[],
            uploaded_hall_files=[]
        )

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()


# ==================================================
# DELETE SINGLE HALL
# ==================================================

@app.route(
    "/delete-hall/<int:hall_id>",
    methods=["POST"]
)
def delete_hall(hall_id):

    db = None
    cursor = None

    try:

        db = get_db_connection()

        cursor = db.cursor(dictionary=True)

        # ==================================================
        # GET HALL DETAILS
        # ==================================================

        cursor.execute(
            """
            SELECT
                id,
                hall_name,
                upload_id
            FROM halls
            WHERE id = %s
            """,
            (
                hall_id,
            )
        )

        hall = cursor.fetchone()

        if not hall:

            return redirect(
                url_for(
                    "admin_hall",
                    error="Hall not found."
                )
            )

        upload_id = hall["upload_id"]

        # ==================================================
        # DELETE HALL
        # ==================================================

        cursor.execute(
            """
            DELETE FROM halls
            WHERE id = %s
            """,
            (
                hall_id,
            )
        )

        # ==================================================
        # CHECK WHETHER UPLOAD FILE IS STILL USED
        # ==================================================

        if upload_id:

            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM halls
                WHERE upload_id = %s
                """,
                (
                    upload_id,
                )
            )

            result = cursor.fetchone()

            remaining_halls = result["total"]

            # --------------------------------------------------
            # DELETE UPLOAD RECORD + PHYSICAL FILE
            # ONLY IF NO HALL USES IT
            # --------------------------------------------------

            if remaining_halls == 0:

                cursor.execute(
                    """
                    SELECT file_path
                    FROM uploaded_hall_files
                    WHERE id = %s
                    """,
                    (
                        upload_id,
                    )
                )

                upload_data = cursor.fetchone()

                if upload_data:

                    file_path = upload_data["file_path"]

                    if (
                        file_path
                        and os.path.exists(file_path)
                    ):

                        os.remove(file_path)

                cursor.execute(
                    """
                    DELETE FROM uploaded_hall_files
                    WHERE id = %s
                    """,
                    (
                        upload_id,
                    )
                )

        db.commit()

        return redirect(
            url_for(
                "admin_hall",
                success=(
                    f"{hall['hall_name']} "
                    f"deleted successfully."
                )
            )
        )

    except Exception as e:

        if db:
            db.rollback()

        return redirect(
            url_for(
                "admin_hall",
                error="Delete Error: " + str(e)
            )
        )

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()


# ==================================================
# VIEW UPLOADED HALL EXCEL
# ==================================================

@app.route(
    "/view-hall-file/<int:file_id>"
)
def view_hall_file(file_id):

    db = None
    cursor = None

    try:

        db = get_db_connection()

        cursor = db.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                file_name,
                file_path
            FROM uploaded_hall_files
            WHERE id = %s
            """,
            (
                file_id,
            )
        )

        file_data = cursor.fetchone()

        if not file_data:

            return "Hall Excel file not found."

        file_path = file_data["file_path"]

        if not os.path.exists(file_path):

            return "Physical Excel file not found."

        return send_file(
            file_path,
            as_attachment=False
        )

    except Exception as e:

        return "View Error: " + str(e)

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()


# ==================================================
# DELETE UPLOADED HALL EXCEL
# ==================================================

@app.route(
    "/delete-hall-file/<int:file_id>",
    methods=["POST"]
)
def delete_hall_file(file_id):

    db = None
    cursor = None

    try:

        db = get_db_connection()

        cursor = db.cursor(dictionary=True)

        # ==================================================
        # GET FILE
        # ==================================================

        cursor.execute(
            """
            SELECT
                file_name,
                file_path
            FROM uploaded_hall_files
            WHERE id = %s
            """,
            (
                file_id,
            )
        )

        file_data = cursor.fetchone()

        if not file_data:

            return redirect(
                url_for(
                    "admin_hall",
                    error="Uploaded hall file not found."
                )
            )

        # ==================================================
        # DELETE RELATED HALLS
        # ==================================================

        cursor.execute(
            """
            DELETE FROM halls
            WHERE upload_id = %s
            """,
            (
                file_id,
            )
        )

        # ==================================================
        # DELETE PHYSICAL FILE
        # ==================================================

        file_path = file_data["file_path"]

        if (
            file_path
            and os.path.exists(file_path)
        ):

            os.remove(file_path)

        # ==================================================
        # DELETE FILE RECORD
        # ==================================================

        cursor.execute(
            """
            DELETE FROM uploaded_hall_files
            WHERE id = %s
            """,
            (
                file_id,
            )
        )

        db.commit()

        return redirect(
            url_for(
                "admin_hall",
                success=(
                    f"{file_data['file_name']} "
                    f"deleted successfully."
                )
            )
        )

    except Exception as e:

        if db:
            db.rollback()

        return redirect(
            url_for(
                "admin_hall",
                error="Delete File Error: " + str(e)
            )
        )

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()


# ==================================================
# ADMIN DASHBOARD STATUS SEARCH
# ==================================================
def _fill_timetable_departments(cursor, timetable_results):
    """Fill blank timetable departments from the Students table.

    Older timetable uploads may have saved department as blank. For Status
    timetable searches, derive the department using normalized Course + Year.
    Existing Hall/Faculty allotment logic is not changed.
    """
    if not timetable_results:
        return

    cursor.execute("""
        SELECT department, course, year
        FROM students
        WHERE department IS NOT NULL
          AND TRIM(department) <> ''
          AND course IS NOT NULL
          AND TRIM(course) <> ''
          AND year IS NOT NULL
          AND TRIM(year) <> ''
    """)
    student_rows = cursor.fetchall()

    department_map = {}
    for student in student_rows:
        course_key = normalize_course_for_match(student.get("course"))
        year_key = normalize_year_for_match(student.get("year"))
        department = str(student.get("department") or "").strip()
        if not course_key or not year_key or not department:
            continue
        key = (course_key.lower(), year_key.lower())
        department_map.setdefault(key, [])
        if department.lower() not in {d.lower() for d in department_map[key]}:
            department_map[key].append(department)

    for row in timetable_results:
        current = str(row.get("department") or "").strip()
        if current:
            continue
        course_key = normalize_course_for_match(row.get("course"))
        year_key = normalize_year_for_match(row.get("year"))
        key = (course_key.lower(), year_key.lower()) if course_key and year_key else None
        departments = department_map.get(key, []) if key else []
        row["department"] = ", ".join(departments) if departments else "-"


@app.route("/status", methods=["GET"])
def status():

    search = (request.args.get("search") or "").strip()
    search_type = (request.args.get("search_type") or "hall_faculty").strip().lower()

    status_results = []
    timetable_results = []

    if search:
        db = None
        cursor = None
        try:
            db = get_db_connection()
            cursor = db.cursor(dictionary=True, buffered=True)

            # ==================================================
            # EXISTING FEATURE: HALL NAME / FACULTY NAME SEARCH
            # ==================================================
            if search_type == "hall_faculty":
                cursor.execute("""
                    SELECT
                        h.hall_name,
                        s.register_number,
                        s.name AS student_name,
                        s.course,
                        s.year,
                        NULL AS subject,
                        NULL AS subject_name,
                        f.faculty_name,
                        f.department AS faculty_department,
                        e.exam_date,
                        e.exam_type,
                        e.exam_name,
                        e.start_time,
                        e.end_time,
                        a.seat_number,
                        a.row_no,
                        a.column_no,
                        a.side
                    FROM allotments a
                    INNER JOIN students s ON a.student_id = s.id
                    INNER JOIN halls h ON a.hall_id = h.id
                    INNER JOIN exam_timetable e ON a.exam_id = e.id
                    LEFT JOIN faculty_details f ON a.faculty_id = f.id
                    WHERE UPPER(TRIM(e.course)) = 'HALL ALLOTMENT'
                      AND UPPER(TRIM(e.year)) = 'ALL'
                      AND (
                        LOWER(TRIM(h.hall_name)) LIKE LOWER(TRIM(%s))
                        OR LOWER(TRIM(COALESCE(f.faculty_name, ''))) LIKE LOWER(TRIM(%s))
                      )
                    ORDER BY e.exam_date DESC, h.hall_name, a.seat_number, a.side
                """, ("%" + search + "%", "%" + search + "%"))
                status_results = cursor.fetchall()

                # Keep existing timetable subject-code matching for allotment status.
                cursor.execute("""
                    SELECT id, course, year, subject, subject_name, subject_name,
                           exam_date, exam_type, exam_name
                    FROM exam_timetable
                    WHERE UPPER(TRIM(course)) <> 'HALL ALLOTMENT'
                """)
                timetable_rows = cursor.fetchall()
                timetable_map = {}
                for tt in timetable_rows:
                    tt_date = tt.get("exam_date")
                    if hasattr(tt_date, "date"):
                        tt_date = tt_date.date()
                    key = (
                        normalize_course_for_match(tt.get("course")),
                        normalize_year_for_match(tt.get("year")),
                        str(tt_date or ""),
                        str(tt.get("exam_type") or "").strip().lower(),
                        str(tt.get("exam_name") or "").strip().lower()
                    )
                    subject = str(tt.get("subject_name") or tt.get("subject") or "").strip()
                    subject_name = str(tt.get("subject_name") or "").strip()
                    if subject or subject_name:
                        timetable_map[key] = {"subject": subject, "subject_name": subject_name}

                for row in status_results:
                    row_date = row.get("exam_date")
                    if hasattr(row_date, "date"):
                        row_date = row_date.date()
                    key = (
                        normalize_course_for_match(row.get("course")),
                        normalize_year_for_match(row.get("year")),
                        str(row_date or ""),
                        str(row.get("exam_type") or "").strip().lower(),
                        str(row.get("exam_name") or "").strip().lower()
                    )
                    detail = timetable_map.get(key)
                    row["subject"] = detail["subject"] if detail else ""
                    row["subject_name"] = detail["subject_name"] if detail else ""

                for row in status_results:
                    if row.get("exam_date") is not None:
                        row["exam_date"] = str(row["exam_date"])
                    if row.get("start_time") is not None:
                        row["start_time"] = str(row["start_time"])
                    if row.get("end_time") is not None:
                        row["end_time"] = str(row["end_time"])

                summary = {}
                for row in status_results:
                    course = str(row.get("course") or "").strip()
                    subject_name = str(row.get("subject_name") or "").strip()
                    subject = str(row.get("subject") or "").strip()
                    faculty_name = str(row.get("faculty_name") or "").strip()
                    register_number = str(row.get("register_number") or "").strip()
                    key = (course.lower(), subject_name.lower(), subject.lower(), faculty_name.lower())
                    if key not in summary:
                        summary[key] = {
                            "course": course, "subject_name": subject_name,
                            "subject": subject, "strength": 0,
                            "register_numbers": [], "faculty_name": faculty_name
                        }
                    summary[key]["strength"] += 1
                    if register_number:
                        summary[key]["register_numbers"].append(register_number)

                for item in summary.values():
                    regs = list(dict.fromkeys(item["register_numbers"]))
                    regs.sort(key=lambda x: str(x).lower())
                final_results = []
                for item in summary.values():
                    regs = list(dict.fromkeys(item["register_numbers"]))
                    regs.sort(key=lambda x: str(x).lower())
                    final_results.append({
                        "course": item["course"],
                        "subject_name": item["subject_name"] or "-",
                        "subject": item["subject"] or "-",
                        "strength": item["strength"],
                        "reg_no_from": regs[0] if regs else "-",
                        "reg_no_to": regs[-1] if regs else "-",
                        "faculty_name": item["faculty_name"] or "-"
                    })
                final_results.sort(key=lambda x: (str(x.get("course") or "").lower(), str(x.get("subject") or "").lower()))
                status_results = final_results

            # ==================================================
            # NEW FEATURE: EXAM DATE SEARCH FROM TIMETABLE
            # ==================================================
            elif search_type == "exam_date":
                from datetime import datetime
                parsed_date = None
                for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
                    try:
                        parsed_date = datetime.strptime(search, fmt).date()
                        break
                    except ValueError:
                        pass
                if not parsed_date:
                    raise ValueError("Enter exam date as DD-MM-YYYY or YYYY-MM-DD.")

                cursor.execute("""
                    SELECT department, course, year, subject, subject_name,
                           subject_name, exam_date, start_time, end_time,
                           exam_type, exam_name
                    FROM exam_timetable
                    WHERE UPPER(TRIM(course)) <> 'HALL ALLOTMENT'
                      AND DATE(exam_date) = %s
                    ORDER BY course, year, start_time, subject
                """, (parsed_date,))
                timetable_results = cursor.fetchall()
                _fill_timetable_departments(cursor, timetable_results)

            # ==================================================
            # NEW FEATURE: COURSE SEARCH FROM TIMETABLE
            # ==================================================
            elif search_type == "course":
                cursor.execute("""
                    SELECT department, course, year, subject, subject_name,
                           subject_name, exam_date, start_time, end_time,
                           exam_type, exam_name
                    FROM exam_timetable
                    WHERE UPPER(TRIM(course)) <> 'HALL ALLOTMENT'
                      AND LOWER(TRIM(course)) LIKE LOWER(TRIM(%s))
                    ORDER BY exam_date, year, start_time, subject
                """, ("%" + search + "%",))
                timetable_results = cursor.fetchall()
                _fill_timetable_departments(cursor, timetable_results)

            # ==================================================
            # NEW FEATURE: DATE + COURSE SEARCH FROM TIMETABLE
            # Search text format: COURSE | DD-MM-YYYY
            # ==================================================
            elif search_type == "date_course":
                parts = [x.strip() for x in search.split("|")]
                if len(parts) != 2:
                    raise ValueError("Use format: Course | Exam Date (example: BCA | 15-09-2026).")
                course_text, date_text = parts
                from datetime import datetime
                parsed_date = None
                for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
                    try:
                        parsed_date = datetime.strptime(date_text, fmt).date()
                        break
                    except ValueError:
                        pass
                if not parsed_date:
                    raise ValueError("Invalid exam date in Course + Date search.")
                cursor.execute("""
                    SELECT department, course, year, subject, subject_name,
                           subject_name, exam_date, start_time, end_time,
                           exam_type, exam_name
                    FROM exam_timetable
                    WHERE UPPER(TRIM(course)) <> 'HALL ALLOTMENT'
                      AND LOWER(TRIM(course)) LIKE LOWER(TRIM(%s))
                      AND DATE(exam_date) = %s
                    ORDER BY course, year, start_time, subject
                """, ("%" + course_text + "%", parsed_date))
                timetable_results = cursor.fetchall()
                _fill_timetable_departments(cursor, timetable_results)

            for row in timetable_results:
                if row.get("exam_date") is not None:
                    row["exam_date"] = str(row["exam_date"])
                if row.get("start_time") is not None:
                    row["start_time"] = str(row["start_time"])
                if row.get("end_time") is not None:
                    row["end_time"] = str(row["end_time"])
                row["subject"] = str(row.get("subject_name") or row.get("subject") or "").strip()
                row["subject_name"] = str(row.get("subject_name") or "").strip()

        except Exception as e:
            return render_template(
                "status.html", status_results=[], timetable_results=[],
                search=search, search_type=search_type,
                status_error="Status Search Error: " + str(e)
            )
        finally:
            if cursor:
                cursor.close()
            if db:
                db.close()

    return render_template(
        "status.html",
        status_results=status_results,
        timetable_results=timetable_results,
        search=search,
        search_type=search_type
    )

# ==================================================
# ADMIN DASHBOARD
# ==================================================

@app.route("/admin-dashboard")
def admin_dashboard():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    return render_template("admin_dashboard.html")


# ==================================================
# TEST MYSQL CONNECTION
# ==================================================

@app.route("/test-db")
def test_db():

    db = None
    cursor = None

    try:

        db = get_db_connection()
        cursor = db.cursor()

        cursor.execute("SELECT 1")
        cursor.fetchone()

        return "MySQL Connected Successfully!"

    except Exception as e:

        return "MySQL Connection Error: " + str(e)

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()


@app.route(
    "/student-login",
    methods=["GET", "POST"]
)
def student_login():

    error = None

    if request.method == "POST":

        register_number = request.form.get(
            "register_number"
        )

        if not register_number:

            error = "Please enter your Register Number."

            return render_template(
                "student_login.html",
                error=error
            )

        db = None
        cursor = None

        try:

            db = get_db_connection()

            cursor = db.cursor(
                dictionary=True
            )

            # ------------------------------------------
            # CHECK STUDENT
            # ------------------------------------------

            cursor.execute(
                """
                SELECT
                    id,
                    register_number,
                    name,
                    department,
                    course,
                    year
                FROM students
                WHERE register_number = %s
                """,
                (register_number,)
            )

            student = cursor.fetchone()

            if student is None:

                return render_template(
                    "student_login.html",
                    error="Register Number not found."
                )

            # ------------------------------------------
            # SAVE STUDENT DETAILS IN SESSION
            # ------------------------------------------

            session["student_register_number"] = (
                student["register_number"]
            )

            session["student_department"] = (
                student["department"]
            )

            session["student_course"] = (
                student["course"]
            )

            session["student_year"] = (
                student["year"]
            )

            # ------------------------------------------
            # GO TO STUDENT DASHBOARD
            # ------------------------------------------

            return redirect(
                url_for("student_dashboard")
            )

        except Exception as e:

            return render_template(
                "student_login.html",
                error="Login Error: " + str(e)
            )

        finally:

            if cursor:
                cursor.close()

            if db:
                db.close()

    return render_template(
        "student_login.html",
        error=error
    )
# ==================================================
# FACULTY REGISTER
# ==================================================

# ==================================================
# FACULTY REGISTER
# ==================================================

@app.route(
    "/faculty-register",
    methods=["GET", "POST"]
)
def faculty_register():

    db = None
    cursor = None

    try:

        db = get_db_connection()

        cursor = db.cursor(
            dictionary=True,
            buffered=True
        )

        # ==================================================
        # GET DEPARTMENT + COURSE
        # ==================================================

        cursor.execute("""
            SELECT
                department_name,
                course_name
            FROM departments
            ORDER BY
                department_name,
                course_name
        """)

        departments = cursor.fetchall()

        # ==================================================
        # REGISTER
        # ==================================================

        if request.method == "POST":

            name = (
                request.form.get("name") or ""
            ).strip()

            username = (
                request.form.get("username") or ""
            ).strip()

            password = (
                request.form.get("password") or ""
            )

            confirm_password = (
                request.form.get(
                    "confirm_password"
                ) or ""
            )

            department = (
                request.form.get(
                    "department"
                ) or ""
            ).strip()

            course = (
                request.form.get(
                    "course"
                ) or ""
            ).strip()

            # ==================================================
            # VALIDATION
            # ==================================================

            if not all([
                name,
                username,
                password,
                confirm_password,
                department,
                course
            ]):

                return render_template(
                    "faculty_register.html",
                    departments=departments,
                    error="Please fill all fields."
                )

            # ==================================================
            # PASSWORD MATCH
            # ==================================================

            if password != confirm_password:

                return render_template(
                    "faculty_register.html",
                    departments=departments,
                    error="Passwords do not match."
                )

            # ==================================================
            # CHECK ADMIN ADDED FACULTY
            #
            # Year is NOT checked now.
            # ==================================================

            cursor.execute(
                """
                SELECT
                    id
                FROM faculty_details
                WHERE
                    LOWER(TRIM(faculty_name))
                    =
                    LOWER(TRIM(%s))

                    AND

                    LOWER(TRIM(department))
                    =
                    LOWER(TRIM(%s))

                    AND

                    LOWER(TRIM(course))
                    =
                    LOWER(TRIM(%s))
                """,
                (
                    name,
                    department,
                    course
                )
            )

            admin_faculty = cursor.fetchone()

            if not admin_faculty:

                return render_template(
                    "faculty_register.html",
                    departments=departments,
                    error=(
                        "Your Faculty Name, Department "
                        "and Course do not match "
                        "the details added by Admin."
                    )
                )

            # ==================================================
            # CHECK USERNAME
            # ==================================================

            cursor.execute(
                """
                SELECT
                    id
                FROM faculty
                WHERE username = %s
                """,
                (username,)
            )

            existing_user = cursor.fetchone()

            if existing_user:

                return render_template(
                    "faculty_register.html",
                    departments=departments,
                    error="Username already exists."
                )

            # ==================================================
            # HASH PASSWORD
            # ==================================================

            hashed_password = (
                generate_password_hash(
                    password
                )
            )

            # ==================================================
            # SAVE FACULTY
            #
            # Year removed.
            # ==================================================

            cursor.execute(
                """
                INSERT INTO faculty
                (
                    name,
                    username,
                    password,
                    department,
                    course
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    name,
                    username,
                    hashed_password,
                    department,
                    course
                )
            )

            db.commit()

            return redirect(
                url_for("faculty_login")
            )

        # ==================================================
        # GET REGISTER PAGE
        # ==================================================

        return render_template(
            "faculty_register.html",
            departments=departments
        )

    # ==================================================
    # DUPLICATE USERNAME
    # ==================================================

    except mysql.connector.IntegrityError:

        if db:
            db.rollback()

        return render_template(
            "faculty_register.html",
            departments=departments,
            error="Username already exists."
        )

    # ==================================================
    # OTHER ERROR
    # ==================================================

    except Exception as e:

        if db:
            db.rollback()

        return render_template(
            "faculty_register.html",
            departments=departments,
            error=(
                "Registration Error: "
                + str(e)
            )
        )

    # ==================================================
    # CLOSE DATABASE
    # ==================================================

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()
# ==================================================
# FACULTY LOGIN
# ==================================================

@app.route(
    "/faculty-login",
    methods=["GET", "POST"]
)
def faculty_login():

    error = None

    if request.method == "POST":

        faculty_code = (
            request.form.get("faculty_code")
            or request.form.get("username")
            or ""
        ).strip()

        password = (request.form.get("password") or "").strip()

        db = None
        cursor = None

        try:
            db = get_db_connection()
            cursor = db.cursor(dictionary=True)

            # Make sure login columns exist.
            cursor.execute("""
                SELECT COUNT(*) AS total
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'faculty_details'
                  AND COLUMN_NAME = 'faculty_code'
            """)
            if cursor.fetchone()["total"] == 0:
                cursor.execute("""
                    ALTER TABLE faculty_details
                    ADD COLUMN faculty_code VARCHAR(50) NULL
                """)

            cursor.execute("""
                SELECT COUNT(*) AS total
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'faculty_details'
                  AND COLUMN_NAME = 'faculty_password_hash'
            """)
            if cursor.fetchone()["total"] == 0:
                cursor.execute("""
                    ALTER TABLE faculty_details
                    ADD COLUMN faculty_password_hash VARCHAR(255) NULL
                """)

            cursor.execute("""
                SELECT COUNT(*) AS total
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'faculty_details'
                  AND COLUMN_NAME = 'faculty_password_changed'
            """)
            if cursor.fetchone()["total"] == 0:
                cursor.execute("""
                    ALTER TABLE faculty_details
                    ADD COLUMN faculty_password_changed TINYINT(1) NOT NULL DEFAULT 0
                """)

            cursor.execute("""
                SELECT
                    id,
                    faculty_code,
                    faculty_name,
                    department,
                    course,
                    faculty_password_hash,
                    faculty_password_changed
                FROM faculty_details
                WHERE LOWER(TRIM(faculty_code))
                      = LOWER(TRIM(%s))
                LIMIT 1
            """, (faculty_code,))

            faculty = cursor.fetchone()

            if not faculty:
                error = "Invalid Faculty ID or password."

            else:
                # Existing faculty records get the common password
                # initialized automatically.
                if not faculty["faculty_password_hash"]:
                    new_hash = generate_password_hash(
                        FACULTY_COMMON_PASSWORD
                    )

                    cursor.execute("""
                        UPDATE faculty_details
                        SET faculty_password_hash = %s,
                            faculty_password_changed = 0
                        WHERE id = %s
                    """, (new_hash, faculty["id"]))

                    db.commit()
                    faculty["faculty_password_hash"] = new_hash

                password_ok = check_password_hash(
                    faculty["faculty_password_hash"],
                    password
                )

                # If this account has never changed its password, allow the
                # common initial password even if an older/stale hash exists.
                if (
                    not password_ok
                    and password == FACULTY_COMMON_PASSWORD
                    and not faculty.get("faculty_password_changed", 0)
                ):
                    fresh_hash = generate_password_hash(FACULTY_COMMON_PASSWORD)
                    cursor.execute("""
                        UPDATE faculty_details
                        SET faculty_password_hash = %s,
                            faculty_password_changed = 0
                        WHERE id = %s
                    """, (fresh_hash, faculty["id"]))
                    db.commit()
                    password_ok = True

                if password_ok:
                    session["faculty_logged_in"] = True
                    session["faculty_db_id"] = faculty["id"]
                    session["faculty_code"] = faculty["faculty_code"]
                    session["faculty_name"] = faculty["faculty_name"]

                    return redirect(
                        url_for("faculty_dashboard")
                    )

                error = "Invalid Faculty ID or password."

        except Exception as e:
            error = "Login Error: " + str(e)

        finally:
            if cursor:
                cursor.close()

            if db:
                db.close()

    return render_template(
        "faculty_login.html",
        error=error
    )


# ==================================================
# FACULTY CHANGE PASSWORD
# ==================================================

@app.route(
    "/faculty-change-password",
    methods=["GET", "POST"]
)
def faculty_change_password():

    if not session.get("faculty_logged_in"):
        return redirect(url_for("faculty_login"))

    error = None
    success = None

    if request.method == "POST":

        current_password = request.form.get(
            "current_password"
        ) or ""

        new_password = request.form.get(
            "new_password"
        ) or ""

        confirm_password = request.form.get(
            "confirm_password"
        ) or ""

        if len(new_password) < 6:
            error = "New password must be at least 6 characters."

        elif new_password != confirm_password:
            error = "New passwords do not match."

        else:
            db = None
            cursor = None

            try:
                db = get_db_connection()
                cursor = db.cursor(dictionary=True)

                faculty_id = session.get("faculty_db_id")

                cursor.execute("""
                    SELECT
                        id,
                        faculty_password_hash
                    FROM faculty_details
                    WHERE id = %s
                    LIMIT 1
                """, (faculty_id,))

                faculty = cursor.fetchone()

                if not faculty:
                    error = "Faculty account not found."

                elif not faculty["faculty_password_hash"]:
                    error = "Faculty password is not initialized."

                elif not check_password_hash(
                    faculty["faculty_password_hash"],
                    current_password
                ):
                    error = "Current password is incorrect."

                else:
                    cursor.execute("""
                        UPDATE faculty_details
                        SET faculty_password_hash = %s,
                            faculty_password_changed = 1
                        WHERE id = %s
                    """, (
                        generate_password_hash(new_password),
                        faculty_id
                    ))

                    db.commit()
                    success = "Password changed successfully."

            except Exception as e:
                if db:
                    db.rollback()

                error = "Password change error: " + str(e)

            finally:
                if cursor:
                    cursor.close()

                if db:
                    db.close()

    return render_template(
        "faculty_change_password.html",
        error=error,
        success=success
    )


@app.route("/faculty-logout")
def faculty_logout():

    session.pop("faculty_logged_in", None)
    session.pop("faculty_db_id", None)
    session.pop("faculty_code", None)
    session.pop("faculty_name", None)

    return redirect(url_for("faculty_login"))


# ==================================================
# FACULTY DASHBOARD
# ==================================================

@app.route("/faculty-dashboard")
def faculty_dashboard():

    # Faculty login check
    if not session.get("faculty_logged_in"):
        return redirect(url_for("faculty_login"))

    # Get faculty details from session
    faculty_name = session.get("faculty_name", "Faculty")
    faculty_code = session.get("faculty_code", "")

    # Send details to dashboard HTML
    return render_template(
        "faculty_dashboard.html",
        faculty_name=faculty_name,
        faculty_code=faculty_code
    )
# ==================================================
# STUDENT EXCEL UPLOAD
# ==================================================

@app.route(
    "/student-upload",
    methods=["GET", "POST"]
)
# ==================================================
# STUDENT EXCEL UPLOAD
# ==================================================

# ==================================================
# STUDENT EXCEL UPLOAD
# ==================================================

@app.route("/student-upload", methods=["GET", "POST"])
def student_upload():

    if request.method == "POST":

        file = request.files.get("student_file")

        if file is None or file.filename == "":
            return render_template(
                "student_upload.html",
                error="Please select an Excel file."
            )

        if not file.filename.lower().endswith(".xlsx"):
            return render_template(
                "student_upload.html",
                error="Only .xlsx files are allowed."
            )

        db = None
        cursor = None

        try:

            # ------------------------------------------
            # OPEN EXCEL
            # ------------------------------------------

            excel_file = pd.ExcelFile(file)

            db = get_db_connection()

            cursor = db.cursor()

            total_students = 0

            # ------------------------------------------
            # PROCESS EACH SHEET
            # ------------------------------------------

            for sheet_name in excel_file.sheet_names:

                print("PROCESSING SHEET:", sheet_name)

                df = pd.read_excel(
                    excel_file,
                    sheet_name=sheet_name,
                    header=None
                )

                # --------------------------------------
                # FIND HEADER ROW
                # --------------------------------------

                header_row = None

                # Convert once instead of calling
                # df.to_numpy() for every row
                sheet_values = df.to_numpy()

                for i, values in enumerate(sheet_values):

                    row_values = [
                        str(value).strip().upper()
                        for value in values
                    ]

                    row_text = " ".join(row_values)

                    clean_row_text = (
                        row_text
                        .replace(" ", "")
                        .replace(".", "")
                        .replace("_", "")
                        .replace("-", "")
                        .upper()
                    )

                    if (
                        (
                            "REGNO" in clean_row_text
                            or "REGISTERNO" in clean_row_text
                            or "REGISTERNUMBER" in clean_row_text
                            or "REGNUMBER" in clean_row_text
                        )
                        and
                        (
                            "STUDENTNAME" in clean_row_text
                            or "NAME" in clean_row_text
                        )
                    ):

                        header_row = int(i)

                        print(
                            "HEADER FOUND:",
                            sheet_name,
                            "ROW:",
                            header_row
                        )

                        break

                # --------------------------------------
                # HEADER NOT FOUND
                # --------------------------------------

                if header_row is None:

                    raise ValueError(
                        f"Invalid Excel format in sheet '{sheet_name}'. "
                        "Required columns: S.NO, REG NO, STUDENT NAME, "
                        "DEPARTMENT, COURSE, YEAR."
                    )

                # --------------------------------------
                # GET HEADER VALUES
                # --------------------------------------

                header_values = sheet_values[header_row]

                new_columns = [
                    str(value)
                    .replace("\n", " ")
                    .replace(".", "")
                    .strip()
                    .upper()
                    for value in header_values
                ]

                df = df.iloc[header_row + 1:].copy()

                df.columns = new_columns

                df.reset_index(
                    drop=True,
                    inplace=True
                )

                # --------------------------------------
                # FIND COLUMNS
                # --------------------------------------

                department_column = None
                year_column = None
                course_column = None
                reg_column = None
                name_column = None

                for column in df.columns:

                    clean_column = (
                        str(column)
                        .replace(" ", "")
                        .replace("_", "")
                        .replace(".", "")
                        .upper()
                    )

                    if clean_column in [
                        "DEPARTMENT",
                        "DEPT"
                    ]:

                        department_column = column

                    elif clean_column in [
                        "YEAR",
                        "CLASS"
                    ]:

                        year_column = column

                    elif clean_column in [
                        "COURSE",
                        "COURCE",
                        "PROGRAMME",
                        "PROGRAM"
                    ]:

                        course_column = column

                    elif clean_column in [
                        "REGNO",
                        "REGISTERNO",
                        "REGISTERNUMBER",
                        "REGNUMBER"
                    ]:

                        reg_column = column

                    elif clean_column in [
                        "STUDENTNAME",
                        "NAME",
                        "STUDENT"
                    ]:

                        name_column = column

                # --------------------------------------
                # CHECK COLUMNS
                # --------------------------------------

                print(
                    "COLUMNS:",
                    sheet_name,
                    department_column,
                    year_column,
                    course_column,
                    reg_column,
                    name_column
                )

                if (
                    department_column is None
                    or year_column is None
                    or course_column is None
                    or reg_column is None
                    or name_column is None
                ):

                    raise ValueError(
                        f"Invalid Excel format in sheet '{sheet_name}'. "
                        "Required columns: REG NO, STUDENT NAME, "
                        "DEPARTMENT, COURSE, YEAR."
                    )

                # --------------------------------------
                # REMOVE EMPTY STUDENTS
                # --------------------------------------

                df = df.dropna(
                    subset=[
                        reg_column,
                        name_column
                    ]
                )

                # --------------------------------------
                # SQL
                # --------------------------------------

                sql = """
                    INSERT INTO students
                    (
                        register_number,
                        name,
                        department,
                        course,
                        year
                    )
                    VALUES
                    (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    ON DUPLICATE KEY UPDATE
                        name = VALUES(name),
                        department = VALUES(department),
                        course = VALUES(course),
                        year = VALUES(year)
                """

                # --------------------------------------
                # COLUMN POSITIONS
                # --------------------------------------

                reg_position = df.columns.get_loc(
                    reg_column
                )

                name_position = df.columns.get_loc(
                    name_column
                )

                department_position = df.columns.get_loc(
                    department_column
                )

                course_position = df.columns.get_loc(
                    course_column
                )

                year_position = df.columns.get_loc(
                    year_column
                )

                # --------------------------------------
                # STUDENT DATA
                # --------------------------------------

                # Convert dataframe once
                student_values = df.to_numpy()

                for row_number, row_data in enumerate(
                    student_values
                ):

                    register_number = str(
                        row_data[reg_position]
                    ).strip()

                    student_name = str(
                        row_data[name_position]
                    ).strip()

                    department = str(
                        row_data[department_position]
                    ).strip()

                    course = str(
                        row_data[course_position]
                    ).strip()

                    year = str(
                        row_data[year_position]
                    ).strip()

                    # ----------------------------------
                    # SKIP EMPTY
                    # ----------------------------------

                    if (
                        register_number == ""
                        or register_number.lower() == "nan"
                        or student_name == ""
                        or student_name.lower() == "nan"
                    ):

                        continue

                    # ----------------------------------
                    # REQUIRED DATA VALIDATION
                    # ----------------------------------

                    if (
                        department == ""
                        or department.lower() == "nan"
                        or course == ""
                        or course.lower() == "nan"
                        or year == ""
                        or year.lower() == "nan"
                    ):

                        raise ValueError(
                            f"Invalid Excel format/data in sheet "
                            f"'{sheet_name}', row "
                            f"{row_number + header_row + 2}. "
                            "REG NO, STUDENT NAME, DEPARTMENT, "
                            "COURSE and YEAR must contain values."
                        )

                    # ----------------------------------
                    # NORMALIZE YEAR ROBUSTLY
                    # Supports:
                    # 1, 1.0, I, I Year,
                    # 1st Year, etc.
                    # ----------------------------------

                    year_upper = year.upper().strip()

                    if year_upper.endswith(".0"):

                        year_upper = (
                            year_upper[:-2].strip()
                        )

                    if year_upper in (
                        "I",
                        "1",
                        "1 YEAR",
                        "I YEAR",
                        "1ST",
                        "1ST YEAR"
                    ):

                        year = "I Year"

                    elif year_upper in (
                        "II",
                        "2",
                        "2 YEAR",
                        "II YEAR",
                        "2ND",
                        "2ND YEAR"
                    ):

                        year = "II Year"

                    elif year_upper in (
                        "III",
                        "3",
                        "3 YEAR",
                        "III YEAR",
                        "3RD",
                        "3RD YEAR"
                    ):

                        year = "III Year"

                    elif year_upper in (
                        "IV",
                        "4",
                        "4 YEAR",
                        "IV YEAR",
                        "4TH",
                        "4TH YEAR"
                    ):

                        year = "IV Year"

                    # ----------------------------------
                    # SAVE
                    # ----------------------------------

                    cursor.execute(
                        sql,
                        (
                            register_number,
                            student_name,
                            department,
                            course,
                            year
                        )
                    )

                    total_students += 1

            # ------------------------------------------
            # FINAL FORMAT / DATA CHECK
            # ------------------------------------------

            if total_students == 0:

                raise ValueError(
                    "Invalid Excel file. "
                    "No valid student records were found."
                )

            # ------------------------------------------
            # COMMIT
            # ------------------------------------------

            db.commit()

            print(
                "TOTAL STUDENTS SAVED:",
                total_students
            )

            return render_template(
                "student_upload.html",
                success=(
                    "Student Excel uploaded successfully! "
                    + str(total_students)
                    + " students saved to database."
                )
            )

        except Exception as e:

            if db:

                db.rollback()

            print(
                "UPLOAD ERROR:",
                str(e)
            )

            return render_template(
                "student_upload.html",
                error="Upload Error: " + str(e)
            )

        finally:

            if cursor:

                cursor.close()

            if db:

                db.close()

    return render_template(
        "student_upload.html"
    )
# ==================================================
# EXTRA STUDENT UPLOAD URL
# ==================================================

@app.route(
    "/students-upload",
    methods=["GET", "POST"]
)
def students_upload():

    return student_upload()


# ==================================================
# STUDENT DATA DISPLAY
# ==================================================

# ==================================================
# STUDENT DATA DISPLAY
# ==================================================

@app.route("/students")
def students():

    db = None
    cursor = None

    try:

        db = get_db_connection()

        cursor = db.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                id,
                register_number,
                name,
                department,
                course,
                year
            FROM students
            ORDER BY id
        """)

        student_list = cursor.fetchall()
        print("STUDENT COUNT:", len(student_list))
        print("FIRST STUDENT:", student_list[0] if student_list else "NO DATA")

        print("STUDENT COUNT:", len(student_list))
        print(
            "FIRST STUDENT:",
            student_list[0] if student_list else "NO DATA"
        )

        return render_template(
            "students.html",
            students=student_list
        )

    except Exception as e:

        return "Error loading students: " + str(e)

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()
# ==================================================
# DELETE ALL STUDENT DATA
# ==================================================

@app.route("/delete-all-students", methods=["POST"])
def delete_all_students():

    db = None
    cursor = None

    try:

        db = get_db_connection()
        cursor = db.cursor()

        cursor.execute("DELETE FROM students")

        db.commit()

        return redirect(url_for("students"))

    except Exception as e:

        if db:
            db.rollback()

        return "Delete Error: " + str(e)

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()
# ==================================================
# FACULTY DETAILS MANAGEMENT
# ==================================================

# ==================================================
# FACULTY MANAGEMENT
# ==================================================

@app.route("/faculty-upload", methods=["GET", "POST"])
def faculty_upload():

    db = None
    cursor = None

    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        success = None
        error = None

        # Ensure login columns exist.
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'faculty_details'
              AND COLUMN_NAME = 'faculty_code'
        """)
        if cursor.fetchone()["total"] == 0:
            cursor.execute("""
                ALTER TABLE faculty_details
                ADD COLUMN faculty_code VARCHAR(50) NULL
            """)

        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'faculty_details'
              AND COLUMN_NAME = 'faculty_password_hash'
        """)
        if cursor.fetchone()["total"] == 0:
            cursor.execute("""
                ALTER TABLE faculty_details
                ADD COLUMN faculty_password_hash VARCHAR(255) NULL
            """)

        if request.method == "POST":

            faculty_file = request.files.get("faculty_file")

            if faculty_file and faculty_file.filename != "":

                filename = faculty_file.filename

                if not (
                    filename.lower().endswith(".xlsx")
                    or filename.lower().endswith(".xls")
                ):
                    error = "Please upload only Excel files."
                else:
                    upload_path = os.path.join(
                        UPLOAD_FOLDER,
                        secure_filename(filename)
                    )

                    try:
                        df = pd.read_excel(faculty_file)

                        # Required format:
                        # S.NO. | ID | STAFF NAME | DEPARTMENT
                        required_columns = [
                            "ID",
                            "STAFF NAME",
                            "DEPARTMENT"
                        ]

                        missing_columns = [
                            c for c in required_columns
                            if c not in df.columns
                        ]

                        if missing_columns:
                            raise Exception(
                                "Excel must contain ID, STAFF NAME and DEPARTMENT columns."
                            )

                        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                        faculty_file.stream.seek(0)
                        faculty_file.save(upload_path)

                        cursor.execute("""
                            INSERT INTO uploaded_faculty_files
                            (file_name, file_path)
                            VALUES (%s, %s)
                        """, (filename, upload_path))

                        upload_id = cursor.lastrowid
                        total_added = 0

                        for _, row in df.iterrows():

                            faculty_code = str(row["ID"]).strip()
                            faculty_name = str(row["STAFF NAME"]).strip()
                            department = str(row["DEPARTMENT"]).strip()

                            if (
                                not faculty_code
                                or faculty_code.lower() == "nan"
                                or not faculty_name
                                or faculty_name.lower() == "nan"
                            ):
                                continue

                            # ID must be unique.
                            cursor.execute("""
                                SELECT id
                                FROM faculty_details
                                WHERE LOWER(TRIM(faculty_code))
                                      = LOWER(TRIM(%s))
                                LIMIT 1
                            """, (faculty_code,))

                            existing = cursor.fetchone()

                            if existing:
                                # Existing faculty: update profile details only.
                                # NEVER reset an existing personal password during Excel re-upload.
                                cursor.execute("""
                                    UPDATE faculty_details
                                    SET faculty_name = %s,
                                        department = %s,
                                        upload_id = %s
                                    WHERE id = %s
                                """, (
                                    faculty_name,
                                    department,
                                    upload_id,
                                    existing["id"]
                                ))
                                total_added += 1
                                continue

                            cursor.execute("""
                                INSERT INTO faculty_details
                                (
                                    faculty_code,
                                    faculty_name,
                                    department,
                                    course,
                                    year,
                                    upload_id,
                                    faculty_password_hash,
                                    faculty_password_changed
                                )
                                VALUES
                                (
                                    %s, %s, %s, %s, %s, %s, %s, %s
                                )
                            """, (
                                faculty_code,
                                faculty_name,
                                department,
                                "",
                                None,
                                upload_id,
                                generate_password_hash(
                                    FACULTY_COMMON_PASSWORD
                                ),
                                0
                            ))

                            total_added += 1

                        db.commit()

                        success = (
                            f"{total_added} faculty records uploaded successfully!"
                        )

                    except Exception as excel_error:
                        db.rollback()

                        if os.path.exists(upload_path):
                            os.remove(upload_path)

                        error = (
                            "Excel Upload Error: "
                            + str(excel_error)
                        )

            else:
                faculty_name = (
                    request.form.get("faculty_name") or ""
                ).strip()

                faculty_code = (
                    request.form.get("faculty_code") or ""
                ).strip()

                department = (
                    request.form.get("department") or ""
                ).strip()

                course = (
                    request.form.get("course") or ""
                ).strip()

                if not all([
                    faculty_code,
                    faculty_name,
                    department,
                    course
                ]):
                    error = "Please fill all fields."

                else:
                    cursor.execute("""
                        SELECT id
                        FROM faculty_details
                        WHERE LOWER(TRIM(faculty_code))
                              = LOWER(TRIM(%s))
                        LIMIT 1
                    """, (faculty_code,))

                    if cursor.fetchone():
                        error = "Faculty ID already exists."
                    else:
                        cursor.execute("""
                            INSERT INTO faculty_details
                            (
                                faculty_code,
                                faculty_name,
                                department,
                                course,
                                year,
                                upload_id,
                                faculty_password_hash
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """, (
                            faculty_code,
                            faculty_name,
                            department,
                            course,
                            None,
                            None,
                            generate_password_hash(
                                FACULTY_COMMON_PASSWORD
                            ),
                            0
                        ))

                        db.commit()
                        success = "Faculty added successfully!"

        cursor.execute("""
            SELECT
                id,
                faculty_code,
                faculty_name,
                department,
                course,
                year
            FROM faculty_details
            ORDER BY id
        """)

        faculty_list = cursor.fetchall()

        cursor.execute("""
            SELECT
                id,
                file_name,
                file_path,
                uploaded_at
            FROM uploaded_faculty_files
            ORDER BY uploaded_at DESC
        """)

        uploaded_faculty_files = cursor.fetchall()

        return render_template(
            "faculty_upload.html",
            faculty_list=faculty_list,
            uploaded_faculty_files=uploaded_faculty_files,
            success=success,
            error=error
        )

    except Exception as e:

        if db:
            db.rollback()

        return "Faculty Upload Error: " + str(e)

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()


@app.route(
    "/faculty-file-delete/<int:file_id>",
    methods=["POST"]
)
def faculty_file_delete(file_id):

    db = None
    cursor = None

    try:

        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        # ------------------------------------------
        # GET FILE DETAILS
        # ------------------------------------------

        cursor.execute(
            """
            SELECT
                file_name,
                file_path
            FROM uploaded_faculty_files
            WHERE id = %s
            """,
            (file_id,)
        )

        uploaded_file = cursor.fetchone()

        if not uploaded_file:

            return redirect(
                url_for("faculty_upload")
            )

        # ------------------------------------------
        # DELETE ALL FACULTY RECORDS
        # FROM THIS EXCEL
        # ------------------------------------------

        cursor.execute(
            """
            DELETE FROM faculty_details
            WHERE upload_id = %s
            """,
            (file_id,)
        )

        # ------------------------------------------
        # DELETE DATABASE FILE RECORD
        # ------------------------------------------

        cursor.execute(
            """
            DELETE FROM uploaded_faculty_files
            WHERE id = %s
            """,
            (file_id,)
        )

        # ------------------------------------------
        # DELETE ACTUAL EXCEL FILE
        # ------------------------------------------

        file_path = uploaded_file["file_path"]

        if file_path and os.path.exists(file_path):

            os.remove(file_path)

        # ------------------------------------------
        # COMMIT
        # ------------------------------------------

        db.commit()

        return redirect(
            url_for("faculty_upload")
        )

    except Exception as e:

        if db:
            db.rollback()

        return "Error deleting faculty Excel: " + str(e)

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()
                

# ==================================================
# HALL MANAGEMENT
# ==================================================

# ==================================================
# HALL MANAGEMENT
# ==================================================

@app.route(
    "/hall-management",
    methods=["GET", "POST"]
)
def hall_management():

    db = None
    cursor = None

    try:

        db = get_db_connection()

        cursor = db.cursor(
            dictionary=True
        )

        success = None
        error = None

        # ==================================================
        # ADD HALL
        # ==================================================

        if request.method == "POST":

            hall_name = (
                request.form.get("hall_name") or ""
            ).strip()

            seating_capacity = (
                request.form.get("seating_capacity") or ""
            ).strip()

            # ==================================================
            # BASIC VALIDATION
            # ==================================================

            if not hall_name or not seating_capacity:

                error = (
                    "Please enter hall name "
                    "and seating capacity."
                )

            else:

                try:

                    seating_capacity = int(
                        seating_capacity
                    )

                    if seating_capacity <= 0:

                        error = (
                            "Seating capacity "
                            "must be greater than 0."
                        )

                except ValueError:

                    error = (
                        "Please enter a valid "
                        "seating capacity."
                    )

                # ==================================================
                # DUPLICATE HALL CHECK
                # ==================================================

                if not error:

                    cursor.execute(
                        """
                        SELECT id
                        FROM halls
                        WHERE LOWER(TRIM(hall_name))
                              =
                              LOWER(TRIM(%s))
                        LIMIT 1
                        """,
                        (hall_name,)
                    )

                    existing_hall = (
                        cursor.fetchone()
                    )

                    if existing_hall:

                        error = (
                            "Hall name already exists. "
                            "Please enter a different hall name."
                        )

                # ==================================================
                # INSERT HALL
                # ==================================================

                if not error:

                    cursor.execute(
                        """
                        INSERT INTO halls
                        (
                            hall_name,
                            seating_capacity
                        )
                        VALUES
                        (
                            %s,
                            %s
                        )
                        """,
                        (
                            hall_name,
                            seating_capacity
                        )
                    )

                    db.commit()

                    success = (
                        "Hall added successfully!"
                    )

        # ==================================================
        # GET ALL HALLS
        # ==================================================

        cursor.execute(
            """
            SELECT
                id,
                hall_name,
                seating_capacity
            FROM halls
            ORDER BY id
            """
        )

        halls = cursor.fetchall()

        return render_template(
            "hall_management.html",
            halls=halls,
            success=success,
            error=error
        )

    except Exception as e:

        if db:
            db.rollback()

        return render_template(
            "hall_management.html",
            halls=[],
            success=None,
            error=(
                "Database Error: "
                + str(e)
            )
        )

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()
# ==================================================
# HALL ALLOTMENT - HELPERS
# ==================================================

def _convert_12h_to_mysql_time(hour, minute, ampm):
    """Convert Hall Allotment page 12-hour time to MySQL TIME."""
    if not hour or not minute or not ampm:
        return None

    hour = int(hour)
    minute = int(minute)
    ampm = str(ampm).strip().upper()

    if hour < 1 or hour > 12 or minute < 0 or minute > 59:
        return None
    if ampm not in ("AM", "PM"):
        return None

    if ampm == "AM":
        hour24 = 0 if hour == 12 else hour
    else:
        hour24 = 12 if hour == 12 else hour + 12

    return f"{hour24:02d}:{minute:02d}:00"


def _format_display_time(value):
    """Return a MySQL TIME/datetime time value in 12-hour display format."""
    if value is None:
        return ""
    text = str(value)
    if len(text) >= 5:
        try:
            hour, minute = [int(x) for x in text[:5].split(":")]
            suffix = "AM" if hour < 12 else "PM"
            display_hour = hour % 12
            if display_hour == 0:
                display_hour = 12
            return f"{display_hour:02d}:{minute:02d} {suffix}"
        except Exception:
            pass
    return text


def _normalize_year_value(value):
    text = str(value or "").strip()
    upper = text.upper()
    if upper in ("I", "1", "1 YEAR", "I YEAR"):
        return "I Year"
    if upper in ("II", "2", "2 YEAR", "II YEAR"):
        return "II Year"
    if upper in ("III", "3", "3 YEAR", "III YEAR"):
        return "III Year"
    if upper in ("IV", "4", "4 YEAR", "IV YEAR"):
        return "IV Year"
    return text


def _get_selected_combinations(request, session_name):
    """Read Department|Course|Year checkbox values from the current session."""
    combinations = []
    for raw in request.form.getlist(f"{session_name}_course_years"):
        parts = [str(x).strip() for x in str(raw).split("|", 2)]
        if len(parts) != 3 or not all(parts):
            continue
        combinations.append((parts[0], parts[1], _normalize_year_value(parts[2])))
    return combinations


def _fetch_allotment_groups(cursor):
    """Build the data structure expected by hall_allotment.html."""
    cursor.execute("""
        SELECT
            a.exam_id,
            a.hall_id,
            a.session,
            a.seat_number,
            a.row_no,
            a.column_no,
            a.side,
            s.register_number,
            s.name,
            s.department,
            s.course,
            s.year,
            h.hall_name,
            h.seating_capacity,
            e.exam_date,
            e.start_time,
            e.end_time,
            f.faculty_name,
            f.department AS faculty_department
        FROM allotments a
        INNER JOIN students s ON a.student_id = s.id
        INNER JOIN halls h ON a.hall_id = h.id
        INNER JOIN exam_timetable e ON a.exam_id = e.id
        LEFT JOIN faculty_details f ON a.faculty_id = f.id
        WHERE e.course = 'HALL ALLOTMENT'
          AND e.year = 'ALL'
        ORDER BY a.exam_id DESC, a.hall_id, a.seat_number, a.side
    """)
    rows = cursor.fetchall()

    grouped = {}
    for row in rows:
        key = (row["exam_id"], row["hall_id"], row.get("session") or "")
        if key not in grouped:
            grouped[key] = {
                "exam_id": row["exam_id"],
                "hall_id": row["hall_id"],
                "session": row.get("session") or "",
                "hall_name": row["hall_name"],
                "exam_date": row["exam_date"],
                "start_time": _format_display_time(row["start_time"]),
                "end_time": _format_display_time(row["end_time"]),
                "faculty_name": row["faculty_name"] or "",
                "faculty_department": row["faculty_department"] or "",
                "seating_capacity": min(int(row["seating_capacity"] or 30), 30),
                "rows": [],
                "course_year_set": [],
                "student_count": 0,
            }

        group = grouped[key]
        group["rows"].append({
            "seat_number": row["seat_number"],
            "row_no": row["row_no"],
            "column_no": row["column_no"],
            "side": row["side"],
            "register_number": row["register_number"],
            "course": row["course"],
            "year": row["year"],
        })
        pair = f"{row['course']} - {row['year']}"
        if pair not in group["course_year_set"]:
            group["course_year_set"].append(pair)
        group["student_count"] += 1

    result = []
    for group in grouped.values():
        group["course_years"] = ", ".join(group.pop("course_year_set"))
        result.append(group)
    return result
#=========================================
#pdf
#=========================================

def _draw_pdf_header(
    pdf,
    title,
    exam_date=None,
    session_name=None,
    start_time=None,
    end_time=None,
    hall_name=None,
    faculty_name=None,
    faculty_department=None,
    hall_course_years=None
):
    width, height = A4

    y = height - 42

    # ==================================================
    # COLLEGE NAME
    # ==================================================

    pdf.setFont(
        "Helvetica-Bold",
        14
    )

    pdf.drawCentredString(
        width / 2,
        y,
        "SHREE VENKATESWARA ARTS AND SCIENCE COLLEGE"
    )

    y -= 18

    # ==================================================
    # EXAMINATION CELL
    # ==================================================

    pdf.setFont(
        "Helvetica-Bold",
        12
    )

    pdf.drawCentredString(
        width / 2,
        y,
        "COLLEGE EXAMINATION CELL"
    )

    y -= 18

    # ==================================================
    # TITLE
    # ==================================================

    pdf.drawCentredString(
        width / 2,
        y,
        title
    )

    y -= 24

    # ==================================================
    # DETAILS
    # ==================================================

    pdf.setFont(
        "Helvetica",
        9.5
    )

    details = []

    if exam_date is not None:

        details.append(
            f"Exam Date : {exam_date}"
        )

    if session_name:

        details.append(
            f"Session : {session_name}"
        )

    if start_time or end_time:

        details.append(
            f"Time : "
            f"{start_time or ''} - "
            f"{end_time or ''}"
        )

    if hall_name:

        details.append(
            f"Hall No. : {hall_name}"
        )

    # ==================================================
    # COURSE + YEAR
    # ==================================================

    if hall_course_years:

        if isinstance(
            hall_course_years,
            (list, tuple)
        ):

            course_year_text = ", ".join(
                str(x)
                for x in hall_course_years
                if str(x).strip()
            )

        else:

            course_year_text = str(
                hall_course_years
            ).strip()

        if course_year_text:

            details.append(
                f"Course / Year : "
                f"{course_year_text}"
            )

    # ==================================================
    # FACULTY
    # ==================================================

    if faculty_name:

        details.append(
            f"Faculty : {faculty_name}"
        )

    if faculty_department:

        details.append(
            f"Department : {faculty_department}"
        )

    # ==================================================
    # DRAW DETAILS
    # ==================================================

    for detail in details:

        pdf.drawString(
            45,
            y,
            str(detail)
        )

        y -= 14

    return y - 8


# ==================================================
# PDF 2 - SEATING ARRANGEMENT
# ==================================================

def _build_pdf2_seating(exam_id=None, hall_id=None):
    from reportlab.lib.pagesizes import landscape
    """
    PDF 2 - Hall Allotment / Seating Arrangement

    Output format:
      - Landscape A4
      - Hall details at top
      - Course / Year
      - Subject Code / Subject are shown only in the
        course-wise summary box below the seating table
      - 5 vertical blocks
      - Each block contains S.No + Reg. No
      - Number of rows is calculated from the actual allotted seats
      - No hard-coded 6-row limit
    """

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:
        # ==================================================
        # WHERE CONDITION
        # ==================================================

        where = [
            "e.course = 'HALL ALLOTMENT'",
            "e.year = 'ALL'"
        ]

        params = []

        if exam_id is not None:
            where.append(
                "a.exam_id = %s"
            )
            params.append(exam_id)

        if hall_id is not None:
            where.append(
                "a.hall_id = %s"
            )
            params.append(hall_id)

        # ==================================================
        # GET SEATING DATA
        #
        # IMPORTANT:
        # Subject + Subject Code are taken directly from
        # exam_timetable. Nothing is hard-coded.
        # ==================================================

        cursor.execute(
            f"""
            SELECT
                a.exam_id,
                a.hall_id,
                a.seat_number,
                a.row_no,
                a.column_no,
                a.side,
                a.session,

                s.register_number,
                s.name,
                s.course,
                s.year,

                h.hall_name,
                h.seating_capacity,

                e.exam_date,

                -- --------------------------------------------------
                -- Course/Year-wise Subject
                --
                -- Timetable year may be stored as:
                --   I / II / III
                --   1 / 2 / 3
                --   1st / 2nd / 3rd
                --   I Year / II Year / III Year
                --
                -- Student year can use the same variants.
                -- Normalize both sides before matching.
                -- --------------------------------------------------
                (
                    SELECT
                        NULLIF(TRIM(et.subject), '')
                    FROM exam_timetable et
                    WHERE
                        LOWER(TRIM(et.course))
                            = LOWER(TRIM(s.course))
                        AND
                        LOWER(
                            TRIM(
                                REPLACE(
                                    LOWER(TRIM(s.year)),
                                    ' year',
                                    ''
                                )
                            )
                        )
                            =
                        LOWER(TRIM(et.year))
                        AND
                        et.exam_date = e.exam_date
                        AND
                        LOWER(TRIM(et.exam_type))
                            = LOWER(TRIM(e.exam_type))
                        AND
                        LOWER(TRIM(et.exam_name))
                            = LOWER(TRIM(e.exam_name))
                        AND
                        UPPER(TRIM(et.course))
                            <> 'HALL ALLOTMENT'
                    ORDER BY et.id DESC
                    LIMIT 1
                ) AS subject,

                -- --------------------------------------------------
                -- Course/Year-wise Subject Code
                -- --------------------------------------------------
                (
                    SELECT
                        NULLIF(TRIM(et.subject_name), '')
                    FROM exam_timetable et
                    WHERE
                        LOWER(TRIM(et.course))
                            = LOWER(TRIM(s.course))
                        AND
                        LOWER(
                            TRIM(
                                REPLACE(
                                    LOWER(TRIM(s.year)),
                                    ' year',
                                    ''
                                )
                            )
                        )
                            =
                        LOWER(TRIM(et.year))
                        AND
                        et.exam_date = e.exam_date
                        AND
                        LOWER(TRIM(et.exam_type))
                            = LOWER(TRIM(e.exam_type))
                        AND
                        LOWER(TRIM(et.exam_name))
                            = LOWER(TRIM(e.exam_name))
                        AND
                        UPPER(TRIM(et.course))
                            <> 'HALL ALLOTMENT'
                    ORDER BY et.id DESC
                    LIMIT 1
                ) AS subject_name,

                e.exam_type,
                e.exam_name,

                f.faculty_name,
                f.department AS faculty_department

            FROM allotments a

            INNER JOIN students s
                ON a.student_id = s.id

            INNER JOIN halls h
                ON a.hall_id = h.id

            INNER JOIN exam_timetable e
                ON a.exam_id = e.id

            LEFT JOIN faculty_details f
                ON a.faculty_id = f.id

            WHERE {' AND '.join(where)}

            ORDER BY
                a.exam_id DESC,
                a.hall_id,
                a.seat_number,
                a.side
            """,
            tuple(params)
        )

        rows = cursor.fetchall()

        if not rows:
            raise ValueError(
                "No seating arrangement available."
            )

        # ==================================================
        # ARREAR FIRST - PDF DISPLAY ONLY
        #
        # Arrear is stored separately from Regular. For the
        # seating PDF, display Arrear first and shift Regular
        # seat numbers after the Arrear count.
        #
        # Example: Arrear 10
        #   1-10  -> Arrear
        #   11+   -> Regular
        #
        # IMPORTANT: This changes ONLY PDF display data.
        # Database allocation logic is untouched.
        # ==================================================

        base_exam_date = rows[0].get("exam_date")
        base_exam_type = str(rows[0].get("exam_type") or "").strip()
        base_exam_name = str(rows[0].get("exam_name") or "").strip()

        arrear_params = [base_exam_date]
        arrear_where = ["aa.exam_date = %s"]

        if hall_id is not None:
            arrear_where.append("aa.hall_id = %s")
            arrear_params.append(hall_id)

        cursor.execute(
            f"""
            SELECT
                aa.hall_id,
                aa.seat_number,
                aa.side,
                aa.faculty_id,
                ars.reg_no AS register_number,
                ars.student_name AS name,
                ars.course,
                ars.department,
                ars.batch,
                h.hall_name,
                h.seating_capacity,
                f.faculty_name,
                f.department AS faculty_department
            FROM arrear_allotments aa
            INNER JOIN arrear_students ars
                ON aa.student_id = ars.id
            INNER JOIN halls h
                ON aa.hall_id = h.id
            LEFT JOIN faculty_details f
                ON aa.faculty_id = f.id
            WHERE {" AND ".join(arrear_where)}
            ORDER BY aa.hall_id, aa.seat_number
            """,
            tuple(arrear_params)
        )

        arrear_rows = cursor.fetchall()

        arrear_count_by_hall = {}
        for ar in arrear_rows:
            hid = int(ar["hall_id"])
            arrear_count_by_hall[hid] = (
                arrear_count_by_hall.get(hid, 0) + 1
            )

        # Shift Regular display seats only.
        for row in rows:
            hid = int(row["hall_id"])
            offset = int(arrear_count_by_hall.get(hid, 0))
            try:
                regular_seat = int(row.get("seat_number") or 0)
            except (ValueError, TypeError):
                regular_seat = 0

            row["seat_number"] = regular_seat + offset

        # Add Arrear students at the beginning of each hall.
        for ar in arrear_rows:
            hid = int(ar["hall_id"])
            try:
                ar_seat = int(ar.get("seat_number") or 0)
            except (ValueError, TypeError):
                ar_seat = 0

            rows.append({
                "exam_id": rows[0]["exam_id"],
                "hall_id": hid,
                "seat_number": ar_seat,
                "row_no": None,
                "column_no": None,
                "side": "CENTER",
                "session": rows[0].get("session"),
                "register_number": ar.get("register_number") or "",
                "name": ar.get("name") or "",
                "course": ar.get("course") or "ARREAR",
                "year": ar.get("batch") or "",
                "hall_name": ar.get("hall_name") or "",
                "seating_capacity": ar.get("seating_capacity") or 0,
                "exam_date": base_exam_date,
                "exam_type": base_exam_type,
                "exam_name": base_exam_name,
                "subject": "",
                "subject_name": "",
                "faculty_name": ar.get("faculty_name") or "",
                "faculty_department": ar.get("faculty_department") or "",
            })

        rows.sort(
            key=lambda r: (
                int(r.get("hall_id") or 0),
                int(r.get("seat_number") or 0),
                0 if str(r.get("side") or "").upper() == "CENTER" else 1
            )
        )

        # ==================================================
        # FIX: MATCH TIMETABLE COURSE/YEAR USING THE SAME
        # NORMALIZATION USED BY HALL ALLOTMENT.
        #
        # Example:
        #   Student course : AI & DS
        #   Timetable      : B.SC AI & DS
        #
        # Hall allocation already handles this correctly, but
        # the old PDF SQL used an exact course-name comparison,
        # which caused Subject / Sub.Code to become blank for
        # AI & DS.  Fill those two fields from exam_timetable
        # using normalized course + year.
        # ==================================================
        cursor.execute(
            """
            SELECT
                id, course, year, subject, subject_name, subject_name,
                exam_date, exam_type, exam_name
            FROM exam_timetable
            WHERE UPPER(TRIM(course)) <> 'HALL ALLOTMENT'
            """
        )
        timetable_rows = cursor.fetchall()

        timetable_map = {}
        for tt in timetable_rows:
            key = (
                normalize_course_for_match(tt.get("course")),
                normalize_year_for_match(tt.get("year")),
                str(tt.get("exam_date") or ""),
                str(tt.get("exam_type") or "").strip().lower(),
                str(tt.get("exam_name") or "").strip().lower(),
            )

            # exam_timetable stores:
            #   subject      = Subject Code
            #   subject_name = Subject Name
            # PDF fields need:
            #   subject      = Subject Name
            #   subject_name = Subject Code (displayed as Sub.Code)
            subject = str(
                tt.get("subject_name")
                or ""
            ).strip()
            subject_name = str(
                tt.get("subject")
                or ""
            ).strip()

            if subject or subject_name:
                timetable_map[key] = {
                    "subject": subject,
                    "subject_name": subject_name,
                }

        for row in rows:
            key = (
                normalize_course_for_match(row.get("course")),
                normalize_year_for_match(row.get("year")),
                str(row.get("exam_date") or ""),
                str(row.get("exam_type") or "").strip().lower(),
                str(row.get("exam_name") or "").strip().lower(),
            )

            detail = timetable_map.get(key)
            if detail:
                if not str(row.get("subject") or "").strip():
                    row["subject"] = detail["subject"]
                if not str(row.get("subject_name") or "").strip():
                    row["subject_name"] = detail["subject_name"]

        # ==================================================
        # PDF FILE NAME
        # ==================================================

        if exam_id is None:
            filename = (
                "admin_seating_arrangement.pdf"
            )
        else:
            filename = (
                f"seating_arrangement_"
                f"{exam_id}_"
                f"{hall_id or 'all'}.pdf"
            )

        path = os.path.join(
            UPLOAD_FOLDER,
            filename
        )

        # ==================================================
        # LANDSCAPE A4
        # ==================================================

        pdf = canvas.Canvas(
            path,
            pagesize=landscape(A4)
        )

        width, height = landscape(A4)

        # ==================================================
        # GROUP BY HALL
        # ==================================================

        hall_groups = {}

        for row in rows:

            hall_key = (
                row["exam_id"],
                row["hall_id"]
            )

            hall_groups.setdefault(
                hall_key,
                []
            ).append(row)

        # ==================================================
        # EACH HALL
        # ==================================================

        for hall_index, (
            hall_key,
            hall_rows
        ) in enumerate(
            hall_groups.items()
        ):

            if hall_index > 0:
                pdf.showPage()

            first = hall_rows[0]

            # ==================================================
            # HEADER
            # ==================================================

            y = height - 35

            pdf.setFont(
                "Helvetica-Bold",
                15
            )

            pdf.drawCentredString(
                width / 2,
                y,
                "HALL ALLOTMENT"
            )

            pdf.setFont(
                "Helvetica-Bold",
                9
            )

            session_text = str(first.get("session") or "").strip()
            hall_header = f"HALL NO: {first.get('hall_name') or ''}"
            if session_text:
                hall_header += f"    Session: {session_text}"

            pdf.drawString(
                35,
                y - 22,
                hall_header
            )

            y -= 22

            y -= 16

            # --------------------------------------------------
            # Course + Year values actually present in this hall.
            # --------------------------------------------------

            course_years = []

            seen = set()

            for r in hall_rows:

                course = str(
                    r.get("course") or ""
                ).strip()

                year = str(
                    r.get("year") or ""
                ).strip()

                key = (
                    course.lower(),
                    year.lower()
                )

                if key in seen:
                    continue

                seen.add(key)

                if course and year:
                    course_years.append(
                        f"{course} - {year}"
                    )
                elif course:
                    course_years.append(course)
                elif year:
                    course_years.append(year)

            course_year_text = ", ".join(
                course_years
            )

            subject_name = str(
                first.get("subject_name") or ""
            ).strip()

            subject_name = str(
                first.get("subject") or ""
            ).strip()

            # --------------------------------------------------
            # Details block
            # --------------------------------------------------

            details = [
                (
                    "Course / Year",
                    course_year_text
                )
            ]

            pdf.setFont(
                "Helvetica",
                8
            )

            for label, value in details:

                pdf.setFont(
                    "Helvetica-Bold",
                    8
                )

                pdf.drawString(
                    35,
                    y,
                    f"{label}:"
                )

                pdf.setFont(
                    "Helvetica",
                    8
                )

                pdf.drawString(
                    125,
                    y,
                    value
                )

                y -= 13

            # ==================================================
            # SEATING LIST
            #
            # 5 BLOCKS
            #
            # Each block:
            #   S.No | Reg. No
            #
            # Example for 34 seats:
            #
            # Block 1 -> 1 - 7
            # Block 2 -> 8 - 14
            # Block 3 -> 15 - 21
            # Block 4 -> 22 - 28
            # Block 5 -> 29 - 34
            # ==================================================

            COLUMNS = 6

            # --------------------------------------------------
            # Only one physical seat is represented by one list
            # entry. In 2-student mode, both register numbers are
            # shown in the same S.No cell.
            # --------------------------------------------------

            seat_map = {}

            for r in hall_rows:

                try:
                    seat_no = int(
                        r.get("seat_number")
                    )
                except (
                    ValueError,
                    TypeError
                ):
                    continue

                seat_map.setdefault(
                    seat_no,
                    []
                ).append(r)

            if not seat_map:
                continue

            max_seat = max(
                seat_map.keys()
            )

            # Capacity from the hall table is the physical seat
            # capacity. If available, use it so empty physical
            # seats are also visible in the PDF.
            try:
                hall_capacity = int(
                    first.get("seating_capacity")
                    or 0
                )
            except (
                ValueError,
                TypeError
            ):
                hall_capacity = 0

            if hall_capacity > 0:
                total_physical_seats = max(
                    hall_capacity,
                    max_seat
                )
            else:
                total_physical_seats = max_seat

            ROWS = (
                total_physical_seats
                + COLUMNS
                - 1
            ) // COLUMNS

            # --------------------------------------------------
            # Fit the table below the header.
            # --------------------------------------------------

            available_height = (
                y - 35
            )

            max_rows_that_fit = int(
                available_height / 25
            )

            if max_rows_that_fit < 1:
                max_rows_that_fit = 1

            # --------------------------------------------------
            # If the hall is very large, continue on another page.
            # --------------------------------------------------

            block_start = 0

            while block_start < ROWS:

                block_rows = min(
                    max_rows_that_fit,
                    ROWS - block_start
                )

                table_top = y

                # ==================================================
                # TABLE DIMENSIONS
                # ==================================================

                left = 30
                table_width = width - 60

                block_width = (
                    table_width / COLUMNS
                )

                sno_width = (
                    block_width * 0.28
                )

                reg_width = (
                    block_width * 0.72
                )

                header_h = 20
                row_h = 25

                # ==================================================
                # BLOCK HEADERS
                # ==================================================

                pdf.setFont(
                    "Helvetica-Bold",
                    7
                )

                for block in range(
                    COLUMNS
                ):

                    x = (
                        left
                        + block * block_width
                    )

                    pdf.rect(
                        x,
                        table_top - header_h,
                        sno_width,
                        header_h
                    )

                    pdf.rect(
                        x + sno_width,
                        table_top - header_h,
                        reg_width,
                        header_h
                    )

                    pdf.drawCentredString(
                        x + sno_width / 2,
                        table_top - 14,
                        "S.No"
                    )

                    pdf.drawCentredString(
                        x + sno_width + reg_width / 2,
                        table_top - 14,
                        "Reg. No"
                    )

                # ==================================================
                # TABLE ROWS
                # ==================================================

                for local_row in range(
                    block_rows
                ):

                    global_row = (
                        block_start
                        + local_row
                    )

                    y_row = (
                        table_top
                        - header_h
                        - local_row * row_h
                    )

                    for block in range(
                        COLUMNS
                    ):

                        # ------------------------------------------
                        # Seat number:
                        # Column-wise numbering.
                        #
                        # Block 0:
                        #   1,2,3...
                        #
                        # Block 1:
                        #   ROWS+1...
                        # ------------------------------------------

                        seat_no = (
                            block * ROWS
                            + global_row
                            + 1
                        )

                        x = (
                            left
                            + block * block_width
                        )

                        pdf.rect(
                            x,
                            y_row - row_h,
                            sno_width,
                            row_h
                        )

                        pdf.rect(
                            x + sno_width,
                            y_row - row_h,
                            reg_width,
                            row_h
                        )

                        # ------------------------------------------
                        # S.No
                        # ------------------------------------------

                        if (
                            seat_no
                            <= total_physical_seats
                        ):

                            pdf.setFont(
                                "Helvetica",
                                7
                            )

                            pdf.drawCentredString(
                                x + sno_width / 2,
                                y_row - 16,
                                str(seat_no)
                            )

                        # ------------------------------------------
                        # Register number(s)
                        # ------------------------------------------

                        students_in_seat = (
                            seat_map.get(
                                seat_no,
                                []
                            )
                        )

                        if students_in_seat:

                            # LEFT first, RIGHT second.
                            students_in_seat = sorted(
                                students_in_seat,
                                key=lambda r: (
                                    0
                                    if str(
                                        r.get("side")
                                        or ""
                                    ).upper()
                                    == "LEFT"
                                    else 1
                                )
                            )

                            if len(
                                students_in_seat
                            ) == 1:

                                reg = str(
                                    students_in_seat[0].get(
                                        "register_number"
                                    ) or ""
                                )

                                pdf.setFont(
                                    "Helvetica-Bold",
                                    7
                                )

                                pdf.drawCentredString(
                                    x
                                    + sno_width
                                    + reg_width / 2,
                                    y_row - 16,
                                    reg
                                )

                            else:

                                reg1 = str(
                                    students_in_seat[0].get(
                                        "register_number"
                                    ) or ""
                                )

                                reg2 = str(
                                    students_in_seat[1].get(
                                        "register_number"
                                    ) or ""
                                )

                                # 2 students in ONE physical seat:
                                # show both Reg.Nos side-by-side in the
                                # SAME Reg.No box.
                                reg_x = x + sno_width
                                reg_y = y_row - row_h

                                pdf.setFont(
                                    "Helvetica-Bold",
                                    6.5
                                )

                                # Vertical divider between the two Reg.Nos.
                                pdf.setLineWidth(0.5)
                                pdf.line(
                                    reg_x + reg_width / 2,
                                    reg_y,
                                    reg_x + reg_width / 2,
                                    reg_y + row_h
                                )

                                # Student 1 - left half
                                pdf.drawCentredString(
                                    reg_x + reg_width * 0.25,
                                    reg_y + row_h / 2 - 2.5,
                                    reg1
                                )

                                # Student 2 - right half
                                pdf.drawCentredString(
                                    reg_x + reg_width * 0.75,
                                    reg_y + row_h / 2 - 2.5,
                                    reg2
                                )

                block_start += block_rows

                # --------------------------------------------------
                # Continue on next PDF page if needed.
                # --------------------------------------------------

                if block_start < ROWS:

                    pdf.setFont(
                        "Helvetica",
                        7
                    )

                    pdf.drawCentredString(
                        width / 2,
                        18,
                        "College Examination Cell - Seating Arrangement"
                    )

                    pdf.showPage()

                    y = height - 35

                    pdf.setFont(
                        "Helvetica-Bold",
                        11
                    )

                    session_text = str(first.get("session") or "").strip()
                    hall_header = f"HALL NO: {first.get('hall_name') or ''}"
                    if session_text:
                        hall_header += f"    Session: {session_text}"

                    pdf.drawCentredString(
                        width / 2,
                        y,
                        hall_header
                    )

                    y -= 22

            # ==================================================
            # COURSE / SUB.CODE / SUBJECT / STRENGTH
            # ==================================================
            #
            # This summary belongs ONLY to the current hall.
            # Strength = number of students from that Course/Year
            # actually seated in this hall.
            # ==================================================

            course_summary = {}

            for r in hall_rows:

                course = str(
                    r.get("course") or ""
                ).strip()

                year = str(
                    r.get("year") or ""
                ).strip()

                sub_code = str(
                    r.get("subject_name") or ""
                ).strip()

                subject = str(
                    r.get("subject") or ""
                ).strip()

                key = (
                    course,
                    year,
                    sub_code,
                    subject
                )

                course_summary[key] = (
                    course_summary.get(key, 0) + 1
                )

            # Put the summary below the seating table.
            # If it does not fit, continue on the next page.
            summary_top = (
                y
                - 8
                - ROWS * row_h
                - header_h
            )

            # For a large hall/table, use the bottom area first.
            if summary_top < 120:

                pdf.showPage()

                summary_top = (
                    height - 45
                )

                pdf.setFont(
                    "Helvetica-Bold",
                    11
                )

                session_text = str(first.get("session") or "").strip()
                hall_header = f"HALL NO: {first.get('hall_name') or ''}"
                if session_text:
                    hall_header += f"    Session: {session_text}"

                pdf.setFont("Helvetica-Bold", 11)
                pdf.drawCentredString(
                    width / 2,
                    summary_top,
                    hall_header
                )

                summary_top -= 18

            summary_left = 30
            summary_width = width - 60

            course_w = summary_width * 0.22
            code_w = summary_width * 0.13
            subject_w = summary_width * 0.50
            strength_w = (
                summary_width
                - course_w
                - code_w
                - subject_w
            )

            summary_header_h = 20
            summary_row_h = 24

            xs = [
                summary_left,
                summary_left + course_w,
                summary_left + course_w + code_w,
                summary_left + course_w + code_w + subject_w
            ]

            ws = [
                course_w,
                code_w,
                subject_w,
                strength_w
            ]

            headers = [
                "Course",
                "Sub.Code",
                "Subject",
                "Strength"
            ]

            pdf.setFont(
                "Helvetica-Bold",
                7.5
            )

            for i in range(4):

                pdf.rect(
                    xs[i],
                    summary_top - summary_header_h,
                    ws[i],
                    summary_header_h
                )

                pdf.drawCentredString(
                    xs[i] + ws[i] / 2,
                    summary_top - 14,
                    headers[i]
                )

            summary_y = (
                summary_top
                - summary_header_h
            )

            for (
                course,
                year,
                sub_code,
                subject
            ), strength in course_summary.items():

                if summary_y - summary_row_h < 30:

                    pdf.showPage()

                    summary_y = (
                        height - 45
                    )

                    pdf.setFont(
                        "Helvetica-Bold",
                        10
                    )

                    pdf.drawString(
                        30,
                        summary_y,
                        f"HALL NO: {first.get('hall_name') or ''} - Course Summary"
                    )

                    summary_y -= 18

                course_text = (
                    f"{course} - {year}"
                    if course and year
                    else course or year
                )

                values = [
                    course_text,
                    sub_code,
                    subject,
                    str(strength)
                ]

                for i in range(4):

                    pdf.rect(
                        xs[i],
                        summary_y - summary_row_h,
                        ws[i],
                        summary_row_h
                    )

                    value = values[i]

                    max_chars = (
                        38 if i == 0
                        else 70 if i == 2
                        else 20
                    )

                    if len(value) > max_chars:

                        value = (
                            value[:max_chars - 3]
                            + "..."
                        )

                    pdf.setFont(
                        "Helvetica",
                        7
                    )

                    pdf.drawCentredString(
                        xs[i] + ws[i] / 2,
                        summary_y - 15,
                        value
                    )

                summary_y -= summary_row_h

            # ==================================================
            # FOOTER
            # ==================================================

            pdf.setFont(
                "Helvetica",
                7
            )

            pdf.drawCentredString(
                width / 2,
                18,
                "College Examination Cell - Hall Allotment"
            )

        # ==================================================
        # SAVE
        # ==================================================

        pdf.save()

        return path

    finally:

        cursor.close()
        db.close()






# ==================================================
# HALL ALLOTMENT PAGE
# ==================================================

@app.route("/hall-allotment", methods=["GET"])
def hall_allotment():

    db = None
    cursor = None

    try:

        # ==================================================
        # DATABASE CONNECTION
        # ==================================================

        db = get_db_connection()

        cursor = db.cursor(
            dictionary=True,
            buffered=True
        )


        # ==================================================
        # GET ALL HALLS
        # ==================================================

        cursor.execute("""
            SELECT
                id,
                hall_name,
                seating_capacity,
                floor
            FROM halls
            ORDER BY
                CASE
                    WHEN UPPER(TRIM(COALESCE(floor, ''))) = 'GF' THEN 1
                    WHEN UPPER(TRIM(COALESCE(floor, ''))) = 'FF' THEN 2
                    WHEN UPPER(TRIM(COALESCE(floor, ''))) = 'SF' THEN 3
                    ELSE 4
                END,
                floor,
                hall_name
        """)

        halls = cursor.fetchall()

        # ==================================================
        # HIDE FULL-ARREAR HALLS FROM REGULAR HALL ALLOTMENT
        # ==================================================
        # Arrear students occupy one physical seat each. If Arrear has
        # completely filled a hall, that hall is not offered to Regular.
        # After the Arrear allocation is deleted, it becomes visible again.
        try:
            cursor.execute("""
                SELECT aa.hall_id
                FROM arrear_allotments aa
                INNER JOIN halls ah ON ah.id = aa.hall_id
                GROUP BY aa.hall_id, ah.seating_capacity
                HAVING COUNT(*) >= ah.seating_capacity
            """)
            full_arrear_hall_ids = {
                int(r["hall_id"]) for r in cursor.fetchall()
            }
            halls = [
                h for h in halls
                if int(h.get("id") or 0) not in full_arrear_hall_ids
            ]
        except Exception:
            # Keep existing behaviour if the Arrear table is unavailable.
            pass


        # ==================================================
        # GET DEPARTMENTS + COURSES
        #
        # Department selection is taken from
        # Department Management.
        # ==================================================

        cursor.execute("""
            SELECT DISTINCT
                department_name,
                course_name
            FROM departments

            WHERE
                department_name IS NOT NULL
                AND TRIM(department_name) <> ''

                AND course_name IS NOT NULL
                AND TRIM(course_name) <> ''

            ORDER BY
                department_name,
                course_name
        """)

        departments = cursor.fetchall()


        # ==================================================
        # GET TIMETABLE DATA
        #
        # IMPORTANT:
        #
        # Course
        # Year
        # Subject Code
        # Subject
        # Exam Type
        # Exam Name
        # Exam Date
        #
        # EVERYTHING comes from exam_timetable.
        #
        # Do NOT take Course/Year from students table
        # for displaying the available courses.
        # ==================================================

        cursor.execute("""
            SELECT DISTINCT

                id,

                department,

                course,

                year,

                subject,

                subject_name,

                subject_name,

                exam_date,

                start_time,

                end_time,

                exam_type,

                exam_name,

                exam_start_date,

                exam_end_date

            FROM exam_timetable

            WHERE

                exam_date IS NOT NULL

                AND course IS NOT NULL
                AND TRIM(course) <> ''

                AND year IS NOT NULL
                AND TRIM(year) <> ''

                AND exam_type IS NOT NULL
                AND TRIM(exam_type) <> ''

                AND exam_name IS NOT NULL
                AND TRIM(exam_name) <> ''

                AND UPPER(TRIM(course))
                    <> 'HALL ALLOTMENT'

                AND UPPER(TRIM(year))
                    <> 'ALL'

            ORDER BY

                exam_date,

                exam_type,

                exam_name,

                course,

                year

        """)

        timetable_rows = cursor.fetchall()


        # ==================================================
        # CONVERT DATE / TIME VALUES TO STRING
        #
        # This prevents:
        #
        # Object of type date is not JSON serializable
        # Object of type timedelta is not JSON serializable
        #
        # ==================================================

        for row in timetable_rows:

            # ----------------------------------------------
            # Exam Date
            # ----------------------------------------------

            if row.get("exam_date") is not None:

                row["exam_date"] = str(
                    row["exam_date"]
                )


            # ----------------------------------------------
            # Start Time
            # ----------------------------------------------

            if row.get("start_time") is not None:

                row["start_time"] = str(
                    row["start_time"]
                )


            # ----------------------------------------------
            # End Time
            # ----------------------------------------------

            if row.get("end_time") is not None:

                row["end_time"] = str(
                    row["end_time"]
                )


            # ----------------------------------------------
            # Start Date
            # ----------------------------------------------

            if row.get("exam_start_date") is not None:

                row["exam_start_date"] = str(
                    row["exam_start_date"]
                )


            # ----------------------------------------------
            # End Date
            # ----------------------------------------------

            if row.get("exam_end_date") is not None:

                row["exam_end_date"] = str(
                    row["exam_end_date"]
                )


            # ----------------------------------------------
            # Text fields
            # ----------------------------------------------

            row["department"] = str(
                row.get("department") or ""
            ).strip()


            row["course"] = str(
                row.get("course") or ""
            ).strip()


            row["year"] = str(
                row.get("year") or ""
            ).strip()


            row["subject"] = str(
                row.get("subject") or ""
            ).strip()


            row["subject_name"] = str(
                row.get("subject_name") or ""
            ).strip()


            row["subject_name"] = str(
                row.get("subject_name") or ""
            ).strip()


            row["exam_type"] = str(
                row.get("exam_type") or ""
            ).strip()


            row["exam_name"] = str(
                row.get("exam_name") or ""
            ).strip()


        # ==================================================
        # UNIQUE EXAM TYPES
        #
        # Example:
        #
        # Regular
        # Arrear
        # Supplementary
        #
        # ==================================================

        exam_types = []

        seen_exam_types = set()


        for row in timetable_rows:

            exam_type = str(
                row.get("exam_type") or ""
            ).strip()


            if not exam_type:
                continue


            key = exam_type.lower()


            if key in seen_exam_types:
                continue


            seen_exam_types.add(key)

            exam_types.append(
                exam_type
            )


        # ==================================================
        # UNIQUE EXAM TYPE + EXAM NAME
        #
        # This is useful for the Exam Name dropdown.
        # ==================================================

        exam_names = []

        seen_exam_names = set()


        for row in timetable_rows:

            exam_type = str(
                row.get("exam_type") or ""
            ).strip()


            exam_name = str(
                row.get("exam_name") or ""
            ).strip()


            if not exam_type or not exam_name:
                continue


            key = (
                exam_type.lower(),
                exam_name.lower()
            )


            if key in seen_exam_names:
                continue


            seen_exam_names.add(key)


            exam_names.append({

                "exam_type":
                    exam_type,

                "exam_name":
                    exam_name

            })


        # ==================================================
        # UNIQUE TIMETABLE DATES
        # ==================================================

        timetable_dates = []

        seen_dates = set()


        for row in timetable_rows:

            exam_date = str(
                row.get("exam_date") or ""
            ).strip()


            if not exam_date:
                continue


            if exam_date in seen_dates:
                continue


            seen_dates.add(
                exam_date
            )


            timetable_dates.append(
                exam_date
            )


        # ==================================================
        # COURSE + YEAR FROM TIMETABLE
        #
        # IMPORTANT:
        #
        # This is NOT from students table.
        #
        # This is ONLY for compatibility with the
        # existing HTML.
        # ==================================================

        course_year_rows = []

        seen_course_year = set()


        for row in timetable_rows:

            department = str(
                row.get("department") or ""
            ).strip()


            course = str(
                row.get("course") or ""
            ).strip()


            year = str(
                row.get("year") or ""
            ).strip()


            if not course or not year:
                continue


            key = (

                department.lower(),

                course.lower(),

                year.lower()

            )


            if key in seen_course_year:
                continue


            seen_course_year.add(
                key
            )


            course_year_rows.append({

                "department":
                    department,

                "course":
                    course,

                "year":
                    year

            })


        # ==================================================
        # GET FACULTY
        # ==================================================

        # Regular page: faculty already assigned in Arrear Hall Allotment
        # must not appear in the Regular faculty list.
        cursor.execute("""
            SELECT
                f.id,
                f.faculty_name,
                f.department,
                f.course,
                f.year
            FROM faculty_details f
            WHERE f.id NOT IN (
                SELECT DISTINCT aa.faculty_id
                FROM arrear_allotments aa
                WHERE aa.faculty_id IS NOT NULL
            )
            ORDER BY f.faculty_name
        """)

        faculties = cursor.fetchall()


        # ==================================================
        # GET EXISTING HALL ALLOTMENTS
        # ==================================================

        allotment_groups = (
            _fetch_allotment_groups(
                cursor
            )
        )


        # ==================================================
        # COMPATIBILITY
        #
        # Existing HTML / old code may use "exams".
        # Keep it available.
        # ==================================================

        exams = exam_names


        # ==================================================
        # SUCCESS MESSAGE
        # ==================================================

        success = request.args.get(
            "success"
        )


        # ==================================================
        # ERROR MESSAGE
        # ==================================================

        error = request.args.get(
            "error"
        )


        # ==================================================
        # RENDER HALL ALLOTMENT PAGE
        # ==================================================

        return render_template(

            "hall_allotment.html",

            # ----------------------------------------------
            # Halls
            # ----------------------------------------------

            halls=halls,


            # ----------------------------------------------
            # Departments
            # ----------------------------------------------

            departments=departments,


            # ----------------------------------------------
            # Faculty
            # ----------------------------------------------

            faculties=faculties,


            # ----------------------------------------------
            # Timetable
            # ----------------------------------------------

            timetable_rows=timetable_rows,

            timetable_dates=timetable_dates,


            # ----------------------------------------------
            # Exam Type / Name
            # ----------------------------------------------

            exam_types=exam_types,

            exam_names=exam_names,

            exams=exams,


            # ----------------------------------------------
            # Course / Year
            # ----------------------------------------------

            course_year_rows=course_year_rows,


            # ----------------------------------------------
            # Existing allotments
            # ----------------------------------------------

            allotment_groups=allotment_groups,


            # ----------------------------------------------
            # Messages
            # ----------------------------------------------

            success=success,

            error=error

        )


    # ==================================================
    # ERROR HANDLING
    # ==================================================

    except Exception as e:

        if db:

            try:

                db.rollback()

            except Exception:

                pass


        return render_template(

            "hall_allotment.html",

            halls=[],

            departments=[],

            faculties=[],

            timetable_rows=[],

            timetable_dates=[],

            exam_types=[],

            exam_names=[],

            exams=[],

            course_year_rows=[],

            allotment_groups=[],

            success=None,

            error=(
                "Hall Allotment Error: "
                + str(e)
            )

        )


    # ==================================================
    # CLOSE DATABASE
    # ==================================================

    finally:

        if cursor:

            try:

                cursor.close()

            except Exception:

                pass


        if db:

            try:

                db.close()

            except Exception:

                pass
# ==================================================
# DELETE ONE HALL ALLOTMENT
# ==================================================

@app.route("/delete-hall-allotment/<int:exam_id>/<int:hall_id>")
def delete_hall_allotment(exam_id, hall_id):
    db = get_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM allotments WHERE exam_id = %s AND hall_id = %s", (exam_id, hall_id))
        deleted_count = cursor.rowcount
        # Remove the internal exam record only when no allotment remains for it.
        cursor.execute("SELECT COUNT(*) FROM allotments WHERE exam_id = %s", (exam_id,))
        remaining = cursor.fetchone()[0]
        if remaining == 0:
            cursor.execute("DELETE FROM exam_timetable WHERE id = %s AND course = 'HALL ALLOTMENT' AND year = 'ALL'", (exam_id,))
        db.commit()
        return redirect(url_for("hall_allotment", success=f"Hall allotment deleted successfully. {deleted_count} records deleted."))
    except Exception as e:
        db.rollback()
        return redirect(url_for("hall_allotment", error=f"Delete Error: {str(e)}"))
    finally:
        cursor.close()
        db.close()


# ==================================================
# DELETE TOTAL HALL ALLOTMENT
# ==================================================

@app.route("/delete-total-hall-allotment")
def delete_total_hall_allotment():
    db = get_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM allotments")
        deleted_count = cursor.rowcount
        cursor.execute("DELETE FROM exam_timetable WHERE course = 'HALL ALLOTMENT' AND year = 'ALL'")
        db.commit()
        return redirect(url_for("hall_allotment", success=f"Total hall allotment deleted successfully. {deleted_count} records deleted."))
    except Exception as e:
        db.rollback()
        return redirect(url_for("hall_allotment", error=f"Delete Error: {str(e)}"))
    finally:
        cursor.close()
        db.close()

def _build_pdf1_general(exam_id=None, hall_id=None):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:

        where = [
            "e.course = 'HALL ALLOTMENT'",
            "e.year = 'ALL'"
        ]

        params = []

        if exam_id is not None:

            where.append(
                "a.exam_id = %s"
            )

            params.append(exam_id)

        if hall_id is not None:

            where.append(
                "a.hall_id = %s"
            )

            params.append(hall_id)

        cursor.execute(
            f"""
            SELECT
                a.exam_id,
                a.hall_id,

                s.register_number,
                s.course,
                s.year,

                h.hall_name,

                e.exam_date,
                e.start_time,
                e.end_time,
                a.session

            FROM allotments a

            INNER JOIN students s
                ON a.student_id = s.id

            INNER JOIN halls h
                ON a.hall_id = h.id

            INNER JOIN exam_timetable e
                ON a.exam_id = e.id

            WHERE {' AND '.join(where)}

            ORDER BY
                a.exam_id DESC,
                h.hall_name,
                s.course,
                s.year,
                a.seat_number,
                a.side
            """,
            tuple(params)
        )

        rows = cursor.fetchall()

        if not rows:

            raise ValueError(
                "No hall allotment available."
            )

        filename = (
            "admin_hall_allotment.pdf"
            if exam_id is None
            else
            f"hall_allotment_"
            f"{exam_id}_"
            f"{hall_id or 'all'}.pdf"
        )

        path = os.path.join(
            UPLOAD_FOLDER,
            filename
        )

        pdf = canvas.Canvas(
            path,
            pagesize=A4
        )

        width, height = A4

        # ==================================================
        # COURSE + YEAR FOR FIRST PAGE HEADER
        # ==================================================

        first_course_years = []

        seen = set()

        for row in rows:

            key = (
                str(row["course"]).strip().lower(),
                str(row["year"]).strip().lower()
            )

            if key not in seen:

                seen.add(key)

                first_course_years.append(
                    f'{row["course"]} - {row["year"]}'
                )

        y = _draw_pdf_header(
            pdf,
            "HALL ALLOTMENT",

            rows[0]["exam_date"],

            rows[0].get("session") or "",

            _format_display_time(
                rows[0]["start_time"]
            ),

            _format_display_time(
                rows[0]["end_time"]
            ),

            None,
            None,
            None,

            first_course_years
        )

        # ==================================================
        # TABLE HEADER
        # ==================================================

        pdf.setFont(
            "Helvetica-Bold",
            9
        )

        headers = [
            (45, "Hall No."),
            (145, "Course"),
            (245, "Year"),
            (345, "Regno From"),
            (455, "Regno To")
        ]

        for x, text in headers:

            pdf.drawString(
                x,
                y,
                text
            )

        y -= 15

        # ==================================================
        # GROUP
        # ==================================================

        groups = {}

        for row in rows:

            key = (
                row["hall_name"],
                row["course"],
                row["year"]
            )

            groups.setdefault(
                key,
                []
            ).append(
                str(
                    row["register_number"]
                )
            )

        # ==================================================
        # DRAW DATA
        # ==================================================

        pdf.setFont(
            "Helvetica",
            8.5
        )

        for (
            hall_name,
            course,
            year
        ), regs in groups.items():

            if y < 45:

                pdf.showPage()

                y = _draw_pdf_header(
                    pdf,
                    "HALL ALLOTMENT",
                    rows[0]["exam_date"],
                    rows[0].get("session") or "",
                    _format_display_time(rows[0]["start_time"]),
                    _format_display_time(rows[0]["end_time"]),
                    None,
                    None,
                    None,
                    first_course_years
                )

                pdf.setFont(
                    "Helvetica-Bold",
                    9
                )

                for x, text in headers:

                    pdf.drawString(
                        x,
                        y,
                        text
                    )

                y -= 15

                pdf.setFont(
                    "Helvetica",
                    8.5
                )

            regs = sorted(regs)

            values = [
                hall_name,
                course,
                year,
                regs[0],
                regs[-1]
            ]

            for x, value in zip(
                [45, 145, 245, 345, 455],
                values
            ):

                pdf.drawString(
                    x,
                    y,
                    str(value)
                )

            y -= 16

        # ==================================================
        # SAVE
        # ==================================================

        pdf.save()

        return path

    finally:

        cursor.close()
        db.close()
# ==================================================
# PDF 1 - GENERAL HALL ALLOTMENT
# ==================================================
#
@app.route("/admin-hall-allotment-pdf")
def admin_hall_allotment_pdf():
    try:
        path = _build_pdf1_general()
        return send_from_directory(UPLOAD_FOLDER, os.path.basename(path), as_attachment=True)
    except Exception as e:
        return "Admin PDF Error: " + str(e)


# ==================================================
# EXTRA PDF - STUDENT SIGNATURE SHEET (COURSE / YEAR WISE)
# ==================================================
def _build_student_signature_pdf(exam_id=None):
    """
    Extra Hall Allotment PDF.
    Students are grouped Hall -> Course / Year.
    Columns: S.No, Reg.No, Name, Signature.
    Existing Hall Allotment / Seating logic is not changed.
    """
    db = get_db_connection()
    cursor = db.cursor(dictionary=True, buffered=True)

    try:
        params = []
        where = [
            "e.course = 'HALL ALLOTMENT'",
            "e.year = 'ALL'"
        ]

        if exam_id is not None:
            where.append("a.exam_id = %s")
            params.append(exam_id)

        cursor.execute(
            f"""
            SELECT
                a.exam_id,
                a.hall_id,
                h.hall_name,
                e.exam_date,
                e.exam_type,
                e.exam_name,
                a.seat_number,
                a.side,
                s.register_number,
                s.name AS student_name,
                s.course,
                s.year
            FROM allotments a
            INNER JOIN students s ON s.id = a.student_id
            INNER JOIN halls h ON h.id = a.hall_id
            INNER JOIN exam_timetable e ON e.id = a.exam_id
            WHERE {' AND '.join(where)}
            ORDER BY
                a.exam_id DESC,
                h.hall_name,
                s.course,
                s.year,
                a.seat_number,
                CASE
                    WHEN UPPER(COALESCE(a.side, '')) = 'LEFT' THEN 1
                    WHEN UPPER(COALESCE(a.side, '')) = 'RIGHT' THEN 2
                    ELSE 3
                END,
                a.id
            """,
            tuple(params)
        )

        rows = cursor.fetchall()

        if not rows:
            raise ValueError("No Hall Allotment students available for Student Signature PDF.")

        filename = (
            "hall_student_signature.pdf"
            if exam_id is None
            else f"hall_student_signature_{exam_id}.pdf"
        )
        path = os.path.join(UPLOAD_FOLDER, filename)

        pdf = canvas.Canvas(path, pagesize=A4)
        width, height = A4

        left = 40
        right = width - 40
        row_h = 24
        table_width = right - left

        # Column widths: S.No, Reg.No, Name, Signature
        col_widths = [42, 125, 210, table_width - 42 - 125 - 210]
        headers = ["S.No", "Reg.No", "Name", "Signature"]

        def draw_page_header(hall_name=None, course=None, year=None):
            pdf.setFont("Helvetica-Bold", 15)
            pdf.drawCentredString(
                width / 2,
                height - 42,
                "STUDENT HALL ALLOTMENT"
            )

            first = rows[0]
            exam_date = str(first.get("exam_date") or "")
            exam_name = str(first.get("exam_name") or "").strip()

            pdf.setFont("Helvetica", 9)
            meta = f"Exam Date: {exam_date}"
            if exam_name:
                meta += f"    Exam: {exam_name}"
            pdf.drawCentredString(width / 2, height - 59, meta)

            if hall_name:
                pdf.setFont("Helvetica-Bold", 11)
                pdf.drawCentredString(
                    width / 2,
                    height - 78,
                    f"Hall: {hall_name}"
                )

            if course is not None and year is not None:
                pdf.setFont("Helvetica-Bold", 10)
                pdf.drawCentredString(
                    width / 2,
                    height - 94,
                    f"Course: {course}    Year: {year}"
                )

        def draw_table_header(y):
            pdf.setFont("Helvetica-Bold", 9)
            x = left
            for i, header in enumerate(headers):
                w = col_widths[i]
                pdf.rect(x, y - row_h, w, row_h)
                pdf.drawCentredString(
                    x + w / 2,
                    y - 16,
                    header
                )
                x += w

        def draw_student_row(y, serial_no, row):
            values = [
                str(serial_no),
                str(row.get("register_number") or ""),
                str(row.get("student_name") or ""),
                ""
            ]

            pdf.setFont("Helvetica", 9)
            x = left

            for i, value in enumerate(values):
                w = col_widths[i]
                pdf.rect(x, y - row_h, w, row_h)

                if i in (0, 1):
                    pdf.drawCentredString(
                        x + w / 2,
                        y - 16,
                        value
                    )
                else:
                    pdf.drawString(
                        x + 5,
                        y - 16,
                        value
                    )

                x += w

        # Group by Hall -> Course -> Year.
        hall_groups = {}
        for row in rows:
            hall_key = (
                row.get("exam_id"),
                row.get("hall_id"),
                str(row.get("hall_name") or "")
            )
            hall_groups.setdefault(hall_key, [])

            course = str(row.get("course") or "").strip()
            year = str(row.get("year") or "").strip()
            hall_groups[hall_key].append((course, year, row))

        first_page = True

        for hall_key, hall_rows in hall_groups.items():
            exam_id_value, hall_id_value, hall_name = hall_key

            course_year_groups = {}
            for course, year, row in hall_rows:
                key = (course, year)
                course_year_groups.setdefault(key, []).append(row)

            for (course, year), student_rows in course_year_groups.items():
                if not first_page:
                    pdf.showPage()

                first_page = False

                draw_page_header(
                    hall_name=hall_name,
                    course=course,
                    year=year
                )

                y = height - 112
                draw_table_header(y)
                y -= row_h

                serial_no = 1

                for row in student_rows:
                    if y < 55:
                        pdf.showPage()
                        draw_page_header(
                            hall_name=hall_name,
                            course=course,
                            year=year
                        )
                        y = height - 112
                        draw_table_header(y)
                        y -= row_h

                    draw_student_row(
                        y,
                        serial_no,
                        row
                    )

                    serial_no += 1
                    y -= row_h

        pdf.save()
        return path

    finally:
        cursor.close()
        db.close()


@app.route("/hall-student-signature-pdf")
def hall_student_signature_pdf():
    try:
        path = _build_student_signature_pdf()
        return send_from_directory(
            UPLOAD_FOLDER,
            os.path.basename(path),
            as_attachment=True
        )
    except Exception as e:
        return "Student Signature PDF Error: " + str(e)


@app.route("/hall-student-signature-pdf/<int:exam_id>")
def hall_student_signature_pdf_exam(exam_id):
    try:
        path = _build_student_signature_pdf(exam_id)
        return send_from_directory(
            UPLOAD_FOLDER,
            os.path.basename(path),
            as_attachment=True
        )
    except Exception as e:
        return "Student Signature PDF Error: " + str(e)


# ==================================================
# EXTRA PDF - HALL + FACULTY SIGNATURE SHEET
# ==================================================
def _build_hall_faculty_signature_pdf(exam_id=None):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:
        params = []
        where = [
            "e.course = 'HALL ALLOTMENT'",
            "e.year = 'ALL'"
        ]

        if exam_id is not None:
            where.append("a.exam_id = %s")
            params.append(exam_id)

        cursor.execute(
            f"""
            SELECT
                a.exam_id,
                a.hall_id,
                h.hall_name,
                GROUP_CONCAT(
                    DISTINCT NULLIF(TRIM(f.faculty_name), '')
                    ORDER BY f.faculty_name
                    SEPARATOR ', '
                ) AS faculty_name,
                MIN(e.exam_date) AS exam_date,
                MIN(e.start_time) AS start_time,
                MIN(e.end_time) AS end_time,
                MIN(a.session) AS session
            FROM allotments a
            INNER JOIN halls h ON a.hall_id = h.id
            INNER JOIN exam_timetable e ON a.exam_id = e.id
            LEFT JOIN faculty_details f ON a.faculty_id = f.id
            WHERE {' AND '.join(where)}
            GROUP BY a.exam_id, a.hall_id, h.hall_name
            ORDER BY a.exam_id DESC, h.hall_name
            """,
            tuple(params)
        )

        rows = cursor.fetchall()

        if not rows:
            raise ValueError("No hall allotment available for Faculty Signature PDF.")

        filename = (
            "hall_faculty_signature.pdf"
            if exam_id is None
            else f"hall_faculty_signature_{exam_id}.pdf"
        )
        path = os.path.join(UPLOAD_FOLDER, filename)

        pdf = canvas.Canvas(path, pagesize=A4)
        width, height = A4

        def draw_page_header():
            pdf.setFont("Helvetica-Bold", 15)
            pdf.drawCentredString(width / 2, height - 45, "HALL FACULTY SIGNATURE SHEET")

            if rows[0].get("exam_date"):
                pdf.setFont("Helvetica", 9)
                date_text = str(rows[0]["exam_date"])
                session_text = str(rows[0].get("session") or "")
                time_text = (
                    f'{_format_display_time(rows[0]["start_time"])} - '
                    f'{_format_display_time(rows[0]["end_time"])}'
                )
                pdf.drawCentredString(
                    width / 2, height - 62,
                    f"Date: {date_text}    Session: {session_text}    Time: {time_text}"
                )

        draw_page_header()

        left = 45
        right = width - 45
        top = height - 90
        row_h = 28
        col_widths = [45, 105, 230, right - left - 45 - 105 - 230]
        headers = ["S.No", "Hall Name", "Faculty Name", "Signature"]

        def draw_table_header(y):
            pdf.setFont("Helvetica-Bold", 9)
            x = left
            for i, text in enumerate(headers):
                w = col_widths[i]
                pdf.rect(x, y - row_h, w, row_h)
                pdf.drawCentredString(x + w / 2, y - 18, text)
                x += w

        y = top
        draw_table_header(y)
        y -= row_h
        pdf.setFont("Helvetica", 9)

        for index, row in enumerate(rows, start=1):
            if y < 55:
                pdf.showPage()
                draw_page_header()
                y = top
                draw_table_header(y)
                y -= row_h
                pdf.setFont("Helvetica", 9)

            values = [
                str(index),
                str(row.get("hall_name") or ""),
                str(row.get("faculty_name") or "Not Assigned"),
                ""
            ]

            x = left
            for i, value in enumerate(values):
                w = col_widths[i]
                pdf.rect(x, y - row_h, w, row_h)
                if i == 0:
                    pdf.drawCentredString(x + w / 2, y - 18, value)
                else:
                    pdf.drawString(x + 5, y - 18, value)
                x += w

            y -= row_h

        pdf.save()
        return path

    finally:
        cursor.close()
        db.close()


@app.route("/hall-faculty-signature-pdf")
def hall_faculty_signature_pdf():
    try:
        path = _build_hall_faculty_signature_pdf()
        return send_from_directory(UPLOAD_FOLDER, os.path.basename(path), as_attachment=True)
    except Exception as e:
        return "Hall Faculty Signature PDF Error: " + str(e)


@app.route("/hall-faculty-signature-pdf/<int:exam_id>")
def hall_faculty_signature_pdf_exam(exam_id):
    try:
        path = _build_hall_faculty_signature_pdf(exam_id)
        return send_from_directory(UPLOAD_FOLDER, os.path.basename(path), as_attachment=True)
    except Exception as e:
        return "Hall Faculty Signature PDF Error: " + str(e)


# Existing per-hall template link compatibility.
@app.route("/hall-allotment-pdf/<int:exam_id>/<int:hall_id>")
def hall_allotment_pdf(exam_id, hall_id):
    try:
        path = _build_pdf1_general(exam_id, hall_id)
        return send_from_directory(UPLOAD_FOLDER, os.path.basename(path), as_attachment=True)
    except Exception as e:
        return "Hall Allotment PDF Error: " + str(e)


# ==================================================
# PDF 2 - SEATING ARRANGEMENT
# ==================================================

@app.route("/admin-seating-arrangement-pdf")
def admin_seating_arrangement_pdf():
    try:
        path = _build_pdf2_seating()
        return send_from_directory(UPLOAD_FOLDER, os.path.basename(path), as_attachment=True)
    except Exception as e:
        return "Seating PDF Error: " + str(e)


# ==================================================
# NORMALIZE COURSE FOR MATCHING
# ==================================================
#
# Timetable may contain:
#   B.Sc Cyber Security
#   B.Sc IT
#
# while students table may contain:
#   CYBER SECURITY
#   IT
#
# Treat these as the same course for Hall Allotment matching.
# Other course names are kept intact after harmless formatting cleanup.
# ==================================================

def normalize_course_for_match(value):

    value = str(value or "").strip().lower()

    if not value:
        return ""

    # Normalize common punctuation/spacing.
    value = value.replace(".", " ")
    value = " ".join(value.split())

    # Remove common degree prefixes only when they are prefixes.
    prefixes = (
        "b sc ",
        "bsc ",
        "bachelor of science ",
        "bachelor science ",
    )

    for prefix in prefixes:
        if value.startswith(prefix):
            value = value[len(prefix):].strip()
            break

    # Common aliases.
    aliases = {
        "computer applications": "bca",
        "bachelor of computer applications": "bca",
        "information technology": "it",
        "computer science information technology": "it",
        "cyber security": "cyber security",
    }

    return aliases.get(value, value)


# ==================================================
# NORMALIZE YEAR FOR MATCHING
# ==================================================

def normalize_year_for_match(value):

    value = str(value or "").strip()

    if not value:
        return ""

    value = value.lower()

    # Remove "year"
    value = value.replace("year", "").strip()

    # Convert ordinal formats
    mapping = {
        "1": "1",
        "01": "1",
        "1st": "1",
        "first": "1",

        "2": "2",
        "02": "2",
        "2nd": "2",
        "second": "2",

        "3": "3",
        "03": "3",
        "3rd": "3",
        "third": "3",

        "4": "4",
        "04": "4",
        "4th": "4",
        "fourth": "4",

        "5": "5",
        "05": "5",
        "5th": "5",
        "fifth": "5",

        "6": "6",
        "06": "6",
        "6th": "6",
        "sixth": "6"
    }

    return mapping.get(
        value,
        value
    )
# ============================================================
# GENERATE HALL ALLOTMENT
# ============================================================

# ============================================================
# HELPER - NORMALIZE YEAR
# ============================================================

def _normalize_year_value(value):

    value = str(value or "").strip().lower()

    if not value:
        return ""

    value = value.replace("year", "").strip()

    roman_map = {
        "i": "1",
        "ii": "2",
        "iii": "3",
        "iv": "4",
        "v": "5",
        "vi": "6"
    }

    if value in roman_map:
        return roman_map[value]

    text_map = {
        "first": "1",
        "second": "2",
        "third": "3",
        "fourth": "4",
        "fifth": "5",
        "sixth": "6"
    }

    if value in text_map:
        return text_map[value]

    value = value.replace("st", "")
    value = value.replace("nd", "")
    value = value.replace("rd", "")
    value = value.replace("th", "")

    value = value.strip()

    if value.isdigit():
        return str(int(value))

    return value


@app.route("/generate-hall-allotment", methods=["POST"])
def generate_hall_allotment():

    start_time = time.time()
    print("=== HALL ALLOTMENT STARTED ===", flush=True)

    db = None
    cursor = None

    try:

        # ========================================================
        # DATABASE CONNECTION
        # ========================================================

        db = get_db_connection()

        cursor = db.cursor(
            dictionary=True,
            buffered=True
        )


        # ========================================================
        # EXAM TYPE
        # ========================================================

        exam_type = str(
            request.form.get("exam_type") or ""
        ).strip()


        if not exam_type:

            raise ValueError(
                "Please select Exam Type."
            )


        # ========================================================
        # EXAM NAME
        # ========================================================

        exam_name = str(
            request.form.get("exam_name") or ""
        ).strip()


        if not exam_name:

            raise ValueError(
                "Please select Exam Name."
            )


        # ========================================================
        # EXAM DATE
        #
        # No time is used.
        # ========================================================

        raw_exam_date = str(
            request.form.get("morning_exam_date")
            or
            request.form.get("exam_date")
            or
            ""
        ).strip()


        if not raw_exam_date:

            raise ValueError(
                "Please select Exam Date."
            )


        # ========================================================
        # CONVERT EXAM DATE
        # ========================================================

        exam_date = None


        # --------------------------------------------------------
        # CASE 1:
        # Actual date
        #
        # 2026-08-30
        # --------------------------------------------------------

        try:

            exam_date = datetime.strptime(
                raw_exam_date,
                "%Y-%m-%d"
            ).date()

        except (ValueError, TypeError):

            exam_date = None


        # --------------------------------------------------------
        # CASE 2:
        # Date format DD/MM/YYYY
        # --------------------------------------------------------

        if exam_date is None:

            try:

                exam_date = datetime.strptime(
                    raw_exam_date,
                    "%d/%m/%Y"
                ).date()

            except (ValueError, TypeError):

                exam_date = None


        # --------------------------------------------------------
        # CASE 3:
        # HTML accidentally sends timetable ID
        #
        # Example:
        # 39
        # --------------------------------------------------------

        if (
            exam_date is None
            and
            raw_exam_date.isdigit()
        ):

            timetable_id = int(
                raw_exam_date
            )


            cursor.execute(
                """
                SELECT exam_date
                FROM exam_timetable
                WHERE id = %s
                LIMIT 1
                """,
                (
                    timetable_id,
                )
            )


            id_date_row = cursor.fetchone()


            if id_date_row:

                database_date = (
                    id_date_row.get(
                        "exam_date"
                    )
                )


                if database_date:

                    if hasattr(
                        database_date,
                        "date"
                    ):

                        exam_date = (
                            database_date.date()
                        )

                    else:

                        exam_date = (
                            database_date
                        )


        # --------------------------------------------------------
        # INVALID DATE
        # --------------------------------------------------------

        if exam_date is None:

            raise ValueError(
                "Invalid Exam Date. "
                "Please select a valid date from timetable."
            )


        # ========================================================
        # NORMALIZED DATE
        # ========================================================

        exam_date = exam_date.strftime(
            "%Y-%m-%d"
        )

        # ========================================================
        # SESSION
        # User selects the exam session for this hall allotment.
        # Only FORENOON or AFTERNOON are allowed.
        # This value is stored in allotments.session and shown in PDF.
        # ========================================================

        session_name = str(
            request.form.get("session")
            or request.form.get("exam_session")
            or ""
        ).strip().upper()

        # Accept old labels if an older template is still used.
        session_aliases = {
            "MORNING": "FORENOON",
            "FORENOON": "FORENOON",
            "AFTERNOON": "AFTERNOON",
            "EVENING": "AFTERNOON",
        }
        session_name = session_aliases.get(session_name, session_name)

        if session_name not in {"FORENOON", "AFTERNOON"}:
            raise ValueError(
                "Please select Session: Forenoon or Afternoon."
            )


        # ========================================================
        # CHANGE MODE
        # If enabled, the new allotment must avoid the hall used by
        # the student on the latest earlier hall-allotment date for
        # the same Exam Type + Exam Name. Normal allotment remains
        # completely unchanged when this option is not selected.
        # ========================================================
        # Read checkbox safely; when checked Flask receives ["1"].
        change_mode_values = [
            str(v).strip().lower()
            for v in request.form.getlist("change_mode")
        ]
        # Accept normal checkbox value (1) plus common HTML values.
        # Also accept a fallback field named `change` if an older template
        # is still being used.
        fallback_change = str(request.form.get("change") or "").strip().lower()
        change_mode = (
            any(v in {"1", "on", "true", "yes", "checked"} for v in change_mode_values)
            or fallback_change in {"1", "on", "true", "yes", "checked"}
        )


        # ========================================================
        # VERIFY EXAM TYPE + EXAM NAME + DATE
        # ========================================================

        cursor.execute(
            """
            SELECT
                id,
                exam_date,
                exam_type,
                exam_name
            FROM exam_timetable

            WHERE
                exam_date = %s

                AND

                LOWER(TRIM(exam_type))
                =
                LOWER(TRIM(%s))

                AND

                LOWER(TRIM(exam_name))
                =
                LOWER(TRIM(%s))

                AND

                course IS NOT NULL

                AND

                TRIM(course) <> ''

                AND

                UPPER(TRIM(course))
                <> 'HALL ALLOTMENT'

            LIMIT 1
            """,
            (
                exam_date,
                exam_type,
                exam_name
            )
        )


        exam_check = cursor.fetchone()


        if not exam_check:

            raise ValueError(
                f"No timetable found for "
                f"{exam_type} / "
                f"{exam_name} / "
                f"{exam_date}."
            )


        # ========================================================
        # GET TIMETABLE DETAILS
        #
        # IMPORTANT:
        #
        # Only selected Exam Type
        # + Exam Name
        # + Exam Date
        #
        # ========================================================

        cursor.execute(
            """
            SELECT DISTINCT

                id,

                department,

                course,

                year,

                subject,

                subject_name,

                subject_name,

                exam_date,

                exam_type,

                exam_name

            FROM exam_timetable

            WHERE

                exam_date = %s

                AND

                LOWER(TRIM(exam_type))
                =
                LOWER(TRIM(%s))

                AND

                LOWER(TRIM(exam_name))
                =
                LOWER(TRIM(%s))

                AND

                course IS NOT NULL

                AND

                TRIM(course) <> ''

                AND

                year IS NOT NULL

                AND

                TRIM(year) <> ''

                AND

                UPPER(TRIM(course))
                <> 'HALL ALLOTMENT'

            ORDER BY

                course,

                year

            """,
            (
                exam_date,
                exam_type,
                exam_name
            )
        )


        timetable_rows = cursor.fetchall()


        if not timetable_rows:

            raise ValueError(
                "No valid Course and Year "
                "found for this date."
            )


        # ========================================================
        # SELECTED COURSE + YEAR
        #
        # Expected HTML value:
        #
        # department|course|year
        #
        # Example:
        #
        # |CYBER SECURITY|I
        #
        # ========================================================

        raw_course_years = request.form.getlist(
            "morning_course_years"
        )


        # --------------------------------------------------------
        # Fallback names
        # --------------------------------------------------------

        if not raw_course_years:

            raw_course_years = request.form.getlist(
                "course_years"
            )


        if not raw_course_years:

            raw_course_years = request.form.getlist(
                "selected_course_years"
            )


        # ========================================================
        # PARSE COURSE + YEAR
        # ========================================================

        selected_course_years = []

        seen_course_years = set()


        for raw_value in raw_course_years:

            raw_value = str(
                raw_value or ""
            ).strip()


            if not raw_value:
                continue


            # ----------------------------------------------------
            # Expected:
            #
            # department|course|year
            # ----------------------------------------------------

            parts = raw_value.split(
                "|",
                2
            )


            if len(parts) == 3:

                department = str(
                    parts[0]
                ).strip()

                course = str(
                    parts[1]
                ).strip()

                year = str(
                    parts[2]
                ).strip()


            # ----------------------------------------------------
            # Alternative:
            #
            # course|year
            # ----------------------------------------------------

            elif len(parts) == 2:

                department = ""

                course = str(
                    parts[0]
                ).strip()

                year = str(
                    parts[1]
                ).strip()


            else:

                continue


            if not course or not year:
                continue


            normalized_year = (
                normalize_year_for_match(
                    year
                )
            )


            key = (
                normalize_course_for_match(course).lower(),
                normalized_year
            )


            if key in seen_course_years:
                continue


            seen_course_years.add(
                key
            )


            selected_course_years.append({

                "department":
                    department,

                "course":
                    course,

                "year":
                    normalized_year

            })


        # ========================================================
        # IF NOTHING SELECTED
        # ========================================================

        if not selected_course_years:

            raise ValueError(
                "Please select at least one "
                "Course and Year."
            )


        # ========================================================
        # BUILD TIMETABLE COURSE/YEAR MAP
        # ========================================================

        timetable_map = {}


        for row in timetable_rows:

            course = normalize_course_for_match(
                row.get("course")
            )


            year = normalize_year_for_match(
                row.get("year")
            )


            if not course or not year:
                continue


            key = (
                course.lower(),
                year
            )


            if key not in timetable_map:

                timetable_map[key] = []


            timetable_map[key].append(
                row
            )


        # ========================================================
        # VALIDATE SELECTED COURSE/YEAR
        # ========================================================

        final_groups = []


        for selected in selected_course_years:

            course = selected["course"]

            year = selected["year"]

            normalized_course = normalize_course_for_match(course)

            key = (
                normalized_course,
                year
            )


            if key not in timetable_map:

                raise ValueError(
                    f"{course} - {year} "
                    f"is not available for "
                    f"{exam_date}."
                )


            timetable_detail = (
                timetable_map[key][0]
            )


            subject = str(
                timetable_detail.get(
                    "subject_name"
                )
                or
                timetable_detail.get(
                    "subject"
                )
                or
                ""
            ).strip()


            subject_name = str(
                timetable_detail.get(
                    "subject_name"
                )
                or
                ""
            ).strip()


            final_groups.append({

                "department":
                    selected["department"],

                "course":
                    course,

                "year":
                    year,

                "subject":
                    subject,

                "subject_name":
                    subject_name,

                "timetable_id":
                    timetable_detail.get(
                        "id"
                    )

            })


        # ========================================================
        # GET STUDENTS
        #
        # IMPORTANT:
        # Fetch students first, then normalize COURSE + YEAR
        # in Python. This avoids MySQL string-format mismatches
        # such as:
        #
        # Timetable : B.SC CYBER SECURITY
        # Students  : CYBER SECURITY
        #
        # Timetable : B.SC IT
        # Students  : IT
        #
        # Allocation logic is NOT changed.
        # ========================================================

        cursor.execute(
            """
            SELECT
                id,
                register_number,
                name,
                department,
                course,
                year
            FROM students
            ORDER BY
                course,
                year,
                register_number
            """
        )

        all_students = cursor.fetchall()

        print(
            f"STUDENTS FETCHED: {len(all_students)} | "
            f"TIME: {time.time() - start_time:.2f}s",
            flush=True
        )

        # --------------------------------------------------------
        # Build selected normalized Course/Year keys
        # --------------------------------------------------------
        selected_match_keys = set()

        for group in final_groups:
            selected_match_keys.add(
                (
                    normalize_course_for_match(
                        group.get("course")
                    ),
                    normalize_year_for_match(
                        group.get("year")
                    )
                )
            )

        # --------------------------------------------------------
        # Match students using normalized Course + Year
        # --------------------------------------------------------
        students = []

        for student in all_students:
            student_key = (
                normalize_course_for_match(
                    student.get("course")
                ),
                normalize_year_for_match(
                    student.get("year")
                )
            )

            if student_key in selected_match_keys:
                students.append(student)

# ========================================================
        # CHECK STUDENTS
        # ========================================================

        if not students:

            raise ValueError(
                "No students found for the selected "
                "Course and Year."
            )


        # ========================================================
        # GROUP STUDENTS
        # ========================================================

        student_groups = {}


        for student in students:

            course = normalize_course_for_match(
                student.get("course")
            )


            year = normalize_year_for_match(
                student.get("year")
            )


            key = (
                course.lower(),
                year
            )


            if key not in student_groups:

                student_groups[key] = []


            student_groups[key].append(
                student
            )


        # ========================================================
        # SORT STUDENTS
        # ========================================================

        for key in student_groups:

            student_groups[key].sort(

                key=lambda s: str(
                    s.get(
                        "register_number"
                    )
                    or
                    ""
                )

            )


        # ========================================================
        # GROUP ORDER
        # ========================================================

        group_keys = []


        for group in final_groups:

            normalized_course = normalize_course_for_match(
                group.get("course")
            )

            normalized_year = normalize_year_for_match(
                group.get("year")
            )

            key = (
                normalized_course.lower(),
                normalized_year
            )


            if (
                key in student_groups
                and
                key not in group_keys
            ):

                group_keys.append(
                    key
                )


        if not group_keys:

            raise ValueError(
                "Selected Course / Year has "
                "no matching students."
            )


        # ========================================================
        # GET FACULTY
        # ========================================================

        faculty_ids = [

            str(x).strip()

            for x in request.form.getlist(
                "faculty_ids"
            )

            if str(x).strip()

        ]


        # --------------------------------------------------------
        # Check morning faculty field
        # --------------------------------------------------------

        if not faculty_ids:

            faculty_ids = [

                str(x).strip()

                for x in request.form.getlist(
                    "morning_faculty_ids"
                )

                if str(x).strip()

            ]


        if not faculty_ids:

            raise ValueError(
                "Please select at least one Faculty."
            )


        faculty_placeholders = ",".join(

            ["%s"] * len(faculty_ids)

        )


        cursor.execute(

            f"""
            SELECT

                id,

                faculty_name,

                department,

                course,

                year

            FROM faculty_details

            WHERE id IN (
                {faculty_placeholders}
            )

            ORDER BY id
            """,

            tuple(faculty_ids)

        )


        faculty_pool = cursor.fetchall()


        if not faculty_pool:

            raise ValueError(
                "Selected Faculty not found."
            )


        # ========================================================
        # GET HALLS
        # ========================================================

        hall_ids = [

            str(x).strip()

            for x in request.form.getlist(
                "hall_ids"
            )

            if str(x).strip()

        ]


        if not hall_ids:

            raise ValueError(
                "Please select at least one Hall."
            )


        hall_placeholders = ",".join(

            ["%s"] * len(hall_ids)

        )


        cursor.execute(

            f"""
            SELECT

                id,

                hall_name,

                seating_capacity

            FROM halls

            WHERE id IN (
                {hall_placeholders}
            )

            ORDER BY id
            """,

            tuple(hall_ids)

        )


        halls = cursor.fetchall()


        if not halls:

            raise ValueError(
                "Selected halls not found."
            )


        # ========================================================
        # ARREAR OCCUPANCY / SHARED HALL CAPACITY
        # ========================================================
        # Arrear students already allotted to a hall for this exam date
        # must reduce the Regular student capacity of that same hall.
        # The reduction is applied to STUDENT SLOTS, not to the hall list.
        # Example (1-student mode): capacity 34, arrear 10 => regular 24.
        # Example (2-student mode): capacity 34 physical seats = 68 student
        # slots, arrear 10 => regular 58 student slots.
        # If there is no Arrear allotment, existing Regular behaviour is
        # preserved exactly as before.
        arrear_used_by_hall = {}
        arrear_faculty_by_hall = {}
        try:
            arrear_hall_placeholders = ",".join(["%s"] * len(hall_ids))
            cursor.execute(
                f"""
                SELECT
                    hall_id,
                    COUNT(*) AS arrear_count,
                    MAX(faculty_id) AS arrear_faculty_id
                FROM arrear_allotments
                WHERE exam_date = %s
                  AND hall_id IN ({arrear_hall_placeholders})
                GROUP BY hall_id
                """,
                (exam_date, *hall_ids)
            )
            for r in cursor.fetchall():
                hid = int(r["hall_id"])
                arrear_used_by_hall[hid] = int(r["arrear_count"] or 0)
                if r.get("arrear_faculty_id") is not None:
                    arrear_faculty_by_hall[hid] = int(r["arrear_faculty_id"])
        except Exception:
            # If the Arrear table is not available yet, do not change
            # the existing Regular Hall Allotment behaviour.
            arrear_used_by_hall = {}
            arrear_faculty_by_hall = {}

        for hall in halls:
            hall_id = int(hall["id"])
            hall_capacity = int(hall.get("seating_capacity") or 0)
            arrear_count = int(arrear_used_by_hall.get(hall_id, 0))
            hall["arrear_used"] = arrear_count
            hall["regular_capacity"] = max(0, hall_capacity - arrear_count)


        # ========================================================
        # SEATING MODE
        #
        # 1 = One student per seat
        # 2 = Two students per seat
        # ========================================================

        seat_mode = str(
            request.form.get("seat_mode") or ""
        ).strip()


        if seat_mode not in ("1", "2"):

            raise ValueError(
                "Please select Seating Mode."
            )


        # ========================================================
        # CREATE HALL ALLOTMENT RECORD
        #
        # TIME IS NOT USED.
        #
        # 00:00:00 is only because DB columns are NOT NULL.
        # ========================================================

        department_names = []


        for group in final_groups:

            department = str(
                group.get(
                    "department"
                ) or ""
            ).strip()


            if (
                department
                and
                department not in department_names
            ):

                department_names.append(
                    department
                )


        department_text = ", ".join(
            department_names
        )


        first_group = final_groups[0]


        cursor.execute(
            """
            INSERT INTO exam_timetable
            (
                department,
                course,
                year,
                subject,
                subject_name,
                exam_date,
                start_time,
                end_time,
                exam_type,
                exam_name
            )

            VALUES
            (
                %s,
                'HALL ALLOTMENT',
                'ALL',
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
            """,
            (

                department_text,

                first_group.get(
                    "subject"
                ),

                first_group.get(
                    "subject_name"
                ),

                exam_date,

                # ----------------------------------------------
                # NOT USED
                # Database constraint only
                # ----------------------------------------------

                "00:00:00",

                "00:00:00",

                exam_type,

                exam_name

            )
        )


        exam_id = cursor.lastrowid

        # ========================================================
        # TARGETED FIX: REMOVE STALE REGULAR SEATING ROWS
        #
        # This prevents old Regular allotments from a previous
        # generation from appearing as empty/gapped seats.
        # No student/group/faculty/allocation logic is changed.
        #
        # Change Mode is intentionally excluded because its existing
        # allotments are required for reassignment.
        # Arrear allotments are stored separately and are untouched.
        # ========================================================
        if not change_mode:
            cleanup_placeholders = ",".join(["%s"] * len(hall_ids))
            cursor.execute(
                f"""
                DELETE a
                FROM allotments a
                INNER JOIN exam_timetable e
                    ON e.id = a.exam_id
                WHERE e.exam_date = %s
                  AND e.course = 'HALL ALLOTMENT'
                  AND e.year = 'ALL'
                  AND a.hall_id IN ({cleanup_placeholders})
                """,
                (exam_date, *[int(x) for x in hall_ids])
            )


        # ========================================================
        # STUDENT POSITION
        # ========================================================

        positions = {

            key: 0

            for key in group_keys

        }


        # ========================================================
        # FACULTY INDEX
        # ========================================================

        # ========================================================
        # TOTALS
        # ========================================================

        total_allocated = 0

        total_unallocated = 0


        # ========================================================
        # HALL ALLOCATION
        # ========================================================
        #
        # 2-student mode needs GLOBAL planning for the final two halls.
        # Otherwise the earlier greedy halls can completely consume some
        # Course/Year groups, leaving CF6 with only 41 students even though
        # CF6 can hold 64.
        #
        # Reserve at least one full CF6 capacity across four groups. Earlier
        # halls may use those groups only up to the non-reserved amount.
        # The reservation is released automatically for the last two halls.
        final_two_student_reserve = {}

        if seat_mode == "2" and len(halls) >= 2:
            cf6_capacity_students = int(
                halls[-2].get("seating_capacity") or 0
            ) * 2

            reserve_groups = sorted(
                group_keys,
                key=lambda g: len(student_groups[g]),
                reverse=True
            )[:4]

            reserve_left = cf6_capacity_students

            # Spread the reserve across four groups. This is the key
            # rebalancing step: no single earlier hall can consume the whole
            # tail needed by CF6.
            for g in reserve_groups:
                if reserve_left <= 0:
                    break

                reserve_here = min(
                    16,
                    len(student_groups[g])
                )

                final_two_student_reserve[g] = reserve_here
                reserve_left -= reserve_here

            # If the first pass could not reserve enough, distribute the
            # remaining amount among any groups with spare students.
            if reserve_left > 0:
                for g in sorted(
                    group_keys,
                    key=lambda x: len(student_groups[x]),
                    reverse=True
                ):
                    available = (
                        len(student_groups[g])
                        - final_two_student_reserve.get(g, 0)
                    )

                    if available <= 0:
                        continue

                    add_here = min(available, reserve_left)
                    final_two_student_reserve[g] = (
                        final_two_student_reserve.get(g, 0) + add_here
                    )
                    reserve_left -= add_here

                    if reserve_left <= 0:
                        break

        used_hall_ids = []

        for hall_index, hall in enumerate(halls):

            print(
                f"PROCESSING HALL {hall_index + 1}/{len(halls)} | "
                f"TIME: {time.time() - start_time:.2f}s",
                flush=True
            )

            # ----------------------------------------------------
            # Remaining students
            # ----------------------------------------------------

            remaining_students = sum(

                len(
                    student_groups[key]
                )
                -
                positions[key]

                for key in group_keys

            )


            if remaining_students <= 0:

                break


            hall_id = hall["id"]


            # Keep the REAL physical hall capacity unchanged. Arrear
            # students consume student slots inside that hall. This is
            # important for seat_mode=2: a 34-seat hall has 68 student
            # slots, so 10 Arrear students leave 58 Regular slots.
            hall_physical_capacity = int(
                hall.get("seating_capacity") or 0
            )
            arrear_count = int(hall.get("arrear_used", 0) or 0)

            if hall_physical_capacity <= 0:
                continue

            physical_seats = hall_physical_capacity

            if seat_mode == "2":
                # Two Regular students can occupy one physical seat.
                # Arrear students occupy complete physical seats first,
                # so Regular students may use only the remaining seats.
                max_students = max(
                    0,
                    (physical_seats - arrear_count) * 2
                )
            else:
                # One student per physical seat. Arrear students already
                # occupying this hall must reduce the Regular capacity.
                max_students = max(0, physical_seats - arrear_count)

            # A fully Arrear-occupied hall is not available for Regular.
            # The Regular page already hides it; this also protects against
            # a direct/manual POST containing that hall ID.
            if arrear_count >= hall_physical_capacity:
                continue

            if max_students <= 0:
                continue

            # `capacity` is used by the seating code below. It must always be
            # defined before that code runs. In 1-student mode it means the
            # number of Regular seats still available; in 2-student mode the
            # seating grid is based on the physical hall capacity.
            capacity = max_students if seat_mode == "1" else physical_seats


            # ----------------------------------------------------
            # Students for hall
            # 2-student mode: maximum 3 active Course/Year groups.
            # A new group enters only after an active group is exhausted.
            students_for_hall = []

            if seat_mode == "2":
                # =========================================================
                # 2-STUDENT MODE - GLOBAL CAPACITY-FIRST HALL ALLOCATION
                # =========================================================
                #
                # Goal:
                #   * Every hall is filled to its physical capacity (x2
                #     students) whenever enough students remain.
                #   * Only the final hall is allowed to be partially filled
                #     when the total number of remaining students is smaller
                #     than that hall's capacity.
                #
                # Earlier halls:
                #   * maximum 3 Course/Year groups
                #   * Course must be unique inside the hall
                #   * Year must be unique inside the hall
                #
                # Last 2 halls:
                #   * maximum 4 Course/Year groups
                #   * same Course allowed
                #   * same Year allowed
                #
                # The important difference from the old greedy logic is that
                # we choose a COMPLETE group combination for the target
                # capacity before consuming students. Therefore CF6 cannot
                # stop at 41 while enough students remain for its 64/68-seat
                # capacity.

                import itertools

                is_last_two_halls = hall_index >= max(0, len(halls) - 2)

                def course_of_group(g):
                    return str(g[0]).strip().lower()

                def year_of_group(g):
                    return str(g[1]).strip().lower()

                def raw_remaining(g):
                    return max(
                        0,
                        len(student_groups[g]) - positions[g]
                    )

                remaining_groups = [
                    g for g in group_keys
                    if raw_remaining(g) > 0
                ]

                target_students = min(
                    max_students,
                    remaining_students
                )

                # ---------------------------------------------------------
                # COURSE-PER-HALL PREFERENCE
                #
                # Target rule:
                #   1) First try to keep THIS HALL to maximum 2 distinct
                #      COURSE/YEAR groups.
                #   2) If a full hall is impossible, relax to 3 groups.
                #   3) If still impossible, relax to 4 groups.
                #
                # IMPORTANT:
                #   BBA - I Year and BBA - II Year are TWO different
                #   Course/Year groups. They must count separately.
                #
                # So the normal target is exactly/maximum 2 Course/Year
                # combinations per hall. We only allow 3 or 4 when the
                # remaining students/capacity make 2 impossible.
                # ---------------------------------------------------------

                def choose_course_limit(limit, require_full=True, distinct_courses_only=False):
                    # Try combinations of up to 4 Course/Year groups.
                    # IMPORTANT: when possible, each selected group must be
                    # from a DIFFERENT Course. Therefore BCA-I + BCA-II is
                    # not selected together while another Course is available.
                    max_groups = min(4, len(remaining_groups))
                    candidates = []

                    for k in range(1, max_groups + 1):
                        for combo in itertools.combinations(
                            remaining_groups, k
                        ):
                            distinct_course_years = len(set(combo))

                            if distinct_course_years > limit:
                                continue

                            if distinct_courses_only:
                                distinct_courses = {
                                    course_of_group(g)
                                    for g in combo
                                }
                                if len(distinct_courses) != len(combo):
                                    continue

                            total_available = sum(
                                raw_remaining(g) for g in combo
                            )

                            candidates.append((
                                combo,
                                total_available,
                                distinct_course_years
                            ))

                    if not candidates:
                        return None

                    # For the 2 -> 3 -> 4 preference, only a combination
                    # capable of filling the hall counts as success.
                    full = [
                        item for item in candidates
                        if item[1] >= target_students
                    ]

                    if full:
                        return min(
                            full,
                            key=lambda item: (
                                item[2],
                                item[1] - target_students,
                                -len(item[0])
                            )
                        )[0]

                    if require_full:
                        return None

                    # No Course limit can completely fill the hall. Use the
                    # best possible partial combination as the final fallback.
                    return max(
                        candidates,
                        key=lambda item: (
                            item[1],
                            -item[2],
                            len(item[0])
                        )
                    )[0]

                # IMPORTANT: try 2 Courses FIRST. Only if a full hall is
                # impossible with 2, try 3; only then try 4.
                selected_combo = choose_course_limit(2, require_full=True)
                allowed_course_limit = 2

                if selected_combo is None:
                    selected_combo = choose_course_limit(3, require_full=True)
                    allowed_course_limit = 3

                if selected_combo is None:
                    selected_combo = choose_course_limit(4, require_full=True)
                    allowed_course_limit = 4

                if selected_combo is None:
                    # Even 4 Courses cannot fill this hall. Take the maximum
                    # possible students rather than wasting capacity.
                    selected_combo = choose_course_limit(4, require_full=False, distinct_courses_only=False)
                    allowed_course_limit = 4

                    # Absolute last fallback: if there are not enough
                    # different Courses left, allow another year of the same
                    # Course only to avoid leaving seats unnecessarily empty.
                    if selected_combo is None:
                        selected_combo = choose_course_limit(4, require_full=False, distinct_courses_only=False)

                if selected_combo is None:
                    active_groups = []
                else:
                    active_groups = list(selected_combo)

                # All halls follow the same 2 -> 3 -> 4 Course/Year preference.
                # Different courses/years can mix; the same exact Course + Year
                # combination is never introduced twice into one hall.

                # ---------------------------------------------------------
                # Consume students until THIS HALL reaches target capacity.
                # When an active group exhausts, replace it.
                # ---------------------------------------------------------
                used_groups = set(active_groups)

                while len(students_for_hall) < target_students:
                    active_groups[:] = [
                        g for g in active_groups
                        if raw_remaining(g) > 0
                    ]

                    # Add replacement groups only when they stay inside the
                    # Course/Year limit already selected for this hall.
                    # If a group is exhausted, another group can replace it
                    # only if the selected Course/Year limit is not exceeded.
                    current_course_years = set(active_groups)

                    candidates = [
                        g for g in remaining_groups
                        if g not in used_groups
                        and raw_remaining(g) > 0
                    ]

                    # Only the exact Course + Year combination matters.
                    # Different courses may have the same year, and different
                    # years may belong to another course in the same hall.
                    for g in candidates:
                        if (
                            g in current_course_years
                            or
                            len(current_course_years) < allowed_course_limit
                        ):
                            active_groups.append(g)
                            used_groups.add(g)
                            current_course_years.add(g)

                        if len(active_groups) >= 4:
                            break

                    if not active_groups:
                        break

                    progress = False

                    # Take one from each active group in round-robin order.
                    for g in list(active_groups):
                        if len(students_for_hall) >= target_students:
                            break

                        if raw_remaining(g) <= 0:
                            continue

                        student = student_groups[g][positions[g]]
                        positions[g] += 1
                        students_for_hall.append((student, g))
                        progress = True

                    if not progress:
                        break

                # Final safety pass: if this hall still has free capacity and
                # students remain, use any remaining students. This can only
                # be reached when the strict Course/Year rules make a complete
                # combination impossible; it prevents avoidable empty seats.
                if len(students_for_hall) < target_students:
                    fallback_groups = sorted(
                        [
                            g for g in group_keys
                            if raw_remaining(g) > 0
                        ],
                        key=lambda g: raw_remaining(g),
                        reverse=True
                    )

                    for g in fallback_groups:
                        while (
                            len(students_for_hall) < target_students
                            and raw_remaining(g) > 0
                        ):
                            student = student_groups[g][positions[g]]
                            positions[g] += 1
                            students_for_hall.append((student, g))
            else:
                # 1-student mode: NEVER cycle through all Course/Year groups.
                # Keep at most TWO active groups at a time. A new group is
                # introduced only after one of the active groups is exhausted.
                active_groups_1s = []
                next_group_index_1s = 0

                def add_next_group_1s():
                    nonlocal next_group_index_1s

                    # First prefer a different Course. Example: if BCA-I is
                    # active, choose B.Sc CS / B.Sc IT / another Course next,
                    # instead of BCA-II, whenever possible.
                    active_courses = {
                        str(g[0]).strip().lower()
                        for g in active_groups_1s
                    }

                    for idx in range(next_group_index_1s, len(group_keys)):
                        candidate = group_keys[idx]
                        candidate_course = str(candidate[0]).strip().lower()
                        if (
                            positions[candidate] < len(student_groups[candidate])
                            and candidate not in active_groups_1s
                            and candidate_course not in active_courses
                        ):
                            next_group_index_1s = idx + 1
                            active_groups_1s.append(candidate)
                            return True

                    # Absolute fallback: if no different Course remains, use
                    # another year of the same Course so seats are not wasted.
                    while next_group_index_1s < len(group_keys):
                        candidate = group_keys[next_group_index_1s]
                        next_group_index_1s += 1
                        if (
                            positions[candidate] < len(student_groups[candidate])
                            and candidate not in active_groups_1s
                        ):
                            active_groups_1s.append(candidate)
                            return True
                    return False

                # Start with exactly two groups when available.
                while len(active_groups_1s) < 2 and add_next_group_1s():
                    pass

                # Fill this hall while respecting the max-2-active rule.
                # Students are taken from the active groups in round-robin
                # order so both groups can occupy separate columns.
                turn = 0
                while len(students_for_hall) < max_students:
                    active_groups_1s[:] = [
                        g for g in active_groups_1s
                        if positions[g] < len(student_groups[g])
                    ]

                    # Only now, after an active group is exhausted, introduce
                    # the next Course/Year. Never add a 3rd group early.
                    while len(active_groups_1s) < 2 and add_next_group_1s():
                        pass

                    if not active_groups_1s:
                        break

                    if turn >= len(active_groups_1s):
                        turn = 0

                    group_key = active_groups_1s[turn]
                    if positions[group_key] >= len(student_groups[group_key]):
                        active_groups_1s.remove(group_key)
                        continue

                    student = student_groups[group_key][positions[group_key]]
                    positions[group_key] += 1
                    students_for_hall.append((student, group_key))

                    # Move to the other currently-active group. If the selected
                    # group is exhausted, the next loop activates its replacement.
                    if active_groups_1s:
                        turn = (turn + 1) % len(active_groups_1s)

            # Faculty
            # ----------------------------------------------------

            # ====================================================
            # FACULTY ASSIGNMENT
            # ONE UNIQUE FACULTY PER ACTUALLY USED HALL
            # ====================================================
            # Faculty is assigned temporarily here so allocation can continue
            # through ALL halls needed by the students. Final faculty validation
            # is performed after the complete allocation is calculated.
            # This prevents an early/wrong error such as 27 halls when the
            # complete allocation actually needs 45 halls.
            if not students_for_hall:
                continue

            # For a partially Arrear-occupied hall, the faculty selected
            # on the Arrear Hall Allotment page must supervise the combined
            # Arrear + Regular students in that hall.
            arrear_faculty_id = arrear_faculty_by_hall.get(hall_id)
            if (
                arrear_faculty_id is not None
                and arrear_count > 0
                and arrear_count < hall_physical_capacity
            ):
                faculty = next(
                    (
                        f for f in faculty_pool
                        if int(f.get("id")) == int(arrear_faculty_id)
                    ),
                    None
                )

                # Arrear-selected faculty are excluded from the Regular
                # faculty dropdown, so load the required faculty directly.
                if faculty is None:
                    cursor.execute("""
                        SELECT id, faculty_name, department, course, year
                        FROM faculty_details
                        WHERE id = %s
                        LIMIT 1
                    """, (arrear_faculty_id,))
                    faculty = cursor.fetchone()

                if not faculty:
                    raise ValueError(
                        f"Arrear-selected faculty for hall {hall_id} was not found."
                    )
            else:
                faculty = faculty_pool[hall_index % len(faculty_pool)]

            used_hall_ids.append(hall_id)


            # ====================================================
            # SEAT INSERT
            #
            # FINAL SEATING RULE
            #
            # 1 STUDENT PER SEAT:
            #   - Fill the hall column-by-column.
            #   - A column uses one Course/Year as long as students
            #     are available.
            #   - If that Course/Year finishes before the column is
            #     full, the NEXT seat gets the next Course/Year.
            #   - The next column must not START with the same
            #     Course/Year as the previous column when another
            #     group is available.
            #   - Therefore, capacity is not wasted just because a
            #     Course/Year finishes.
            #
            # 2 STUDENTS PER SEAT:
            #   - Every physical seat can contain 2 students when
            #     enough students exist.
            #   - LEFT and RIGHT students must be different
            #     Course/Year groups.
            #   - Same Course/Year is allowed in neighbouring
            #     columns.
            #
            # The original student selection / hall distribution
            # above is NOT changed.
            # ====================================================

            COLUMNS = 6

            ROWS = (
                capacity // COLUMNS
            )

            if capacity % COLUMNS != 0:
                ROWS += 1

            # ----------------------------------------------------
            # Convert the already-selected students for this hall
            # into Course/Year queues.
            # ----------------------------------------------------

            hall_group_students = {}
            hall_group_order = []

            for student, group_key in students_for_hall:

                if group_key not in hall_group_students:
                    hall_group_students[group_key] = []
                    hall_group_order.append(group_key)

                hall_group_students[group_key].append(student)

            hall_group_positions = {
                key: 0
                for key in hall_group_order
            }

            def group_has_student(group_key):
                return (
                    group_key in hall_group_students
                    and
                    hall_group_positions[group_key]
                    <
                    len(hall_group_students[group_key])
                )

            def take_student(group_key):
                student = hall_group_students[group_key][
                    hall_group_positions[group_key]
                ]

                hall_group_positions[group_key] += 1

                return student

            def insert_student(
                student,
                seat_number,
                row_no,
                column_no,
                side
            ):
                cursor.execute(
                    """
                    INSERT INTO allotments
                    (
                        student_id,
                        hall_id,
                        exam_id,
                        faculty_id,
                        seat_number,
                        row_no,
                        column_no,
                        side,
                        session
                    )
                    VALUES
                    (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    """,
                    (
                        student["id"],
                        hall_id,
                        exam_id,
                        faculty["id"],
                        seat_number,
                        row_no,
                        column_no,
                        side,
                        session_name
                    )
                )

            # ====================================================
            # 1 STUDENT PER SEAT
            # FINAL COLUMN-WISE ALLOCATION
            # ====================================================
            # 1 physical seat = 1 student.
            #
            # Rules:
            #   * Maximum 2 active Course/Year groups in a hall.
            #   * A new group is introduced only after one active
            #     group is completely exhausted.
            #   * Allocation is column-wise (top to bottom).
            #   * Adjacent columns must not use the same group at
            #     the same row when another active group is available.
            #   * No duplicate student and no empty seat between
            #     allocated students.
            #   * If a group finishes in the middle of a column, the
            #     very next seat uses another active group; if needed,
            #     the next group is activated only after exhaustion.
            # ====================================================

            if seat_mode == "1":

                # At most two groups are active at any moment.
                active_groups = []
                next_group_index = 0

                def activate_next_group_1s():
                    nonlocal next_group_index
                    while next_group_index < len(hall_group_order):
                        g = hall_group_order[next_group_index]
                        next_group_index += 1
                        if group_has_student(g) and g not in active_groups:
                            active_groups.append(g)
                            return True
                    return False

                # Start with the first two available groups.
                while len(active_groups) < 2 and activate_next_group_1s():
                    pass

                previous_column_groups = []
                seat_count = 0

                for column_no in range(1, COLUMNS + 1):
                    if seat_count >= physical_seats:
                        break

                    # Remove exhausted groups and introduce replacements.
                    active_groups[:] = [
                        g for g in active_groups if group_has_student(g)
                    ]
                    while len(active_groups) < 2 and activate_next_group_1s():
                        pass

                    if not active_groups:
                        break

                    # Choose the group for the start of this column.
                    # Prefer a group different from the previous column.
                    column_group = None
                    if previous_column_groups:
                        for g in active_groups:
                            if g != previous_column_groups[0] and group_has_student(g):
                                column_group = g
                                break
                    if column_group is None:
                        column_group = next((g for g in active_groups if group_has_student(g)), None)
                    if column_group is None:
                        break

                    current_column_groups = []

                    for row_no in range(1, ROWS + 1):
                        if seat_count >= physical_seats:
                            break

                        # Keep active list clean.
                        active_groups[:] = [
                            g for g in active_groups if group_has_student(g)
                        ]
                        while len(active_groups) < 2 and activate_next_group_1s():
                            pass
                        if not active_groups:
                            break

                        # Normally continue the selected column group.
                        selected_group = column_group if group_has_student(column_group) else None

                        # If that group finished, use the other active group
                        # immediately (no empty gap), then activate a new group
                        # only when an active group has been exhausted.
                        if selected_group is None:
                            for g in active_groups:
                                if g != column_group and group_has_student(g):
                                    selected_group = g
                                    break
                            if selected_group is None:
                                selected_group = next((g for g in active_groups if group_has_student(g)), None)

                        # Prevent same Course/Year in adjacent columns at the
                        # same row whenever an alternative active group exists.
                        if previous_column_groups and row_no <= len(previous_column_groups):
                            prev_g = previous_column_groups[row_no - 1]
                            alternatives = [
                                g for g in active_groups
                                if g != prev_g and group_has_student(g)
                            ]
                            if alternatives and selected_group == prev_g:
                                # Prefer the other active group; this is the
                                # column-separation rule from the reference PDF.
                                selected_group = alternatives[0]

                        if selected_group is None:
                            break

                        student = take_student(selected_group)
                        seat_count += 1
                        seat_number = (column_no - 1) * ROWS + row_no

                        insert_student(
                            student,
                            seat_number,
                            row_no,
                            column_no,
                            "CENTER"
                        )
                        total_allocated += 1
                        current_column_groups.append(selected_group)

                        # If the selected group is exhausted, remove it and
                        # introduce the next group. This can happen on the very
                        # next seat, exactly as required.
                        if not group_has_student(selected_group):
                            if selected_group in active_groups:
                                active_groups.remove(selected_group)
                            while len(active_groups) < 2 and activate_next_group_1s():
                                pass

                    previous_column_groups = current_column_groups

            # ====================================================
            # 2 STUDENTS PER SEAT
            if seat_mode == "2":
                # Physical seats normally contain 2 students.
                # If the final remaining student cannot form a valid pair,
                # that last physical seat may contain 1 LEFT student.
                #
                # Pairing rule:
                #   I Year  + I Year   -> NOT allowed
                #   II Year + II Year  -> NOT allowed
                #   III Year + III Year -> ALLOWED
                #   I/II with III      -> allowed
                #   I Year + II Year   -> allowed
                #
                # Subject name/code are completely ignored here.
                COLUMNS = 6
                ROWS = max(1, (capacity + COLUMNS - 1) // COLUMNS)
                physical_seats = capacity

                def year_of_student(student):
                    return str(student.get("year") or "").strip().casefold()

                # Keep the selected students in the existing order.
                remaining_for_pairing = [
                    (student, group_key)
                    for student, group_key in students_for_hall
                ]

                pair_plan = []

                def pair_allowed(s1, s2):
                    y1 = year_of_student(s1)
                    y2 = year_of_student(s2)

                    # Only I + I and II + II are prohibited.
                    if y1 == "i" and y2 == "i":
                        return False
                    if y1 == "ii" and y2 == "ii":
                        return False
                    return True

                # Make exactly two students for every physical seat.
                # First preference is to preserve the existing student order,
                # then find the first valid partner anywhere in this hall.
                while remaining_for_pairing and len(pair_plan) < physical_seats:
                    s1, g1 = remaining_for_pairing.pop(0)

                    partner_index = next(
                        (
                            idx
                            for idx, (candidate, _candidate_group)
                            in enumerate(remaining_for_pairing)
                            if pair_allowed(s1, candidate)
                        ),
                        None
                    )

                    if partner_index is None:
                        # If this is the FINAL remaining student in this hall,
                        # allow a single LEFT student in 2-student mode.
                        # This prevents one last student from being skipped
                        # when the total student count is odd.
                        #
                        # If other students are still available, keep this
                        # student for the next hall so the existing pairing
                        # rules are preserved.
                        if not remaining_for_pairing:
                            pair_plan.append((s1, g1, None, None))
                            break

                        remaining_for_pairing.insert(0, (s1, g1))
                        break

                    s2, g2 = remaining_for_pairing.pop(partner_index)
                    pair_plan.append((s1, g1, s2, g2))

                # Roll back students that could not be placed as a complete
                # two-student seat. They remain available for the next hall.
                # The final single student is already part of pair_plan and
                # therefore is not rolled back.
                allocated_ids = set()
                for s1, _g1, s2, _g2 in pair_plan:
                    allocated_ids.add(s1["id"])
                    # Final single student has no RIGHT-side partner.
                    if s2 is not None:
                        allocated_ids.add(s2["id"])

                rollback_counts = {}
                for student, group_key in students_for_hall:
                    if student["id"] not in allocated_ids:
                        rollback_counts[group_key] = rollback_counts.get(group_key, 0) + 1

                for group_key, count in rollback_counts.items():
                    positions[group_key] -= count

                # Insert complete LEFT + RIGHT pairs contiguously.
                # A single LEFT student is allowed only for the final
                # remaining student in this hall.
                plan_index = 0
                for column_no in range(1, COLUMNS + 1):
                    if plan_index >= len(pair_plan):
                        break
                    for row_no in range(1, ROWS + 1):
                        if plan_index >= len(pair_plan):
                            break

                        s1, g1, s2, g2 = pair_plan[plan_index]
                        plan_index += 1
                        seat_number = (column_no - 1) * ROWS + row_no

                        insert_student(
                            s1, seat_number, row_no, column_no, "LEFT"
                        )
                        total_allocated += 1

                        # Normal case: two students share the physical seat.
                        # Final odd student: keep the RIGHT side empty.
                        if s2 is not None:
                            insert_student(
                                s2, seat_number, row_no, column_no, "RIGHT"
                            )
                            total_allocated += 1

        # REMAINING STUDENTS
        # ========================================================

        total_unallocated = sum(

            len(
                student_groups[key]
            )
            -
            positions[key]

            for key in group_keys

        )


        # ========================================================
        # FINAL FACULTY VALIDATION
        # ========================================================
        # Validate against the ACTUAL number of halls that received
        # students, not the number of halls selected in the form and not
        # the hall index reached before the allocation completed.
        # Partial-Arrear halls already have their faculty fixed by the
        # Arrear Hall Allotment. Only other used halls consume a Regular
        # faculty selected on the Regular page.
        regular_faculty_halls = []
        for used_hall_id in used_hall_ids:
            hall_info = next(
                (h for h in halls if int(h["id"]) == int(used_hall_id)),
                None
            )
            hall_capacity = int(
                (hall_info or {}).get("seating_capacity") or 0
            )
            hall_arrear_count = int(
                arrear_used_by_hall.get(int(used_hall_id), 0) or 0
            )
            has_partial_arrear = (
                hall_arrear_count > 0
                and hall_arrear_count < hall_capacity
                and int(used_hall_id) in arrear_faculty_by_hall
            )
            if not has_partial_arrear:
                regular_faculty_halls.append(int(used_hall_id))

        required_faculty = len(regular_faculty_halls)
        available_faculty = len(faculty_pool)

        if available_faculty < required_faculty:
            faculty_shortage = required_faculty - available_faculty
            raise ValueError(
                f"Faculty shortage: students require {required_faculty} halls, "
                f"but only {available_faculty} faculty selected. "
                f"Please add/select {faculty_shortage} more faculty."
            )

        # Partial-Arrear halls keep the Arrear-selected faculty.
        # All other used halls receive one unique Regular faculty.
        regular_index = 0
        for used_hall_id in used_hall_ids:
            hall_info = next(
                (h for h in halls if int(h["id"]) == int(used_hall_id)),
                None
            )
            hall_capacity = int(
                (hall_info or {}).get("seating_capacity") or 0
            )
            hall_arrear_count = int(
                arrear_used_by_hall.get(int(used_hall_id), 0) or 0
            )

            if (
                hall_arrear_count > 0
                and hall_arrear_count < hall_capacity
                and int(used_hall_id) in arrear_faculty_by_hall
            ):
                final_faculty_id = int(
                    arrear_faculty_by_hall[int(used_hall_id)]
                )
            else:
                final_faculty_id = faculty_pool[regular_index]["id"]
                regular_index += 1

            cursor.execute(
                """
                UPDATE allotments
                SET faculty_id = %s
                WHERE exam_id = %s AND hall_id = %s
                """,
                (final_faculty_id, exam_id, used_hall_id)
            )


        # ========================================================
        # CHECK
        # ========================================================

        if total_allocated <= 0:

            raise ValueError(
                "No students were allocated."
            )


        # ========================================================
        # CHANGE MODE - AVOID PREVIOUS HALL
        # ========================================================
        # NORMAL MODE: existing allocation is kept exactly as generated.
        # CHANGE MODE: a student must NOT return to the hall used in the
        # previous Hall Allotment.  We do NOT forbid today's normal hall,
        # because today's normal hall may already be different from the
        # previous hall.
        #
        # Today's occupied rows are reused as destination slots. This keeps
        # the same hall capacities, seat count and physical seat layout.
        if change_mode:
            cursor.execute("""
                SELECT id, student_id, hall_id, seat_number, row_no,
                       column_no, side, faculty_id, session
                FROM allotments
                WHERE exam_id = %s
                ORDER BY id
            """, (exam_id,))
            today_rows = cursor.fetchall()

            if not today_rows:
                raise ValueError("Change Mode: no students were allocated.")

            selected_hall_ids = [int(h["id"]) for h in halls]
            hall_capacity = {}
            for r in today_rows:
                hid = int(r["hall_id"])
                hall_capacity[hid] = hall_capacity.get(hid, 0) + 1

            active_halls = [
                hid for hid in selected_hall_ids
                if hall_capacity.get(hid, 0) > 0
            ]

            if len(active_halls) < 2:
                raise ValueError(
                    "Change Mode needs at least two halls with allocated students."
                )

            # Find the latest previous hall for each student directly from
            # allotments. This is more reliable than depending on a particular
            # HALL ALLOTMENT row in exam_timetable.
            previous_hall = {}
            for r in today_rows:
                sid = int(r["student_id"])
                cursor.execute("""
                    SELECT hall_id
                    FROM allotments
                    WHERE student_id = %s
                      AND exam_id <> %s
                      AND hall_id IS NOT NULL
                    ORDER BY id DESC
                    LIMIT 1
                """, (sid, exam_id))
                old_row = cursor.fetchone()
                if old_row and old_row.get("hall_id") is not None:
                    previous_hall[sid] = int(old_row["hall_id"])

            # --------------------------------------------------------
            # MAX-FLOW: student -> destination hall
            # ONLY previous hall is forbidden.
            # Today's current hall is NOT forbidden.
            # --------------------------------------------------------
            student_count = len(today_rows)
            hall_count = len(active_halls)
            source = 0
            student_base = 1
            hall_base = student_base + student_count
            sink = hall_base + hall_count
            node_count = sink + 1
            graph = [[] for _ in range(node_count)]

            def add_edge(u, v, cap):
                graph[u].append([v, cap, len(graph[v])])
                graph[v].append([u, 0, len(graph[u]) - 1])

            for i in range(student_count):
                add_edge(source, student_base + i, 1)

            hall_node = {hid: hall_base + i for i, hid in enumerate(active_halls)}
            for hid in active_halls:
                add_edge(hall_node[hid], sink, hall_capacity[hid])

            for i, r in enumerate(today_rows):
                sid = int(r["student_id"])
                old_hall = previous_hall.get(sid)
                for hid in active_halls:
                    if old_hall is None or hid != old_hall:
                        add_edge(student_base + i, hall_node[hid], 1)

            from collections import deque
            flow = 0
            INF = 10 ** 9

            while True:
                level = [-1] * node_count
                level[source] = 0
                q = deque([source])
                while q:
                    u = q.popleft()
                    for v, cap, rev in graph[u]:
                        if cap > 0 and level[v] < 0:
                            level[v] = level[u] + 1
                            q.append(v)

                if level[sink] < 0:
                    break

                it = [0] * node_count

                def dfs(u, pushed):
                    if u == sink:
                        return pushed
                    while it[u] < len(graph[u]):
                        e = graph[u][it[u]]
                        v, cap, rev = e
                        if cap > 0 and level[v] == level[u] + 1:
                            got = dfs(v, min(pushed, cap))
                            if got:
                                e[1] -= got
                                graph[v][rev][1] += got
                                return got
                        it[u] += 1
                    return 0

                while True:
                    pushed = dfs(source, INF)
                    if not pushed:
                        break
                    flow += pushed

            if flow != student_count:
                raise ValueError(
                    "Change Mode could not create a valid hall change. "
                    "Please select at least two halls with sufficient capacity."
                )

            assigned_hall = {}
            for i, r in enumerate(today_rows):
                u = student_base + i
                for e in graph[u]:
                    v, cap, rev = e
                    if hall_base <= v < sink and cap == 0:
                        assigned_hall[int(r["student_id"])] = active_halls[v - hall_base]
                        break

            if len(assigned_hall) != student_count:
                raise ValueError("Change Mode assignment could not be completed.")

            # Destination slots are the rows already generated today.
            destination_slots = {}
            for r in today_rows:
                hid = int(r["hall_id"])
                destination_slots.setdefault(hid, []).append(r)

            for hid in destination_slots:
                destination_slots[hid].sort(key=lambda x: int(x["id"]))
            destination_index = {hid: 0 for hid in destination_slots}

            # Keep the faculty assigned to each destination hall.
            hall_faculty = {}
            for hid in active_halls:
                cursor.execute("""
                    SELECT faculty_id
                    FROM allotments
                    WHERE exam_id = %s
                      AND hall_id = %s
                      AND faculty_id IS NOT NULL
                    ORDER BY id
                    LIMIT 1
                """, (exam_id, hid))
                fr = cursor.fetchone()
                hall_faculty[hid] = fr["faculty_id"] if fr else None

            for r in today_rows:
                sid = int(r["student_id"])
                new_hall = assigned_hall[sid]
                old_hall = previous_hall.get(sid)

                if old_hall is not None and new_hall == old_hall:
                    raise ValueError(
                        f"Change Mode returned student ID {sid} to the previous hall."
                    )

                slots = destination_slots.get(new_hall, [])
                idx = destination_index.get(new_hall, 0)
                if idx >= len(slots):
                    raise ValueError(
                        f"No destination seat available in hall {new_hall}."
                    )

                slot = slots[idx]
                destination_index[new_hall] = idx + 1
                new_faculty = hall_faculty.get(new_hall)
                if new_faculty is None:
                    new_faculty = r.get("faculty_id")

                cursor.execute("""
                    UPDATE allotments
                    SET hall_id = %s,
                        faculty_id = %s,
                        seat_number = %s,
                        row_no = %s,
                        column_no = %s,
                        side = %s
                    WHERE id = %s
                      AND exam_id = %s
                      AND student_id = %s
                """, (
                    new_hall,
                    new_faculty,
                    slot["seat_number"],
                    slot["row_no"],
                    slot["column_no"],
                    slot.get("side"),
                    r["id"],
                    exam_id,
                    sid
                ))

            # Final verification: students with a previous hall must not be
            # assigned back to that same hall.
            cursor.execute("""
                SELECT student_id, hall_id
                FROM allotments
                WHERE exam_id = %s
            """, (exam_id,))
            for r in cursor.fetchall():
                sid = int(r["student_id"])
                current_hall = int(r["hall_id"])
                if sid in previous_hall and current_hall == previous_hall[sid]:
                    raise ValueError(
                        f"Change Mode verification failed for student ID {sid}."
                    )

        # COMMIT
        # ========================================================

        print(
            f"ALLOCATION COMPLETE | TOTAL: {total_allocated} | "
            f"TIME: {time.time() - start_time:.2f}s",
            flush=True
        )

        db.commit()


        # ========================================================
        # SUCCESS MESSAGE
        # ========================================================

        if total_unallocated > 0:

            success_message = (

                f"{total_allocated} students "
                f"allocated successfully. "

                f"{total_unallocated} students "
                f"could not be allocated because "
                f"hall capacity was insufficient."

            )

        else:

            success_message = (

                f"{total_allocated} students "
                f"allocated successfully."

            )


        # ========================================================
        # REDIRECT
        # ========================================================

        return redirect(

            url_for(

                "hall_allotment",

                success=success_message

            )

        )


    # ============================================================
    # ERROR HANDLING
    # ============================================================

    except Exception as e:
        print("GENERATE HALL ALLOTMENT ERROR:", repr(e), flush=True)
        traceback.print_exc()

        if db:

            try:

                db.rollback()

            except Exception:

                pass


        return redirect(

            url_for(

                "hall_allotment",

                error=(
                    "Generate Hall Allotment Error: "
                    + str(e)
                )

            )

        )


    # ============================================================
    # CLOSE DATABASE
    # ============================================================

    finally:

        if cursor:

            try:

                cursor.close()

            except Exception:

                pass


        if db:

            try:

                db.close()

            except Exception:

                pass
# ==================================================
# STUDENT TIMETABLE
# ==================================================



# ==================================================
# STUDENT TIMETABLE
# ==================================================


@app.route("/student-timetable")
def student_timetable():

    register_no = session.get("student_register_number")

    if not register_no:
        return redirect(url_for("student_login"))

    db = None
    cursor = None

    try:

        db = get_db_connection()

        cursor = db.cursor(dictionary=True)

        # Get student details
        cursor.execute(
            """
            SELECT
                register_number,
                name,
                department,
                course,
                year
            FROM students
            WHERE register_number = %s
            """,
            (register_no,)
        )

        student = cursor.fetchone()

        if student is None:
            return redirect(url_for("student_login"))

        # Get timetable
        cursor.execute(
            """
            SELECT
                subject,
                exam_date,
                start_time,
                end_time
            FROM exam_timetable
            WHERE department = %s
              AND course = %s
              AND year = %s
            ORDER BY exam_date
            """,
            (
                student["department"],
                student["course"],
                student["year"]
            )
        )

        timetable = cursor.fetchall()

        return render_template(
            "student_timetable.html",
            student=student,
            timetable=timetable
        )

    except Exception as e:

        return "Student Timetable Error: " + str(e)

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()
# ==================================================
# STUDENT DASHBOARD
# ==================================================

@app.route("/student-dashboard")
def student_dashboard():

    register_number = session.get(
        "student_register_number"
    )

    if not register_number:
        return redirect(
            url_for("student_login")
        )

    db = None
    cursor = None

    try:

        db = get_db_connection()

        cursor = db.cursor(
            dictionary=True
        )

        # ------------------------------------------
        # GET STUDENT DETAILS
        # ------------------------------------------

        cursor.execute(
            """
            SELECT
                register_number,
                name,
                department,
                course,
                year
            FROM students
            WHERE register_number = %s
            """,
            (register_number,)
        )

        student = cursor.fetchone()

        if student is None:

            session.pop(
                "student_register_number",
                None
            )

            return redirect(
                url_for("student_login")
            )

        # ------------------------------------------
        # GET MATCHING TIMETABLE
        # Department + Course + Year
        # ------------------------------------------

        cursor.execute(
            """
            SELECT
                id,
                department,
                course,
                year,
                file_name,
                uploaded_at
            FROM faculty_timetables
            WHERE department = %s
              AND course = %s
              AND year = %s
            ORDER BY uploaded_at DESC
            """,
            (
                student["department"],
                student["course"],
                student["year"]
            )
        )

        timetables = cursor.fetchall()

        # ------------------------------------------
        # GET STUDENT HALL ALLOTMENT
        #
        # Only the logged-in student's allotment is
        # fetched. Dashboard needs only Exam Date
        # and a PDF link.
        # ------------------------------------------

        cursor.execute(
            """
            SELECT
                a.id AS allotment_id,
                a.exam_id,
                e.exam_date
            FROM allotments a
            INNER JOIN students s
                ON a.student_id = s.id
            INNER JOIN exam_timetable e
                ON a.exam_id = e.id
            WHERE s.register_number = %s
              AND UPPER(TRIM(e.course)) = 'HALL ALLOTMENT'
              AND UPPER(TRIM(e.year)) = 'ALL'
            ORDER BY
                e.exam_date DESC,
                a.id DESC
            LIMIT 1
            """,
            (register_number,)
        )

        allotment = cursor.fetchone()

        if allotment and allotment.get("exam_date") is not None:
            allotment["exam_date"] = str(
                allotment["exam_date"]
            )

        # ------------------------------------------
        # STUDENT DASHBOARD
        # ------------------------------------------

        return render_template(
            "student_dashboard.html",
            student=student,
            timetables=timetables,
            allotment=allotment
        )

    except Exception as e:

        return (
            "Student Dashboard Error: "
            + str(e)
        )

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()

# ==================================================
# FACULTY TIMETABLE MANAGEMENT
# ==================================================

@app.route(
    "/faculty-timetables",
    methods=["GET", "POST"]
)
def faculty_timetables():

    db = None
    cursor = None

    try:

        # ==================================================
        # DATABASE CONNECTION
        # ==================================================

        db = get_db_connection()

        cursor = db.cursor(
            dictionary=True,
            buffered=True
        )

        # ==================================================
        # YEAR NORMALIZATION
        # ==================================================

        def normalize_year(value):

            text = str(value or "").strip()
            upper = text.upper()

            # Excel numeric values may appear as 1.0 / 2.0 / 3.0 / 4.0
            if upper.endswith(".0"):
                upper = upper[:-2].strip()

            if upper in (
                "I", "1", "1 YEAR", "I YEAR", "1ST", "1ST YEAR"
            ):
                return "I Year"

            if upper in (
                "II", "2", "2 YEAR", "II YEAR", "2ND", "2ND YEAR"
            ):
                return "II Year"

            if upper in (
                "III", "3", "3 YEAR", "III YEAR", "3RD", "3RD YEAR"
            ):
                return "III Year"

            if upper in (
                "IV", "4", "4 YEAR", "IV YEAR", "4TH", "4TH YEAR"
            ):
                return "IV Year"

            return text



        # ==================================================
        # GET DEPARTMENT + COURSE + YEAR
        # FROM STUDENTS TABLE
        #
        # IMPORTANT:
        # No ORDER BY here because MySQL DISTINCT
        # gives Error 3065 with expressions.
        # ==================================================

        cursor.execute("""
            SELECT DISTINCT
                TRIM(department) AS department,
                TRIM(course) AS course,
                TRIM(year) AS year
            FROM students
            WHERE department IS NOT NULL
              AND TRIM(department) != ''
              AND course IS NOT NULL
              AND TRIM(course) != ''
              AND year IS NOT NULL
              AND TRIM(year) != ''
        """)

        raw_academic_data = cursor.fetchall()


        # ==================================================
        # NORMALIZE ACADEMIC DATA
        # ==================================================

        student_academic_data = []

        seen_combinations = set()


        for item in raw_academic_data:

            department = str(
                item.get("department") or ""
            ).strip()

            course = str(
                item.get("course") or ""
            ).strip()

            year = normalize_year(
                item.get("year")
            )


            # Skip empty values

            if not department:
                continue

            if not course:
                continue

            if not year:
                continue


            # ==================================================
            # REMOVE DUPLICATES
            # ==================================================

            combination_key = (
                department.lower(),
                course.lower(),
                year.lower()
            )


            if combination_key in seen_combinations:
                continue


            seen_combinations.add(
                combination_key
            )


            # ==================================================
            # ADD DATA
            # ==================================================

            student_academic_data.append({

                "department": department,

                "course": course,

                "year": year

            })


        # ==================================================
        # YEAR SORTING
        # ==================================================

        year_order = {

            "I Year": 1,

            "II Year": 2,

            "III Year": 3,

            "IV Year": 4

        }


        # ==================================================
        # SORT DEPARTMENT + COURSE + YEAR
        # ==================================================

        student_academic_data.sort(
            key=lambda x: (
                x["department"].lower(),

                x["course"].lower(),

                year_order.get(
                    x["year"],
                    99
                )
            )
        )


        # ==================================================
        # POST - UPLOAD TIMETABLE
        # ==================================================

        if request.method == "POST":


            # ==================================================
            # GET FORM VALUES
            # ==================================================

            department = (
                request.form.get(
                    "department"
                ) or ""
            ).strip()


            course = (
                request.form.get(
                    "course"
                ) or ""
            ).strip()


            year = normalize_year(
                request.form.get(
                    "year"
                ) or ""
            )


            timetable_file = request.files.get(
                "timetable_file"
            )


            # ==================================================
            # VALIDATE DEPARTMENT
            # ==================================================

            if not department:

                return render_template(
                    "faculty_timetables.html",

                    student_academic_data=
                        student_academic_data,

                    timetables=[],

                    success=None,

                    error=
                        "Please select Department."
                )


            # ==================================================
            # VALIDATE COURSE
            # ==================================================

            if not course:

                return render_template(
                    "faculty_timetables.html",

                    student_academic_data=
                        student_academic_data,

                    timetables=[],

                    success=None,

                    error=
                        "Please select Course."
                )


            # ==================================================
            # VALIDATE YEAR
            # ==================================================

            if not year:

                return render_template(
                    "faculty_timetables.html",

                    student_academic_data=
                        student_academic_data,

                    timetables=[],

                    success=None,

                    error=
                        "Please select Year."
                )


            # ==================================================
            # VERIFY DEPARTMENT + COURSE + YEAR
            # ==================================================

            valid_academic_data = False


            for item in student_academic_data:

                item_department = (
                    str(
                        item.get("department") or ""
                    )
                    .strip()
                    .lower()
                )


                item_course = (
                    str(
                        item.get("course") or ""
                    )
                    .strip()
                    .lower()
                )


                item_year = normalize_year(
                    item.get("year")
                ).strip().lower()


                if (

                    item_department
                    ==
                    department.strip().lower()

                    and

                    item_course
                    ==
                    course.strip().lower()

                    and

                    item_year
                    ==
                    normalize_year(
                        year
                    ).strip().lower()

                ):

                    valid_academic_data = True

                    break


            # ==================================================
            # INVALID COMBINATION
            # ==================================================

            if not valid_academic_data:

                return render_template(

                    "faculty_timetables.html",

                    student_academic_data=
                        student_academic_data,

                    timetables=[],

                    success=None,

                    error=(
                        "Selected Department, "
                        "Course and Year are "
                        "not available in "
                        "Student Management data."
                    )

                )


            # ==================================================
            # CHECK TIMETABLE FILE
            # ==================================================

            if (

                timetable_file is None

                or

                timetable_file.filename == ""

            ):

                return render_template(

                    "faculty_timetables.html",

                    student_academic_data=
                        student_academic_data,

                    timetables=[],

                    success=None,

                    error=
                        "Please select a timetable file."

                )


            # ==================================================
            # ALLOWED FILE TYPES
            # ==================================================

            allowed_extensions = (

                ".xlsx",

                ".xls",

                ".pdf"

            )


            original_filename = (
                timetable_file.filename
            )


            if not original_filename.lower().endswith(
                allowed_extensions
            ):

                return render_template(

                    "faculty_timetables.html",

                    student_academic_data=
                        student_academic_data,

                    timetables=[],

                    success=None,

                    error=(
                        "Only Excel or PDF files "
                        "are allowed."
                    )

                )


            # ==================================================
            # SECURE FILE NAME
            # ==================================================

            filename = secure_filename(
                original_filename
            )


            if not filename:

                return render_template(

                    "faculty_timetables.html",

                    student_academic_data=
                        student_academic_data,

                    timetables=[],

                    success=None,

                    error="Invalid file name."

                )


            # ==================================================
            # CREATE UPLOAD FOLDER
            # ==================================================

            if not os.path.exists(
                UPLOAD_FOLDER
            ):

                os.makedirs(
                    UPLOAD_FOLDER
                )


            # ==================================================
            # FILE PATH
            # ==================================================

            file_path = os.path.join(

                UPLOAD_FOLDER,

                filename

            )


            # ==================================================
            # SAVE FILE
            # ==================================================

            timetable_file.save(
                file_path
            )


            # ==================================================
            # SAVE TO DATABASE
            # ==================================================

            faculty_id = session.get("faculty_db_id")

            cursor.execute("""
                INSERT INTO faculty_timetables
                (
                    department,
                    course,
                    year,
                    file_name,
                    faculty_id
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
            """, (

                department,

                course,

                year,

                filename,

                faculty_id

            ))


            db.commit()


            # ==================================================
            # SUCCESS MESSAGE
            # ==================================================

            success = (
                "Timetable uploaded successfully!"
            )


        else:

            success = None


        # ==================================================
        # GET ALL UPLOADED TIMETABLES
        # ==================================================

        faculty_id = session.get("faculty_db_id")

        cursor.execute("""
            SELECT
                id,
                department,
                course,
                year,
                file_name,
                uploaded_at
            FROM faculty_timetables
            WHERE faculty_id = %s
            ORDER BY id DESC
        """, (faculty_id,))


        timetables = cursor.fetchall()


        # ==================================================
        # DISPLAY PAGE
        # ==================================================

        return render_template(

            "faculty_timetables.html",

            student_academic_data=
                student_academic_data,

            timetables=
                timetables,

            success=
                success,

            error=
                None

        )


    # ==================================================
    # ERROR HANDLING
    # ==================================================

    except Exception as e:

        if db:

            db.rollback()


        return render_template(

            "faculty_timetables.html",

            student_academic_data=[],

            timetables=[],

            success=None,

            error=(
                "Timetable Error: "
                + str(e)
            )

        )


    # ==================================================
    # CLOSE DATABASE
    # ==================================================

    finally:

        if cursor:

            cursor.close()


        if db:

            db.close()
# ==================================================
# FACULTY VIEW OWN TIMETABLES
# ==================================================

@app.route("/faculty-view-timetables")
def faculty_view_timetables():

    # ------------------------------------------
    # FACULTY LOGIN CHECK
    # ------------------------------------------

    if not session.get("faculty_logged_in"):
        return redirect(
            url_for("faculty_login")
        )


    faculty_id = session.get(
        "faculty_db_id"
    )


    db = None
    cursor = None

    try:

        db = get_db_connection()

        cursor = db.cursor(
            dictionary=True
        )


        # ------------------------------------------
        # GET ONLY LOGGED-IN FACULTY TIMETABLES
        # ------------------------------------------

        cursor.execute(
            """
            SELECT
                id,
                department,
                course,
                year,
                file_name,
                uploaded_at
            FROM faculty_timetables
            WHERE faculty_id = %s
            ORDER BY id DESC
            """,
            (
                faculty_id,
            )
        )


        timetables = cursor.fetchall()


        # ------------------------------------------
        # VIEW PAGE
        # ------------------------------------------

        return render_template(
            "faculty_view_timetables.html",
            timetables=timetables
        )


    except Exception as e:

        return (
            "Error loading timetables: "
            + str(e)
        )


    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()
# ==================================================
# DOWNLOAD FACULTY TIMETABLE
# ==================================================

@app.route(
    "/download-faculty-timetables/<path:filename>"
)
def download_faculty_timetables(filename):

    return send_from_directory(
        UPLOAD_FOLDER,
        filename,
        as_attachment=True
    )


# ==================================================
# DELETE FACULTY TIMETABLE
# ==================================================

@app.route(
    "/delete-faculty-timetables/<int:timetable_id>",
    methods=["POST"]
)
def delete_faculty_timetables(
    timetable_id
):

    db = None
    cursor = None

    try:

        db = get_db_connection()

        cursor = db.cursor(
            dictionary=True
        )

        # ==================================================
        # GET FILE DETAILS
        # ==================================================

        cursor.execute("""
            SELECT
                file_name
            FROM faculty_timetables
            WHERE id = %s
        """, (
            timetable_id,
        ))

        timetable = cursor.fetchone()

        if not timetable:

            return (
                "Timetable not found.",
                404
            )

        filename = (
            timetable["file_name"]
        )

        # ==================================================
        # DELETE DATABASE RECORD
        # ==================================================

        cursor.execute("""
            DELETE FROM faculty_timetables
            WHERE id = %s
        """, (
            timetable_id,
        ))

        db.commit()

        # ==================================================
        # DELETE FILE
        # ==================================================

        file_path = os.path.join(
            UPLOAD_FOLDER,
            filename
        )

        upload_folder_abs = os.path.abspath(
            UPLOAD_FOLDER
        )

        file_path_abs = os.path.abspath(
            file_path
        )

        # Security check

        if not file_path_abs.startswith(
            upload_folder_abs
        ):

            return "Invalid file path.", 400

        if os.path.exists(
            file_path
        ):

            os.remove(
                file_path
            )

        # ==================================================
        # REDIRECT
        # ==================================================

        return redirect(
            url_for(
                "faculty_timetables"
            )
        )

    except Exception as e:

        if db:
            db.rollback()

        return (
            "Delete Error: "
            + str(e)
        )

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()
# ==================================================
# QUESTION PAPER UPLOAD
# ==================================================

@app.route(
    "/question-paper-upload",
    methods=["GET", "POST"]
)
def question_paper_upload():

    db = None
    cursor = None

    departments = []
    courses = []
    student_academic_data = []

    # ==================================================
    # GET DEPARTMENT + COURSE + YEAR
    # FROM STUDENTS TABLE
    # ==================================================

    try:

        db = get_db_connection()

        cursor = db.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT DISTINCT
                TRIM(department) AS department,
                TRIM(course) AS course,
                TRIM(year) AS year
            FROM students
            WHERE department IS NOT NULL
              AND TRIM(department) <> ''
              AND course IS NOT NULL
              AND TRIM(course) <> ''
              AND year IS NOT NULL
              AND TRIM(year) <> ''
            ORDER BY department, course, year
            """
        )

        student_academic_data = cursor.fetchall()

        departments = []
        courses = []

        for row in student_academic_data:

            # ------------------------------------------
            # UNIQUE DEPARTMENT
            # ------------------------------------------

            if not any(
                d["department"].strip().lower()
                == row["department"].strip().lower()
                for d in departments
            ):

                departments.append({
                    "department": row["department"]
                })

            # ------------------------------------------
            # UNIQUE DEPARTMENT + COURSE
            # ------------------------------------------

            if not any(
                c["department"].strip().lower()
                == row["department"].strip().lower()
                and
                c["course"].strip().lower()
                == row["course"].strip().lower()
                for c in courses
            ):

                courses.append({
                    "department": row["department"],
                    "course": row["course"]
                })


    except Exception as e:

        return (
            "Error loading department/course/year: "
            + str(e)
        )


    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()


    # ==================================================
    # POST
    # ==================================================

    if request.method == "POST":

        department = request.form.get(
            "department"
        )

        course = request.form.get(
            "course"
        )

        year = request.form.get(
            "year"
        )

        subject = request.form.get(
            "subject"
        )

        subject_name = request.form.get(
            "subject_name"
        )

        total_strength = request.form.get(
            "total_strength"
        )

        exam_date = request.form.get(
            "exam_date"
        )

        file = request.files.get(
            "question_paper"
        )


        # ==================================================
        # CHECK ALL FIELDS
        # ==================================================

        if not all([
            department,
            course,
            year,
            subject,
            subject_name,
            total_strength,
            exam_date
        ]):

            return render_template(
                "question_paper_upload.html",
                departments=departments,
                courses=courses,
                student_academic_data=student_academic_data,
                error="Please fill all fields."
            )


        # ==================================================
        # CHECK FILE
        # ==================================================

        if file is None or file.filename == "":

            return render_template(
                "question_paper_upload.html",
                departments=departments,
                courses=courses,
                student_academic_data=student_academic_data,
                error="Please select a question paper."
            )


        # ==================================================
        # ALLOWED FILE TYPES
        # ==================================================

        allowed_extensions = [
            ".pdf",
            ".doc",
            ".docx"
        ]

        if not any(
            file.filename.lower().endswith(ext)
            for ext in allowed_extensions
        ):

            return render_template(
                "question_paper_upload.html",
                departments=departments,
                courses=courses,
                student_academic_data=student_academic_data,
                error=(
                    "Only PDF or Word files "
                    "are allowed."
                )
            )


        # ==================================================
        # UPLOAD + DATABASE
        # ==================================================

        db = None
        cursor = None

        try:

            filename = file.filename

            file_path = os.path.join(
                UPLOAD_FOLDER,
                filename
            )

            # ------------------------------------------
            # SAVE FILE
            # ------------------------------------------

            file.save(
                file_path
            )


            # ------------------------------------------
            # DATABASE CONNECTION
            # ------------------------------------------

            db = get_db_connection()

            cursor = db.cursor()


            # ------------------------------------------
            # INSERT QUESTION PAPER
            # ------------------------------------------

            faculty_id = session.get("faculty_db_id")

            cursor.execute(
                """
                INSERT INTO question_papers
                (
                    department,
                    course,
                    year,
                    subject,
                    subject_name,
                    total_strength,
                    exam_date,
                    file_name,
                    faculty_id
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    department,
                    course,
                    year,
                    subject,
                    subject_name,
                    total_strength,
                    exam_date,
                    filename,
                    faculty_id
                )
            )


            # ------------------------------------------
            # COMMIT
            # ------------------------------------------

            db.commit()


            # ------------------------------------------
            # SUCCESS
            # ------------------------------------------

            return render_template(
                "question_paper_upload.html",
                departments=departments,
                courses=courses,
                student_academic_data=student_academic_data,
                success=(
                    "Question paper uploaded "
                    "successfully!"
                )
            )


        except Exception as e:

            if db:
                db.rollback()

            return render_template(
                "question_paper_upload.html",
                departments=departments,
                courses=courses,
                student_academic_data=student_academic_data,
                error=(
                    "Upload Error: "
                    + str(e)
                )
            )


        finally:

            if cursor:
                cursor.close()

            if db:
                db.close()


    # ==================================================
    # GET
    # ==================================================

    return render_template(
        "question_paper_upload.html",
        departments=departments,
        courses=courses,
        student_academic_data=student_academic_data
    
    )
# ==================================================
# DOWNLOAD QUESTION PAPER
# ==================================================

@app.route("/download-question-paper/<filename>")
def download_question_paper(filename):

    return send_from_directory(
        UPLOAD_FOLDER,
        filename,
        as_attachment=True
    )
# ==================================================
# QUESTION PAPER LIST
# ==================================================

# ==================================================
# QUESTION PAPER MANAGEMENT
# ==================================================

# ==================================================
# ADMIN QUESTION PAPER MANAGEMENT
# ==================================================

@app.route("/admin-question-management")
def admin_question_management():

    db = None
    cursor = None

    try:

        db = get_db_connection()

        cursor = db.cursor(
            dictionary=True
        )

        # ------------------------------------------
        # GET ALL QUESTION PAPERS FOR ADMIN
        # ------------------------------------------

        cursor.execute(
            """
            SELECT
                id,
                department,
                course,
                year,
                subject,
                subject_name,
                total_strength,
                exam_date,
                file_name,
                uploaded_at
            FROM question_papers
            ORDER BY id DESC
            """
        )

        papers = cursor.fetchall()

        return render_template(
            "admin_question_management.html",
            papers=papers
        )

    except Exception as e:

        return (
            "Error loading question papers: "
            + str(e)
        )

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()


# ==================================================
# FACULTY QUESTION PAPER MANAGEMENT
# ==================================================

@app.route("/question-papers")
def question_papers():

    db = None
    cursor = None

    try:

        db = get_db_connection()

        cursor = db.cursor(
            dictionary=True
        )

        faculty_id = session.get("faculty_db_id")

        cursor.execute(
            """
            SELECT
                id,
                department,
                course,
                year,
                subject,
                subject_name,
                total_strength,
                exam_date,
                file_name,
                uploaded_at
            FROM question_papers
            WHERE faculty_id = %s
            ORDER BY id DESC
            """,
            (faculty_id,)
        )

        papers = cursor.fetchall()

        return render_template(
            "question_papers.html",
            papers=papers
        )

    except Exception as e:

        return (
            "Error loading question papers: "
            + str(e)
        )

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()


# ==================================================
# DELETE QUESTION PAPER
# ==================================================

@app.route(
    "/delete-question-paper/<int:paper_id>",
    methods=["POST"]
)
def delete_question_paper(paper_id):

    db = None
    cursor = None

    try:

        db = get_db_connection()

        cursor = db.cursor(
            dictionary=True
        )

        # ------------------------------------------
        # GET FILE NAME
        # ------------------------------------------

        cursor.execute(
            """
            SELECT
                file_name
            FROM question_papers
            WHERE id = %s
            """,
            (paper_id,)
        )

        paper = cursor.fetchone()

        if paper is None:

            if session.get("admin_logged_in"):
                return redirect(
                    url_for("admin_question_management")
                )

            return redirect(
                url_for("question_papers")
            )

        filename = paper["file_name"]

        # ------------------------------------------
        # DELETE DATABASE RECORD
        # ------------------------------------------

        cursor.execute(
            """
            DELETE FROM question_papers
            WHERE id = %s
            """,
            (paper_id,)
        )

        db.commit()

        # ------------------------------------------
        # DELETE ACTUAL FILE
        # ------------------------------------------

        file_path = os.path.join(
            UPLOAD_FOLDER,
            filename
        )

        if os.path.exists(file_path):

            os.remove(file_path)

        if session.get("admin_logged_in"):

            return redirect(
                url_for("admin_question_management")
            )

        return redirect(
            url_for("question_papers")
        )

    except Exception as e:

        if db:
            db.rollback()

        return (
            "Delete Error: "
            + str(e)
        )

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()

# ==================================================
# DOWNLOAD HALL ALLOTMENT PDF
# ==================================================

@app.route("/student-hall-pdf")
def student_hall_pdf():

    register_number = session.get("student_register_number")

    if not register_number:
        return redirect(url_for("student_login"))

    db = None
    cursor = None

    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        # GET ONLY THE LOGGED-IN STUDENT'S ALLOTMENT
        # Hall allotment data is stored in `allotments`.
        cursor.execute(
            """
            SELECT
                s.register_number,
                s.name,
                h.hall_name,
                a.seat_number,
                a.side,
                a.session,
                e.exam_date
            FROM allotments a
            INNER JOIN students s
                ON a.student_id = s.id
            INNER JOIN halls h
                ON a.hall_id = h.id
            INNER JOIN exam_timetable e
                ON a.exam_id = e.id
            WHERE s.register_number = %s
              AND UPPER(TRIM(e.course)) = 'HALL ALLOTMENT'
              AND UPPER(TRIM(e.year)) = 'ALL'
            ORDER BY
                e.exam_date DESC,
                a.id DESC
            LIMIT 1
            """,
            (register_number,)
        )

        allotment = cursor.fetchone()

        if not allotment:
            return "Hall allotment has not been assigned yet.", 404

        pdf_filename = (
            "student_hall_allotment_"
            + re.sub(r"[^A-Za-z0-9_-]", "_", str(register_number))
            + ".pdf"
        )

        pdf_path = os.path.join(
            UPLOAD_FOLDER,
            pdf_filename
        )

        pdf = canvas.Canvas(
            pdf_path,
            pagesize=A4
        )

        width, height = A4
        y = height - 60

        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawCentredString(
            width / 2,
            y,
            "COLLEGE EXAMINATION CELL"
        )

        y -= 35

        pdf.setFont("Helvetica-Bold", 15)
        pdf.drawCentredString(
            width / 2,
            y,
            "HALL ALLOTMENT"
        )

        y -= 55

        details = [
            ("Register Number", allotment["register_number"]),
            ("Student Name", allotment["name"]),
            ("Exam Date", str(allotment["exam_date"])),
            ("Session", allotment["session"] or "N/A"),
            ("Hall Name", allotment["hall_name"]),
            ("Seat Number", allotment["seat_number"]),
            ("Seat Side", allotment["side"] or "N/A")
        ]

        for label, value in details:

            pdf.setFont("Helvetica-Bold", 11)
            pdf.drawString(
                70,
                y,
                label + ":"
            )

            pdf.setFont("Helvetica", 11)
            pdf.drawString(
                210,
                y,
                str(value)
            )

            y -= 32

        pdf.save()

        return send_from_directory(
            UPLOAD_FOLDER,
            pdf_filename,
            as_attachment=True
        )

    except Exception as e:

        return (
            "PDF Error: "
            + str(e)
        )

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()

# ==================================================
# ADMIN EXAM TIMETABLE EXCEL UPLOAD
# ==================================================

@app.route("/admin-timetable-upload", methods=["GET", "POST"])
def admin_timetable_upload():

    success = None
    error = None

    db = None
    cursor = None

    try:

        db = get_db_connection()

        cursor = db.cursor(
            dictionary=True,
            buffered=True
        )

        # ==================================================
        # UPLOAD
        # ==================================================

        if request.method == "POST":

            exam_type = (
                request.form.get("exam_type")
                or ""
            ).strip()

            exam_name = (
                request.form.get("exam_name")
                or ""
            ).strip()

            exam_start_date = (
                request.form.get("exam_start_date")
                or ""
            ).strip()

            exam_end_date = (
                request.form.get("exam_end_date")
                or ""
            ).strip()

            timetable_file = request.files.get(
                "timetable_file"
            )

            # ==================================================
            # VALIDATION
            # ==================================================

            if not exam_type:

                error = (
                    "Please select exam type."
                )

            elif not exam_name:

                error = (
                    "Please enter exam name."
                )

            elif not exam_start_date:

                error = (
                    "Please select exam start date."
                )

            elif not exam_end_date:

                error = (
                    "Please select exam end date."
                )

            elif not timetable_file:

                error = (
                    "Please select Excel file."
                )

            elif timetable_file.filename == "":

                error = (
                    "Please select Excel file."
                )

            else:

                filename = timetable_file.filename

                # ==================================================
                # FILE VALIDATION
                # ==================================================

                if not (
                    filename.lower().endswith(".xlsx")
                    or
                    filename.lower().endswith(".xls")
                ):

                    error = (
                        "Please upload only Excel files."
                    )

                else:

                    # ==================================================
                    # UPLOAD FOLDER
                    # ==================================================

                    if not os.path.exists(
                        UPLOAD_FOLDER
                    ):

                        os.makedirs(
                            UPLOAD_FOLDER
                        )

                    # ==================================================
                    # SAVE FILE
                    # ==================================================

                    upload_path = os.path.join(
                        UPLOAD_FOLDER,
                        filename
                    )

                    timetable_file.save(
                        upload_path
                    )

                    # ==================================================
                    # READ EXCEL
                    # ==================================================

                    df = pd.read_excel(
                        upload_path,
                        header=0
                    )

                    # ==================================================
                    # CHECK COLUMNS
                    # ==================================================

                    if len(df.columns) < 3:

                        raise Exception(
                            "Excel format is incorrect. "
                            "Course, Year and date columns are required."
                        )

                    # ==================================================
                    # FIRST TWO COLUMNS
                    # ==================================================

                    course_column = df.columns[0]

                    year_column = df.columns[1]

                    total_subjects = 0

                    # ==================================================
                    # REMOVE OLD TIMETABLE FOR SAME
                    # EXAM TYPE + EXAM NAME
                    # ==================================================

                    cursor.execute(
                        """
                        DELETE FROM exam_timetable
                        WHERE
                            LOWER(TRIM(exam_type))
                                = LOWER(TRIM(%s))
                            AND
                            LOWER(TRIM(exam_name))
                                = LOWER(TRIM(%s))
                        """,
                        (
                            exam_type,
                            exam_name
                        )
                    )

                    # ==================================================
                    # REMOVE OLD UPLOADED FILE RECORD
                    # FOR SAME EXAM
                    # ==================================================

                    cursor.execute(
                        """
                        DELETE FROM uploaded_exam_files
                        WHERE
                            LOWER(TRIM(exam_type))
                                = LOWER(TRIM(%s))
                            AND
                            LOWER(TRIM(exam_name))
                                = LOWER(TRIM(%s))
                        """,
                        (
                            exam_type,
                            exam_name
                        )
                    )

                    # ==================================================
                    # PROCESS EXCEL ROWS
                    # ==================================================

                    for _, row in df.iterrows():

                        course = str(
                            row[course_column]
                        ).strip()

                        year = str(
                            row[year_column]
                        ).strip()

                        # ==================================================
                        # SKIP EMPTY ROW
                        # ==================================================

                        if (
                            course == ""
                            or
                            course.lower() == "nan"
                            or
                            year == ""
                            or
                            year.lower() == "nan"
                        ):

                            continue

                        # ==================================================
                        # PROCESS DATE COLUMNS
                        # ==================================================

                        for date_column in df.columns[2:]:

                            subject_value = (
                                row[date_column]
                            )

                            # ==================================================
                            # SKIP EMPTY SUBJECT
                            # ==================================================

                            if pd.isna(
                                subject_value
                            ):

                                continue

                            subject_text = str(
                                subject_value
                            ).strip()

                            if (
                                subject_text == ""
                                or
                                subject_text.lower() == "nan"
                            ):

                                continue

                            # ==================================================
                            # EXAM DATE
                            # ==================================================

                            exam_date = pd.to_datetime(
                                date_column
                            ).date()

                            # ==================================================
                            # SUBJECT CODE + SUBJECT NAME
                            #
                            # Example:
                            # 11T - TAMIL - I
                            # ==================================================

                            parts = (
                                subject_text.split(
                                    " - ",
                                    1
                                )
                            )

                            if len(parts) == 2:

                                subject_code = (
                                    parts[0].strip()
                                )

                                subject_name = (
                                    parts[1].strip()
                                )

                            else:

                                subject_code = None

                                subject_name = (
                                    subject_text
                                )

                            # ==================================================
                            # INSERT
                            # ==================================================
                            #
                            # exam_timetable mapping:
                            #   subject      -> Subject Code
                            #   subject_name -> Subject Name
                            #
                            # Example:
                            #   11T - Tamil - I
                            #   subject      = 11T
                            #   subject_name = Tamil - I
                            # ==================================================

                            cursor.execute(
                                """
                                INSERT INTO exam_timetable
                                (
                                    department,
                                    course,
                                    year,
                                    subject,
                                    exam_date,
                                    start_time,
                                    end_time,
                                    exam_type,
                                    exam_name,
                                    exam_start_date,
                                    exam_end_date,
                                    subject_name
                                )
                                VALUES
                                (
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    %s
                                )
                                """,
                                (
                                    "",
                                    course,
                                    year,
                                    subject_code,
                                    exam_date,
                                    "00:00:00",
                                    "00:00:00",
                                    exam_type,
                                    exam_name,
                                    exam_start_date,
                                    exam_end_date,
                                    subject_name
                                )
                            )

                            total_subjects += 1

                    # ==================================================
                    # SAVE UPLOADED FILE DETAILS
                    # ==================================================

                    cursor.execute(
                        """
                        INSERT INTO uploaded_exam_files
                        (
                            exam_type,
                            exam_name,
                            exam_start_date,
                            exam_end_date,
                            file_name,
                            file_path
                        )
                        VALUES
                        (
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s
                        )
                        """,
                        (
                            exam_type,
                            exam_name,
                            exam_start_date,
                            exam_end_date,
                            filename,
                            upload_path
                        )
                    )

                    # ==================================================
                    # COMMIT
                    # ==================================================

                    db.commit()

                    success = (
                        "Exam timetable uploaded successfully! "
                        + str(total_subjects)
                        + " timetable entries saved."
                    )

        # ==================================================
        # GET UPLOADED FILES
        # ==================================================

        cursor.execute(
            """
            SELECT
                id,
                exam_type,
                exam_name,
                exam_start_date,
                exam_end_date,
                file_name,
                uploaded_at
            FROM uploaded_exam_files
            ORDER BY uploaded_at DESC
            """
        )

        uploaded_files = (
            cursor.fetchall()
        )

        # ==================================================
        # RENDER
        # ==================================================

        return render_template(
            "admin_timetable_upload.html",
            success=success,
            error=error,
            uploaded_files=uploaded_files
        )

    # ==================================================
    # ERROR
    # ==================================================

    except Exception as e:

        if db:

            try:
                db.rollback()

            except Exception:
                pass

        return render_template(
            "admin_timetable_upload.html",
            success=None,
            error=(
                "Error: "
                + str(e)
            ),
            uploaded_files=[]
        )

    # ==================================================
    # CLOSE
    # ==================================================

    finally:

        if cursor:

            try:
                cursor.close()

            except Exception:
                pass

        if db:

            try:
                db.close()

            except Exception:
                pass
# ==================================================
# DELETE EXAM TIMETABLE FILE
# ==================================================

@app.route("/delete-exam-timetable/<int:file_id>", methods=["POST"])
def delete_exam_timetable_file(file_id):

    db = None
    cursor = None

    try:

        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        # ------------------------------------------
        # GET FILE DETAILS
        # ------------------------------------------

        cursor.execute(
            """
            SELECT file_name, file_path
            FROM uploaded_exam_files
            WHERE id = %s
            """,
            (file_id,)
        )

        file_data = cursor.fetchone()

        if not file_data:

            return redirect(
                url_for("admin_timetable_upload")
            )

        # ------------------------------------------
        # DELETE PHYSICAL EXCEL FILE
        # ------------------------------------------

        file_path = file_data["file_path"]

        if os.path.exists(file_path):

            os.remove(file_path)

        # ------------------------------------------
        # DELETE DATABASE RECORD
        # ------------------------------------------

        cursor.execute(
            """
            DELETE FROM uploaded_exam_files
            WHERE id = %s
            """,
            (file_id,)
        )

        db.commit()

        return redirect(
            url_for(
                "admin_timetable_upload"
            )
        )

    except Exception as e:

        if db:
            db.rollback()

        return (
            "Error deleting timetable: "
            + str(e)
        )

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()
# ==================================================
# OPEN UPLOADED FILE
# ==================================================

@app.route(
    "/uploads/<path:filename>"
)
def uploaded_file(filename):

    return send_from_directory(
        UPLOAD_FOLDER,
        filename
    )


# ==================================================
# EXAM HALL ATTENDANCE SYSTEM
# ==================================================

def ensure_attendance_table():
    """Create the attendance table once; does not alter hall-allotment logic."""
    db = None
    cur = None
    try:
        db = get_db_connection()
        cur = db.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS exam_attendance (
                id INT PRIMARY KEY AUTO_INCREMENT,
                allotment_id INT NOT NULL UNIQUE,
                student_id INT NOT NULL,
                hall_id INT NOT NULL,
                exam_id INT NOT NULL,
                faculty_id INT NOT NULL,
                attendance_status VARCHAR(20) NOT NULL,
                marked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_attendance_hall (hall_id),
                INDEX idx_attendance_exam (exam_id),
                INDEX idx_attendance_faculty (faculty_id)
            )
        """)

        # ----------------------------------------------------------
        # ADMIN ATTENDANCE CLOSE TABLE
        # Stores a separate close status for each HALL + EXAM.
        # Existing attendance table / marking logic is not changed.
        # ----------------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS exam_attendance_closures (
                id INT PRIMARY KEY AUTO_INCREMENT,
                hall_id INT NOT NULL,
                exam_id INT NOT NULL,
                closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_attendance_close_hall_exam (hall_id, exam_id),
                INDEX idx_close_hall (hall_id),
                INDEX idx_close_exam (exam_id)
            )
        """)

        db.commit()
    finally:
        if cur:
            cur.close()
        if db:
            db.close()


def _attendance_timetable_map(cur, exam_ids):
    """Return (exam_id, normalized course, normalized year) -> subject."""
    if not exam_ids:
        return {}
    placeholders = ",".join(["%s"] * len(exam_ids))
    cur.execute(f"""
        SELECT id, exam_date, exam_type, exam_name
        FROM exam_timetable
        WHERE id IN ({placeholders})
    """, tuple(exam_ids))
    exams = cur.fetchall()
    result = {}
    for ex in exams:
        cur.execute("""
            SELECT course, year, subject_name, subject, subject_name
            FROM exam_timetable
            WHERE exam_date = %s
              AND LOWER(TRIM(exam_type)) = LOWER(TRIM(%s))
              AND LOWER(TRIM(exam_name)) = LOWER(TRIM(%s))
              AND course IS NOT NULL
              AND TRIM(course) <> ''
              AND UPPER(TRIM(course)) <> 'HALL ALLOTMENT'
        """, (ex.get('exam_date'), ex.get('exam_type'), ex.get('exam_name')))
        rows = cur.fetchall()
        for row in rows:
            course = normalize_course_for_match(row.get('course'))
            year = normalize_year_for_match(row.get('year'))
            if not course or not year:
                continue
            subject = str(row.get('subject_name') or row.get('subject') or '').strip()
            result[(ex['id'], course.lower(), year)] = subject
    return result


def _attendance_rows(cur, where_sql='', params=()):
    cur.execute(f'''
        SELECT a.id AS allotment_id, NULL AS arrear_allotment_id,
               a.student_id, a.hall_id, a.exam_id, a.faculty_id,
               a.seat_number, a.row_no, a.column_no, a.side,
               h.hall_name, s.register_number, s.name AS student_name,
               s.department, s.course, s.year, f.faculty_name,
               ea.attendance_status, 0 AS is_arrear
        FROM allotments a
        INNER JOIN students s ON s.id = a.student_id
        INNER JOIN halls h ON h.id = a.hall_id
        LEFT JOIN faculty_details f ON f.id = a.faculty_id
        LEFT JOIN exam_attendance ea ON ea.allotment_id = a.id
        {where_sql}
        ORDER BY h.hall_name, a.seat_number, a.id
    ''', tuple(params))
    rows = cur.fetchall()

    if "a.faculty_id = %s" in where_sql:
        cur.execute('''
            SELECT -(aa.id) AS allotment_id, aa.id AS arrear_allotment_id,
                   aa.student_id, aa.hall_id, NULL AS exam_id,
                   aa.faculty_id, aa.seat_number, aa.row_no, aa.column_no,
                   aa.side, h.hall_name, s.reg_no AS register_number,
                   s.student_name, s.department, s.course, s.batch AS year,
                   f.faculty_name, aea.attendance_status, 1 AS is_arrear
            FROM arrear_allotments aa
            INNER JOIN arrear_students s ON s.id = aa.student_id
            INNER JOIN halls h ON h.id = aa.hall_id
            LEFT JOIN faculty_details f ON f.id = aa.faculty_id
            LEFT JOIN arrear_exam_attendance aea
                ON aea.arrear_allotment_id = aa.id
            WHERE aa.faculty_id = %s
            ORDER BY h.hall_name, aa.seat_number, aa.id
        ''', tuple(params))
        rows.extend(cur.fetchall())

    exam_ids = sorted({r.get('exam_id') for r in rows if r.get('exam_id') is not None})
    subject_map = _attendance_timetable_map(cur, exam_ids)
    for r in rows:
        course = normalize_course_for_match(r.get('course'))
        year = normalize_year_for_match(r.get('year'))
        r['subject'] = (
            subject_map.get((r.get('exam_id'), course.lower(), year), '')
            if course and year and r.get('exam_id') is not None else ''
        )

    rows.sort(key=lambda r: (
        str(r.get('hall_name') or '').lower(),
        int(r.get('seat_number') or 0),
        int(r.get('is_arrear') or 0),
        abs(int(r.get('allotment_id') or 0))
    ))
    return rows


def ensure_arrear_attendance_table():
    db = None
    cur = None
    try:
        db = get_db_connection()
        cur = db.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS arrear_exam_attendance (
                id INT PRIMARY KEY AUTO_INCREMENT,
                arrear_allotment_id INT NOT NULL UNIQUE,
                student_id INT NOT NULL,
                hall_id INT NOT NULL,
                exam_date DATE NOT NULL,
                faculty_id INT NULL,
                attendance_status VARCHAR(20) NOT NULL,
                marked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP
            )
        ''')
        db.commit()
    finally:
        if cur:
            cur.close()
        if db:
            db.close()


@app.route('/faculty-attendance', methods=['GET', 'POST'])
def faculty_attendance():
    if not session.get('faculty_logged_in'):
        return redirect(url_for('faculty_login'))

    faculty_id = session.get('faculty_db_id')
    ensure_attendance_table()
    ensure_arrear_attendance_table()

    db = None
    cur = None

    try:
        db = get_db_connection()
        cur = db.cursor(dictionary=True, buffered=True)

        # ==========================================================
        # ADMIN CLOSED ATTENDANCE LOCK
        # If Admin closes the hall assigned to this faculty,
        # this faculty cannot open or submit attendance.
        # ==========================================================
        cur.execute("""
            SELECT COUNT(*) AS total
            FROM allotments a
            INNER JOIN exam_attendance_closures c
                ON c.hall_id = a.hall_id
               AND c.exam_id = a.exam_id
            WHERE a.faculty_id = %s
        """, (faculty_id,))

        admin_closed = int((cur.fetchone() or {}).get('total') or 0)

        if admin_closed > 0:
            cur.execute("""
                SELECT DISTINCT h.hall_name
                FROM allotments a
                INNER JOIN halls h ON h.id = a.hall_id
                INNER JOIN exam_attendance_closures c
                    ON c.hall_id = a.hall_id AND c.exam_id = a.exam_id
                WHERE a.faculty_id = %s
                ORDER BY h.hall_name
            """, (faculty_id,))
            closed_rows = cur.fetchall()
            closed_hall_names = [str(r.get('hall_name') or '').strip() for r in closed_rows if r.get('hall_name')]
            hall_text = ', '.join(closed_hall_names) if closed_hall_names else 'the assigned hall'
            faculty_name = str(session.get('faculty_name') or 'Faculty')
            return f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Attendance Closed</title>
<style>
body{{font-family:Arial,sans-serif;background:#f5f7fb;margin:0;padding:30px;}}
.box{{max-width:650px;margin:80px auto;background:#fff;padding:35px;border-radius:14px;box-shadow:0 4px 18px rgba(0,0,0,.08);text-align:center;}}
h1{{color:#b91c1c;margin-bottom:18px;}}
.msg{{font-size:18px;line-height:1.6;color:#333;}}
.hall{{font-weight:bold;color:#111827;}}
</style>
</head>
<body>
<div class="box">
<h1>🔒 Attendance Closed</h1>
<div class="msg">
<p>Dear <b>{faculty_name}</b>,</p>
<p>Admin has closed attendance for <span class="hall">{hall_text}</span>.</p>
<p>You cannot open or submit attendance for this hall now.</p>
</div>
</div>
</body>
</html>
"""

        # ==========================================================
        # ATTENDANCE LOCK
        # Once this faculty has submitted attendance, the attendance
        # page cannot be opened or submitted again.
        # ==========================================================
        cur.execute("""
            SELECT COUNT(*) AS total
            FROM exam_attendance ea
            INNER JOIN allotments a
                ON a.id = ea.allotment_id
            WHERE a.faculty_id = %s
        """, (faculty_id,))

        submitted = int((cur.fetchone() or {}).get('total') or 0)

        if submitted > 0:
            return redirect(url_for('faculty_attendance_submitted'))

        # ==========================================================
        # SAVE ATTENDANCE
        #
        # Checkbox rule:
        #   CHECKED   -> ABSENT
        #   UNCHECKED -> PRESENT
        #
        # Therefore ALL students assigned to this faculty are saved.
        # Students whose checkbox is not ticked are automatically
        # recorded as PRESENT.
        # ==========================================================
        if request.method == 'POST':

            cur.execute('''
                SELECT id, student_id, hall_id, exam_id, faculty_id
                FROM allotments
                WHERE faculty_id = %s
                ORDER BY id
            ''', (faculty_id,))
            faculty_allotments = cur.fetchall()

            cur.execute('''
                SELECT aa.id AS arrear_allotment_id,
                       aa.student_id, aa.hall_id, aa.faculty_id, aa.exam_date
                FROM arrear_allotments aa
                WHERE aa.faculty_id = %s
                ORDER BY aa.id
            ''', (faculty_id,))
            faculty_arrear_allotments = cur.fetchall()

            if not faculty_allotments and not faculty_arrear_allotments:
                return redirect(url_for('faculty_attendance_submitted'))

            changed = 0

            for a in faculty_allotments:
                allotment_id = int(a['id'])
                status = (
                    "absent"
                    if f"attendance_{allotment_id}" in request.form
                    else "present"
                )
                cur.execute('''
                    INSERT INTO exam_attendance
                    (allotment_id, student_id, hall_id, exam_id,
                     faculty_id, attendance_status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        attendance_status = VALUES(attendance_status),
                        faculty_id = VALUES(faculty_id),
                        marked_at = CURRENT_TIMESTAMP
                ''', (
                    allotment_id, a['student_id'], a['hall_id'],
                    a['exam_id'], a['faculty_id'], status
                ))
                changed += 1

            for a in faculty_arrear_allotments:
                arrear_id = int(a['arrear_allotment_id'])
                form_id = -arrear_id
                status = (
                    "absent"
                    if f"attendance_{form_id}" in request.form
                    else "present"
                )
                cur.execute('''
                    INSERT INTO arrear_exam_attendance
                    (arrear_allotment_id, student_id, hall_id, exam_date,
                     faculty_id, attendance_status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        attendance_status = VALUES(attendance_status),
                        faculty_id = VALUES(faculty_id),
                        marked_at = CURRENT_TIMESTAMP
                ''', (
                    arrear_id, a['student_id'], a['hall_id'],
                    a['exam_date'], a['faculty_id'], status
                ))
                changed += 1

            db.commit()

            # Do NOT redirect back to faculty-attendance.
            return redirect(
                url_for(
                    'faculty_attendance_submitted',
                    saved=changed
                )
            )

        # ==========================================================
        # GET STUDENTS
        # ==========================================================
        rows = _attendance_rows(
            cur,
            'WHERE a.faculty_id = %s',
            (faculty_id,)
        )

        # ==========================================================
        # COURSE + YEAR WISE GROUPING
        # ==========================================================
        grouped = {}

        for row in rows:
            course = str(
                row.get('course') or 'Unknown Course'
            ).strip()

            year = str(
                row.get('year') or 'Unknown Year'
            ).strip()

            key = (course, year)

            if key not in grouped:
                grouped[key] = []

            grouped[key].append(row)

        # ==========================================================
        # SORT COURSE/YEAR
        # ==========================================================
        sorted_grouped = {}

        for key in sorted(
            grouped.keys(),
            key=lambda x: (
                x[0].lower(),
                x[1].lower()
            )
        ):
            sorted_grouped[key] = sorted(
                grouped[key],
                key=lambda r: (
                    str(
                        r.get('hall_name') or ''
                    ).lower(),
                    int(
                        r.get('seat_number') or 0
                    ),
                    int(
                        r.get('allotment_id') or 0
                    )
                )
            )

        return render_template(
            'faculty_attendance.html',
            grouped=sorted_grouped,
            rows=rows,
            faculty_name=session.get('faculty_name', 'Faculty'),
            faculty_code=session.get('faculty_code', ''),
            saved=request.args.get('saved', '0')
        )

    finally:
        if cur:
            cur.close()
        if db:
            db.close()


@app.route('/faculty-attendance-submitted')
def faculty_attendance_submitted():
    if not session.get('faculty_logged_in'):
        return redirect(url_for('faculty_login'))

    return render_template(
        'faculty_attendance_submitted.html',
        faculty_name=session.get('faculty_name', 'Faculty'),
        faculty_code=session.get('faculty_code', '')
    )
#=======================================================
#ADMIN ATTENDANCE
#=======================================================


# ==================================================
# ADMIN ATTENDANCE - CLOSE ONE HALL
# ==================================================

@app.route('/admin-attendance-close/<int:hall_id>/<int:exam_id>', methods=['POST'])
def admin_attendance_close(hall_id, exam_id):

    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    ensure_attendance_table()

    db = None
    cur = None

    try:
        db = get_db_connection()
        cur = db.cursor(dictionary=True, buffered=True)

        # Close only this allotted hall for this exam.
        # Only halls whose attendance is still pending are accepted.
        cur.execute("""
            SELECT COUNT(*) AS total
            FROM allotments a
            WHERE a.hall_id = %s
              AND a.exam_id = %s
        """, (hall_id, exam_id))

        allotted = int((cur.fetchone() or {}).get('total') or 0)

        if allotted == 0:
            return redirect(url_for('admin_attendance'))

        cur.execute("""
            SELECT COUNT(*) AS total
            FROM allotments a
            INNER JOIN exam_attendance ea
                ON ea.allotment_id = a.id
            WHERE a.hall_id = %s
              AND a.exam_id = %s
        """, (hall_id, exam_id))

        submitted = int((cur.fetchone() or {}).get('total') or 0)

        cur.execute("""
            SELECT id
            FROM exam_attendance_closures
            WHERE hall_id = %s
              AND exam_id = %s
            LIMIT 1
        """, (hall_id, exam_id))

        already_closed = cur.fetchone()

        if submitted == 0 and not already_closed:
            cur.execute("""
                INSERT INTO exam_attendance_closures
                    (hall_id, exam_id)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE closed_at = CURRENT_TIMESTAMP
            """, (hall_id, exam_id))
            db.commit()

        return redirect(url_for('admin_attendance'))

    except Exception as e:
        if db:
            db.rollback()
        return "Attendance Close Error: " + str(e)

    finally:
        if cur:
            cur.close()
        if db:
            db.close()


# ==================================================
# ADMIN ATTENDANCE - OPEN ONE CLOSED HALL
# ==================================================

@app.route('/admin-attendance-open/<int:hall_id>/<int:exam_id>', methods=['POST'])
def admin_attendance_open(hall_id, exam_id):

    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    ensure_attendance_table()
    db = None
    cur = None
    try:
        db = get_db_connection()
        cur = db.cursor(dictionary=True, buffered=True)
        cur.execute("""
            DELETE FROM exam_attendance_closures
            WHERE hall_id = %s AND exam_id = %s
        """, (hall_id, exam_id))
        db.commit()
        return redirect(url_for('admin_attendance'))
    except Exception as e:
        if db:
            db.rollback()
        return "Attendance Open Error: " + str(e)
    finally:
        if cur:
            cur.close()
        if db:
            db.close()


# ==================================================
# ADMIN ATTENDANCE - CLOSE ALL PENDING HALLS
# ==================================================

@app.route('/admin-attendance-close-all', methods=['POST'])
def admin_attendance_close_all():

    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    ensure_attendance_table()

    db = None
    cur = None

    try:
        db = get_db_connection()
        cur = db.cursor(dictionary=True, buffered=True)

        # Find only allotted hall + exam combinations whose attendance
        # has not been submitted and which are not already closed.
        cur.execute("""
            SELECT
                a.hall_id,
                a.exam_id
            FROM allotments a
            LEFT JOIN exam_attendance ea
                ON ea.allotment_id = a.id
            LEFT JOIN exam_attendance_closures c
                ON c.hall_id = a.hall_id
               AND c.exam_id = a.exam_id
            WHERE ea.id IS NULL
              AND c.id IS NULL
            GROUP BY a.hall_id, a.exam_id
        """)

        pending = cur.fetchall()

        for row in pending:
            cur.execute("""
                INSERT INTO exam_attendance_closures
                    (hall_id, exam_id)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE closed_at = CURRENT_TIMESTAMP
            """, (row['hall_id'], row['exam_id']))

        db.commit()

        return redirect(url_for('admin_attendance'))

    except Exception as e:
        if db:
            db.rollback()
        return "Close All Attendance Error: " + str(e)

    finally:
        if cur:
            cur.close()
        if db:
            db.close()


# ==================================================
# ADMIN ATTENDANCE
# ==================================================

@app.route('/admin-attendance')
def admin_attendance():

    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    ensure_attendance_table()

    db = None
    cur = None

    try:

        db = get_db_connection()

        cur = db.cursor(
            dictionary=True,
            buffered=True
        )

        rows = _attendance_rows(cur)

        # ------------------------------------------
        # PENDING HALLS
        # Only halls whose attendance has NOT been submitted
        # and has NOT been closed by Admin are shown.
        # ------------------------------------------
        cur.execute("""
            SELECT
                a.hall_id,
                a.exam_id,
                h.hall_name,
                MAX(f.faculty_name) AS faculty_name
            FROM allotments a
            INNER JOIN halls h
                ON h.id = a.hall_id
            LEFT JOIN faculty_details f
                ON f.id = a.faculty_id
            LEFT JOIN exam_attendance ea
                ON ea.allotment_id = a.id
            LEFT JOIN exam_attendance_closures c
                ON c.hall_id = a.hall_id
               AND c.exam_id = a.exam_id
            WHERE ea.id IS NULL
              AND c.id IS NULL
            GROUP BY a.hall_id, a.exam_id, h.hall_name
            ORDER BY h.hall_name, a.exam_id
        """)
        pending_halls = cur.fetchall()

        # ------------------------------------------
        # CLOSED HALLS
        # ------------------------------------------
        cur.execute("""
            SELECT
                c.hall_id,
                c.exam_id,
                h.hall_name,
                MAX(f.faculty_name) AS faculty_name,
                c.closed_at
            FROM exam_attendance_closures c
            INNER JOIN halls h ON h.id = c.hall_id
            INNER JOIN allotments a
                ON a.hall_id = c.hall_id AND a.exam_id = c.exam_id
            LEFT JOIN faculty_details f ON f.id = a.faculty_id
            GROUP BY c.hall_id, c.exam_id, h.hall_name, c.closed_at
            ORDER BY h.hall_name, c.exam_id
        """)
        closed_halls = cur.fetchall()

        # ------------------------------------------
        # COURSE + YEAR WISE GROUPING
        # ------------------------------------------

        grouped = {}

        for row in rows:

            course = str(
                row.get('course') or
                'Unknown Course'
            ).strip()

            year = str(
                row.get('year') or
                'Unknown Year'
            ).strip()

            key = (course, year)

            if key not in grouped:
                grouped[key] = []

            grouped[key].append(row)

        # ------------------------------------------
        # SORT COURSE + YEAR
        # ------------------------------------------

        sorted_grouped = {}

        for key in sorted(
            grouped.keys(),
            key=lambda x: (
                x[0].lower(),
                x[1].lower()
            )
        ):

            sorted_grouped[key] = sorted(
                grouped[key],
                key=lambda r: (
                    str(
                        r.get('hall_name') or ''
                    ).lower(),

                    int(
                        r.get('seat_number') or 0
                    ),

                    int(
                        r.get('allotment_id') or 0
                    )
                )
            )

        # ------------------------------------------
        # OLD HALL DATA ALSO KEEP
        # ------------------------------------------

        halls_data = []
        hall_map = {}

        for row in rows:

            hall_name = (
                row.get('hall_name')
                or 'Unknown Hall'
            )

            if hall_name not in hall_map:

                hall_map[hall_name] = {
                    'hall_name': hall_name,
                    'present': [],
                    'absent': [],
                    'unmarked': []
                }

                halls_data.append(
                    hall_map[hall_name]
                )

            status = str(
                row.get('attendance_status') or ''
            ).lower()

            if status == 'present':

                hall_map[
                    hall_name
                ]['present'].append(row)

            elif status == 'absent':

                hall_map[
                    hall_name
                ]['absent'].append(row)

            else:

                hall_map[
                    hall_name
                ]['unmarked'].append(row)

        return render_template(
            'admin_attendance.html',

            # NEW COURSE/YEAR DATA
            grouped=sorted_grouped,

            # OLD DATA - KEEP
            halls=halls_data,

            # PENDING HALLS - CLOSE OPTIONS
            pending_halls=pending_halls,

            # CLOSED HALLS - OPEN OPTIONS
            closed_halls=closed_halls
        )

    finally:

        if cur:
            cur.close()

        if db:
            db.close()


# ==================================================
# ADMIN ATTENDANCE PDF
# COURSE + YEAR WISE
# ==================================================

@app.route('/admin-attendance-pdf')
def admin_attendance_pdf():

    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    status = str(
        request.args.get(
            'status',
            'present'
        )
    ).strip().lower()

    if status not in ('present', 'absent'):
        return 'Invalid attendance status', 400

    ensure_attendance_table()

    db = None
    cur = None

    try:

        db = get_db_connection()

        cur = db.cursor(
            dictionary=True,
            buffered=True
        )

        rows = _attendance_rows(
            cur,
            """
            WHERE LOWER(
                COALESCE(
                    ea.attendance_status,
                    ''
                )
            ) = %s
            """,
            (status,)
        )

        # ------------------------------------------
        # INCLUDE ARREAR STUDENTS
        # ------------------------------------------
        # Arrear attendance is stored separately in
        # arrear_exam_attendance, so _attendance_rows()
        # cannot pick these rows when filtering by the
        # regular exam_attendance table. Add them here
        # for the Admin Present/Absent PDF only.
        ensure_arrear_attendance_table()

        cur.execute('''
            SELECT -(aa.id) AS allotment_id,
                   aa.id AS arrear_allotment_id,
                   aa.student_id,
                   aa.hall_id,
                   NULL AS exam_id,
                   aa.faculty_id,
                   aa.seat_number,
                   aa.row_no,
                   aa.column_no,
                   aa.side,
                   h.hall_name,
                   s.reg_no AS register_number,
                   s.student_name,
                   s.department,
                   s.course,
                   s.batch AS year,
                   f.faculty_name,
                   aea.attendance_status,
                   1 AS is_arrear
            FROM arrear_allotments aa
            INNER JOIN arrear_students s
                ON s.id = aa.student_id
            INNER JOIN halls h
                ON h.id = aa.hall_id
            LEFT JOIN faculty_details f
                ON f.id = aa.faculty_id
            INNER JOIN arrear_exam_attendance aea
                ON aea.arrear_allotment_id = aa.id
            WHERE LOWER(
                COALESCE(aea.attendance_status, '')
            ) = %s
            ORDER BY h.hall_name, aa.seat_number, aa.id
        ''', (status,))

        rows.extend(cur.fetchall())

        # ------------------------------------------
        # COURSE + YEAR GROUP
        # ------------------------------------------

        grouped = {}

        for row in rows:

            course = str(
                row.get('course') or
                'Unknown Course'
            ).strip()

            year = str(
                row.get('year') or
                'Unknown Year'
            ).strip()

            key = (course, year)

            if key not in grouped:
                grouped[key] = []

            grouped[key].append(row)

        # ------------------------------------------
        # SORT
        # ------------------------------------------

        sorted_groups = {}

        for key in sorted(
            grouped.keys(),
            key=lambda x: (
                x[0].lower(),
                x[1].lower()
            )
        ):

            sorted_groups[key] = sorted(
                grouped[key],
                key=lambda r: (
                    str(
                        r.get('hall_name') or ''
                    ).lower(),

                    int(
                        r.get('seat_number') or 0
                    ),

                    int(
                        r.get('allotment_id') or 0
                    )
                )
            )

        # ------------------------------------------
        # PDF
        # ------------------------------------------

        buffer = BytesIO()

        if status == 'present':

            pdf_filename = (
                'Present_Students_Course_Year_Wise.pdf'
            )

            pdf_title = (
                'PRESENT STUDENTS ATTENDANCE'
            )

        else:

            pdf_filename = (
                'Absent_Students_Course_Year_Wise.pdf'
            )

            pdf_title = (
                'ABSENT STUDENTS ATTENDANCE'
            )

        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            rightMargin=25,
            leftMargin=25,
            topMargin=25,
            bottomMargin=25,
            title=pdf_title,
            author='College Examination Cell'
        )

        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            'PDFTitle',
            parent=styles['Title'],
            fontSize=16,
            leading=20,
            alignment=1,
            spaceAfter=8
        )

        group_style = ParagraphStyle(
            'GroupHeading',
            parent=styles['Heading2'],
            fontSize=13,
            leading=16,
            spaceBefore=8,
            spaceAfter=8
        )

        cell_style = ParagraphStyle(
            'Cell',
            parent=styles['BodyText'],
            fontSize=8,
            leading=10
        )

        head_style = ParagraphStyle(
            'Head',
            parent=styles['BodyText'],
            fontSize=8,
            leading=10,
            alignment=1
        )

        story = []

        story.append(
            Paragraph(
                'COLLEGE EXAMINATION CELL',
                title_style
            )
        )

        story.append(
            Paragraph(
                pdf_title,
                title_style
            )
        )

        story.append(
            Spacer(1, 8)
        )

        # ------------------------------------------
        # COURSE + YEAR WISE TABLE
        # ------------------------------------------

        for (
            course,
            year
        ), course_rows in sorted_groups.items():

            total = len(course_rows)

            story.append(
                Paragraph(
                    '<b>COURSE:</b> ' +
                    course +
                    ' &nbsp;&nbsp; | &nbsp;&nbsp; ' +
                    '<b>YEAR:</b> ' +
                    year +
                    ' &nbsp;&nbsp; | &nbsp;&nbsp; ' +
                    '<b>TOTAL:</b> ' +
                    str(total),
                    group_style
                )
            )

            # ONE TABLE
            # HALL IS A COLUMN

            data = [[

                Paragraph(
                    '<b>Hall</b>',
                    head_style
                ),

                Paragraph(
                    '<b>Reg No</b>',
                    head_style
                ),

                Paragraph(
                    '<b>Student Name</b>',
                    head_style
                ),

                Paragraph(
                    '<b>Department</b>',
                    head_style
                ),

                Paragraph(
                    '<b>Subject</b>',
                    head_style
                ),

                Paragraph(
                    '<b>Seat No</b>',
                    head_style
                )

            ]]

            for row in course_rows:

                data.append([

                    Paragraph(
                        str(
                            row.get(
                                'hall_name'
                            ) or ''
                        ),
                        cell_style
                    ),

                    Paragraph(
                        str(
                            row.get(
                                'register_number'
                            ) or ''
                        ),
                        cell_style
                    ),

                    Paragraph(
                        str(
                            row.get(
                                'student_name'
                            ) or ''
                        ),
                        cell_style
                    ),

                    Paragraph(
                        str(
                            row.get(
                                'department'
                            ) or ''
                        ),
                        cell_style
                    ),

                    Paragraph(
                        str(
                            row.get(
                                'subject'
                            ) or ''
                        ),
                        cell_style
                    ),

                    Paragraph(
                        str(
                            row.get(
                                'seat_number'
                            ) or ''
                        ),
                        cell_style
                    )

                ])

            table = Table(
                data,
                colWidths=[
                    75,
                    90,
                    150,
                    120,
                    190,
                    60
                ],
                repeatRows=1
            )

            table.setStyle(
                TableStyle([

                    (
                        'BACKGROUND',
                        (0, 0),
                        (-1, 0),
                        colors.lightgrey
                    ),

                    (
                        'GRID',
                        (0, 0),
                        (-1, -1),
                        0.5,
                        colors.grey
                    ),

                    (
                        'VALIGN',
                        (0, 0),
                        (-1, -1),
                        'MIDDLE'
                    ),

                    (
                        'ALIGN',
                        (0, 0),
                        (0, -1),
                        'CENTER'
                    ),

                    (
                        'ALIGN',
                        (-1, 0),
                        (-1, -1),
                        'CENTER'
                    ),

                    (
                        'LEFTPADDING',
                        (0, 0),
                        (-1, -1),
                        5
                    ),

                    (
                        'RIGHTPADDING',
                        (0, 0),
                        (-1, -1),
                        5
                    ),

                    (
                        'TOPPADDING',
                        (0, 0),
                        (-1, -1),
                        5
                    ),

                    (
                        'BOTTOMPADDING',
                        (0, 0),
                        (-1, -1),
                        5
                    )

                ])
            )

            story.append(table)

            story.append(
                Spacer(1, 12)
            )

        # ------------------------------------------
        # PDF METADATA
        # ------------------------------------------

        def set_pdf_metadata(
            canvas_obj,
            doc_obj
        ):

            canvas_obj.setTitle(
                pdf_title
            )

            canvas_obj.setAuthor(
                'College Examination Cell'
            )

            canvas_obj.setSubject(
                'Course and Year Wise Attendance Report'
            )

        doc.build(
            story,
            onFirstPage=set_pdf_metadata,
            onLaterPages=set_pdf_metadata
        )

        buffer.seek(0)

        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=pdf_filename
        )

    finally:

        if cur:
            cur.close()

        if db:
            db.close()

# ==================================================
# ADMIN ATTENDANCE SUMMARY PDF
# COURSE + YEAR + SUBJECT WISE
# ==================================================

@app.route('/admin-attendance-summary-pdf')
def admin_attendance_summary_pdf():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    ensure_attendance_table()
    db = None
    cur = None
    try:
        db = get_db_connection()
        cur = db.cursor(dictionary=True, buffered=True)

        regular_rows = _attendance_rows(
            cur,
            """
            WHERE LOWER(COALESCE(ea.attendance_status, '')) IN ('present', 'absent')
            """,
        )

        ensure_arrear_attendance_table()
        cur.execute("""
            SELECT aa.id AS allotment_id,
                   aa.student_id,
                   aa.hall_id,
                   aa.faculty_id,
                   s.course,
                   s.batch AS year,
                   s.subject_name AS subject,
                   aea.attendance_status
            FROM arrear_allotments aa
            INNER JOIN arrear_students s ON s.id = aa.student_id
            INNER JOIN arrear_exam_attendance aea
                ON aea.arrear_allotment_id = aa.id
            WHERE LOWER(COALESCE(aea.attendance_status, '')) IN ('present', 'absent')
            ORDER BY s.course, s.batch, s.subject_name, aa.id
        """)
        arrear_rows = cur.fetchall()

        grouped = {}
        for row in regular_rows + arrear_rows:
            course = str(row.get('course') or 'Unknown Course').strip()
            year = str(row.get('year') or 'Unknown Year').strip()
            subject = str(row.get('subject') or 'Unknown Subject').strip()
            key = (course.casefold(), year.casefold(), subject.casefold())
            if key not in grouped:
                grouped[key] = {
                    'course': course,
                    'year': year,
                    'subject': subject,
                    'total': 0,
                    'absent': 0,
                    'present': 0,
                }
            grouped[key]['total'] += 1
            status = str(row.get('attendance_status') or '').strip().lower()
            if status == 'absent':
                grouped[key]['absent'] += 1
            elif status == 'present':
                grouped[key]['present'] += 1

        buffer = BytesIO()
        pdf_title = 'ATTENDANCE SUMMARY REPORT'
        pdf_filename = 'Attendance_Summary_Report.pdf'
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            rightMargin=25,
            leftMargin=25,
            topMargin=25,
            bottomMargin=25,
            title=pdf_title,
            author='College Examination Cell'
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'AttendanceSummaryTitle', parent=styles['Title'],
            fontSize=16, leading=20, alignment=1, spaceAfter=8
        )
        cell_style = ParagraphStyle(
            'AttendanceSummaryCell', parent=styles['BodyText'],
            fontSize=8, leading=10, alignment=1
        )
        head_style = ParagraphStyle(
            'AttendanceSummaryHead', parent=styles['BodyText'],
            fontSize=8, leading=10, alignment=1
        )

        story = [
            Paragraph('COLLEGE EXAMINATION CELL', title_style),
            Paragraph('OTHAKUTHIRAI, GOBI - 638455', title_style),
            Paragraph(pdf_title, title_style),
            Spacer(1, 10),
        ]
        data = [[
            Paragraph('<b>S.No</b>', head_style),
            Paragraph('<b>Course</b>', head_style),
            Paragraph('<b>Year</b>', head_style),
            Paragraph('<b>Subject</b>', head_style),
            Paragraph('<b>Total Strength</b>', head_style),
            Paragraph('<b>Absent Student</b>', head_style),
            Paragraph('<b>Present Student</b>', head_style),
            Paragraph('<b>Faculty Signature</b>', head_style),
        ]]

        items = sorted(
            grouped.values(),
            key=lambda x: (x['course'].casefold(), x['year'].casefold(), x['subject'].casefold())
        )
        for index, item in enumerate(items, start=1):
            data.append([
                Paragraph(str(index), cell_style),
                Paragraph(item['course'], cell_style),
                Paragraph(item['year'], cell_style),
                Paragraph(item['subject'], cell_style),
                Paragraph(str(item['total']), cell_style),
                Paragraph(str(item['absent']), cell_style),
                Paragraph(str(item['present']), cell_style),
                Paragraph('', cell_style),
            ])

        table = Table(
            data,
            colWidths=[40, 90, 65, 180, 75, 85, 90, 120],
            repeatRows=1
        )
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ]))
        story.append(table)

        def set_pdf_metadata(canvas_obj, doc_obj):
            canvas_obj.setTitle(pdf_title)
            canvas_obj.setAuthor('College Examination Cell')
            canvas_obj.setSubject('Course, Year and Subject Wise Attendance Summary')

        doc.build(story, onFirstPage=set_pdf_metadata, onLaterPages=set_pdf_metadata)
        buffer.seek(0)
        return send_file(
            buffer, mimetype='application/pdf', as_attachment=True,
            download_name=pdf_filename
        )
    except Exception as e:
        traceback.print_exc()
        return 'Attendance Summary PDF Error: ' + str(e), 500
    finally:
        if cur:
            cur.close()
        if db:
            db.close()


# ==================================================
# ARREAR MODULE - DATABASE TABLES
# ==================================================
def ensure_arrear_tables():
    db = None
    cur = None
    try:
        db = get_db_connection()
        cur = db.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS arrear_students (
                id INT PRIMARY KEY AUTO_INCREMENT,
                department VARCHAR(255) NOT NULL,
                course VARCHAR(255) NOT NULL,
                reg_no VARCHAR(100) NOT NULL,
                student_name VARCHAR(255) NOT NULL,
                subject_name VARCHAR(100) NOT NULL,
                batch VARCHAR(100) NOT NULL,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_arrear_student_match (course, batch, subject_name),
                INDEX idx_arrear_reg (reg_no)
            )
        """)
        # Create Arrear timetable first so older databases can be migrated safely.
        # CREATE TABLE IF NOT EXISTS does not add missing columns to an existing table.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS arrear_timetable (
                id INT PRIMARY KEY AUTO_INCREMENT,
                course VARCHAR(255) NOT NULL,
                batch VARCHAR(100) NOT NULL,
                exam_date DATE NOT NULL,
                subject_name VARCHAR(100) NOT NULL,
                subject_text TEXT NOT NULL,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_arrear_tt_match (course, batch, exam_date),
                INDEX idx_arrear_tt_subject (subject_name)
            )
        """)
        # Migrate older Arrear tables safely. This fixes old databases where
        # arrear_students exists without subject_name.
        for table_name, column_name, definition in [
            ('arrear_students', 'subject_name', "VARCHAR(100) NOT NULL DEFAULT ''"),
            ('arrear_timetable', 'subject_name', "VARCHAR(100) NOT NULL DEFAULT ''"),
            ('arrear_timetable', 'subject_text', "TEXT NULL"),
        ]:
            cur.execute("""
                SELECT COUNT(*)
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = %s
                  AND COLUMN_NAME = %s
            """, (table_name, column_name))
            row = cur.fetchone()
            # Normal mysql.connector cursors return tuples, not dictionaries.
            if row is not None and int(row[0]) == 0:
                cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS arrear_allotments (
                id INT PRIMARY KEY AUTO_INCREMENT,
                student_id INT NOT NULL,
                hall_id INT NOT NULL,
                exam_date DATE NOT NULL,
                seat_number INT NOT NULL,
                row_no INT NULL,
                column_no INT NULL,
                side VARCHAR(30) DEFAULT 'CENTER',
                faculty_id INT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_arrear_allot_exam_hall (exam_date, hall_id),
                INDEX idx_arrear_allot_student (student_id)
            )
        """)
        db.commit()
    finally:
        if cur:
            cur.close()
        if db:
            db.close()


def _arrear_norm(value):
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _arrear_subject_parts(value):
    text = str(value or "").strip()
    if " - " in text:
        code, name = text.split(" - ", 1)
        return code.strip(), name.strip()
    if " + " in text:
        code, name = text.split(" + ", 1)
        return code.strip(), name.strip()
    return text, text


def _arrear_parse_date_header(value):
    try:
        return pd.to_datetime(value).date()
    except Exception:
        text = str(value or "").strip()
        for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(text, fmt).date()
            except Exception:
                pass
    return None


@app.route("/arrear-hall-allotment", methods=["GET", "POST"])
def arrear_hall_allotment():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    ensure_arrear_tables()

    db = None
    cur = None

    message = request.args.get("success")
    error = request.args.get("error")

    try:
        db = get_db_connection()
        cur = db.cursor(dictionary=True, buffered=True)

        # ============================================================
        # POST ACTIONS
        # ============================================================
        if request.method == "POST":

            action = str(request.form.get("action") or "").strip()
            upload = request.files.get("file")

            # ========================================================
            # ARREAR HALL ALLOTMENT GENERATION
            # ========================================================
            if action == "generate":

                exam_date_text = str(
                    request.form.get("exam_date") or ""
                ).strip()

                hall_ids = list(
                    dict.fromkeys(
                        int(x)
                        for x in request.form.getlist("hall_ids")
                        if str(x).strip().isdigit()
                    )
                )

                # ----------------------------------------------------
                # Faculty selected separately for each Arrear hall
                # ----------------------------------------------------
                faculty_by_hall = {}

                for hid in hall_ids:

                    raw_fid = str(
                        request.form.get(f"faculty_id_{hid}") or ""
                    ).strip()

                    if not raw_fid.isdigit():
                        raise ValueError(
                            f"Please choose a faculty for hall ID {hid}."
                        )

                    faculty_by_hall[hid] = int(raw_fid)

                # ----------------------------------------------------
                # Validate exam date
                # ----------------------------------------------------
                if (
                    not exam_date_text
                    or exam_date_text == "Select Exam Date"
                ):
                    raise ValueError(
                        "Please select an Exam Date."
                    )

                if not hall_ids:
                    raise ValueError(
                        "Please select at least one hall."
                    )

                exam_date = _arrear_parse_date_header(
                    exam_date_text
                )

                if not exam_date:
                    raise ValueError(
                        "Invalid exam date."
                    )

                # ====================================================
                # FETCH ARREAR STUDENTS FOR EXAM DATE
                #
                # IMPORTANT:
                # Student subject_code is matched with
                # Timetable subject_code.
                # ====================================================

                cur.execute(
                    """
                    SELECT
                        s.id,
                        s.department,
                        s.course,
                        s.reg_no,
                        s.student_name,
                        s.subject_code,
                        s.subject_name,
                        s.batch,
                        t.subject_code AS timetable_subject_code,
                        t.subject_name AS timetable_subject_name,
                        t.subject_text

                    FROM arrear_students s

                    INNER JOIN (
                        SELECT
                            course,
                            batch,
                            exam_date,
                            subject_code,
                            MAX(subject_name) AS subject_name,
                            MAX(subject_text) AS subject_text

                        FROM arrear_timetable

                        WHERE exam_date = %s

                        GROUP BY
                            course,
                            batch,
                            exam_date,
                            subject_code
                    ) t

                        ON LOWER(TRIM(s.course))
                           = LOWER(TRIM(t.course))

                       AND LOWER(TRIM(s.batch))
                           = LOWER(TRIM(t.batch))

                       AND LOWER(TRIM(s.subject_code))
                           = LOWER(TRIM(t.subject_code))

                    ORDER BY
                        s.course,
                        s.batch,
                        s.reg_no
                    """,
                    (exam_date,)
                )

                arrear_rows = cur.fetchall()

                if not arrear_rows:
                    raise ValueError(
                        "No Arrear students found for the selected Exam Date."
                    )

                # ====================================================
                # FETCH SELECTED HALLS
                # ====================================================

                placeholders = ",".join(
                    ["%s"] * len(hall_ids)
                )

                cur.execute(
                    f"""
                    SELECT
                        id,
                        hall_name,
                        seating_capacity
                    FROM halls
                    WHERE id IN ({placeholders})
                    ORDER BY hall_name
                    """,
                    tuple(hall_ids)
                )

                selected_halls = cur.fetchall()

                if len(selected_halls) != len(hall_ids):
                    raise ValueError(
                        "One or more selected halls were not found."
                    )

                # ====================================================
                # VALIDATE FACULTY
                # ====================================================

                faculty_placeholders = ",".join(
                    ["%s"] * len(faculty_by_hall)
                )

                cur.execute(
                    f"""
                    SELECT
                        id,
                        faculty_code,
                        faculty_name
                    FROM faculty_details
                    WHERE id IN ({faculty_placeholders})
                    """,
                    tuple(faculty_by_hall.values())
                )

                faculty_rows = cur.fetchall()

                faculty_map = {
                    int(f["id"]): f
                    for f in faculty_rows
                }

                if len(faculty_map) != len(faculty_by_hall):
                    raise ValueError(
                        "One or more selected faculty members were not found."
                    )

                # Same faculty cannot be assigned to multiple halls
                if (
                    len(set(faculty_by_hall.values()))
                    != len(faculty_by_hall)
                ):
                    raise ValueError(
                        "The same faculty cannot be assigned "
                        "to more than one selected Arrear hall."
                    )

                # ====================================================
                # ARREAR IS FIRST OCCUPANT OF SHARED HALL
                # ====================================================
                #
                # If Regular allotment already exists for the same
                # exam date and selected hall, remove only those
                # Regular rows.
                #
                # Arrear students occupy the first physical seats.
                #
                # Example:
                #
                # Hall capacity = 34
                # Arrear students = 10
                #
                # Arrear -> seats 1 to 10
                # Regular -> remaining 24 seats
                #
                # ====================================================

                regular_cleanup_placeholders = ",".join(
                    ["%s"] * len(hall_ids)
                )

                cur.execute(
                    f"""
                    DELETE a
                    FROM allotments a

                    INNER JOIN exam_timetable e
                        ON e.id = a.exam_id

                    WHERE e.exam_date = %s
                      AND e.course = 'HALL ALLOTMENT'
                      AND e.year = 'ALL'
                      AND a.hall_id IN
                          ({regular_cleanup_placeholders})
                    """,
                    (exam_date, *hall_ids)
                )

                # ====================================================
                # DELETE PREVIOUS ARREAR GENERATION
                # ====================================================

                cur.execute(
                    f"""
                    DELETE FROM arrear_allotments
                    WHERE exam_date = %s
                      AND hall_id IN ({placeholders})
                    """,
                    (exam_date, *hall_ids)
                )

                # ====================================================
                # INITIAL HALL CAPACITY
                # ====================================================

                capacity_left = {
                    hall["id"]: max(
                        0,
                        int(hall["seating_capacity"] or 0)
                    )
                    for hall in selected_halls
                }

                total_available = sum(
                    capacity_left.values()
                )

                if total_available < len(arrear_rows):
                    raise ValueError(
                        f"Not enough seats in selected halls. "
                        f"Arrear students: {len(arrear_rows)}, "
                        f"available seats: {total_available}."
                    )

                # ====================================================
                # ALLOT ARREAR STUDENTS
                # ====================================================

                hall_index = 0
                seat_no = 1

                for student in arrear_rows:

                    # Move to next hall when current hall is full
                    while (
                        hall_index < len(selected_halls)
                        and capacity_left[
                            selected_halls[hall_index]["id"]
                        ] <= 0
                    ):
                        hall_index += 1
                        seat_no = 1

                    if hall_index >= len(selected_halls):
                        raise ValueError(
                            "Selected hall capacity is insufficient."
                        )

                    hall_id = selected_halls[
                        hall_index
                    ]["id"]

                    # ------------------------------------------------
                    # ARREAR FIRST
                    #
                    # Arrear students occupy:
                    # 1, 2, 3, ... N
                    # ------------------------------------------------

                    cur.execute(
                        """
                        INSERT INTO arrear_allotments
                        (
                            student_id,
                            hall_id,
                            exam_date,
                            seat_number,
                            row_no,
                            column_no,
                            side,
                            faculty_id
                        )
                        VALUES
                        (
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s
                        )
                        """,
                        (
                            student["id"],
                            hall_id,
                            exam_date,
                            seat_no,
                            None,
                            None,
                            "CENTER",
                            faculty_by_hall[hall_id]
                        )
                    )

                    capacity_left[hall_id] -= 1
                    seat_no += 1

                # ====================================================
                # COMMIT
                # ====================================================

                db.commit()

                message = (
                    "Arrear Hall Allotment generated successfully. "
                    f"{len(arrear_rows)} unique students allotted to "
                    f"{len(selected_halls)} hall(s)."
                )

            # ========================================================
            # ARREAR STUDENT / TIMETABLE UPLOAD
            # ========================================================
            elif action in {
                "upload_student",
                "upload_timetable"
            }:

                if not upload or not upload.filename:
                    raise ValueError(
                        "Please select an Excel file."
                    )

                if not upload.filename.lower().endswith(
                    (".xlsx", ".xls")
                ):
                    raise ValueError(
                        "Please upload an Excel file (.xlsx or .xls)."
                    )

                # ----------------------------------------------------
                # Read Excel
                # ----------------------------------------------------

                df = pd.read_excel(upload)

                df.columns = [
                    str(c).strip()
                    for c in df.columns
                ]

                # ====================================================
                # ARREAR STUDENT DATABASE UPLOAD
                # ====================================================

                if action == "upload_student":

                    aliases = {
                        "department": [
                            "DEPARTMENT",
                            "DEPT"
                        ],

                        "course": [
                            "COURSE"
                        ],

                        "reg_no": [
                            "REG NO",
                            "REGNO",
                            "REGISTER NUMBER",
                            "REGISTER NO"
                        ],

                        "student_name": [
                            "STUDENT NAME",
                            "NAME"
                        ],

                        "subject_code": [
                            "SUBJECT CODE",
                            "SUB CODE",
                            "SUBJECT CODE+SUBJECT"
                        ],

                        "batch": [
                            "BATCH"
                        ],
                    }

                    # ------------------------------------------------
                    # Find Excel column
                    # ------------------------------------------------

                    def find_col(options):

                        normalized = {
                            _arrear_norm(c).replace(" ", ""): c
                            for c in df.columns
                        }

                        for opt in options:

                            key = (
                                _arrear_norm(opt)
                                .replace(" ", "")
                            )

                            if key in normalized:
                                return normalized[key]

                        return None

                    cols = {
                        k: find_col(v)
                        for k, v in aliases.items()
                    }

                    # ------------------------------------------------
                    # Check missing columns
                    # ------------------------------------------------

                    missing = [
                        k
                        for k, v in cols.items()
                        if not v
                    ]

                    if missing:
                        raise ValueError(
                            "Arrear DB missing columns: "
                            + ", ".join(missing)
                        )

                    # ------------------------------------------------
                    # Clear old student database
                    # ------------------------------------------------

                    cur.execute(
                        "DELETE FROM arrear_students"
                    )

                    count = 0

                    # =================================================
                    # INSERT STUDENTS
                    # =================================================

                    for _, row in df.iterrows():

                        department = str(
                            row[cols["department"]]
                        ).strip()

                        course = str(
                            row[cols["course"]]
                        ).strip()

                        reg_no = str(
                            row[cols["reg_no"]]
                        ).strip()

                        student_name = str(
                            row[cols["student_name"]]
                        ).strip()

                        subject_code = str(
                            row[cols["subject_code"]]
                        ).strip()

                        batch = str(
                            row[cols["batch"]]
                        ).strip()

                        # ------------------------------------------------
                        # Skip incomplete rows
                        # ------------------------------------------------

                        if (
                            not department
                            or department.casefold() == "nan"

                            or not course
                            or course.casefold() == "nan"

                            or not reg_no
                            or reg_no.casefold() == "nan"

                            or not student_name
                            or student_name.casefold() == "nan"

                            or not subject_code
                            or subject_code.casefold() == "nan"

                            or not batch
                            or batch.casefold() == "nan"
                        ):
                            continue

                        # ------------------------------------------------
                        # IMPORTANT
                        #
                        # Database contains:
                        #   subject_code
                        #   subject_name
                        #
                        # Student Excel contains subject code.
                        #
                        # Keep subject_name = subject_code here because
                        # existing student-side Arrear logic may use it.
                        # The actual Hall Allotment matching is now done
                        # using subject_code.
                        # ------------------------------------------------

                        cur.execute(
                            """
                            INSERT INTO arrear_students
                            (
                                department,
                                course,
                                reg_no,
                                student_name,
                                subject_code,
                                subject_name,
                                batch
                            )
                            VALUES
                            (
                                %s,
                                %s,
                                %s,
                                %s,
                                %s,
                                %s,
                                %s
                            )
                            """,
                            (
                                department,
                                course,
                                reg_no,
                                student_name,
                                subject_code,
                                subject_code,
                                batch
                            )
                        )

                        count += 1

                    # ------------------------------------------------
                    # Commit student upload
                    # ------------------------------------------------

                    db.commit()

                    message = (
                        "Arrear Student DB uploaded successfully. "
                        f"{count} records loaded."
                    )

                # ====================================================
                # ARREAR TIMETABLE UPLOAD
                # ====================================================

                else:

                    if len(df.columns) < 3:
                        raise ValueError(
                            "Arrear Time Table must contain "
                            "Course, Batch and at least one date column."
                        )

                    # First two columns
                    course_col = df.columns[0]
                    batch_col = df.columns[1]

                    # ------------------------------------------------
                    # Clear old timetable
                    # ------------------------------------------------

                    cur.execute(
                        "DELETE FROM arrear_timetable"
                    )

                    count = 0

                    # =================================================
                    # DATE COLUMNS
                    # =================================================

                    for date_col in df.columns[2:]:

                        exam_date = _arrear_parse_date_header(
                            date_col
                        )

                        if not exam_date:
                            continue

                        # ---------------------------------------------
                        # Each course/batch row
                        # ---------------------------------------------

                        for _, row in df.iterrows():

                            course = str(
                                row[course_col]
                            ).strip()

                            batch = str(
                                row[batch_col]
                            ).strip()

                            subject_text = str(
                                row[date_col]
                            ).strip()

                            if (
                                not course
                                or course.casefold() == "nan"

                                or not batch
                                or batch.casefold() == "nan"

                                or not subject_text
                                or subject_text.casefold() == "nan"
                            ):
                                continue

                            # -----------------------------------------
                            # Example:
                            #
                            # 98B - CORE:COMPUTER APPLICATION
                            #
                            # code = 98B
                            # name = CORE:COMPUTER APPLICATION
                            # -----------------------------------------

                            code, name = _arrear_subject_parts(
                                subject_text
                            )

                            # ------------------------------------------------
                            # IMPORTANT FIX
                            #
                            # arrear_timetable.subject_code is mandatory.
                            # So insert code into subject_code.
                            # ------------------------------------------------

                            cur.execute(
                                """
                                INSERT INTO arrear_timetable
                                (
                                    course,
                                    batch,
                                    exam_date,
                                    subject_code,
                                    subject_name,
                                    subject_text
                                )
                                VALUES
                                (
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    %s
                                )
                                """,
                                (
                                    course,
                                    batch,
                                    exam_date,
                                    code,
                                    name,
                                    subject_text
                                )
                            )

                            count += 1

                    # ------------------------------------------------
                    # Commit timetable upload
                    # ------------------------------------------------

                    db.commit()

                    message = (
                        "Arrear Time Table uploaded successfully. "
                        f"{count} exam entries loaded."
                    )

        # ============================================================
        # PAGE DATA
        # ============================================================

        # ------------------------------------------------------------
        # Student count
        # ------------------------------------------------------------

        cur.execute(
            """
            SELECT COUNT(*) AS total
            FROM arrear_students
            """
        )

        student_count = cur.fetchone()["total"]

        # ------------------------------------------------------------
        # Timetable count
        # ------------------------------------------------------------

        cur.execute(
            """
            SELECT COUNT(*) AS total
            FROM arrear_timetable
            """
        )

        timetable_count = cur.fetchone()["total"]

        # ------------------------------------------------------------
        # Exam dates
        # ------------------------------------------------------------

        cur.execute(
            """
            SELECT DISTINCT exam_date
            FROM arrear_timetable
            ORDER BY exam_date
            """
        )

        exam_dates = cur.fetchall()

        # ------------------------------------------------------------
        # Halls
        # ------------------------------------------------------------

        cur.execute(
            """
            SELECT
                id,
                hall_name,
                seating_capacity,
                floor
            FROM halls
            ORDER BY hall_name
            """
        )

        halls = cur.fetchall()

        # ------------------------------------------------------------
        # Faculty
        # ------------------------------------------------------------

        cur.execute(
            """
            SELECT
                id,
                faculty_code,
                faculty_name,
                department,
                course,
                year
            FROM faculty_details
            ORDER BY
                faculty_name,
                faculty_code
            """
        )

        faculties = cur.fetchall()

        # ============================================================
        # RENDER PAGE
        # ============================================================

        return render_template(
            "arrear_hall_allotment.html",
            message=message,
            error=error,
            student_count=student_count,
            timetable_count=timetable_count,
            exam_dates=exam_dates,
            halls=halls,
            faculties=faculties
        )

    # ================================================================
    # ERROR HANDLING
    # ================================================================

    except Exception as e:

        if db:
            try:
                db.rollback()
            except Exception:
                pass

        return render_template(
            "arrear_hall_allotment.html",
            message=message,
            error=str(e),
            student_count=0,
            timetable_count=0,
            exam_dates=[],
            halls=[],
            faculties=[]
        )

    # ================================================================
    # CLOSE DATABASE
    # ================================================================

    finally:

        if cur:
            cur.close()

        if db:
            db.close()
# ==================================================
# DELETE TOTAL ARREAR HALL ALLOTMENT
# ==================================================

@app.route("/delete-arrear-timetable", methods=["POST", "GET"])
def delete_arrear_timetable():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    db = get_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM arrear_timetable")
        deleted_count = cursor.rowcount
        db.commit()
        return redirect(url_for(
            "arrear_hall_allotment",
            success=f"Arrear Timetable deleted successfully. {deleted_count} records deleted."
        ))
    except Exception as e:
        db.rollback()
        return redirect(url_for("arrear_hall_allotment", error=f"Delete Timetable Error: {str(e)}"))
    finally:
        cursor.close()
        db.close()


@app.route("/delete-arrear-student-database", methods=["POST", "GET"])
def delete_arrear_student_database():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    db = get_db_connection()
    cursor = db.cursor()
    try:
        # Remove allocations first so no orphaned Arrear allotment records remain.
        cursor.execute("DELETE FROM arrear_allotments")
        cursor.execute("DELETE FROM arrear_students")
        deleted_count = cursor.rowcount
        db.commit()
        return redirect(url_for(
            "arrear_hall_allotment",
            success=f"Arrear Student Database deleted successfully. {deleted_count} student records deleted."
        ))
    except Exception as e:
        db.rollback()
        return redirect(url_for("arrear_hall_allotment", error=f"Delete Student DB Error: {str(e)}"))
    finally:
        cursor.close()
        db.close()


# ==================================================
# DELETE TOTAL ARREAR HALL ALLOTMENT
# ==================================================

@app.route("/delete-total-arrear-hall-allotment", methods=["POST", "GET"])
def delete_total_arrear_hall_allotment():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    db = get_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM arrear_allotments")
        deleted_count = cursor.rowcount
        db.commit()
        return redirect(url_for(
            "arrear_hall_allotment",
            success=f"Total Arrear Hall Allotment deleted successfully. {deleted_count} records deleted."
        ))
    except Exception as e:
        db.rollback()
        return redirect(url_for("arrear_hall_allotment", error=f"Delete Error: {str(e)}"))
    finally:
        cursor.close()
        db.close()

# ==================================================
# ARREAR PDFS - 3 REPORTS
# ==================================================

def _arrear_pdf_date(exam_date=None):
    db = get_db_connection()
    cur = db.cursor(dictionary=True, buffered=True)
    try:
        if exam_date:
            d = _arrear_parse_date_header(exam_date)
            if not d:
                raise ValueError("Invalid Arrear exam date.")
            return d
        cur.execute("SELECT MAX(exam_date) AS exam_date FROM arrear_allotments")
        row = cur.fetchone()
        if row and row.get("exam_date"):
            return row["exam_date"]
        cur.execute("SELECT MIN(exam_date) AS exam_date FROM arrear_timetable")
        row = cur.fetchone()
        return row.get("exam_date") if row else None
    finally:
        cur.close(); db.close()


def _build_arrear_hall_allotment_pdf(exam_date=None):
    """Arrear Hall Allotment PDF matching the uploaded Admin Hall Allotment format."""
    d = _arrear_pdf_date(exam_date)
    if not d:
        raise ValueError("No Arrear allotment available.")

    db = get_db_connection()
    cur = db.cursor(dictionary=True, buffered=True)
    try:
        cur.execute("""
            SELECT aa.hall_id, h.hall_name,
                   s.course, s.batch,
                   s.reg_no,
                   s.subject_name,
                   COALESCE(t.subject_name, t.subject_text, '') AS timetable_subject_name
            FROM arrear_allotments aa
            JOIN halls h ON h.id = aa.hall_id
            JOIN arrear_students s ON s.id = aa.student_id
            LEFT JOIN (
                SELECT course, batch, exam_date,
                       MAX(subject_name) AS subject_name,
                       MAX(subject_text) AS subject_text
                FROM arrear_timetable
                WHERE exam_date = %s
                GROUP BY course, batch, exam_date, subject_name
            ) t ON LOWER(TRIM(t.course)) = LOWER(TRIM(s.course))
              AND LOWER(TRIM(t.batch)) = LOWER(TRIM(s.batch))
              AND t.exam_date = aa.exam_date
              AND LOWER(TRIM(t.subject_name)) = LOWER(TRIM(s.subject_name))
            WHERE aa.exam_date = %s
            ORDER BY aa.hall_id, s.course, s.batch, aa.seat_number, s.reg_no
        """, (d, d))
        rows = cur.fetchall()
        if not rows:
            raise ValueError(f"No Arrear allotment found for {d}.")

        # Same report structure as the uploaded regular Hall Allotment PDF:
        # college heading, examination cell, title, date/session/time/course-year,
        # followed by Hall No / Course / Year / Regno From / Regno To.
        path = os.path.join(UPLOAD_FOLDER, f"Arrear_Hall_Allotment_{d}.pdf")
        pdf = canvas.Canvas(path, pagesize=A4)
        width, height = A4

        # Group each hall + course + batch and calculate actual reg range.
        groups = []
        seen = set()
        for r in rows:
            key = (r['hall_id'], str(r['course']).strip(), str(r['batch']).strip())
            if key in seen:
                continue
            seen.add(key)
            regs = [str(x['reg_no']) for x in rows
                    if x['hall_id'] == r['hall_id']
                    and str(x['course']).strip() == str(r['course']).strip()
                    and str(x['batch']).strip() == str(r['batch']).strip()]
            groups.append({
                'hall_name': r['hall_name'],
                'course': r['course'],
                'batch': r['batch'],
                'reg_from': regs[0] if regs else '-',
                'reg_to': regs[-1] if regs else '-',
            })

        course_years = []
        seen_cy = set()
        for r in rows:
            text = f"{str(r['course']).strip()} - {str(r['batch']).strip()}"
            if text.lower() not in seen_cy:
                seen_cy.add(text.lower())
                course_years.append(text)

        # Header matching uploaded PDF.
        pdf.setFont('Helvetica-Bold', 14)
        pdf.drawCentredString(width/2, height-42, 'SHREE VENKATESWARA ARTS AND SCIENCE COLLEGE')
        pdf.setFont('Helvetica-Bold', 12)
        pdf.drawCentredString(width/2, height-60, 'COLLEGE EXAMINATION CELL')
        pdf.setFont('Helvetica-Bold', 12)
        pdf.drawCentredString(width/2, height-78, 'HALL ALLOTMENT')

        pdf.setFont('Helvetica', 9.5)
        y = height - 105
        pdf.drawString(45, y, f'Exam Date : {d}')
        y -= 14

        # Keep the same header positions. Session/time are shown only when
        # they can be obtained from the regular exam record for this date.
        session_text = ''
        start_text = ''
        end_text = ''
        try:
            cur.execute("""
                SELECT session, start_time, end_time
                FROM exam_timetable
                WHERE course = 'HALL ALLOTMENT'
                  AND year = 'ALL'
                  AND exam_date = %s
                ORDER BY id DESC
                LIMIT 1
            """, (d,))
            meta = cur.fetchone()
            if meta:
                session_text = str(meta.get('session') or '').strip()
                start_text = _format_display_time(meta.get('start_time'))
                end_text = _format_display_time(meta.get('end_time'))
        except Exception:
            pass

        if session_text:
            pdf.drawString(45, y, f'Session : {session_text}')
            y -= 14
        if start_text or end_text:
            pdf.drawString(45, y, f'Time : {start_text} - {end_text}')
            y -= 14

        pdf.drawString(45, y, f'Course / Year : {", ".join(course_years)}')
        y -= 22

        # Table: Hall No. | Course | Year | Regno From | Regno To
        col_x = [45, 145, 245, 345, 455]
        headers = ['Hall No.', 'Course', 'Year', 'Regno From', 'Regno To']
        pdf.setFont('Helvetica-Bold', 8.5)
        for x, label in zip(col_x, headers):
            pdf.drawString(x, y, label)
        y -= 14
        pdf.setFont('Helvetica', 8.2)

        for g in groups:
            if y < 42:
                pdf.showPage()
                pdf.setFont('Helvetica-Bold', 14)
                pdf.drawCentredString(width/2, height-42, 'SHREE VENKATESWARA ARTS AND SCIENCE COLLEGE')
                pdf.setFont('Helvetica-Bold', 12)
                pdf.drawCentredString(width/2, height-60, 'COLLEGE EXAMINATION CELL')
                pdf.drawCentredString(width/2, height-78, 'HALL ALLOTMENT')
                pdf.setFont('Helvetica', 9.5)
                y = height - 105
                pdf.drawString(45, y, f'Exam Date : {d}')
                y -= 14
                if session_text:
                    pdf.drawString(45, y, f'Session : {session_text}')
                    y -= 14
                if start_text or end_text:
                    pdf.drawString(45, y, f'Time : {start_text} - {end_text}')
                    y -= 14
                pdf.drawString(45, y, f'Course / Year : {", ".join(course_years)}')
                y -= 22
                pdf.setFont('Helvetica-Bold', 8.5)
                for x, label in zip(col_x, headers):
                    pdf.drawString(x, y, label)
                y -= 14
                pdf.setFont('Helvetica', 8.2)

            values = [g['hall_name'], g['course'], g['batch'], g['reg_from'], g['reg_to']]
            for x, value in zip(col_x, values):
                pdf.drawString(x, y, str(value))
            y -= 16

        pdf.setFont('Helvetica', 7.5)
        pdf.drawCentredString(width/2, 20, 'College Examination Cell - Hall Allotment')
        pdf.save()
        return path
    finally:
        cur.close()
        db.close()


def _build_arrear_seating_pdf(exam_date=None):
    """Arrear seating PDF matching the uploaded Admin Seating Arrangement PDF."""
    from reportlab.lib.pagesizes import landscape
    d = _arrear_pdf_date(exam_date)
    if not d:
        raise ValueError('No Arrear allotment available.')

    db = get_db_connection()
    cur = db.cursor(dictionary=True, buffered=True)
    try:
        cur.execute("""
            SELECT aa.id, aa.hall_id, h.hall_name,
                   s.reg_no, s.course, s.batch,
                   s.subject_name,
                   COALESCE(t.subject_name, t.subject_text, '') AS subject,
                   aa.seat_number, aa.side
            FROM arrear_allotments aa
            JOIN halls h ON h.id = aa.hall_id
            JOIN arrear_students s ON s.id = aa.student_id
            LEFT JOIN (
                SELECT course, batch, exam_date,
                       MAX(subject_name) AS subject_name,
                       MAX(subject_text) AS subject_text
                FROM arrear_timetable
                WHERE exam_date = %s
                GROUP BY course, batch, exam_date, subject_name
            ) t ON LOWER(TRIM(t.course)) = LOWER(TRIM(s.course))
              AND LOWER(TRIM(t.batch)) = LOWER(TRIM(s.batch))
              AND t.exam_date = aa.exam_date
              AND LOWER(TRIM(t.subject_name)) = LOWER(TRIM(s.subject_name))
            WHERE aa.exam_date = %s
            ORDER BY aa.hall_id, aa.seat_number, s.reg_no
        """, (d, d))
        rows = cur.fetchall()
        if not rows:
            raise ValueError(f'No Arrear seating found for {d}.')

        path = os.path.join(UPLOAD_FOLDER, f'Arrear_Student_Seating_{d}.pdf')
        pdf = canvas.Canvas(path, pagesize=landscape(A4))
        width, height = landscape(A4)

        halls = {}
        for r in rows:
            halls.setdefault(r['hall_id'], []).append(r)

        for hall_index, hall_rows in enumerate(halls.values()):
            first = hall_rows[0]
            if hall_index:
                pdf.showPage()

            # Exact overall header arrangement from the uploaded seating PDF.
            pdf.setFont('Helvetica-Bold', 15)
            pdf.drawCentredString(width/2, height-35, 'HALL ALLOTMENT')
            pdf.setFont('Helvetica-Bold', 9)
            pdf.drawString(35, height-57, f"HALL NO: {first['hall_name']}")

            course_years = []
            seen = set()
            for r in hall_rows:
                text = f"{str(r['course']).strip()} - {str(r['batch']).strip()}"
                if text.lower() not in seen:
                    seen.add(text.lower())
                    course_years.append(text)
            pdf.setFont('Helvetica', 8)
            pdf.drawString(35, height-80, f"Course / Year: {', '.join(course_years)}")

            # 6 vertical blocks: S.No | Reg. No, matching the supplied PDF.
            seats = sorted(hall_rows, key=lambda r: (r.get('seat_number') or 0, str(r.get('reg_no') or '')))
            total = len(seats)
            blocks = 6
            rows_per_block = (total + blocks - 1) // blocks
            # The supplied 34-seat layout uses 6 rows in each block.
            if total <= 34:
                rows_per_block = 6

            # Arrange seats sequentially down each vertical block.
            block_data = []
            for b in range(blocks):
                start_i = b * rows_per_block
                block_data.append(seats[start_i:start_i + rows_per_block])

            left = 15
            table_top = height - 105
            table_bottom = 205
            table_h = table_top - table_bottom
            rh = table_h / rows_per_block
            total_table_w = width - 30
            pair_w = total_table_w / blocks
            sno_w = pair_w * 0.46
            reg_w = pair_w - sno_w

            pdf.setFont('Helvetica-Bold', 7.5)
            for b in range(blocks):
                x = left + b * pair_w
                pdf.rect(x, table_bottom, sno_w, table_h)
                pdf.rect(x+sno_w, table_bottom, reg_w, table_h)
                pdf.drawCentredString(x+sno_w/2, table_top-11, 'S.No')
                pdf.drawCentredString(x+sno_w+reg_w/2, table_top-11, 'Reg. No')
                # horizontal row lines
                for rr in range(1, rows_per_block+1):
                    yy = table_top - rr*rh
                    pdf.line(x, yy, x+pair_w, yy)

            pdf.setFont('Helvetica', 7.2)
            for b, block in enumerate(block_data):
                x = left + b * pair_w
                for rr in range(rows_per_block):
                    yy = table_top - (rr+1)*rh
                    if rr < len(block):
                        r = block[rr]
                        pdf.drawCentredString(x+sno_w/2, yy+rh/2-2, str(rr+1 + b*rows_per_block))
                        pdf.drawCentredString(x+sno_w+reg_w/2, yy+rh/2-2, str(r['reg_no']))

            # Course-wise subject summary exactly below the seating table.
            summary_y = 185
            pdf.setFont('Helvetica-Bold', 7.5)
            summary_cols = [15, 220, 315, 610, width-15]
            summary_headers = ['Course', 'Sub.Code', 'Subject', 'Strength']
            for i, htxt in enumerate(summary_headers):
                pdf.rect(summary_cols[i], summary_y-28, summary_cols[i+1]-summary_cols[i], 28)
                pdf.drawCentredString((summary_cols[i]+summary_cols[i+1])/2, summary_y-18, htxt)

            # Group by course/batch/subject code.
            summary = []
            seen_sum = set()
            for r in hall_rows:
                key = (str(r['course']).strip(), str(r['batch']).strip(), str(r['subject_name']).strip())
                if key in seen_sum:
                    continue
                seen_sum.add(key)
                strength = sum(1 for x in hall_rows if (str(x['course']).strip(), str(x['batch']).strip(), str(x['subject_name']).strip()) == key)
                summary.append((r['course'], r['batch'], r['subject_name'], r['subject'] or '-', strength))

            sy = summary_y - 28
            pdf.setFont('Helvetica', 7)
            for course, batch, code, subject, strength in summary:
                label = f'{course} - {batch}'
                vals = [label, code, subject, strength]
                for i, value in enumerate(vals):
                    x1, x2 = summary_cols[i], summary_cols[i+1]
                    pdf.rect(x1, sy-24, x2-x1, 24)
                    pdf.drawCentredString((x1+x2)/2, sy-15, str(value)[:90])
                sy -= 24

            pdf.setFont('Helvetica', 7)
            pdf.drawCentredString(width/2, 20, 'College Examination Cell - Hall Allotment')

        pdf.save()
        return path
    finally:
        cur.close()
        db.close()


def _build_arrear_signature_pdf(exam_date=None):
    """Arrear signature sheet matching the supplied Hall Faculty Signature Sheet."""
    d = _arrear_pdf_date(exam_date)
    if not d:
        raise ValueError('No Arrear allotment available.')

    db = get_db_connection()
    cur = db.cursor(dictionary=True, buffered=True)
    try:
        # Prefer faculty selected specifically for Arrear allotment.
        cur.execute("""
            SELECT aa.hall_id, h.hall_name,
                   COALESCE(MAX(fa.faculty_name), MAX(rf.faculty_name), 'Not Assigned') AS faculty_name,
                   COALESCE(MAX(ra.session), '') AS session_name,
                   COALESCE(MAX(e.start_time), NULL) AS start_time,
                   COALESCE(MAX(e.end_time), NULL) AS end_time
            FROM arrear_allotments aa
            JOIN halls h ON h.id = aa.hall_id
            LEFT JOIN faculty_details fa ON fa.id = aa.faculty_id
            LEFT JOIN allotments ra ON ra.hall_id = aa.hall_id
            LEFT JOIN faculty_details rf ON rf.id = ra.faculty_id
            LEFT JOIN exam_timetable e ON e.id = ra.exam_id
            WHERE aa.exam_date = %s
            GROUP BY aa.hall_id, h.hall_name
            ORDER BY h.hall_name
        """, (d,))
        rows = cur.fetchall()
        if not rows:
            raise ValueError(f'No Arrear hall/faculty data found for {d}.')

        path = os.path.join(UPLOAD_FOLDER, f'Arrear_Hall_Faculty_Signature_{d}.pdf')
        pdf = canvas.Canvas(path, pagesize=A4)
        width, height = A4

        pdf.setFont('Helvetica-Bold', 15)
        pdf.drawCentredString(width/2, height-45, 'HALL FACULTY SIGNATURE SHEET')
        pdf.setFont('Helvetica', 9)
        pdf.drawString(45, height-68, f'Date: {d}')

        # Use session/time if available from the hall assignment.
        session_name = next((str(r.get('session_name') or '').strip() for r in rows if r.get('session_name')), '')
        start_time = next((r.get('start_time') for r in rows if r.get('start_time') is not None), None)
        end_time = next((r.get('end_time') for r in rows if r.get('end_time') is not None), None)
        if session_name:
            pdf.drawString(45, height-88, f'Session: {session_name}')
        if start_time is not None or end_time is not None:
            pdf.drawString(45, height-108, f'Time: {_format_display_time(start_time)} - {_format_display_time(end_time)}')

        # Same four-column structure as supplied signature sheet.
        x0 = 45
        y = height - 145
        rh = 30
        widths = [45, 130, 210, 125]
        headers = ['S.No', 'Hall Name', 'Faculty Name', 'Signature']
        pdf.setFont('Helvetica-Bold', 9)
        x = x0
        for htxt, w in zip(headers, widths):
            pdf.rect(x, y-rh, w, rh)
            pdf.drawCentredString(x+w/2, y-19, htxt)
            x += w
        y -= rh

        pdf.setFont('Helvetica', 9)
        for i, r in enumerate(rows, 1):
            if y < 50:
                pdf.showPage()
                pdf.setFont('Helvetica-Bold', 15)
                pdf.drawCentredString(width/2, height-45, 'HALL FACULTY SIGNATURE SHEET')
                pdf.setFont('Helvetica', 9)
                pdf.drawString(45, height-68, f'Date: {d}')
                y = height - 95
                pdf.setFont('Helvetica-Bold', 9)
                x = x0
                for htxt, w in zip(headers, widths):
                    pdf.rect(x, y-rh, w, rh)
                    pdf.drawCentredString(x+w/2, y-19, htxt)
                    x += w
                y -= rh
                pdf.setFont('Helvetica', 9)

            x = x0
            for _, w in zip(headers, widths):
                pdf.rect(x, y-rh, w, rh)
                x += w
            pdf.drawCentredString(x0+22.5, y-19, str(i))
            pdf.drawString(x0+50, y-19, str(r['hall_name']))
            pdf.drawString(x0+180, y-19, str(r['faculty_name']))
            y -= rh

        pdf.save()
        return path
    finally:
        cur.close()
        db.close()


@app.route('/arrear-hall-allotment-pdf')
def arrear_hall_allotment_pdf():
    try:
        path=_build_arrear_hall_allotment_pdf(request.args.get('exam_date'))
        return send_from_directory(UPLOAD_FOLDER,os.path.basename(path),as_attachment=True)
    except Exception as e: return 'Arrear Hall Allotment PDF Error: '+str(e)

@app.route('/arrear-student-seating-pdf')
def arrear_student_seating_pdf():
    try:
        path=_build_arrear_seating_pdf(request.args.get('exam_date'))
        return send_from_directory(UPLOAD_FOLDER,os.path.basename(path),as_attachment=True)
    except Exception as e: return 'Arrear Seating PDF Error: '+str(e)

@app.route('/arrear-hall-faculty-signature-pdf')
def arrear_hall_faculty_signature_pdf():
    try:
        path=_build_arrear_signature_pdf(request.args.get('exam_date'))
        return send_from_directory(UPLOAD_FOLDER,os.path.basename(path),as_attachment=True)
    except Exception as e: return 'Arrear Signature PDF Error: '+str(e)

# ==================================================
# RUN APPLICATION
# ==================================================

if __name__ == "__main__":

    app.run(
        app.run(host="0.0.0.0", port=5000, debug=True),
        host="127.0.0.1",
        port=5000
    )
    
