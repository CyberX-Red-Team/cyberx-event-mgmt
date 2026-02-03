#!/usr/bin/env python3
"""
Update frontend templates to use csrfFetch() for CSRF protection.

This script identifies and updates all fetch() calls in template files to use the
csrfFetch() wrapper, which automatically includes CSRF tokens.
"""

import re
import os
from pathlib import Path
from typing import List, Tuple


def find_fetch_calls(content: str) -> List[Tuple[int, str]]:
    """
    Find all fetch() calls in content.

    Returns list of (line_number, full_fetch_call_text)
    """
    lines = content.split('\n')
    fetch_calls = []

    for i, line in enumerate(lines, 1):
        if 'fetch(' in line and 'csrfFetch(' not in line:
            fetch_calls.append((i, line.strip()))

    return fetch_calls


def update_fetch_to_csrf_fetch(content: str) -> Tuple[str, int]:
    """
    Update all fetch() calls to use csrfFetch().

    Handles various patterns:
    1. fetch('/api/endpoint', {method: 'POST', ...})
    2. await fetch(...)
    3. const response = await fetch(...)

    Returns (updated_content, number_of_replacements)
    """
    replacements = 0

    # Pattern 1: Replace "fetch(" with "csrfFetch(" (but not if already csrfFetch)
    # Use word boundary to avoid matching "csrfFetch" itself
    pattern1 = r'(?<!csrf)fetch\s*\('
    content, count1 = re.subn(pattern1, 'csrfFetch(', content)
    replacements += count1

    # Pattern 2: Remove explicit 'Content-Type': 'application/json' headers
    # csrfFetch() adds this automatically when body is an object
    pattern2 = r"'Content-Type'\s*:\s*'application/json'\s*,?\s*"
    content = re.sub(pattern2, '', content)

    pattern3 = r'"Content-Type"\s*:\s*"application/json"\s*,?\s*'
    content = re.sub(pattern3, '', content)

    # Pattern 4: Remove explicit credentials: 'include' - csrfFetch adds this
    pattern4 = r"credentials\s*:\s*['\"]include['\"],?\s*"
    content = re.sub(pattern4, '', content)

    # Pattern 5: Simplify body: JSON.stringify({...}) to just {...}
    # csrfFetch() automatically stringifies objects
    pattern5 = r'body\s*:\s*JSON\.stringify\((\{[^}]*\})\)'
    content = re.sub(pattern5, r'body: \1', content)

    # Pattern 6: Clean up empty headers objects
    pattern6 = r"headers\s*:\s*\{\s*\},?\s*"
    content = re.sub(pattern6, '', content)

    return content, replacements


def process_template(file_path: Path) -> Tuple[bool, int, List[str]]:
    """
    Process a single template file.

    Returns (updated, num_replacements, fetch_calls_found)
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            original_content = f.read()

        # Find fetch calls before updating
        fetch_calls = find_fetch_calls(original_content)

        # Update content
        updated_content, replacements = update_fetch_to_csrf_fetch(original_content)

        if replacements > 0:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(updated_content)
            return True, replacements, [call[1] for call in fetch_calls]

        return False, 0, [call[1] for call in fetch_calls]

    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return False, 0, []


def main():
    """Main function to update all templates."""
    # Find frontend templates directory
    script_dir = Path(__file__).parent
    frontend_dir = script_dir.parent.parent / 'frontend' / 'templates'

    if not frontend_dir.exists():
        print(f"Frontend templates directory not found: {frontend_dir}")
        return

    print(f"Scanning templates in: {frontend_dir}")
    print("=" * 80)

    # Find all HTML template files
    template_files = list(frontend_dir.rglob('*.html'))

    total_files = 0
    total_replacements = 0
    updated_files = []

    for template_file in sorted(template_files):
        relative_path = template_file.relative_to(frontend_dir)
        updated, replacements, fetch_calls = process_template(template_file)

        if updated:
            total_files += 1
            total_replacements += replacements
            updated_files.append((str(relative_path), replacements, len(fetch_calls)))
            print(f"✓ {relative_path}")
            print(f"  Replaced: {replacements} fetch() calls")
            for call in fetch_calls[:3]:  # Show first 3 calls
                print(f"    - {call[:80]}...")
            if len(fetch_calls) > 3:
                print(f"    ... and {len(fetch_calls) - 3} more")
            print()

    print("=" * 80)
    print(f"Summary:")
    print(f"  Files scanned: {len(template_files)}")
    print(f"  Files updated: {total_files}")
    print(f"  Total replacements: {total_replacements}")

    if updated_files:
        print(f"\nUpdated files:")
        for file_path, replacements, fetch_count in updated_files:
            print(f"  • {file_path} - {replacements} replacements ({fetch_count} fetch calls)")


if __name__ == '__main__':
    main()
