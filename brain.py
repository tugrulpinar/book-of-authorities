from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from botocore.exceptions import ClientError
from jinja2 import Environment, FileSystemLoader, PackageLoader, select_autoescape
from PyPDF2 import PdfFileMerger
from bs4 import BeautifulSoup
from selenium import webdriver
from collections import deque
from email.message import EmailMessage
import smtplib
import requests
import boto3
import io
import logging
import time
import random
import re
import os
import string


uppercase_alphabets = list(string.ascii_uppercase)
my_dict = {}

for i in range(1, 27):
    my_dict[i] = uppercase_alphabets[i-1]

try:
    aws_id = os.environ["aws_id"]
    aws_key = os.environ["aws_key"]
except Exception as e:
    print(e)

# Connect to AWS S3
s3_client = boto3.client(
    's3',
    aws_access_key_id=aws_id,
    aws_secret_access_key=aws_key)


FAILED_TO_FIND = []

# Store the bytes objects
QUEUE = deque()

RANDOM_NAME = str(random.random())[2:]


def create_tabs(number, description=""):
    try:
        canvas = Canvas(f"{number}_TAB.pdf", pagesize=LETTER)
        canvas.setFont("Times-Roman", 50)
        canvas.drawString(3.5 * inch, 7 * inch, f"TAB {number}")
        canvas.setFont("Times-Roman", 15)
        canvas.drawString(2.5 * inch, 6 * inch, f"{description}")
        canvas.bookmarkPage(f"TAB {number}")
        canvas.addOutlineEntry(f"TAB {number}", f"TAB {number}")
        data = canvas.getpdfdata()
        QUEUE.append(data)

    except Exception as e:
        print("Error with creating the tab ", e)
        return


def merge_pdf_files():
    merger = PdfFileMerger()

    if not QUEUE:
        return None

    if len(QUEUE) < 2:
        return None

    for _ in range(len(QUEUE)):
        merger.append(io.BytesIO(QUEUE.popleft()))

    filename = f"{RANDOM_NAME}_BookOfAuthorities.pdf"

    try:
        merger.write(filename)
        print("Successfully combined the pdf")
    except:
        print("Error with writing the pdf file")
        return None
    finally:
        merger.close()

    file_size = os.path.getsize(filename)
    return str(round(file_size/1000000, 1)) + " Mb"


def upload_aws_s3():
    try:
        s3_client.upload_file(f"{RANDOM_NAME}_BookOfAuthorities.pdf", "testtugo96",
                              f"{RANDOM_NAME}/BookOfAuthorities.pdf", ExtraArgs={'ACL': 'public-read'})

        os.remove(f"{RANDOM_NAME}_BookOfAuthorities.pdf")
        print("Successfully uploaded to AWS S3")
    except Exception as e:
        print("Error with uploading to AWS S3", e)
        return


def create_presigned_url(expiration=3600):
    """Generate a presigned URL to share an S3 object

    :param expiration: Time in seconds for the presigned URL to remain valid
    :return: Presigned URL as string. If error, returns None.
    """

    # Generate a presigned URL for the S3 object
    try:
        response = s3_client.generate_presigned_url('get_object',
                                                    Params={'Bucket': "testtugo96",
                                                            'Key': f"{RANDOM_NAME}/BookOfAuthorities.pdf"},
                                                    ExpiresIn=expiration)

    except ClientError as e:
        print("Error with creating a presigned url")
        logging.error(e)
        return None

    # The response contains the presigned URL
    print("Successfully created the presigned url")
    return response


def send_email(recipient, url, fails, file_size):
    user = os.environ.get("boa_user")
    pwd = os.environ.get("boa_pwd")

    msg = EmailMessage()
    msg["Subject"] = "Book of Authorities - Please Do Not Reply"
    msg["From"] = user
    msg["To"] = recipient

    msg.set_content(
        f"Hello, \n\nThanks for using our App. Please use the below url to access your file:\n\n \
        {url}\n\nPlease note that we could not find the following files: {fails} \n\nFile Size: {file_size}\n\n Have a great day!")

    try:
        file_loader = FileSystemLoader("templates")
        env = Environment(loader=file_loader,
                          autoescape=select_autoescape(['html', 'xml']))
        template = env.get_template('email_template.html')
        html = template.render(fails=fails, url=url)
        msg.add_alternative(html, subtype="html")
    except Exception as e:
        print("Error with Jinja template1")
        print(e)

    try:
        env = Environment(
            loader=PackageLoader('main', 'templates'),
            autoescape=select_autoescape(['html', 'xml'])
        )
        template = env.get_template('email_template.html')
        html = template.render(fails=fails, url=url)
        msg.add_alternative(html, subtype="html")
    except Exception as e:
        print("Error with Jinja template2")
        print(e)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(user, pwd)
            smtp.send_message(msg)
            print("Successfully sent the email to ", recipient)

    except Exception as e:
        print(str(e))
        print("Failed to send email")


def get_case_law(text):
    # split the text into arrays
    raw_list = text.strip().split("\n")
    # clean the tabs
    cleaner = [item.replace("\r", "") for item in raw_list]
    sec_cleaner = [item.replace("\t", "") for item in cleaner]

    case_law = []
    for item in sec_cleaner:
        try:
            while not item.strip()[0].isalpha():
                item = item.replace(item[0], "").strip()
            case_law.append(item)
        except:
            pass
    return case_law


def get_names_opposer(case_law):
    names = []
    opposer = []
    idx_to_remove = []

    # parse the text
    for idx, item in enumerate(case_law):
        try:
            if " v " in item.lower():
                names.append(item.lower().split(" v ")[0].title())
                opposer.append(item.lower().split(" v ")[1].title())
            elif " v. " in item:
                names.append(item.lower().split(" v. ")[0].title())
                opposer.append(item.lower().split(" v. ")[1].title())
            else:
                idx_to_remove.append(idx)
                print(f"Text is not in correct format for {item}")
        except:
            print(f"Text is not in correct format for {item}")

    counter = 0
    for item in idx_to_remove:
        # take not of the ones we cant find. We'll use it later
        FAILED_TO_FIND.append(case_law[item-counter])
        case_law.pop(item-counter)
        counter += 1

    return names, opposer


# 4 digit number + white space + some text + white space + some more numbers
def get_code(array, names, case_law):
    temp_codes_list = []
    idx_to_clean = []

    for idx, item in enumerate(array):
        try:
            # "\d{4}\s+[a-zA-Z]+\s+\d+"
            id_code = re.findall("\d+\s+\S+\s+\d+", item)
            if id_code:
                temp_codes_list.append(id_code[0])
            else:
                id_code = re.findall("\S+\d{4}\S+", item)
                temp_codes_list.append(id_code[0])
        except:
            idx_to_clean.append(idx)
            print("Cannot find the case code")

    counter = 0
    for item in idx_to_clean:
        names.pop(item-counter)
        FAILED_TO_FIND.append(case_law[item-counter])
        case_law.pop(item-counter)
        counter += 1

    return temp_codes_list


def get_clean_names(names, codes_list, case_law):
    clean_names = []
    idx_to_clean = []

    for idx, name in enumerate(names):
        if name.isalpha():
            clean_names.append(name)
        else:
            try:
                clean_names.append(re.findall(
                    "[a-zA-Z]+\s*[a-zA-Z]+\s*[a-zA-Z]+\s*[a-zA-Z]+", name)[0])
            except:
                idx_to_clean.append(idx)
                print("Problem with clean names", name)

    counter = 0
    for item in idx_to_clean:
        codes_list.pop(item-counter)
        FAILED_TO_FIND.append(case_law[item-counter])
        case_law.pop(item-counter)
        counter += 1

    return clean_names


def get_url(search_term, case_law_code):
    template = 'https://www.canlii.org/en/#search/text={}'
    url_search_term = f"{search_term}&id={case_law_code}"
    url = template.format(url_search_term)
    return url


def collect_files(combined, email):
    global browser
    browser = webdriver.Chrome()

    # define the core url
    BASE_URL = "https://www.canlii.org"

    doc_count = 0
    for name, code, case_law in combined:
        doc_count += 1
        # create the url
        url = get_url(name, code)
        try:
            browser.get(url)
            browser.implicitly_wait(20)
            time.sleep(2)

            # parse the HTML content
            parsed_page = BeautifulSoup(browser.page_source, "html.parser")
            entries = parsed_page.find_all("div", {"class": "title"})
            print(f"Parsing CANLII for {case_law}")

            link_url = [item.a.get("href") for item in entries]
            second_link = link_url[0]
        except:
            print("Search did not match any documents")
            FAILED_TO_FIND.append(case_law)
            continue

        try:
            # create the url of the case page
            page_url = BASE_URL+second_link
            browser.get(page_url)
            time.sleep(0.5)
            parsed_second_page = BeautifulSoup(
                browser.page_source, "html.parser")

            # find the pdf url
            pdf_button = parsed_second_page.find_all(
                "div", {"class": "col-4 col-md-2 text-right"})
            pdf_url = pdf_button[0].a.get("href")
            full_pdf_url = BASE_URL + pdf_url
            r = requests.get(full_pdf_url)
            print(f"Downloading {case_law}...")

            create_tabs(doc_count, description=case_law)
            # store the bytes content in deque container
            QUEUE.append(r.content)

        except:
            FAILED_TO_FIND.append(case_law)
            print(f"Cannot find {case_law}")

    browser.quit()
    print("FAILED TO FIND\n", FAILED_TO_FIND)
    file_size = merge_pdf_files()
    upload_aws_s3()
    url = create_presigned_url()
    send_email(email, url, FAILED_TO_FIND, file_size)
