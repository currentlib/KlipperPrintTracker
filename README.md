# KlipperPrintTracker
Klipper-focused 3D print tracker for counting individual parts from G-code and logging print outcomes.

This repository provides a set of scripts to automate the reporting of 3D print job data from your Klipper-powered 3D printer directly to a Google Sheet. It integrates with your slicer's post-processing capabilities and a Klipper G-code shell command plugin to capture print metrics and send them to a centralized spreadsheet for tracking and analysis.
Current Status

Done:
- slicer_gcode_post_processor.py: Python script for slicer post-processing to inject reporting commands into G-code.
- klipper_post_print_reporter.py: Python script to be run on the Klipper host, responsible for collecting print data and sending it to Google Sheets.
- klipper_post_print_reporter_invoke.sh: A simple shell script to invoke the klipper_post_print_reporter.py script.
- gsheet_data_handler.gs: Google Apps Script to receive data from the Klipper host and append it as a new row in your specified Google Sheet.

To-Do:
- Figure out how to properly configure and invoke slicer_gcode_post_processor.ps1 as a post-processing script for users who prefer PowerShell or do not have Python installed.

#### Setup Instructions:
1. Create Google Sheet and App Script

    Go to Google Sheets and create a new spreadsheet.

    In your new Google Sheet, go to Extensions > Apps Script.

    Delete any existing code (Code.gs) and paste the entire content of gsheet_data_handler.gs into the Apps Script editor.

    Save the project (File > Save project).

2. Publish Your App Script Web App

    In the Apps Script editor, click on Deploy > New deployment.

    For "Select type", choose Web app.

    Configure the deployment:

    - Description: (Optional) Add a description like "Klipper Print Reporter API".

    - Execute as: Me (your Google account).

    -  Who has access: Anyone (this allows your Klipper printer to send data without authentication challenges).

   Click Deploy.

    If prompted, authorize the script to access your Google Sheet.

    Once deployed, you will get a "Web app URL". Copy this URL. You will need it for the next step.

3. Install "[Klipper Gcode Shell Command](https://guilouz.github.io/Creality-Helper-Script-Wiki/helper-script/klipper-gcode-shell-command/)" Plugin

    Ensure you have Moonraker and Mainsail/Fluidd installed on your Klipper host.

    Install the "[Klipper Gcode Shell Command](https://guilouz.github.io/Creality-Helper-Script-Wiki/helper-script/klipper-gcode-shell-command/)" plugin. This is typically done via the Helper Script. Refer to the plugin's official documentation for installation instructions.

4. Upload Klipper Scripts to Your Printer

    Upload klipper_post_print_reporter.py and klipper_post_print_reporter_invoke.sh to a directory on your Klipper host, for example, /usr/data/printer_data/config/.

    Important: Open klipper_post_print_reporter.py and klipper_post_print_reporter_invoke.sh and ensure that the file paths within these scripts correctly point to their respective locations and the Google Sheet Web App URL you obtained in step 2.

5. Add Post-Processing Script to Slicer

    Open your slicer.

    Go to your printer settings or output options where you can specify a post-processing script.

    Add slicer_gcode_post_processor.py as a post-processing script. You will need to provide the full path to this Python script.

6. Update Klipper G-code Macro Config

    Edit your Klipper printer's configuration file.

    Add the following G-code shell command and macro definitions. Make sure the command path for invoke_increment points to where you uploaded klipper_post_print_reporter_invoke.sh.
```
    [gcode_shell_command invoke_increment]
    command: sh /usr/data/printer_data/config/klipper_post_print_reporter_invoke.sh
    timeout: 30.0
    verbose: True

    [gcode_macro INCREMENT_PRINT_COUNT]
    gcode:
      {% if params.ITEMS %}
        {% set items = params.ITEMS|string %}
        RUN_SHELL_COMMAND CMD=invoke_increment PARAMS="{items}"
      {% else %}
        {action_respond_info("Parameter 'ITEMS' is required")}
      {% endif %}
```
   Save your printer.cfg and restart Klipper for the changes to take effect.

7. Final Path Check

    Double-check all file paths in slicer_gcode_post_processor.py, klipper_post_print_reporter.py, klipper_post_print_reporter_invoke.sh, and your printer.cfg to ensure they accurately reflect where you've placed the files on your system and Klipper host.

Customization: 
   You can modify slicer_gcode_post_processor.py to include more or fewer parameters based on what you want to track. Similarly, adjust gsheet_data_handler.gs to match the column order and data types you expect in your Google Sheet.