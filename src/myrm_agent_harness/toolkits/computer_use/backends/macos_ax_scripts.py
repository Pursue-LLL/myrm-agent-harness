"""AppleScript sources for the macOS accessibility probes (window text, blocking dialogs).

[INPUT]
- (none: static script text)

[OUTPUT]
- AX_TEXT_SCRIPT: frontmost app name, window title and visible text values, ``|||``-delimited
- AX_DIALOG_SCRIPT: frontmost app name and whether window 1 is a dialog / sheet, ``|||``-delimited

[POS]
Data-only companion of ``macos.py``: parsing and timeouts stay with the callers there.
"""

from __future__ import annotations

AX_TEXT_SCRIPT = """
tell application "System Events"
    set frontApp to first application process whose frontmost is true
    set appName to name of frontApp
    set winTitle to ""
    try
        set winTitle to name of window 1 of frontApp
    end try

    set textParts to {}
    try
        set uiElements to entire contents of window 1 of frontApp
        set maxElements to (count of uiElements)
        if maxElements > 500 then set maxElements to 500
        repeat with i from 1 to maxElements
            set elem to item i of uiElements
            try
                set elemRole to role of elem
                if elemRole is in {"AXTextField", "AXTextArea", "AXStaticText"} then
                    set elemValue to value of elem
                    if elemValue is not missing value and elemValue is not "" then
                        set end of textParts to elemValue
                    end if
                end if
            end try
        end repeat
    end try

    set AppleScript's text item delimiters to linefeed
    return appName & "|||" & winTitle & "|||" & (textParts as string)
end tell
"""


AX_DIALOG_SCRIPT = """
tell application "System Events"
    set frontApp to first application process whose frontmost is true
    set appName to name of frontApp

    -- If target_app_names is provided, check if frontApp matches
    -- (This logic is handled in Python, here we just return the app name and dialog status)

    set hasDialog to false
    try
        set win1 to window 1 of frontApp
        set winRole to role of win1
        set winSubrole to subrole of win1

        if winRole is "AXWindow" and winSubrole is "AXDialog" then
            set hasDialog to true
        else if winRole is "AXWindow" and winSubrole is "AXSystemDialog" then
            set hasDialog to true
        else if winRole is "AXSheet" then
            set hasDialog to true
        end if
    end try

    return appName & "|||" & (hasDialog as string)
end tell
"""
