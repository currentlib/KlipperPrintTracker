# gcode_post_processor.ps1
#
# PowerShell script for G-code post-processing.
# Counts excluded objects and injects data before the last END_PRINT.
# This script is designed to be run as a slicer post-processing script on Windows.
# No external installations required.

#region Argument Parsing
param(
    [Parameter(Mandatory=$true)]
    [string]$gcodeFilePath
)
#endregion

#region Configuration
$excludeObjectPattern = New-Object -TypeName System.Text.RegularExpressions.Regex `
    -ArgumentList 'EXCLUDE_OBJECT_DEFINE NAME=(.*)(?:\.STL|(?<!\.STL)_id)', ([System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
$endPrintPattern = New-Object -TypeName System.Text.RegularExpressions.Regex `
    -ArgumentList '^\s*END_PRINT\s*$', `
    ([System.Text.RegularExpressions.RegexOptions]::Multiline -bor [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
#endregion

#region Logging Function (Basic)
function Write-Log {
    param (
        [string]$Level,
        [string]$Message
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logEntry = "$timestamp - $Level - $Message"
    Write-Host $logEntry # Output to console
    # For file logging, you'd add:
    # Add-Content -Path "C:\path\to\your\log.txt" -Value $logEntry
}
#endregion


#region Core Logic Functions
function Count-ExcludedObjects {
    param (
        [string]$gcodeContent
    )
    $objectCounts = @{} # PowerShell Hashtable for counting

    # Find all matches for the exclude object pattern
    $matches = $excludeObjectPattern.Matches($gcodeContent)

    foreach ($match in $matches) {
        # Assuming the object name is in the first capturing group (group 1)
        $objectName = $match.Groups[1].Value

        # Increment count in the hashtable
        if ($objectCounts.ContainsKey($objectName)) {
            $objectCounts[$objectName]++
        } else {
            $objectCounts[$objectName] = 1
        }
    }
    return $objectCounts
}

function Inject-PrintCountData {
    param (
        [string]$gcodeContent,
        [hashtable]$objectCounts
    )

    $json_data = $objectCounts | ConvertTo-Json -Compress
    $encoded_json_data = [uri]::EscapeDataString($json_data)
    
    $injectionLine = "INCREMENT_PRINT_COUNT ITEMS=$encoded_json_data"

    Write-Log -Level "DEBUG" -Message "Searching for pattern: $($endPrintPattern.Pattern)"
    Write-Log -Level "DEBUG" -Message "Regex options: $($endPrintPattern.Options)"

    $matches = $endPrintPattern.Matches($gcodeContent)

    #Filter out matches that have a length of 0
    $actualMatches = $matches | Where-Object { $_.Length -gt 0 }

    if (-not $actualMatches.Count) { # Now check the count of actual (non-empty) matches
        Write-Log -Level "WARNING" -Message "No non-empty 'END_PRINT' match found in G-code. Data injection skipped."
        return $gcodeContent # Return original content if no true matches
    }

    # Get the last of the 'actual' (non-empty) match objects
    $lastMatch = $actualMatches[-1]

    # REGEX DEBUGGING
    Write-Log -Level "DEBUG" -Message "--- Last END_PRINT match details (After filtering) ---"
    Write-Log -Level "DEBUG" -Message "  Matched Value: '$($lastMatch.Value)'"
    Write-Log -Level "DEBUG" -Message "  Start Index (Index): $($lastMatch.Index)"
    Write-Log -Level "DEBUG" -Message "  Length (Length): $($lastMatch.Length)"
    Write-Log -Level "DEBUG" -Message "  End Index (Index + Length): $($lastMatch.Index + $lastMatch.Length)"
    # END REGEX DEBUGGING

    $startIndex = $lastMatch.Index
    $endIndex = $lastMatch.Index + $lastMatch.Length

    # Reconstruct the string to insert the injection line after the last END_PRINT
    $modifiedGcode = $gcodeContent.Substring(0, $endIndex) + "`n" + $injectionLine + $gcodeContent.Substring($endIndex)
    
    Write-Log -Level "INFO" -Message "Successfully prepared data for injection after the last 'END_PRINT'."

    return $modifiedGcode
}
#endregion

#region Main Execution
try {
    Write-Log -Level "INFO" -Message "Starting post-processing for G-code: $gcodeFilePath"

    # Read G-code content
    $gcodeContent = Get-Content -Path $gcodeFilePath -Encoding UTF8 -Raw # -Raw reads entire file as single string

    # Count objects
    $objectCounts = Count-ExcludedObjects -gcodeContent $gcodeContent
    Write-Log -Level "INFO" -Message "Detected objects: $($objectCounts | ConvertTo-Json -Compress)"

    # Inject data into G-code
    $modifiedGcodeContent = Inject-PrintCountData -gcodeContent $gcodeContent -objectCounts $objectCounts

    if ($gcodeContent -eq $modifiedGcodeContent) {
        Write-Log -Level "WARNING" -Message "Calculated modified content is identical to original G-code. No actual change was detected by the script."
        # This implies Inject-PrintCountData might not have found the END_PRINT or couldn't modify for some subtle reason
    } else {
        Write-Log -Level "INFO" -Message "Content modification detected. Attempting to write changes to file."
    }

    # Write modified G-code back to file
    Set-Content -Path $gcodeFilePath -Encoding UTF8 -Value $modifiedGcodeContent
    
    Write-Log -Level "INFO" -Message "Successfully processed $gcodeFilePath. Injected object counts."

} catch [System.IO.FileNotFoundException] {
    Write-Log -Level "ERROR" -Message "Error: G-code file not found at '$gcodeFilePath'. Please check the path. Exception: $($_.Exception.Message)"
    exit 1
} catch {
    # Catch any other unexpected errors
    Write-Log -Level "CRITICAL" -Message "An unexpected error occurred during post-processing for '$gcodeFilePath'. Exception: $($_.Exception.Message)"
    Write-Error $_.Exception.ToString()
    exit 1
}
#endregion