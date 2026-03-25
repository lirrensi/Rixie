#!/usr/bin/env python3
"""
copy_to_reading_list.py

Takes all generated HTML files from the output folder and copies them into a reading_list folder.
Because hoarding HTML files like they're going out of style, darling. 💅
"""

import os
import shutil
from pathlib import Path


def copy_htmls_to_reading_list(
    output_dir: str = "output", reading_list_dir: str = "reading_list"
) -> None:
    """
    Copy all HTML files from output subfolders to a reading_list folder.

    Args:
        output_dir: Directory containing processed book folders
        reading_list_dir: Target directory for the reading list
    """
    output_path = Path(output_dir)
    reading_list_path = Path(reading_list_dir)

    # Create reading_list folder if it doesn't exist
    reading_list_path.mkdir(exist_ok=True)
    print(f"✨ Created/verified reading_list folder at: {reading_list_path.absolute()}")

    # Find all HTML files in output subfolders
    html_files = []
    for item in output_path.iterdir():
        if item.is_dir():
            # Look for .html files directly in each book folder
            for html_file in item.glob("*.html"):
                html_files.append(html_file)

    if not html_files:
        print(
            "🚨 Oops! No HTML files found in the output folder. Make sure you've run export_html.py first, darling."
        )
        return

    # Copy each HTML file to reading_list
    copied_count = 0
    for html_file in html_files:
        dest_file = reading_list_path / html_file.name

        # Handle duplicates by adding a suffix
        if dest_file.exists():
            stem = html_file.stem
            suffix = 1
            while dest_file.exists():
                new_name = f"{stem}_{suffix}.html"
                dest_file = reading_list_path / new_name
                suffix += 1

        shutil.copy2(html_file, dest_file)
        print(f"  📄 Copied: {html_file.name}")
        copied_count += 1

    print(f"\n🎉 Done! Copied {copied_count} HTML file(s) to {reading_list_dir}/")


if __name__ == "__main__":
    print("📚 Copying HTML files to your reading list...")
    print("-" * 60)
    copy_htmls_to_reading_list()
    print("-" * 60)
    print("Your reading list is ready to slay! 🔥")
