


import requests
import json
import re

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5:3b"

DISCLAIMER = (
    "Educational information only. Not a medical diagnosis. "
    "Consult a qualified healthcare professional for medical decisions."
)


def format_original_result(test_data):
    value = test_data.get("value")
    unit = test_data.get("unit", "")
    reference = test_data.get(
        "reference_range",
        test_data.get("range", "")
    )
    status = test_data.get("status", "")

    result = str(value) if value is not None else "Not provided"

    if unit:
        result += f" {unit}"

    details = []
    if status:
        details.append(str(status))
    if reference:
        details.append(f"reference: {reference}")

    if details:
        result += " (" + "; ".join(details) + ")"

    return result


def get_report_status(test_data):
    status = str(test_data.get("status", "")).strip().lower()
    if status:
        return status

    value = test_data.get("value")
    reference = str(
        test_data.get("reference_range", test_data.get("range", ""))
    )

    if value is None:
        return ""

    number_pattern = r"[-+]?\d[\d,]*(?:\.\d+)?"
    value_match = re.search(number_pattern, str(value))
    range_match = re.search(
        r"(" + number_pattern + r")\s*[-–—]\s*(" + number_pattern + r")",
        reference
    )

    if not value_match or not range_match:
        return ""

    try:
        number = float(value_match.group().replace(",", ""))
        lower = float(range_match.group(1).replace(",", ""))
        upper = float(range_match.group(2).replace(",", ""))

        if lower > upper:
            return ""
        if number < lower:
            return "low"
        if number > upper:
            return "high"
        return "normal"

    except ValueError:
        return ""


def make_fallback_item(original):
    test_name = str(
        original.get(
            "test",
            original.get("test_name", original.get("name", "Unknown test"))
        )
    )
    status = get_report_status(original)

    return {
        "test": test_name,
        "result": format_original_result(original),
        "possible_meaning": (
            f"This result is reported as {status}. Its significance depends "
            "on the test, reference range, and clinical context. "
            "This result alone does not establish a diagnosis."
        ),
        "precautions": [],
        "diet_and_lifestyle": [],
        "next_steps": (
            "Discuss this finding with a qualified healthcare professional "
            "for interpretation and appropriate follow-up."
        ),
        "warning_signs": []
    }


def apply_finding_guidance(item, original):
    if not original:
        return item

    test_name = str(
        original.get("test", original.get("test_name", original.get("name", "")))
    ).strip().lower()

    status = get_report_status(original)

    if "hemoglobin" in test_name or test_name in {"hb", "haemoglobin"}:
        if status in {"low", "below normal"}:
            item["possible_meaning"] = (
                "The hemoglobin value is below the supplied laboratory "
                "reference range. This can be associated with anemia, "
                "but the result alone cannot establish the cause."
            )
            item["precautions"] = [
                "Do not start iron supplements solely on the basis of this result."
            ]
            item["diet_and_lifestyle"] = [
                "Include iron-containing foods such as lentils, beans, "
                "chickpeas and leafy greens. Pair plant-based iron sources "
                "with vitamin-C-rich foods. Dietary changes do not establish "
                "or treat every cause of low hemoglobin."
            ]
            item["next_steps"] = (
                "Discuss the result with a healthcare professional, who can "
                "interpret it alongside the rest of the blood count and decide "
                "whether iron studies or other tests are appropriate."
            )
            item["warning_signs"] = []

    elif (
        test_name in {"pcv", "hematocrit", "haematocrit"}
        or "packed cell volume" in test_name
    ):
        if status in {"high", "above normal"}:
            item["possible_meaning"] = (
                "The packed cell volume is above the supplied reference range. "
                "Several factors can contribute, and this result alone cannot "
                "identify the cause."
            )
            item["precautions"] = [
                "Do not assume dehydration is the cause or try to correct "
                "the result without appropriate assessment."
            ]
            item["diet_and_lifestyle"] = []
            item["next_steps"] = (
                "Ask a healthcare professional to interpret this value with "
                "the hemoglobin, RBC count, hydration history and clinical "
                "context. They can decide whether repeat testing is needed."
            )
            item["warning_signs"] = []

    elif (
        "wbc" in test_name
        or "white blood cell" in test_name
        or "leukocyte" in test_name
        or "leucocyte" in test_name
    ):
        if status in {"high", "low", "above normal", "below normal"}:
            item["possible_meaning"] = (
                "The white blood cell count is outside the supplied reference "
                "range. This can have several causes; the count alone cannot "
                "confirm an infection or another specific condition."
            )
            item["precautions"] = []
            item["diet_and_lifestyle"] = []
            item["next_steps"] = (
                "Discuss the result with a healthcare professional, considering "
                "the differential count, symptoms, medicines and clinical history."
            )
            item["warning_signs"] = []

    elif "platelet" in test_name or "thrombocyte" in test_name:
        if status in {"low", "borderline", "below normal"}:
            item["possible_meaning"] = (
                "The platelet result is reported as low or borderline. Its "
                "significance depends on the actual count, laboratory range, "
                "previous results and clinical context."
            )
            item["precautions"] = []
            item["diet_and_lifestyle"] = []
            item["next_steps"] = (
                "Review the result with a healthcare professional, who can "
                "decide whether follow-up or repeat testing is appropriate."
            )
            item["warning_signs"] = [
                "Seek prompt medical assessment for unusual or persistent "
                "bleeding, or significant unexplained bruising."
            ]

    return item


def generate_health_summary(report_data):
    report_json = json.dumps(report_data, indent=2, default=str)

    prompt = f"""
You are Swasthya AI, a medical laboratory report explanation assistant.

Explain only the supplied report. Do not diagnose a disease from a
single laboratory result.

REPORT DATA:
{report_json}

RULES:
1. Use the supplied report data only.
2. Focus on abnormal, borderline, and relevant unclear findings.
3. Explain each finding separately and use cautious language.
4. Do not confuse low hemoglobin with a proven low red blood cell count
   or assume iron deficiency.
5. Do not invent patient details, values, ranges, diagnoses, or advice.
6. Do not recommend medicines or supplements without a clinical basis.
7. Give precautions and lifestyle advice only when relevant.
8. Do not assume a particular diet.
9. Explain when the cause cannot be established from the report.
10. Recommend professional follow-up for abnormal results.
11. Preserve borderline findings without exaggerating their importance.
12. Include warning signs only when relevant.
13. Keep the explanation concise and patient-friendly.
14. Return relevant abnormal or borderline findings.
15. The application formats results using the original report.

Return valid JSON only:
{{
  "summary": "Concise overall explanation",
  "items": [
    {{
      "test": "Exact test name from the report",
      "result": "Short result description",
      "possible_meaning": "Possible significance and uncertainty",
      "precautions": [],
      "diet_and_lifestyle": [],
      "next_steps": "Finding-specific follow-up",
      "warning_signs": []
    }}
  ],
  "disclaimer": "{DISCLAIMER}"
}}

Use empty lists when no specific advice is justified.
Do not include Markdown or text outside the JSON.
"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0.2,
                    "num_predict": 400
                }
            },
            timeout=180
        )
        response.raise_for_status()

        result = response.json().get("response", "").strip()
        result = re.sub(
            r"^\s*```(?:json)?\s*|\s*```\s*$",
            "",
            result
        ).strip()

        print("OLLAMA RAW RESPONSE:", repr(result))
        health_data = json.loads(result)

        if not isinstance(health_data, dict):
            raise ValueError("Unexpected response format")

        print("OLLAMA PARSED RESPONSE:", health_data)
        summary = health_data.get("summary")
        items = health_data.get("items", [])

        if not isinstance(summary, str) or not isinstance(items, list):
            print("INVALID SUMMARY TYPE:", type(summary))
            print("INVALID ITEMS TYPE:", type(items))
            raise ValueError("Invalid summary or items")

        original_tests = report_data.get("tests", [])
        if not isinstance(original_tests, list):
            original_tests = []

        test_lookup = {}
        for test_data in original_tests:
            if not isinstance(test_data, dict):
                continue

            name = test_data.get(
                "test", test_data.get("test_name", test_data.get("name", ""))
            )
            if name:
                test_lookup[str(name).strip().casefold()] = test_data

        validated_items = []

        for item in items:
            if not isinstance(item, dict):
                continue

            test_name = item.get("test")
            if not isinstance(test_name, str) or not test_name.strip():
                continue

            original = test_lookup.get(test_name.strip().casefold())

            if original:
                exact_name = original.get(
                    "test", original.get("test_name", original.get("name", test_name))
                )
                result_text = format_original_result(original)
            else:
                exact_name = test_name
                result_text = str(item.get("result", "Not provided"))

            validated_item = {
                "test": str(exact_name),
                "result": result_text,
                "possible_meaning": str(item.get(
                    "possible_meaning",
                    "Insufficient information to interpret this finding."
                )),
                "precautions": (
                    item.get("precautions", [])
                    if isinstance(item.get("precautions", []), list) else []
                ),
                "diet_and_lifestyle": (
                    item.get("diet_and_lifestyle", [])
                    if isinstance(item.get("diet_and_lifestyle", []), list) else []
                ),
                "next_steps": str(item.get(
                    "next_steps",
                    "Discuss this result with a qualified healthcare professional."
                )),
                "warning_signs": (
                    item.get("warning_signs", [])
                    if isinstance(item.get("warning_signs", []), list) else []
                )
            }

            for field in ("precautions", "diet_and_lifestyle", "warning_signs"):
                validated_item[field] = [
                    value.strip()
                    for value in validated_item[field]
                    if isinstance(value, str) and value.strip()
                ]

            validated_item = apply_finding_guidance(validated_item, original)
            validated_items.append(validated_item)

        included_tests = {
            item["test"].strip().casefold() for item in validated_items
        }

        relevant_statuses = {
            "low", "high", "borderline", "abnormal", "critical",
            "critical low", "critical high", "below normal", "above normal"
        }

        for original in original_tests:
            if not isinstance(original, dict):
                continue

            test_name = str(original.get(
                "test", original.get("test_name", original.get("name", ""))
            )).strip()

            if not test_name:
                continue

            status = get_report_status(original)

            if status not in relevant_statuses:
                continue

            if test_name.casefold() in included_tests:
                continue

            fallback_item = make_fallback_item(original)
            fallback_item = apply_finding_guidance(fallback_item, original)
            validated_items.append(fallback_item)
            included_tests.add(test_name.casefold())

        return {
            "summary": summary,
            "items": validated_items,
            "disclaimer": DISCLAIMER
        }

    except requests.exceptions.ConnectionError:
        return {
            "summary": (
                "Cannot connect to Ollama. Make sure Ollama is running "
                "and the selected model is installed."
            ),
            "items": [],
            "disclaimer": DISCLAIMER
        }

    except requests.exceptions.Timeout:
        return {
            "summary": (
                "The AI request timed out. Check model performance and "
                "computer resources, then try again."
            ),
            "items": [],
            "disclaimer": DISCLAIMER
        }

    except (json.JSONDecodeError, ValueError) as e:
        print("AI VALIDATION ERROR:", repr(e))
        return {
            "summary": (
                "The AI response could not be validated. "
                "Please try processing the report again."
            ),
            "items": [],
            "disclaimer": DISCLAIMER
        }

    except requests.exceptions.RequestException as e:
        print("OLLAMA REQUEST ERROR:", repr(e))
        return {
            "summary": (
                "Unable to generate the AI summary. "
                "Check the Ollama service and try again."
            ),
            "items": [],
            "disclaimer": DISCLAIMER
        }


# TEST THE COMPLETE PROGRAM
if __name__ == "__main__":
    report_data = {
        "tests": [
            {
                "name": "Hemoglobin",
                "value": 10.2,
                "unit": "g/dL",
                "reference_range": "12.0-15.0",
                "status": "low"
            },
            {
                "name": "WBC",
                "value": 7500,
                "unit": "cells/uL",
                "reference_range": "4000-11000",
                "status": "normal"
            },
            {
                "name": "Platelet Count",
                "value": 250000,
                "unit": "cells/uL",
                "reference_range": "150000-450000",
                "status": "normal"
            }
        ]
    }

    result = generate_health_summary(report_data)

    print("\nSWASTHYA AI SUMMARY")
    print(result["summary"])

    print("\nFINDINGS")
    for item in result["items"]:
        print("\nTest:", item["test"])
        print("Result:", item["result"])
        print("Possible meaning:", item["possible_meaning"])
        print("Precautions:", item["precautions"])
        print("Diet and lifestyle:", item["diet_and_lifestyle"])
        print("Next steps:", item["next_steps"])
        print("Warning signs:", item["warning_signs"])

    print("\nDisclaimer:", result["disclaimer"])
