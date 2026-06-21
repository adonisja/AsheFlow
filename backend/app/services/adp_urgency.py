from datetime import datetime

URGENCY_RANK = {"routine": 0, "urgent": 1, "mandatory": 2}


def calculate_urgency(detected_at: datetime, company_config) -> str:
    urgent_day    = company_config.adp_urgent_correction_day    if company_config else 5
    mandatory_day = company_config.adp_mandatory_correction_day if company_config else 6
    mandatory_hour = company_config.adp_mandatory_correction_hour if company_config else 0

    if detected_at.weekday() >= mandatory_day and detected_at.hour >= mandatory_hour:
        return "mandatory"
    elif detected_at.weekday() >= urgent_day:
        return "urgent"
    else:
        return "routine"
