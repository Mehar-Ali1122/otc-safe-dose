"""
i18n.py - English / Urdu strings for the interface chrome.

Clinical questions (red flags, contraindications) stay in English in v1:
translating them without professional clinical-translation review could
change their meaning, which is a safety risk.
"""

STRINGS = {
    "en": {
        "app_title": "OTC Safe-Dose Assistant",
        "app_subtitle": "Safety-first guidance on over-the-counter medicines for common adult complaints",
        "disclaimer": "This is general information, not a diagnosis. Confirm with a pharmacist or doctor. "
                      "In an emergency call",
        "step_triage": "Triage",
        "step_profile": "Profile",
        "step_safety": "Safety checks",
        "step_rec": "Recommendation",
        "emergency_title": "EMERGENCY - get medical help now",
        "emergency_body": "Your answers suggest you may need urgent medical attention. No medicine is suggested.",
        "call_now": "Call now, or go to the nearest emergency department",
        "urgent_title": "See a doctor today",
        "urgent_body": "Your symptoms need a doctor's assessment. Please do not self-treat. "
                       "If things get worse, call the emergency number.",
        "refer_title": "Please speak to a pharmacist or doctor",
        "alarm": "Safety check failed - recommendation withheld",
        "safety_ok": "All safety checks passed",
        "start_over": "Start over",
        "language": "Language",
        "profile": "Patient profile",
        "clinical_en_only": "",
        "privacy": "Privacy: answers stay in this browser session and are not stored. "
                   "Only safety incidents and reports you choose to send are logged, without names.",
    },
    "ur": {
        "app_title": "او ٹی سی محفوظ خوراک معاون",
        "app_subtitle": "عام بیماریوں کے لیے بغیر نسخے والی دواؤں کی محفوظ رہنمائی — صرف بالغ افراد کے لیے",
        "disclaimer": "یہ عمومی معلومات ہیں، تشخیص نہیں۔ کسی فارماسسٹ یا ڈاکٹر سے تصدیق کریں۔ ایمرجنسی میں کال کریں",
        "step_triage": "ابتدائی جانچ",
        "step_profile": "مریض کی معلومات",
        "step_safety": "حفاظتی جانچ",
        "step_rec": "سفارش",
        "emergency_title": "ہنگامی صورتحال — فوراً طبی مدد حاصل کریں",
        "emergency_body": "آپ کی بتائی گئی علامات کو فوری طبی توجہ کی ضرورت ہو سکتی ہے۔ کوئی دوا تجویز نہیں کی جا رہی۔",
        "call_now": "ابھی اس نمبر پر کال کریں یا قریبی ایمرجنسی میں جائیں",
        "urgent_title": "آج ہی ڈاکٹر سے ملیں",
        "urgent_body": "آپ کی علامات کا ڈاکٹر سے معائنہ ضروری ہے۔ خود سے علاج نہ کریں۔ حالت بگڑنے پر ایمرجنسی نمبر پر کال کریں۔",
        "refer_title": "فارماسسٹ یا ڈاکٹر سے مشورہ کریں",
        "alarm": "حفاظتی جانچ ناکام — سفارش روک دی گئی",
        "safety_ok": "تمام حفاظتی جانچیں کامیاب",
        "start_over": "دوبارہ شروع کریں",
        "language": "زبان",
        "profile": "مریض کی معلومات",
        "clinical_en_only": "طبی سوالات فی الحال صرف انگریزی میں ہیں؛ ان کا ترجمہ ماہرین کی تصدیق کے بعد شامل کیا جائے گا۔",
        "privacy": "رازداری: آپ کے جوابات محفوظ نہیں کیے جاتے؛ صرف حفاظتی واقعات اور آپ کی بھیجی گئی رپورٹس نام کے بغیر محفوظ ہوتی ہیں۔",
    },
}


def t(key: str, lang: str = "en") -> str:
    return STRINGS.get(lang, STRINGS["en"]).get(key) or STRINGS["en"].get(key, key)
