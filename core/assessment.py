"""Assessment types and their per-type defaults (SPEC sections 4.1, 5.2)."""

ITEM_TYPES = (
    "assignment", "lab", "quiz", "midterm", "final_exam", "project", "presentation", "other",
)

TYPE_LABELS = {
    "assignment": "Assignment", "lab": "Lab", "quiz": "Quiz", "midterm": "Midterm",
    "final_exam": "Final exam", "project": "Project", "presentation": "Presentation", "other": "Other",
}

# B_type: opponent base rating in standard mode
BASE_RATING = {
    "quiz": 900, "assignment": 1000, "lab": 1050, "presentation": 1050,
    "project": 1200, "midterm": 1300, "final_exam": 1450, "other": 1000,
}

# w used when an item has no weight
DEFAULT_WEIGHT = {
    "quiz": 2, "assignment": 3, "lab": 3, "presentation": 5,
    "project": 10, "midterm": 20, "final_exam": 35, "other": 3,
}


def effective_weight(item_type: str, weight_percent: float | None) -> float:
    return DEFAULT_WEIGHT[item_type] if weight_percent is None else weight_percent
