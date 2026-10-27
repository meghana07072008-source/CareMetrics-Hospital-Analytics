
from datetime import date, datetime
from io import BytesIO

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import mysql.connector
import pandas as pd
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from config import DB_CONFIG

app = Flask(__name__)
CORS(app)


# --------------------------------------------------
# DATABASE CONNECTION
# --------------------------------------------------

def get_connection():
    return mysql.connector.connect(**DB_CONFIG)


def close_database(connection=None, cursor=None):
    if cursor:
        cursor.close()

    if connection and connection.is_connected():
        connection.close()


def serialize_dates(records, fields):
    for record in records:
        for field in fields:
            if record.get(field) is not None:
                record[field] = record[field].isoformat()
    return records


# --------------------------------------------------
# HOME
# --------------------------------------------------

@app.route("/")
def home():
    return jsonify({
        "message": "Hospital Patient Analysis System",
        "status": "Backend is working"
    })


# --------------------------------------------------
# DEPARTMENTS
# --------------------------------------------------

@app.route("/api/departments")
def get_departments():
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT department_id, department_name
            FROM departments
            ORDER BY department_name
        """)

        return jsonify(cursor.fetchall())

    except mysql.connector.Error:
        app.logger.exception("Department retrieval failed")
        return jsonify({"error": "Database query failed"}), 500

    finally:
        close_database(connection, cursor)


# --------------------------------------------------
# DASHBOARD SUMMARY
# --------------------------------------------------

@app.route("/api/summary")
def get_summary():
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("SELECT COUNT(*) AS total FROM patients")
        patients = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM visits")
        visits = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM departments")
        departments = cursor.fetchone()["total"]

        return jsonify({
            "total_patients": patients,
            "total_visits": visits,
            "total_departments": departments
        })

    except mysql.connector.Error:
        app.logger.exception("Dashboard summary failed")
        return jsonify({"error": "Database query failed"}), 500

    finally:
        close_database(connection, cursor)


# --------------------------------------------------
# PATIENT DIRECTORY AND SEARCH
# GET /api/patients?search=...
# --------------------------------------------------

@app.route("/api/patients", methods=["GET"])
def get_patients():
    connection = None
    cursor = None

    try:
        search = request.args.get("search", "").strip()

        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                p.patient_id,
                p.patient_name,
                p.phone_number,
                p.date_of_birth,
                p.age_band,
                p.gender,
                COUNT(v.visit_id) AS total_visits
            FROM patients p
            LEFT JOIN visits v ON p.patient_id = v.patient_id
            WHERE
                (%s = '')
                OR CAST(p.patient_id AS CHAR) LIKE %s
                OR COALESCE(p.patient_name, '') LIKE %s
                OR COALESCE(p.phone_number, '') LIKE %s
            GROUP BY
                p.patient_id,
                p.patient_name,
                p.phone_number,
                p.date_of_birth,
                p.age_band,
                p.gender
            ORDER BY p.patient_id DESC
        """, (
            search,
            f"%{search}%",
            f"%{search}%",
            f"%{search}%"
        ))

        patients = serialize_dates(
            cursor.fetchall(),
            ["date_of_birth"]
        )

        return jsonify(patients)

    except mysql.connector.Error:
        app.logger.exception("Patient directory retrieval failed")
        return jsonify({"error": "Unable to retrieve patients"}), 500

    finally:
        close_database(connection, cursor)


# --------------------------------------------------
# REGISTER A PATIENT
# POST /api/patients
# --------------------------------------------------

@app.route("/api/patients", methods=["POST"])
def add_patient():
    connection = None
    cursor = None

    try:
        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify({
                "error": "Please provide valid patient data."
            }), 400

        patient_name = data.get("patient_name")
        phone_number = data.get("phone_number")
        date_of_birth = data.get("date_of_birth")
        gender = data.get("gender")
        age_band = data.get("age_band")

        if not isinstance(patient_name, str) or not patient_name.strip():
            return jsonify({"error": "Patient name is required."}), 400

        patient_name = patient_name.strip()

        if len(patient_name) > 100:
            return jsonify({
                "error": "Patient name must be 100 characters or fewer."
            }), 400

        if phone_number is not None:
            if not isinstance(phone_number, str):
                return jsonify({"error": "Phone number must be text."}), 400

            phone_number = phone_number.strip()

            if phone_number and len(phone_number) > 20:
                return jsonify({
                    "error": "Phone number must be 20 characters or fewer."
                }), 400

            if not phone_number:
                phone_number = None

        dob = None
        calculated_age_band = None

        if date_of_birth:
            if not isinstance(date_of_birth, str):
                return jsonify({
                    "error": "Date of birth must use YYYY-MM-DD format."
                }), 400

            try:
                dob = datetime.strptime(
                    date_of_birth, "%Y-%m-%d"
                ).date()
            except ValueError:
                return jsonify({
                    "error": "Enter a valid date of birth."
                }), 400

            if dob > date.today():
                return jsonify({
                    "error": "Date of birth cannot be in the future."
                }), 400

            age = date.today().year - dob.year
            if (date.today().month, date.today().day) < (
                dob.month, dob.day
            ):
                age -= 1

            if age <= 17:
                calculated_age_band = "0-17"
            elif age <= 35:
                calculated_age_band = "18-35"
            elif age <= 60:
                calculated_age_band = "36-60"
            else:
                calculated_age_band = "60+"

        # Preserve compatibility with forms that only submit age_band.
        if calculated_age_band is None:
            if not isinstance(age_band, str) or not age_band.strip():
                return jsonify({
                    "error": "Provide a date of birth or age band."
                }), 400

            calculated_age_band = age_band.strip()

        if len(calculated_age_band) > 20:
            return jsonify({"error": "Invalid age band."}), 400

        if gender is not None:
            if not isinstance(gender, str):
                return jsonify({"error": "Gender must be text."}), 400

            gender = gender.strip() or None

            if gender and len(gender) > 20:
                return jsonify({
                    "error": "Gender must be 20 characters or fewer."
                }), 400

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            INSERT INTO patients
                (age_band, gender, patient_name, phone_number, date_of_birth)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            calculated_age_band,
            gender,
            patient_name,
            phone_number,
            dob
        ))

        new_patient_id = cursor.lastrowid
        connection.commit()

        return jsonify({
            "message": "Patient added successfully.",
            "patient_id": new_patient_id,
            "patient_name": patient_name,
            "phone_number": phone_number,
            "date_of_birth": dob.isoformat() if dob else None,
            "age_band": calculated_age_band,
            "gender": gender
        }), 201

    except mysql.connector.Error:
        if connection and connection.is_connected():
            connection.rollback()

        app.logger.exception("Unable to add patient")
        return jsonify({
            "error": "Unable to add patient. Check the database connection."
        }), 500

    finally:
        close_database(connection, cursor)


# --------------------------------------------------
# INDIVIDUAL PATIENT PROFILE AND VISIT HISTORY
# GET /api/patients/<patient_id>
# --------------------------------------------------

@app.route("/api/patients/<int:patient_id>", methods=["GET"])
def get_patient_profile(patient_id):
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                patient_id,
                patient_name,
                phone_number,
                date_of_birth,
                age_band,
                gender
            FROM patients
            WHERE patient_id = %s
        """, (patient_id,))

        patient = cursor.fetchone()

        if not patient:
            return jsonify({"error": "Patient not found."}), 404

        serialize_dates([patient], ["date_of_birth"])

        cursor.execute("""
            SELECT
                v.visit_id,
                v.visit_date,
                v.visit_type,
                d.department_id,
                d.department_name
            FROM visits v
            INNER JOIN departments d
                ON v.department_id = d.department_id
            WHERE v.patient_id = %s
            ORDER BY v.visit_date DESC, v.visit_id DESC
        """, (patient_id,))

        visits = serialize_dates(
            cursor.fetchall(),
            ["visit_date"]
        )

        department_names = sorted({
            visit["department_name"] for visit in visits
        })

        patient["total_visits"] = len(visits)
        patient["departments_visited"] = department_names
        patient["visits"] = visits

        return jsonify(patient)

    except mysql.connector.Error:
        app.logger.exception("Patient profile retrieval failed")
        return jsonify({
            "error": "Unable to retrieve patient profile."
        }), 500

    finally:
        close_database(connection, cursor)


# --------------------------------------------------
# PATIENT-SPECIFIC ANALYTICS
# GET /api/patients/<patient_id>/analysis
# --------------------------------------------------

@app.route("/api/patients/<int:patient_id>/analysis")
def patient_analysis(patient_id):
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT patient_id
            FROM patients
            WHERE patient_id = %s
        """, (patient_id,))

        if cursor.fetchone() is None:
            return jsonify({"error": "Patient not found."}), 404

        cursor.execute("""
            SELECT COUNT(*) AS total_visits
            FROM visits
            WHERE patient_id = %s
        """, (patient_id,))
        total_visits = cursor.fetchone()["total_visits"]

        cursor.execute("""
            SELECT
                d.department_name,
                COUNT(*) AS total_visits
            FROM visits v
            INNER JOIN departments d
                ON v.department_id = d.department_id
            WHERE v.patient_id = %s
            GROUP BY d.department_id, d.department_name
            ORDER BY total_visits DESC, d.department_name
        """, (patient_id,))
        department_data = cursor.fetchall()

        cursor.execute("""
            SELECT
                DATE_FORMAT(visit_date, '%Y-%m') AS visit_month,
                COUNT(*) AS total_visits
            FROM visits
            WHERE patient_id = %s
            GROUP BY DATE_FORMAT(visit_date, '%Y-%m')
            ORDER BY visit_month
        """, (patient_id,))
        monthly_data = cursor.fetchall()

        # NumPy statistics: average visits per month with recorded visits.
        monthly_counts = np.array(
            [row["total_visits"] for row in monthly_data],
            dtype=float
        )

        average_visits_per_active_month = (
            round(float(np.mean(monthly_counts)), 2)
            if monthly_counts.size else 0
        )

        return jsonify({
            "patient_id": patient_id,
            "total_visits": total_visits,
            "departments_visited": len(department_data),
            "department_breakdown": department_data,
            "monthly_trends": monthly_data,
            "average_visits_per_active_month":
                average_visits_per_active_month
        })

    except mysql.connector.Error:
        app.logger.exception("Patient analytics failed")
        return jsonify({
            "error": "Unable to analyze patient visit history."
        }), 500

    finally:
        close_database(connection, cursor)


# --------------------------------------------------
# ALL HOSPITAL VISITS
# --------------------------------------------------

@app.route("/api/visits", methods=["GET"])
def get_visits():
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                v.visit_id,
                v.visit_date,
                v.visit_type,
                p.patient_id,
                p.patient_name,
                p.age_band,
                d.department_name
            FROM visits v
            INNER JOIN patients p ON v.patient_id = p.patient_id
            INNER JOIN departments d ON v.department_id = d.department_id
            ORDER BY v.visit_date DESC, v.visit_id DESC
        """)

        records = serialize_dates(
            cursor.fetchall(),
            ["visit_date"]
        )

        return jsonify(records)

    except mysql.connector.Error:
        app.logger.exception("Visit retrieval failed")
        return jsonify({
            "error": "Unable to retrieve visit records."
        }), 500

    finally:
        close_database(connection, cursor)


# --------------------------------------------------
# REGISTER A VISIT
# --------------------------------------------------

@app.route("/api/visits", methods=["POST"])
def add_visit():
    connection = None
    cursor = None

    try:
        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify({
                "error": "Please provide valid visit data."
            }), 400

        try:
            patient_id = int(data.get("patient_id"))
            department_id = int(data.get("department_id"))
        except (TypeError, ValueError):
            return jsonify({
                "error": "Select a valid patient and department."
            }), 400

        visit_date = data.get("visit_date")
        visit_type = data.get("visit_type")

        if patient_id <= 0 or department_id <= 0:
            return jsonify({
                "error": "Patient and department selections must be valid."
            }), 400

        if not isinstance(visit_date, str):
            return jsonify({"error": "Visit date is required."}), 400

        try:
            datetime.strptime(visit_date, "%Y-%m-%d")
        except ValueError:
            return jsonify({
                "error": "Enter a valid visit date in YYYY-MM-DD format."
            }), 400

        if not isinstance(visit_type, str) or not visit_type.strip():
            return jsonify({"error": "Visit type is required."}), 400

        visit_type = visit_type.strip()

        if len(visit_type) > 50:
            return jsonify({
                "error": "Visit type must be 50 characters or fewer."
            }), 400

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            "SELECT patient_id FROM patients WHERE patient_id = %s",
            (patient_id,)
        )
        if cursor.fetchone() is None:
            return jsonify({
                "error": "Selected patient does not exist."
            }), 400

        cursor.execute(
            "SELECT department_id FROM departments WHERE department_id = %s",
            (department_id,)
        )
        if cursor.fetchone() is None:
            return jsonify({
                "error": "Selected department does not exist."
            }), 400

        cursor.execute("""
            INSERT INTO visits
                (patient_id, department_id, visit_date, visit_type)
            VALUES (%s, %s, %s, %s)
        """, (patient_id, department_id, visit_date, visit_type))

        new_visit_id = cursor.lastrowid
        connection.commit()

        return jsonify({
            "message": "Visit registered successfully.",
            "visit_id": new_visit_id
        }), 201

    except mysql.connector.Error:
        if connection and connection.is_connected():
            connection.rollback()

        app.logger.exception("Unable to register visit")
        return jsonify({
            "error": "Unable to register visit."
        }), 500

    finally:
        close_database(connection, cursor)


# --------------------------------------------------
# DEPARTMENT WORKLOAD ANALYSIS
# --------------------------------------------------

@app.route("/api/analysis/department-workload")
def department_workload():
    connection = None

    try:
        connection = get_connection()

        query = """
            SELECT
                d.department_name,
                COUNT(v.visit_id) AS total_visits
            FROM departments d
            LEFT JOIN visits v ON d.department_id = v.department_id
            GROUP BY d.department_id, d.department_name
            ORDER BY total_visits DESC
        """

        df = pd.read_sql(query, connection)
        return jsonify(df.to_dict(orient="records"))

    except Exception:
        app.logger.exception("Department workload analysis failed")
        return jsonify({
            "error": "Unable to analyze department workload."
        }), 500

    finally:
        if connection and connection.is_connected():
            connection.close()


# --------------------------------------------------
# DAILY VISIT TRENDS
# --------------------------------------------------

@app.route("/api/analysis/visit-trends")
def visit_trends():
    connection = None

    try:
        connection = get_connection()

        query = """
            SELECT visit_date, COUNT(*) AS total_visits
            FROM visits
            GROUP BY visit_date
            ORDER BY visit_date
        """

        df = pd.read_sql(query, connection)

        if df.empty:
            return jsonify({
                "daily_visits": [],
                "average_visits_per_day": 0
            })

        df["visit_date"] = pd.to_datetime(
            df["visit_date"]
        ).dt.strftime("%Y-%m-%d")

        counts = df["total_visits"].to_numpy(dtype=float)

        return jsonify({
            "daily_visits": df.to_dict(orient="records"),
            "average_visits_per_day": round(
                float(np.mean(counts)), 2
            )
        })

    except Exception:
        app.logger.exception("Visit trend analysis failed")
        return jsonify({
            "error": "Unable to analyze visit trends."
        }), 500

    finally:
        if connection and connection.is_connected():
            connection.close()


# --------------------------------------------------
# MONTHLY VISIT TRENDS
# --------------------------------------------------

@app.route("/api/analysis/monthly-trends")
def monthly_trends():
    connection = None

    try:
        connection = get_connection()

        query = """
            SELECT
                DATE_FORMAT(visit_date, '%Y-%m') AS visit_month,
                COUNT(*) AS total_visits
            FROM visits
            GROUP BY DATE_FORMAT(visit_date, '%Y-%m')
            ORDER BY visit_month
        """

        df = pd.read_sql(query, connection)
        return jsonify(df.to_dict(orient="records"))

    except Exception:
        app.logger.exception("Monthly trend analysis failed")
        return jsonify({
            "error": "Unable to analyze monthly visit trends."
        }), 500

    finally:
        if connection and connection.is_connected():
            connection.close()


# --------------------------------------------------
# AGE-BAND ANALYSIS
# --------------------------------------------------

@app.route("/api/analysis/age-bands")
def age_band_analysis():
    connection = None

    try:
        connection = get_connection()

        query = """
            SELECT age_band, COUNT(*) AS total_patients
            FROM patients
            GROUP BY age_band
            ORDER BY age_band
        """

        df = pd.read_sql(query, connection)
        return jsonify(df.to_dict(orient="records"))

    except Exception:
        app.logger.exception("Age-band analysis failed")
        return jsonify({
            "error": "Unable to analyze age bands."
        }), 500

    finally:
        if connection and connection.is_connected():
            connection.close()


# --------------------------------------------------
# DEPARTMENT WORKLOAD CHART
# --------------------------------------------------

@app.route("/api/charts/department-workload.png")
def department_workload_chart():
    connection = None
    fig = None

    try:
        connection = get_connection()

        query = """
            SELECT
                d.department_name,
                COUNT(v.visit_id) AS total_visits
            FROM departments d
            LEFT JOIN visits v ON d.department_id = v.department_id
            GROUP BY d.department_id, d.department_name
            ORDER BY total_visits DESC
        """

        df = pd.read_sql(query, connection)

        fig, ax = plt.subplots(figsize=(9, 5))
        ax.bar(df["department_name"], df["total_visits"])
        ax.set_title("Hospital Department Workload")
        ax.set_xlabel("Department")
        ax.set_ylabel("Total Visits")
        ax.tick_params(axis="x", rotation=30)
        fig.tight_layout()

        image_buffer = BytesIO()
        fig.savefig(image_buffer, format="png", dpi=120)
        image_buffer.seek(0)

        return send_file(
            image_buffer,
            mimetype="image/png",
            download_name="department-workload.png"
        )

    except Exception:
        app.logger.exception("Chart generation failed")
        return jsonify({
            "error": "Unable to generate chart."
        }), 500

    finally:
        if fig is not None:
            plt.close(fig)

        if connection and connection.is_connected():
            connection.close()


if __name__ == "__main__":
    app.run(debug=True)
