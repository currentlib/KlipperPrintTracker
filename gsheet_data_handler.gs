/**
 * @file Google Apps Script for Spreadsheet Integration.
 *
 * This script provides endpoints for logging print history to a Google Sheet.
 * It handles both POST requests (for structured JSON data) and GET requests
 * (for simple key-value pairs).
 */

// --- Configuration Constants ---
/**
 * The name of the sheet used for storing print history.
 * @type {string}
 */
const PRINT_HISTORY_SHEET_NAME = "Історія Друку";

// --- Helper Functions ---

/**
 * Retrieves the active spreadsheet's sheet by name.
 * Throws an error if the sheet is not found.
 * @param {string} sheetName The name of the sheet to retrieve.
 * @returns {GoogleAppsScript.Spreadsheet.Sheet} The requested sheet.
 * @throws {Error} If the sheet with the specified name is not found.
 */
function getPrintHistorySheet() {
  const sheet = SpreadsheetApp.getActive().getSheetByName(PRINT_HISTORY_SHEET_NAME);
  if (!sheet) {
    const errorMessage = `Error: Sheet '${PRINT_HISTORY_SHEET_NAME}' not found. Please ensure the sheet exists.`;
    Logger.log(errorMessage);
    throw new Error(errorMessage);
  }
  return sheet;
}

/**
 * Creates and returns a JSON response.
 * @param {number} status The HTTP status code (e.g., 200, 400).
 * @param {string} [message] An optional message to include in the response.
 * @returns {GoogleAppsScript.Content.TextOutput} A ContentService TextOutput object.
 */
function createJsonResponse(status, message = null) {
  const response = { status: status };
  if (message) {
    response.message = message;
  }
  return ContentService.createTextOutput(JSON.stringify(response))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * Logs data to the print history sheet.
 * @param {string} key The key/name of the item.
 * @param {string} value The value/count of the item.
 */
function logPrintEntry(key, value) {
  try {
    const sheet = getPrintHistorySheet();
    sheet.appendRow([new Date(), key, value]);
    Logger.log(`Logged print entry: Key='${key}', Value='${value}'`);
  } catch (error) {
    Logger.log(`Failed to log print entry: ${error.message}`);
    // Re-throw the error to be handled by the calling function if necessary
    throw error;
  }
}

// --- Main Request Handlers ---

/**
 * Handles HTTP POST requests.
 * Expects a 'type' parameter and 'postData.contents' for 'print' type.
 * The 'postData.contents' should be a JSON string.
 * @param {GoogleAppsScript.Events.DoPost} e The event object containing request parameters and post data.
 * @returns {GoogleAppsScript.Content.TextOutput} A JSON response indicating success or failure.
 */
function doPost(e) {
  Logger.log(`doPost received: ${JSON.stringify(e.parameter)}`);

  try {
    if (e.parameter && e.parameter.type === "print") {
      if (!e.postData || !e.postData.contents) {
        Logger.log("Error: Missing postData.contents for 'print' type.");
        return createJsonResponse(400, "Missing request body for 'print' type.");
      }

      let jsonObj;
      try {
        jsonObj = JSON.parse(e.postData.contents);
      } catch (parseError) {
        Logger.log(`Error parsing JSON from postData: ${parseError.message}`);
        return createJsonResponse(400, "Invalid JSON in request body.");
      }

      if (typeof jsonObj !== 'object' || jsonObj === null) {
        Logger.log("Error: Parsed JSON is not an object.");
        return createJsonResponse(400, "Request body must be a JSON object.");
      }

      // Iterate through the JSON object and log each key-value pair
      for (const key in jsonObj) {
        // Ensure the property belongs to the object itself, not its prototype chain
        if (Object.prototype.hasOwnProperty.call(jsonObj, key)) {
          logPrintEntry(key, jsonObj[key]);
        }
      }
      return createJsonResponse(200, "Print history logged successfully via POST.");
    } else {
      Logger.log("Error: Undefined or unsupported 'type' parameter in POST request.");
      return createJsonResponse(400, "Undefined or unsupported 'type'.");
    }
  } catch (error) {
    Logger.log(`Unhandled error in doPost: ${error.message}`);
    return createJsonResponse(500, `Internal server error: ${error.message}`);
  }
}

/**
 * Handles HTTP GET requests.
 * Expects 'type', 'name', and 'count' parameters for 'print' type.
 * @param {GoogleAppsScript.Events.DoGet} e The event object containing request parameters.
 * @returns {GoogleAppsScript.Content.TextOutput} A JSON response indicating success or failure.
 */
function doGet(e) {
  Logger.log(`doGet received: ${JSON.stringify(e.parameter)}`);

  try {
    if (e.parameter && e.parameter.type === "print") {
      const name = e.parameter.name;
      const count = e.parameter.count;

      if (!name || !count) {
        Logger.log("Error: Missing 'name' or 'count' parameters for 'print' type in GET request.");
        return createJsonResponse(400, "Missing 'name' or 'count' parameters.");
      }

      logPrintEntry(name, count);
      return createJsonResponse(200, "Print history logged successfully via GET.");
    } else {
      Logger.log("Error: Undefined or unsupported 'type' parameter in GET request.");
      return createJsonResponse(400, "Undefined or unsupported 'type'.");
    }
  } catch (error) {
    Logger.log(`Unhandled error in doGet: ${error.message}`);
    return createJsonResponse(500, `Internal server error: ${error.message}`);
  }
}

/**
 * A simple test function to append a row to the sheet.
 * Useful for quickly verifying sheet access and append functionality.
 */
function test() {
  Logger.log("Executing test function...");
  try {
    logPrintEntry("test_item", "test_value");
    Logger.log("Test entry appended successfully.");
  } catch (error) {
    Logger.log(`Test function failed: ${error.message}`);
  }
}
