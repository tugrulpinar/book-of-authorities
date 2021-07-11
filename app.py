from flask import Flask, redirect, render_template, request
from flask_session import Session
from helpers import apology
from tempfile import mkdtemp
from rq import Queue, Retry, queue
from worker import conn
from brain import *

# Configure application
app = Flask(__name__)
q = Queue(connection=conn)


# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    response.headers['Cache-Control'] = 'public, max-age=0'
    return response


app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SESSION_COOKIE_SECURE"] = True
# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)


def report_success(job, connection, result, *args, **kwargs):
    print("SUCCESSFUL", job)
    print("SUCCESSFUL", connection)
    print("SUCCESSFUL", result)


def report_failure(job, connection, type, value, traceback):
    print("FAILED", job)
    print("FAILED", connection)
    print("FAILED", type)
    print("FAILED", value)
    print("FAILED", traceback)


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html")


@app.errorhandler(500)
def server_error(e):
    app.logger.error(f"Server Error: {e}, route: {request.url}")
    return render_template("500.html")


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        FAILED_TO_FIND.clear()

        # get the text from the textarea
        text = request.form.get("textbox").strip()

        # ensure the user enters text
        if not text or text == "":
            return apology("Please enter text")

        email = request.form.get("email")
        if not email:
            return apology("Please enter an email")

        case_law = get_case_law(text)

        # ensure the user enters valid case law
        if not case_law:
            FAILED_TO_FIND.clear()
            return apology("Please enter a valid input")

        names, opposer = get_names_opposer(case_law)

        # ensure the user enters valid input
        if not names or not opposer:
            FAILED_TO_FIND.clear()
            return apology("Please enter valid names")

        codes_list = get_code(opposer, names, case_law)

        # ensure the user enters valid case codes
        if not codes_list:
            FAILED_TO_FIND.clear()
            return apology("Please provide the case law codes")

        clean_names = get_clean_names(names, codes_list, case_law)
        combined = list(zip(clean_names, codes_list, case_law))

        collect_job = q.enqueue(collect_files, combined,
                                email, retry=Retry(max=2))

        return render_template("submission_confirmed.html")
        # return redirect(f"/submission-confirmed/{RANDOM_NAME}")
    else:
        return render_template("index.html")


# @app.route("/submission-confirmed/<enc_name>")
# def results(enc_name):
#     return render_template("submission_confirmed.html")


if __name__ == "__main__":
    app.run(debug=True)
