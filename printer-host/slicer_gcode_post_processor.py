import sys
import json
import re
import urllib.parse
import logging
import argparse
from collections import Counter
from typing import Dict, Any, Optional

# --- Configuration ---
EXCLUDE_OBJECT_PATTERN = re.compile(
    r'EXCLUDE_OBJECT_DEFINE NAME=(.*)(.STL|(?<!.STL)_id)',
    re.IGNORECASE
)
# This regex will replace END_PRINT if it's not preceded by any character,
# ensuring it's at the very beginning of a line or file, or after a newline.
END_PRINT_PATTERN = re.compile(r'^END_PRINT$', re.MULTILINE)

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO, # Set to logging.DEBUG for more verbose output
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def parse_arguments() -> argparse.Namespace:
    """Parses command-line arguments using argparse."""
    parser = argparse.ArgumentParser(
        description="Post-process G-code to count objects and inject print data."
    )
    parser.add_argument(
        'gcode_file_path',
        type=str,
        help="Path to the G-code file to process."
    )
    return parser.parse_args()

def count_excluded_objects(gcode_content: str) -> Dict[str, int]:
    """
    Counts occurrences of excluded objects in the G-code content.

    Args:
        gcode_content (str): The entire content of the G-code file.

    Returns:
        Dict[str, int]: A dictionary where keys are object names and values are their counts.
    """
    object_counts = Counter()
    
    for match in EXCLUDE_OBJECT_PATTERN.findall(gcode_content):
        object_name = match[0]
        object_counts[object_name] += 1
        
    return dict(object_counts)

def inject_print_count_data(gcode_content: str, object_counts: Dict[str, int]) -> str:
    """
    Injects the print count data into the G-code content after END_PRINT.

    Args:
        gcode_content (str): The original content of the G-code file.
        object_counts (Dict[str, int]): Dictionary of object names and their counts.

    Returns:
        str: The modified G-code content.
    """

    json_data = json.dumps(object_counts)
    encoded_json_data = urllib.parse.quote_plus(json_data)
    
    injection_line = f'INCREMENT_PRINT_COUNT ITEMS={encoded_json_data}'

    modified_gcode = END_PRINT_PATTERN.sub(
        f"END_PRINT\n{injection_line}",
        gcode_content
    )

    if modified_gcode == gcode_content:
        logging.warning("No 'END_PRINT' found in G-code. Data injection skipped.")

    return modified_gcode

def main():
    """Main function to execute the G-code post-processing."""
    args = parse_arguments()
    gcode_file_path = args.gcode_file_path

    try:
        logging.info(f"Starting post-processing for G-code: {gcode_file_path}")

        # --- Read G-code content ---
        with open(gcode_file_path, 'r', encoding='utf-8') as f:
            gcode_content = f.read()

        # --- Count objects ---
        object_counts = count_excluded_objects(gcode_content)
        logging.info(f"Detected objects: {object_counts}")

        # --- Inject data into G-code ---
        modified_gcode_content = inject_print_count_data(gcode_content, object_counts)

        # --- Write modified G-code back to file ---
        with open(gcode_file_path, 'w', encoding='utf-8') as f:
            f.write(modified_gcode_content)
        
        logging.info(f"Successfully processed {gcode_file_path}. Injected object counts.")

    except FileNotFoundError:
        logging.error(f"Error: G-code file not found at '{gcode_file_path}'. Please check the path.", exc_info=True)
        sys.exit(1)
    except Exception as e:
        # Catch any other unexpected errors
        logging.critical(f"An unexpected error occurred during post-processing: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()