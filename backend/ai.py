
import json
import re
import os
import requests

OLLAMA_URL = "https://subject-yesterday-timing.ngrok-free.dev/api/generate"
MODEL_NAME = "qwen2.5:3b"
TIMEOUT = 180
OLLAMA_USERNAME = os.getenv("shailee kakumanu")
OLLAMA_PASSWORD = os.getenv("shaileeneha2005201019771980")
json={
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.1,
            "num_predict": 1600
        }
    },

DISCLAIMER = (
    "Educational information only. Not a medical diagnosis. "
    "Consult a qualified healthcare professional for medical decisions."
)

ABNORMAL_STATUSES = {
    "high", "low", "abnormal", "borderline", "critical",
    "critical high", "critical low", "above normal", "below normal"
}

CRITICAL_STATUSES = {
    "critical", "critical high", "critical low"
}


def normalize_name(name):
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        str(name or "").casefold()
    ).strip()


def get_test_name(test):
    return str(
        test.get("name")
        or test.get("test_name")
        or test.get("test")
        or ""
    ).strip()


def get_reference(test):
    return str(
        test.get("reference_range")
        or test.get("range")
        or ""
    ).strip()


def format_original_result(test):
    value = test.get("value")
    unit = str(test.get("unit") or "").strip()
    reference = get_reference(test)
    status = get_report_status(test)

    result = str(value) if value is not None else "Not provided"

    if unit:
        result += f" {unit}"

    details = []

    if status:
        details.append(status)

    if reference:
        details.append(f"reference: {reference}")

    if details:
        result += " (" + "; ".join(details) + ")"

    return result


def get_report_status(test):
    status = str(test.get("status") or "").strip().casefold()

    if status and status != "unknown":
        return status

    value_text = str(test.get("value") or "").strip().replace(",", "")
    reference = get_reference(test).replace(",", "")

    number = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"

    if not re.fullmatch(number, value_text):
        return status or "unknown"

    try:
        value = float(value_text)
    except ValueError:
        return status or "unknown"

    interval = re.fullmatch(
        rf"\s*({number})\s*[-–—]\s*({number})\s*",
        reference
    )

    if interval:
        low = float(interval.group(1))
        high = float(interval.group(2))

        if low > high:
            return "unknown"

        if value < low:
            return "low"

        if value > high:
            return "high"

        return "normal"

    threshold = re.fullmatch(
        rf"\s*(<=|>=|<|>)\s*({number})\s*",
        reference
    )

    if threshold:
        operator = threshold.group(1)
        limit = float(threshold.group(2))

        if operator in {"<", "<="}:
            is_normal = (
                value < limit if operator == "<"
                else value <= limit
            )
            return "normal" if is_normal else "high"

        is_normal = (
            value > limit if operator == ">"
            else value >= limit
        )
        return "normal" if is_normal else "low"

    return status or "unknown"


def is_abnormal(test):
    return get_report_status(test) in ABNORMAL_STATUSES


def normalize_list(value):
    if isinstance(value, list):
        return [
            str(entry).strip()
            for entry in value
            if isinstance(entry, (str, int, float))
            and str(entry).strip()
        ]

    if isinstance(value, str) and value.strip():
        return [value.strip()]

    return []


def make_fallback_item(original):
    status = get_report_status(original)

    return {
        "test": get_test_name(original) or "Unknown test",
        "result": format_original_result(original),
        "possible_meaning": (
            f"This result is marked {status} against the supplied "
            "reference range. Its significance depends on the test, "
            "the full report, symptoms and clinical context. "
            "It does not establish a diagnosis by itself."
        ),
        "symptoms_to_watch": [],
        "foods_to_eat": [
            "No specific food treatment can be recommended from "
            "this result alone. Choose a balanced diet."
        ],
        "lifestyle_recommendations": [],
        "precautions": [
            "Verify the value, unit and reference range against "
            "the original laboratory report."
        ],
        "severity": "routine",
        "doctor_advice": (
            "Discuss this result with a qualified healthcare "
            "professional. Urgency depends on the actual result "
            "and clinical context."
        ),
        "diet_and_lifestyle": [],
        "next_steps": (
            "Interpret this result alongside relevant tests, "
            "previous results and clinical history."
        ),
        "warning_signs": []
    }




def apply_finding_guidance(item, original):
    """Apply deterministic, non-diagnostic guidance to a lab finding."""

    item["symptoms_to_watch"] = []
    item["warning_signs"] = []
    item["foods_to_eat"] = []
    item["precautions"] = []
    item["lifestyle_recommendations"] = []

    name = normalize_name(get_test_name(original))
    status = get_report_status(original)

    # Do not infer criticality from a simple high/low flag.
    if status in CRITICAL_STATUSES:
        item["severity"] = "urgent"
        item["doctor_advice"] = (
            "The report labels this result critical. Contact a "
            "healthcare professional or the laboratory immediately "
            "for guidance on appropriate follow-up."
        )
    else:
        item["severity"] = "routine"
        item["doctor_advice"] = (
            "Discuss this result with a healthcare professional "
            "at an appropriate appointment. The urgency depends "
            "on the actual value, symptoms and clinical context."
        )

    # Hemoglobin
    if (
        "hemoglobin" in name
        or "haemoglobin" in name
        or name in {"hb", "hgb"}
    ):
        if status == "low":
            item["possible_meaning"] = (
                "Hemoglobin is below the supplied reference range. "
                "This can be associated with anemia, but the result "
                "alone cannot establish the cause."
            )
            item["foods_to_eat"] = [
                "Iron-containing foods include lentils, beans, "
                "chickpeas and leafy greens. Vitamin-C-rich foods "
                "can improve absorption of iron from plant foods. "
                "Diet alone may not address every cause."
            ]
            item["precautions"] = [
                "Do not start iron supplements solely on the basis "
                "of this result."
            ]
        else:
            item["possible_meaning"] = (
                f"Hemoglobin is marked {status} against the supplied "
                "reference range. Interpret it alongside the other "
                "blood count results and clinical history."
            )

        item["next_steps"] = (
            "Review hemoglobin alongside the other blood count "
            "results and clinical history."
        )
        return item

    # Hematocrit
    if any(term in name for term in (
        "hematocrit", "haematocrit", "packed cell volume"
    )) or name == "pcv":
        item["possible_meaning"] = (
            f"Hematocrit is marked {status} against the supplied "
            "reference range. It measures the proportion of blood "
            "volume occupied by red blood cells and should be "
            "interpreted alongside hemoglobin and other CBC results."
        )
        item["next_steps"] = (
            "Review the complete blood count and clinical context "
            "with a healthcare professional."
        )
        return item

    # Total WBC count
    if (
        "white blood cell" in name
        or "leukocyte" in name
        or "leucocyte" in name
        or name == "wbc"
        or name.startswith("wbc ")
    ):
        item["possible_meaning"] = (
            f"The white blood cell count is marked {status} against "
            "the supplied reference range. White blood cell counts "
            "can change for several reasons. This result alone "
            "cannot confirm an infection or its cause."
        )
        item["next_steps"] = (
            "Interpret the count alongside the differential blood "
            "count, symptoms, medicines and clinical history."
        )
        return item

    # Absolute neutrophil count
    if (
        "absolute neutrophil count" in name
        or name in {"anc", "neutrophil absolute count"}
    ):
        item["possible_meaning"] = (
            f"The absolute neutrophil count is marked {status} "
            "against the supplied reference range. Neutrophils "
            "are white blood cells involved in immune responses. "
            "This result alone cannot establish an infection."
        )
        item["next_steps"] = (
            "Review this count alongside total WBC, the other "
            "differential counts and clinical history."
        )
        return item

    # Lymphocyte percentage
    if (
        "lymphocyte" in name
        and any(term in name for term in (
            "microscopic", "percentage", "percent"
        ))
        and "absolute" not in name
    ):
        item["possible_meaning"] = (
            f"The lymphocyte percentage is marked {status} against "
            "the supplied reference range. A percentage outside "
            "the range does not necessarily mean the absolute "
            "lymphocyte count is abnormal. The two measurements "
            "describe different aspects of the blood count."
        )
        item["next_steps"] = (
            "Compare this percentage with the absolute lymphocyte "
            "count, total WBC and clinical context."
        )
        return item

    # Absolute lymphocyte count
    if (
        "absolute lymphocyte count" in name
        or name in {"alc", "lymphocyte absolute count"}
    ):
        item["possible_meaning"] = (
            f"The absolute lymphocyte count is marked {status} "
            "against the supplied reference range. It is distinct "
            "from the lymphocyte percentage, and the two can "
            "have different statuses."
        )
        item["next_steps"] = (
            "Interpret this count alongside total WBC, the "
            "lymphocyte percentage and clinical context."
        )
        return item

    # MPV
    if name == "mpv" or "mean platelet volume" in name:
        item["possible_meaning"] = (
            f"Mean platelet volume (MPV) is marked {status} against "
            "the supplied reference range. It describes the average "
            "size of platelets. An isolated MPV result cannot diagnose "
            "a platelet disorder or determine clotting risk."
        )
        item["foods_to_eat"] = [
            "No specific food has been established as a treatment "
            "for an isolated abnormal MPV. Choose a balanced diet."
        ]
        item["precautions"] = [
            "Do not start or stop medication based on MPV alone."
        ]
        item["next_steps"] = (
            "Interpret MPV alongside the platelet count, original "
            "report and clinical history."
        )
        return item

    # Platelet count
    if "platelet" in name or "thrombocyte" in name:
        item["possible_meaning"] = (
            f"The platelet result is marked {status} against the "
            "supplied reference range. Its significance depends "
            "on the actual count, previous results and clinical context."
        )
        item["next_steps"] = (
            "Review the platelet count alongside MPV and the "
            "complete blood count."
        )

        if status in {"low", "critical", "critical low"}:
            item["warning_signs"] = [
                "Unusual or persistent bleeding needs prompt "
                "medical assessment. Severe bleeding requires "
                "emergency care."
            ]

        return item

    return item


def filter_unsupported_investigations(item):
    """Remove unsupported imaging recommendations from AI-generated advice."""

    unsupported_phrases = (
        "imaging studies",
        "imaging tests",
        "ct scan",
        "mri scan",
        "x-ray",
        "ultrasound",
    )

    safe_message = (
        "A healthcare professional can review the complete report, "
        "symptoms, and medical history to decide whether further "
        "investigation is appropriate."
    )

    advice = str(item.get("doctor_advice") or "").strip()

    if any(phrase in advice.casefold() for phrase in unsupported_phrases):
        item["doctor_advice"] = safe_message

    precautions = item.get("precautions", [])

    if isinstance(precautions, list):
        filtered_precautions = []

        for precaution in precautions:
            text = str(precaution).strip()

            if any(
                phrase in text.casefold()
                for phrase in unsupported_phrases
            ):
                filtered_precautions.append(safe_message)
            else:
                filtered_precautions.append(text)

        item["precautions"] = filtered_precautions

    return item



def fallback_response(tests, message=None):
    abnormal_tests = [test for test in tests if is_abnormal(test)]

    items = []

    for test in abnormal_tests:
        item = make_fallback_item(test)
        item = apply_finding_guidance(item, test)
        items.append(item)

    if message:
        summary = message
    elif abnormal_tests:
        summary = (
            f"The report contains {len(abnormal_tests)} result(s) "
            "marked outside the supplied reference range. "
            "Interpret them in clinical context."
        )
    else:
        summary = (
            "No results were identified as abnormal in the "
            "available data. This does not guarantee that all "
            "aspects of health are normal."
        )

    return {
        "summary": summary,
        "items": items,
        "disclaimer": DISCLAIMER,
        "source": "fallback"
    }


def generate_health_summary(report_data):
    """
    Generate explanations with local Ollama.

    The full report is provided as context, but only flagged
    results receive individual explanations.
    """

    if isinstance(report_data, dict):
        tests = report_data.get("tests", [])
    elif isinstance(report_data, list):
        tests = report_data
    else:
        tests = []

    if not isinstance(tests, list):
        return fallback_response(
            [],
            "Unsupported report data format."
        )

    tests = [
        test for test in tests
        if isinstance(test, dict) and get_test_name(test)
    ]

    if not tests:
        return fallback_response(
            [],
            "No valid test results were available."
        )

    abnormal_tests = [test for test in tests if is_abnormal(test)]

    if not abnormal_tests:
        return {
            "summary": (
                "No results were marked abnormal in the extracted "
                "data. Review the complete report and clinical context."
            ),
            "items": [],
            "disclaimer": DISCLAIMER,
            "source": "local"
        }

    # Include normal results as context so the model can compare
    # related measurements without generating an item for each normal test.
    report_context = [
        {
            "name": get_test_name(test),
            "value": test.get("value"),
            "unit": test.get("unit", ""),
            "reference_range": get_reference(test),
            "status": get_report_status(test)
        }
        for test in tests
    ]

    abnormal_context = [
        {
            "name": get_test_name(test),
            "value": test.get("value"),
            "unit": test.get("unit", ""),
            "reference_range": get_reference(test),
            "status": get_report_status(test)
        }
        for test in abnormal_tests
    ]

    prompt = f"""
You are SwasthyaAI, an educational laboratory report assistant.

Explain flagged laboratory results in simple, careful language.

Return one valid JSON object only. Do not use Markdown.

MEDICAL SAFETY RULES:
1. Use only the supplied test data. Never invent patient details,
   symptoms, diagnoses, units, reference ranges or medical history.
2. An out-of-range result does not establish a diagnosis.
3. Explain each flagged result specifically, not with repeated
   generic advice.
4. Use the full report to understand related normal and abnormal
   results. Mention a related result only when relevant.
5. A low percentage does not automatically mean the corresponding
   absolute cell count is low. Keep these measurements distinct.
6. Do not claim that a particular food treats or corrects a result.
   If no specific food advice is justified, state that clearly.
7. Do not recommend medication, supplements or dosages.
8. Do not assume the patient has symptoms. List symptoms only
   when they are reasonably relevant, and explain uncertainty.
9. Do not recommend avoiding other people or changing daily
   activities solely because a result is mildly out of range.
10. Use severity "routine" unless clinical information supports
    a more urgent recommendation. Do not invent critical thresholds.
11. If a result is explicitly marked critical in the input, advise
    prompt contact with a healthcare professional or laboratory.
12. Use "prompt" or "urgent" only when justified by supplied
    clinical information. Explain uncertainty when information
    is insufficient.
13. Do not confuse laboratory reference flags with a medical
    assessment of severity.
14. Return exactly one item for every supplied flagged test.
15. Preserve the exact test names and do not add unknown tests.
16. Use short, understandable explanations.
17. Do not describe general hydration, rest or balanced eating as
    a treatment for an abnormal result.
18. Do not give false reassurance or claim that all other results
    prove the patient is healthy.

JSON SCHEMA:
{{
  "summary": "Brief educational overview",
  "items": [
    {{
      "test": "Exact supplied test name",
      "possible_meaning": "Cautious test-specific explanation",
      "symptoms_to_watch": [],
      "foods_to_eat": [],
      "lifestyle_recommendations": [],
      "precautions": [],
      "severity": "routine",
      "doctor_advice": "Appropriate follow-up guidance",
      "next_steps": "Specific useful next step",
      "warning_signs": []
    }}
  ]
}}

FULL REPORT CONTEXT:
{json.dumps(report_context, ensure_ascii=False, default=str)}

RESULTS REQUIRING EXPLANATIONS:
{json.dumps(abnormal_context, ensure_ascii=False, default=str)}
"""

    raw_response = ""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0.1,
                    "num_predict": 1600
                }
            },
            timeout=TIMEOUT
        )

        response.raise_for_status()

        response_data = response.json()

        if not isinstance(response_data, dict):
            raise ValueError("Unexpected Ollama response format.")

        raw_response = response_data.get("response", "")

        if not isinstance(raw_response, str) or not raw_response.strip():
            raise ValueError("Ollama returned an empty response.")

        ai_data = json.loads(raw_response)

        if not isinstance(ai_data, dict):
            raise ValueError("AI response must be a JSON object.")

        ai_items = ai_data.get("items")

        if not isinstance(ai_items, list):
            raise ValueError("AI response is missing an items list.")

        test_lookup = {
            normalize_name(get_test_name(test)): test
            for test in abnormal_tests
        }

        validated_items = []
        included_names = set()

        for item in ai_items:
            if not isinstance(item, dict):
                continue

            requested_name = (
                item.get("test")
                or item.get("test_name")
                or item.get("name")
            )

            normalized_name = normalize_name(requested_name)
            original = test_lookup.get(normalized_name)

            # Ignore unknown tests and duplicate explanations.
            if not original or normalized_name in included_names:
                continue

            severity = str(
                item.get("severity") or "routine"
            ).strip().lower()

            if severity not in {"routine", "prompt", "urgent"}:
                severity = "routine"

            next_steps = item.get("next_steps", "")

            if isinstance(next_steps, list):
                next_steps = "\n".join(normalize_list(next_steps))

            if not isinstance(next_steps, str):
                next_steps = ""

            validated_item = {
                "test": get_test_name(original),
                "result": format_original_result(original),
                "possible_meaning": str(
                    item.get("possible_meaning")
                    or "The significance of this result depends on "
                       "the supplied reference range and clinical context."
                ),
                "symptoms_to_watch": normalize_list(
                    item.get("symptoms_to_watch")
                ),
                "foods_to_eat": normalize_list(
                    item.get("foods_to_eat")
                ),
                "lifestyle_recommendations": normalize_list(
                    item.get("lifestyle_recommendations")
                ),
                "precautions": normalize_list(
                    item.get("precautions")
                ),
                "severity": severity,
                "doctor_advice": str(
                    item.get("doctor_advice")
                    or "Discuss this result with a qualified healthcare professional."
                ),
                "diet_and_lifestyle": normalize_list(
                    item.get("diet_and_lifestyle")
                ),
                "next_steps": (
                    next_steps.strip()
                    or "Review this result with a qualified healthcare professional."
                ),
                "warning_signs": normalize_list(
                    item.get("warning_signs")
                )
            }

            # Apply known test-specific rules after model generation.
            validated_item = apply_finding_guidance(
                validated_item,
                original
            )
            validated_item = filter_unsupported_investigations(
                validated_item
            )

            validated_items.append(validated_item)
            included_names.add(normalized_name)

        # Use safe fallback explanations for tests the model omitted.
        used_fallback = False

        for original in abnormal_tests:
            name = normalize_name(get_test_name(original))

            if name not in included_names:
                fallback_item = make_fallback_item(original)
                fallback_item = apply_finding_guidance(
                    fallback_item,
                    original
                )

                fallback_item = filter_unsupported_investigations(
                    fallback_item
                )

                validated_items.append(fallback_item)
                used_fallback = True

        if not validated_items:
            raise ValueError("No usable explanations were returned.")

        # Calculate counts from the supplied test statuses.
        high_count = sum(
            get_report_status(test) in {
                "high", "critical high", "above normal"
            }
            for test in abnormal_tests
        )

        low_count = sum(
            get_report_status(test) in {
                "low", "critical low", "below normal"
            }
            for test in abnormal_tests
        )

        other_count = len(abnormal_tests) - high_count - low_count

        summary_parts = []

        if high_count:
            summary_parts.append(f"{high_count} high result(s)")

        if low_count:
            summary_parts.append(f"{low_count} low result(s)")

        if other_count:
            summary_parts.append(
                f"{other_count} other abnormal result(s)"
            )

        summary = (
            "The extracted report contains "
            + ", ".join(summary_parts)
            + ". Out-of-range results do not establish a diagnosis. "
              "Interpret them with symptoms, medical history and "
              "laboratory reference ranges alongside a qualified "
              "healthcare professional."
        )

        return {
            "summary": summary,
            "items": validated_items,
            "disclaimer": DISCLAIMER,
            "source": (
                "ollama_with_fallback" if used_fallback else "ollama"
            )
        }

    except requests.exceptions.ConnectionError as error:
        print("OLLAMA CONNECTION ERROR:", repr(error))

        return fallback_response(
            tests,
            "Ollama could not be reached. Check that the local service is running."
        )

    except requests.exceptions.Timeout as error:
        print("OLLAMA TIMEOUT:", repr(error))

        return fallback_response(
            tests,
            "AI generation timed out. Showing basic report-based explanations."
        )

    except (
        requests.exceptions.RequestException,
        ValueError,
        TypeError
    ) as error:
        print("AI RESPONSE ERROR:", repr(error))
        print("AI RESPONSE PREVIEW:", repr(raw_response[:2000]))

        return fallback_response(
            tests,
            "The AI response could not be validated. "
            "Showing basic report-based explanations instead."
        )
