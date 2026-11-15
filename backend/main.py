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
import os
import json
from ai import generate_health_summary
from openai import OpenAI
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
openai_client = None
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

def normalize_ocr_numbers(text):
    text = str(text or "")
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("â€“", "-").replace("â€”", "-")

    # Correct common OCR mistakes inside numbers.
    text = re.sub(r"(?<=\d)[Cc](?=\.\d)", "", text)
    text = re.sub(r"(?<=\.)[Tt](?=\d)", "0", text)
    text = re.sub(r"(?<=\d)[Oo](?=\d)", "0", text)

    return text


def extract_reference_range(text):
    text = normalize_ocr_numbers(text)

    match = re.search(
        r"(?<![A-Za-z0-9])"
        r"([-+]?\d[\d,]*(?:\.\d+)?)\s*-\s*"
        r"([-+]?\d[\d,]*(?:\.\d+)?)"
        r"(?![A-Za-z0-9])",
        text,
    )

    if match:
        return f"{match.group(1)} - {match.group(2)}"

    match = re.search(
        r"(?<![A-Za-z0-9])(?:<=|>=|<|>)\s*"
        r"\d[\d,]*(?:\.\d+)?",
        text,
    )

    if match:
        return normalize_spaces(match.group(0))

    return ""



def extract_lab_unit(text):
    if not text:
        return ""

    units = [
        "million/cumm",
        "millions/cumm",
        "million/cmm",
        "mill/cumm",
        "lakhs/cumm",
        "lakhs/cmm",
        "cells/cumm",
        "cells/cmm",
        "thou/cumm",
        "thou/cmm",
        "thousand/cumm",
        "thousand/cmm",
        "mm/1hr",
        "mm/hr",
        "mm/hour",
        "µIU/mL",
        "μIU/mL",
        "uIU/mL",
        "mIU/L",
        "million/µL",
        "million/uL",
        "10^3/µL",
        "10^3/uL",
        "10^6/µL",
        "10^6/uL",
        "g/dL",
        "mg/dL",
        "mg/L",
        "mmol/L",
        "mEq/L",
        "IU/L",
        "U/L",
        "ng/mL",
        "pg/mL",
        "cells/µL",
        "cells/uL",
        "/cumm",
        "/cmm",
        "/mm3",
        "/µL",
        "/uL",
        "cumm",
        "cmm",
        "fL",
        "pg",
        "%"
    ]

    text_lower = text.lower()

    for unit in sorted(units, key=len, reverse=True):
        pattern = re.escape(unit)

        match = re.search(pattern, text, re.IGNORECASE)
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
    text = normalize_ocr_numbers(normalize_spaces(text))

    numeric_match = re.search(
        r"(?<![A-Za-z0-9])[-+]?\d+(?:\.\d+)?"
        r"(?![A-Za-z0-9])",
        text,
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
            lower_text,
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

    if not line or looks_like_header(line):
        return None

    explicit_status = ""

    flag_match = re.search(
        r"\b([HL])\s*(?=\d)",
        line,
        re.IGNORECASE
    )

    if flag_match:
        explicit_status = (
            "High" if flag_match.group(1).upper() == "H"
            else "Low"
        )
        line = normalize_spaces(
            line[:flag_match.start()] + line[flag_match.end():]
        )

    value, start, end, value_type = extract_result_value(line)

    if not value:
        return None

    name = line[:start].strip(" :-")
    rest = line[end:].strip()

    reference_range = extract_reference_range(rest)

    # Search the complete row because the unit may appear after the range.
    unit = extract_lab_unit(line)

    result = {
        "name": name,
        "value": value,
        "value_type": value_type,
        "range": reference_range,
        "unit": unit,
        "raw": normalize_spaces(line),
    }

    if explicit_status:
        result["explicit_status"] = explicit_status

    return result




def parse_table_row(row):
    cells = [
        normalize_ocr_numbers(normalize_spaces(cell))
        for cell in row
        if normalize_spaces(cell)
    ]

    if len(cells) < 2:
        return parse_single_line(" ".join(cells))

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

    if not name:
        return None

    return {
        "name": name,
        "value": value,
        "value_type": value_type,
        "range": extract_reference_range(remaining),
        "unit": extract_lab_unit(joined),
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

    metadata_patterns = [
        r"^\s*(phone|telephone|mobile|fax)\b",
        r"^\s*(contact|email|e-mail)\b",
        r"^\s*(patient\s*id|report\s*id|accession\s*(no|number)?)\b",
        r"^\s*(date\s*of\s*birth|dob|address)\b",
    ]

    if any(
        re.search(pattern, name, re.IGNORECASE)
        for pattern in metadata_patterns
    ):
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

    if len(unit) > 20 or "," in unit or len(unit.split()) > 2:
        return False

    if raw.count(",") >= 2 or len(raw) > 140:
        return False

    return True



def parse_report(rows):
    tests = []
    qualitative_findings = []

    qualitative_prefixes = (
        "rbc morphology",
        "wbc morphology",
        "platelets morphology",
        "parasites",
    )

    differential_names = {
        "neutrophils microscopic": "Absolute Neutrophil Count",
        "lymphocytes microscopic": "Absolute Lymphocyte Count",
        "eosinophils": "Absolute Eosinophil Count",
        "monocytes": "Absolute Monocyte Count",
        "basophils": "Absolute Basophil Count",
    }

    for row in rows:
        if not row:
            continue

        if len(row) >= 2:
            joined = normalize_spaces(" ".join(
                normalize_spaces(cell) for cell in row if cell
            ))
        else:
            joined = normalize_spaces(row[0])

        if not joined:
            continue

        lower_line = joined.lower()

        # Keep morphology and parasite findings separate from numeric tests
        if lower_line.startswith(qualitative_prefixes):
            qualitative_findings.append({
                "finding": joined,
                "type": "qualitative"
            })
            continue

        test = parse_table_row(row) if len(row) >= 2 else parse_single_line(joined)

        if test and is_probable_test_row(test):
            tests.append(test)

        # Extract absolute differential counts from rows containing
        # percentage and absolute-count columns.
        for original_name, absolute_name in differential_names.items():
            if not lower_line.startswith(original_name):
                continue

            match = re.search(
                r"\b\d+(?:\.\d+)?\s*%\s*"
                r"\d+(?:\.\d+)?\s*[-–—]\s*\d+(?:\.\d+)?\s+"
                r"(\d[\d,]*)\s*/c(?:mm|umm)\s*"
                r"(\d[\d,]*)\s*[-–—]\s*(\d[\d,]*)",
                joined,
                re.IGNORECASE
            )

            if match:
                absolute_value = match.group(1).replace(",", "")
                absolute_range = (
                    f"{match.group(2)} - {match.group(3)}"
                )

                tests.append({
                    "name": absolute_name,
                    "value": absolute_value,
                    "value_type": "numeric",
                    "range": absolute_range,
                    "unit": "/cmm",
                    "raw": joined
                })

            break

    return {
        "tests": tests,
        "qualitative_findings": qualitative_findings
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

    flag_match = re.search(r"(?:^|\s)([HL])\s*$", text)

    if flag_match:
        return "High" if flag_match.group(1) == "h" else "Low"

    return ""
def clean_tests(tests):
    cleaned = []
    seen = set()

    for test in tests:
        if not isinstance(test, dict):
            continue

        name = str(test.get("name", "")).strip()
        value = str(test.get("value", "")).strip()
        reference_range = str(
            test.get("reference_range", test.get("range", ""))
        ).strip()
        unit = str(test.get("unit", "")).strip()
        raw = str(test.get("raw", "")).strip()

        if not name or not value:
            continue

        # Avoid duplicate entries while preserving different results
        key = (
            name.lower(),
            value.lower(),
            reference_range.lower()
        )

        if key in seen:
            continue

        seen.add(key)

        # Determine status from an explicit flag first
        explicit_status = str(
            test.get("explicit_status", "")
        ).strip().lower()

        if not explicit_status and raw:
            explicit_status = extract_explicit_status(raw).lower()

        if explicit_status in ("high", "low", "abnormal", "borderline"):
            status = explicit_status.capitalize()
        else:
            status = "Unknown"

            # Compare numeric result with a reference interval
            try:
                numeric_value = float(
                    value.replace(",", "").strip()
                )

                range_match = re.search(
                    r"([-+]?\d[\d,]*(?:\.\d+)?)\s*[-–—]\s*"
                    r"([-+]?\d[\d,]*(?:\.\d+)?)",
                    reference_range
                )

                if range_match:
                    lower = float(
                        range_match.group(1).replace(",", "")
                    )
                    upper = float(
                        range_match.group(2).replace(",", "")
                    )

                    if numeric_value < lower:
                        status = "Low"
                    elif numeric_value > upper:
                        status = "High"
                    else:
                        status = "Normal"

                else:
                    # Handle reference limits such as < 5 or >= 10
                    threshold_match = re.search(
                        r"\s*(<=|>=|<|>)\s*"
                        r"([-+]?\d+(?:\.\d+)?)\s*",
                        reference_range
                    )

                    if threshold_match:
                        operator = threshold_match.group(1)
                        threshold = float(threshold_match.group(2))

                        if operator == "<":
                            status = (
                                "Normal"
                                if numeric_value < threshold
                                else "High"
                            )
                        elif operator == "<=":
                            status = (
                                "Normal"
                                if numeric_value <= threshold
                                else "High"
                            )
                        elif operator == ">":
                            status = (
                                "Normal"
                                if numeric_value > threshold
                                else "Low"
                            )
                        elif operator == ">=":
                            status = (
                                "Normal"
                                if numeric_value >= threshold
                                else "Low"
                            )

            except (ValueError, TypeError):
                pass

        cleaned.append({
            "name": name,
            "value": value,
            "range": reference_range,
            "unit": unit,
            "status": status,
            "raw": raw
        })

    return cleaned

def build_summary(tests):
    total = len(tests)

    high = sum(1 for test in tests if test.get("status") == "High")
    low = sum(1 for test in tests if test.get("status") == "Low")
    abnormal_only = sum(
        1 for test in tests if test.get("status") == "Abnormal"
    )
    borderline = sum(
        1 for test in tests if test.get("status") == "Borderline"
    )
    normal = sum(1 for test in tests if test.get("status") == "Normal")
    unknown = sum(1 for test in tests if test.get("status") == "Unknown")

    abnormal_total = high + low + abnormal_only + borderline

    return {
        "total_tests": total,
        "normal": normal,
        "high": high,
        "low": low,
        "borderline": borderline,
        "abnormal": abnormal_total,
        "abnormal_only": abnormal_only,
        "unknown": unknown,
    }

def generate_local_insights(tests):
    items = []
    for test in tests:
        if test.get("status") == "Normal":
            continue
        name = str(test.get("name", ""))
        name_lower = name.lower()
        status = test.get("status", "")
        value = test.get("value", "")
        unit = test.get("unit", "")
        reference_range = test.get("range", "")
        possible_meaning = f"{name} is marked as {status}."
        suggested_next_steps = [
            "Discuss this result with a qualified doctor.",
            "Do not start or stop medicines based only on this app.",
            "Interpret this value along with symptoms, history, and other tests.",
        ]
        warning_signs = [
            "Seek urgent care if symptoms are severe or rapidly worsening."
        ]
        if "tsh" in name_lower:
            if status == "High":
                possible_meaning = (
                    "High TSH can be associated with an underactive thyroid "
                    "or thyroid hormone imbalance."
                )
                suggested_next_steps = [
                    "Consult a doctor or endocrinologist for interpretation.",
                    "Doctor may suggest checking Free T3, Free T4, and thyroid antibodies.",
                    "Do not start thyroid medicine without medical advice.",
                ]
                warning_signs = [
                    "Seek care if there is severe weakness, chest pain, fainting, confusion, or severe swelling."
                ]
        elif "hba1c" in name_lower or "hb a1c" in name_lower:
            if status == "High":
                possible_meaning = (
                    "High HbA1c suggests average blood sugar has been elevated "
                    "over the past 2-3 months."
                )
                suggested_next_steps = [
                    "Consult a doctor for diabetes or prediabetes evaluation.",
                    "Reduce sugary drinks and refined carbohydrates.",
                    "Increase physical activity if medically safe.",
                    "Doctor may suggest fasting glucose or repeat HbA1c testing.",
                ]
                warning_signs = [
                    "Seek care if there is excessive thirst, frequent urination, vomiting, confusion, or very high glucose readings."
                ]
        elif "platelet" in name_lower or "plt" in name_lower:
            if status in ["Low", "Borderline"]:
                possible_meaning = (
                    "Low or borderline platelet count may increase bleeding or bruising risk, "
                    "depending on severity and cause."
                )
                suggested_next_steps = [
                    "Consult a doctor to find the cause.",
                    "Avoid self-medicating with blood thinners unless prescribed.",
                    "Watch for unusual bruising, nosebleeds, gum bleeding, or blood in urine/stool.",
                ]
                warning_signs = [
                    "Seek urgent care for heavy bleeding, black stools, blood vomiting, severe headache, or bleeding that does not stop."
                ]
        elif "hemoglobin" in name_lower or "haemoglobin" in name_lower or name_lower == "hb":
            if status == "Low":
                possible_meaning = (
                    "Low hemoglobin may be associated with anemia, iron deficiency, blood loss, "
                    "B12/folate deficiency, or other causes."
                )
                suggested_next_steps = [
                    "Consult a doctor before taking supplements.",
                    "Doctor may suggest iron studies, B12, folate, or repeat CBC.",
                    "Include iron-rich foods if suitable."
                ]
                warning_signs = [
                    "Seek urgent care for chest pain, severe breathlessness, fainting, or severe weakness."
                ]
        items.append({
            "test": name,
            "status": status,
            "value": f"{value} {unit}".strip(),
            "range": reference_range,
            "possible_meaning": possible_meaning,
            "suggested_next_steps": suggested_next_steps,
            "warning_signs": warning_signs,
        })
    if not items:
        return {
            "summary": "No abnormal values were detected in the extracted report.",
            "items": [],
            "disclaimer": "This is educational information only and not medical advice.",
        }
    return {
        "summary": "Some values need attention. Review the details below and consult a qualified doctor.",
        "items": items,
        "disclaimer": "This is educational information only. It is not a diagnosis, cure, prescription, or replacement for a doctor.",
    }
def generate_ai_insights(tests):
    abnormal_tests = [
        test for test in tests
        if test.get("status") != "Normal"
    ]
    if not abnormal_tests:
        return generate_local_insights(tests)
    if not os.getenv("OPENAI_API_KEY"):
        return generate_local_insights(tests)
    prompt = f"""
You are a healthcare report explanation assistant.
Explain the following abnormal medical report values in simple patient-friendly language.
Rules:
- Do not diagnose.
- Do not say "cure".
- Use "possible meaning" and "suggested next steps".
- Do not prescribe medicine.
- Always advise consulting a qualified doctor.
- Mention urgent warning signs when relevant.
- Return valid JSON only.
JSON format:
{{
  "summary": "short overall summary",
  "items": [
    {{
      "test": "test name",
      "status": "High/Low/Borderline/Abnormal",
      "value": "value with unit",
      "range": "reference range",
      "possible_meaning": "simple explanation",
      "suggested_next_steps": ["step 1", "step 2"],
      "warning_signs": ["warning 1", "warning 2"]
    }}
  ],
  "disclaimer": "medical safety disclaimer"
}}
Abnormal tests:
{json.dumps(abnormal_tests, indent=2)}
"""
    try:
        response = openai_client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            input=prompt,
        )
        text = response.output_text.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        print("AI ERROR:", str(e))
        return generate_local_insights(tests)
@app.get("/")
def home():
    return {
        "message": "Backend running"
    }


def validate_tests(tests):
    import re

    qualitative_values = {
        "positive", "negative", "trace", "present", "absent",
        "detected", "not detected", "reactive", "non-reactive",
        "normal", "abnormal", "inconclusive", "indeterminate"
    }

    number_pattern = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"

    def numeric_value(value):
        text = str(value or "").strip().replace(",", "")

        match = re.fullmatch(
            rf"(?:<=|>=|<|>)?\s*({number_pattern})",
            text
        )

        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None

        return None

    def parse_range(reference):
        text = str(reference or "").strip().replace(",", "")

        match = re.match(
            rf"^\s*({number_pattern})\s*-\s*({number_pattern})",
            text
        )
        if match:
            lower = float(match.group(1))
            upper = float(match.group(2))

            if lower <= upper:
                return ("interval", lower, upper)

            return None

        match = re.match(
            rf"^\s*(<=|>=|<|>)\s*({number_pattern})",
            text
        )
        if match:
            return ("limit", match.group(1), float(match.group(2)))

        return None

    for test in tests:
        if not isinstance(test, dict):
            continue

        warnings = list(test.get("validation_warnings", []))

        name = str(test.get("name") or "").strip()
        value = test.get("value")
        reference = test.get("reference_range", test.get("range", ""))
        status = str(test.get("status") or "Unknown").strip().title()

        if not name:
            warnings.append("Test name is missing.")

        if value is None or str(value).strip() == "":
            warnings.append("Test result value is missing.")

        if not str(reference or "").strip():
            warnings.append("Reference range is missing.")

        value_text = str(value or "").strip()
        value_number = numeric_value(value)

        if value_text and value_number is None:
            if value_text.casefold() not in qualitative_values:
                warnings.append(
                    "Result is not a recognized numeric or qualitative value. "
                    "Check the original report."
                )

        parsed_range = parse_range(reference)

        if value_number is not None and parsed_range:
            expected_status = None

            if parsed_range[0] == "interval":
                _, lower, upper = parsed_range

                if value_number < lower:
                    expected_status = "Low"
                elif value_number > upper:
                    expected_status = "High"
                else:
                    expected_status = "Normal"

            else:
                _, operator, limit = parsed_range

                if operator in ("<", "<="):
                    expected_status = (
                        "Normal" if value_number < limit
                        or (operator == "<=" and value_number == limit)
                        else "High"
                    )
                elif operator in (">", ">="):
                    expected_status = (
                        "Normal" if value_number > limit
                        or (operator == ">=" and value_number == limit)
                        else "Low"
                    )

            if expected_status:
                if status in ("High", "Low", "Normal") and status != expected_status:
                    warnings.append(
                        f"Status is '{status}', but the numeric value and "
                        f"reference range suggest '{expected_status}'. "
                        "Check the original report."
                    )

                elif status in ("Abnormal", "Critical") and expected_status == "Normal":
                    warnings.append(
                        "Result is marked abnormal, but its numeric value "
                        "appears within the supplied reference range. "
                        "Check the original report."
                    )

        # Remove duplicate warnings without losing their order.
        test["validation_warnings"] = list(dict.fromkeys(warnings))

    return tests


def correct_differential_units(tests):
    """
    Correct units for differential white blood cell percentages.
    Absolute cell counts must retain their /cmm units.
    """
    percentage_tests = {
        "neutrophils microscopic",
        "lymphocytes microscopic",
        "eosinophils",
        "monocytes",
        "basophils",
    }

    for test in tests:
        if not isinstance(test, dict):
            continue

        name = str(test.get("name", "")).strip().casefold()
        name = " ".join(name.split())

        if name in percentage_tests:
            test["unit"] = "%"

    return tests

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

        parsed_data = parse_report(extracted_rows)
        parsed_data["tests"] = clean_tests(parsed_data["tests"])
        parsed_data["tests"] = correct_differential_units(
        parsed_data["tests"]
)
        parsed_data["tests"] = validate_tests(parsed_data["tests"])

        ai_summary = generate_health_summary(parsed_data)

        return {
            "filename": file.filename,
            "data": parsed_data,
            "summary": build_summary(parsed_data["tests"]),
            "ai_summary": ai_summary,
        }

    except HTTPException:
        raise

    except Exception as e:
        print("ERROR:", str(e))
        raise HTTPException(
            status_code=500,
            detail="An error occurred while processing the report."
        )
