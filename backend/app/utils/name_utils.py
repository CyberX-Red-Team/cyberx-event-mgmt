"""Name normalization and username generation utilities."""
import unicodedata


# Particles that should stay lowercase in names (unless they start the name)
_LOWERCASE_PARTICLES = {"de", "del", "della", "di", "du", "el", "la", "le", "van", "von", "der"}

# Prefixes that get special capitalization (e.g., McDonald, MacGregor, O'Brien)
_MC_PREFIXES = ("mc", "mac")


def normalize_name(name: str) -> str:
    """Normalize a person's name to proper title case.

    Handles:
    - ALL CAPS or all lowercase → Title Case
    - Hyphenated names: mary-jane → Mary-Jane
    - Apostrophes: o'brien → O'Brien
    - Mc/Mac prefixes: mcdonald → McDonald, macgregor → MacGregor
    - Particles: van, de, von, etc. stay lowercase (unless first word)

    Examples:
        >>> normalize_name("john")
        'John'
        >>> normalize_name("MARY-JANE")
        'Mary-Jane'
        >>> normalize_name("o'brien")
        "O'Brien"
        >>> normalize_name("mcdonald")
        'McDonald'
        >>> normalize_name("van der berg")
        'van der Berg'
    """
    if not name or not name.strip():
        return name

    name = name.strip()

    # Split on spaces, process each word
    words = name.split()
    result = []

    for i, word in enumerate(words):
        result.append(_capitalize_word(word, is_first=(i == 0)))

    return " ".join(result)


def _capitalize_word(word: str, is_first: bool = False) -> str:
    """Capitalize a single word with special case handling."""
    lower = word.lower()

    # Particles stay lowercase unless first word
    if not is_first and lower in _LOWERCASE_PARTICLES:
        return lower

    # Handle hyphenated parts separately
    if "-" in word:
        parts = word.split("-")
        return "-".join(_capitalize_word(p, is_first=(i == 0 and is_first)) for i, p in enumerate(parts))

    # Mc/Mac prefix: McDonald, MacGregor
    for prefix in _MC_PREFIXES:
        if lower.startswith(prefix) and len(lower) > len(prefix):
            return prefix.capitalize() + lower[len(prefix):].capitalize()

    # Apostrophe: O'Brien, D'Angelo
    if "'" in word and len(word) > 2:
        parts = word.split("'", 1)
        return parts[0].capitalize() + "'" + parts[1].capitalize()

    return word.capitalize()


def normalize_to_ascii(text: str) -> str:
    """Normalize unicode characters to ASCII equivalents.

    Decomposes accented characters and strips combining marks:
        é → e, ñ → n, ü → u, ç → c

    Args:
        text: Input string possibly containing unicode characters.

    Returns:
        ASCII-only string.
    """
    # NFD decompose: é → e + combining accent
    decomposed = unicodedata.normalize("NFD", text)
    # Strip combining marks (category "M")
    ascii_text = "".join(c for c in decomposed if unicodedata.category(c)[0] != "M")
    return ascii_text


def sanitize_username(first_name: str, last_name: str) -> str:
    """Generate a sanitized base username from a name.

    Format: first_initial + lastname, ASCII-only, alphanumeric, max 50 chars.

    Args:
        first_name: User's first name.
        last_name: User's last name.

    Returns:
        Sanitized base username (without conflict suffix).
    """
    first_initial = first_name[0].lower() if first_name else ""
    base = f"{first_initial}{last_name.lower()}"
    # Normalize unicode to ASCII (é→e, ñ→n, etc.)
    base = normalize_to_ascii(base)
    # Keep only alphanumeric
    base = "".join(c for c in base if c.isalnum())
    return base[:50]
