"""Countries configuration with flag emojis."""

# List of supported countries with their flag emojis
# Format: (value, flag emoji, display name)
COUNTRIES = [
    ("United States", "🇺🇸", "United States"),
    ("Canada", "🇨🇦", "Canada"),
    ("United Kingdom", "🇬🇧", "United Kingdom"),
    # ("Australia", "🇦🇺", "Australia"),
    # ("Germany", "🇩🇪", "Germany"),
    # ("France", "🇫🇷", "France"),
    # ("Japan", "🇯🇵", "Japan"),
    # ("South Korea", "🇰🇷", "South Korea"),
    # ("India", "🇮🇳", "India"),
    # ("Brazil", "🇧🇷", "Brazil"),
    # ("Mexico", "🇲🇽", "Mexico"),
    # ("Netherlands", "🇳🇱", "Netherlands"),
    # ("Sweden", "🇸🇪", "Sweden"),
    # ("Norway", "🇳🇴", "Norway"),
    # ("Denmark", "🇩🇰", "Denmark"),
    # ("Finland", "🇫🇮", "Finland"),
    # ("Spain", "🇪🇸", "Spain"),
    # ("Italy", "🇮🇹", "Italy"),
    # ("Poland", "🇵🇱", "Poland"),
    # ("Switzerland", "🇨🇭", "Switzerland"),
]

# Default country
DEFAULT_COUNTRY = "United States"


def get_countries_list():
    """
    Get the list of countries formatted for API response.

    Returns:
        List of dicts with value, flag, and label keys
    """
    return [
        {
            "value": value,
            "flag": flag,
            "label": display_name
        }
        for value, flag, display_name in COUNTRIES
    ]


def get_country_flag(country_value):
    """
    Get the flag emoji for a country value.

    Args:
        country_value: The country value (e.g., "United States")

    Returns:
        Flag emoji string or empty string if not found
    """
    for value, flag, _ in COUNTRIES:
        if value == country_value:
            return flag
    return ""
