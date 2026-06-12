from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pytesseract
from PIL import Image
import io
import re
import cv2
import numpy as np
import pdfplumber
import fitz
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)
def normalize_spaces(text):
    return " ".join(str(text or "").split()).strip()
def extract_text_from_pdf(content: bytes):
    rows = []
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        cleaned = [
                            str(cell).strip() if cell else ""
                            for cell in row
                        ]
                        if any(cleaned):
                            rows.append(cleaned)
                text = page.extract_text() or ""
                for line in text.splitlines():
                    line = line.strip()
                    if line:
                        rows.append([line])
    except Exception as e:
        print("pdfplumber failed:", e)
    useful_rows = [
        row for row in rows
        if any(str(cell).strip() for cell in row)
    ]
    if useful_rows:
        return useful_rows
    print("PDF appears scanned. Running OCR fallback...")
    doc = fitz.open(stream=content, filetype="pdf")
    ocr_rows = []
    for page in doc:
        pix = page.get_pixmap(
            matrix=fitz.Matrix(2, 2),
            alpha=False
        )
        image = Image.open(
            io.BytesIO(pix.tobytes("png"))
        ).convert("RGB")
        image_bytes = io.BytesIO()
        image.save(image_bytes, format="PNG")
        ocr_rows.extend(
            extract_text_from_image(image_bytes.getvalue())
        )
    doc.close()
    return ocr_rows
def extract_text_from_image(content: bytes):
    image = Image.open(io.BytesIO(content)).convert("RGB")
    image_np = np.array(image)
    gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(
        gray,
        (3, 3),
        0
    )
    thresh = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        11,
        2,
    )
    text = pytesseract.image_to_string(
        thresh,
        config=r"--oem 3 --psm 6",
    )
    print("OCR TEXT:")
    print(text)
    return [
        [line.strip()]
        for line in text.splitlines()
        if line.strip()
    ]
def looks_like_header(text):
    text = normalize_spaces(text).lower()
    header_words = [
        "test",
        "name",
        "result",
        "value",
        "unit",
        "range",
        "reference",
        "normal",
        "method",
    ]
    return sum(word in text for word in header_words) >= 2
def extract_reference_range(text):
    text = str(text)
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("â€“", "-").replace("â€”", "-")
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)",
        text,
    )
    if match:
        return f"{match.group(1)} - {match.group(2)}"
    return ""
def extract_lab_unit(text):
    text = str(text)
    unit_patterns = [
        r"g/dL",
        r"mg/dL",
        r"mg/L",
        r"mmol/L",
        r"mEq/L",
        r"IU/L",
        r"U/L",
        r"ng/mL",
        r"pg/mL",
        r"µIU/mL",
        r"uIU/mL",
        r"million/cumm",
        r"mill/cumm",
        r"cells/cumm",
        r"cumm",
        r"lakhs/cumm",
        r"thou/cumm",
        r"%",
        r"fL",
        r"pg",
    ]
    for pattern in unit_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return ""
QUALITATIVE_RESULTS = [
    "not detected",
    "not seen",
    "non-reactive",
    "non reactive",
    "negative",
    "positive",
    "absent",
    "present",
    "nil",
    "reactive",
    "normal",
    "abnormal",
    "detected",
    "seen",
]
def extract_result_value(text):
    text = normalize_spaces(text)
    numeric_match = re.search(
        r"[-+]?\d+(?:\.\d+)?",
        text
    )
    if numeric_match:
        return (
            numeric_match.group(0),
            numeric_match.start(),
            numeric_match.end(),
            "numeric",
        )
    lower_text = text.lower()
    for result in QUALITATIVE_RESULTS:
        match = re.search(
            rf"\b{re.escape(result)}\b",
            lower_text
        )
        if match:
            return (
                text[match.start():match.end()],
                match.start(),
                match.end(),
                "qualitative",
            )
    return "", -1, -1, ""
def parse_single_line(line):
    line = normalize_spaces(line)
    if looks_like_header(line):
        return None
    value, start, end, value_type = extract_result_value(line)
    if not value:
        return None
    name = line[:start].strip(" :-")
    rest = line[end:].strip()
    return {
        "name": name,
        "value": value,
        "value_type": value_type,
        "range": extract_reference_range(rest),
        "unit": extract_lab_unit(rest),
        "raw": line,
    }
def parse_table_row(row):
    cells = [
        normalize_spaces(cell)
        for cell in row
        if normalize_spaces(cell)
    ]
    if len(cells) < 2:
        return None
    joined = normalize_spaces(" ".join(cells))
    if looks_like_header(joined):
        return None
    value_index = -1
    value = ""
    value_type = ""
    for index, cell in enumerate(cells):
        found_value, _, _, found_type = extract_result_value(cell)
        if found_value:
            value_index = index
            value = found_value
            value_type = found_type
            break
    if value_index <= 0:
        return parse_single_line(joined)
    name = normalize_spaces(" ".join(cells[:value_index]))
    remaining = normalize_spaces(" ".join(cells[value_index + 1:]))
    return {
        "name": name,
        "value": value,
        "value_type": value_type,
        "range": extract_reference_range(remaining),
        "unit": extract_lab_unit(remaining),
        "raw": joined,
    }
def is_probable_test_row(test):
    name = normalize_spaces(test.get("name"))
    value = normalize_spaces(test.get("value"))
    value_type = normalize_spaces(test.get("value_type"))
    reference_range = normalize_spaces(test.get("range"))
    unit = normalize_spaces(test.get("unit"))
    raw = normalize_spaces(test.get("raw"))
    if len(name) < 3 or len(name) > 80:
        return False
    if not re.search(r"[A-Za-z]", name):
        return False
    if value_type == "numeric":
        if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", value):
            return False
        if not reference_range and not unit:
            return False
    elif value_type == "qualitative":
        if len(value) < 3:
            return False
    else:
        return False
    if unit:
        if len(unit) > 20:
            return False

        if "," in unit:
            return False
        if len(unit.split()) > 2:
            return False
    if raw.count(",") >= 2 or len(raw) > 140:
        return False
    return True
def parse_report(rows):
    tests = []
    for row in rows:
        if not row:
            continue
        if len(row) >= 2:
            test = parse_table_row(row)
        else:
            test = parse_single_line(row[0])
        if test and is_probable_test_row(test):
            tests.append(test)
    return {
        "tests": tests
    }
def extract_explicit_status(text):
    text = normalize_spaces(text).lower()

    status_patterns = [
        ("Borderline", r"\bborderline\b"),
        ("Abnormal", r"\babnormal\b"),
        ("High", r"\bhigh\b"),
        ("Low", r"\blow\b"),
    ]

    for status, pattern in status_patterns:
        if re.search(pattern, text):
            return status

    return ""
def clean_tests(tests):
    cleaned = []
    for test in tests:
        name = normalize_spaces(test.get("name"))
        value = normalize_spaces(test.get("value"))
        value_type = normalize_spaces(test.get("value_type"))
        reference_range = normalize_spaces(test.get("range"))
        unit = normalize_spaces(test.get("unit"))
        if any(
            existing["name"].lower() == name.lower()
            for existing in cleaned
        ):
            continue
        raw = normalize_spaces(test.get("raw"))
        explicit_status = extract_explicit_status(raw)
        status = "Normal"
        if explicit_status:
           status = explicit_status
        elif value_type == "numeric":
            try:
                numeric_value = float(value)
                range_match = re.search(
                    r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)",
                    reference_range,
                )
                if range_match:
                    low = float(range_match.group(1))
                    high = float(range_match.group(2))
                    if numeric_value < low:
                        status = "Low"
                    elif numeric_value > high:
                        status = "High"
            except Exception:
                pass
        elif value_type == "qualitative":
            abnormal_words = [
                "positive",
                "reactive",
                "detected",
                "present",
                "seen",
                "abnormal",
            ]
            normal_words = [
                "negative",
                "non-reactive",
                "non reactive",
                "not detected",
                "not seen",
                "absent",
                "nil",
                "normal",
            ]
            lower_value = value.lower()
            if lower_value in abnormal_words:
                status = "Abnormal"
            elif lower_value in normal_words:
                status = "Normal"
        cleaned.append(
            {
                "name": name,
                "value": value,
                "range": reference_range,
                "unit": unit,
                "status": status,
            }
        )
    return cleaned
def build_summary(tests):
    total = len(tests)
    high = sum(1 for test in tests if test["status"] == "High")
    low = sum(1 for test in tests if test["status"] == "Low")
    abnormal = sum(1 for test in tests if test["status"] == "Abnormal")
    normal = sum(1 for test in tests if test["status"] == "Normal")
    return {
        "total_tests": total,
        "normal": normal,
        "high": high,
        "low": low,
        "abnormal": abnormal,
    }
@app.get("/")
def home():
    return {
        "message": "Backend running"
    }
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        content = await file.read()
        if not file.filename:
            raise HTTPException(
                status_code=400,
                detail="File name is missing"
            )
        filename = file.filename.lower()
        if filename.endswith(".pdf"):
            extracted_rows = extract_text_from_pdf(content)
        elif filename.endswith((".png", ".jpg", ".jpeg")):
            extracted_rows = extract_text_from_image(content)
        else:
            raise HTTPException(
                status_code=400,
                detail="Unsupported file type"
            )
        print("EXTRACTED ROWS:")
        print(extracted_rows)
        parsed_data = parse_report(extracted_rows)
        parsed_data["tests"] = clean_tests(parsed_data["tests"])
        print("FINAL CLEANED DATA:")
        print(parsed_data)
        return {
            "filename": file.filename,
            "data": parsed_data,
            "summary": build_summary(parsed_data["tests"]),
            "raw_rows": extracted_rows,
        }
    except HTTPException:
        raise
    except Exception as e:
        print("ERROR:", str(e))
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )