import requests
import json
import sys
import logging
import urllib.parse
from typing import Tuple # Import Tuple from the typing module

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Constants ---
GOOGLE_SCRIPT_ENDPOINT = "https://script.google.com/macros/s/AKfycbxk2QmeLyubXBCuJ5qGh9Cj2Xx-Ug88OeegtGmpPcWka85rCzVE8kaW3bjgoIw2Mw-N/exec?type=print"

def post_data_to_google_script(data: dict) -> Tuple[dict, int]: # Use Tuple instead of tuple[dict, int]
    """
    Sends a POST request with JSON data to a specified Google Apps Script endpoint.

    Args:
        data: A dictionary representing the JSON payload to send.

    Returns:
        A tuple containing:
            - The JSON response from the server (as a dictionary).
            - The HTTP status code of the response.
        Returns an empty dictionary and 0 for status code if an error occurs.
    """
    
    try:
        logging.info(f"Attempting to post data to: {GOOGLE_SCRIPT_ENDPOINT}")
        response = requests.post(GOOGLE_SCRIPT_ENDPOINT, json=data, timeout=10) # Added a timeout
        response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)
        
        response_json = response.json()
        logging.info(f"Successfully received response with status code: {response.status_code}")
        logging.debug(f"Response data: {response_json}")
        
        return response_json, response.status_code
        
    except requests.exceptions.Timeout:
        logging.error("The request timed out.")
        return {}, 0
    except requests.exceptions.ConnectionError:
        logging.error("A connection error occurred. Check network connectivity or URL.")
        return {}, 0
    except requests.exceptions.HTTPError as e:
        logging.error(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
        # Attempt to return JSON from error response if available, otherwise empty dict
        return e.response.json() if e.response.text and e.response.headers.get('content-type') == 'application/json' else {}, e.response.status_code
    except json.JSONDecodeError:
        # This could happen if raise_for_status() didn't catch an error, but the content isn't JSON
        logging.error("Failed to decode JSON from response.")
        return {}, response.status_code if 'response' in locals() else 0
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        return {}, 0

def main():
    """
    Main function to parse command-line arguments, send data, and print results.
    """
    if len(sys.argv) < 2:
        logging.error("Usage: python your_script_name.py '<URL safe JSON>'")
        sys.exit(1)

    try:
        # Load JSON data from the first command-line argument
        items_payload = json.loads(urllib.parse.unquote_plus(sys.argv[1]))
        logging.info("Successfully loaded JSON payload from command line.")
    except json.JSONDecodeError:
        logging.error("Invalid JSON provided in command-line argument.")
        sys.exit(1)
    except Exception as e:
        logging.error(f"An error occurred while parsing command-line arguments: {e}")
        sys.exit(1)

    # Post data and get response
    response_data, status_code = post_data_to_google_script(items_payload)

    # Print the results to standard output
    print(json.dumps(response_data, indent=2)) # Pretty print JSON
    print(f"HTTP Status Code: {status_code}")

if __name__ == "__main__":
    main()