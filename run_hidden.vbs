Set objShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Get the directory where this script is located
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Read Python path from config file
configFile = scriptDir & "\python_config.txt"
If Not fso.FileExists(configFile) Then
    WScript.Echo "ERROR: Configuration file not found!"
    WScript.Echo "Please run install.bat first."
    WScript.Quit 1
End If

Set file = fso.OpenTextFile(configFile, 1)
pythonPath = Trim(file.ReadLine)
file.Close

If pythonPath = "" Then
    WScript.Echo "ERROR: Configuration file is empty!"
    WScript.Echo "Please run install.bat again to select a Python installation."
    WScript.Quit 1
End If

' Try pythonw.exe first (runs without console)
pythonwExe = pythonPath & "\pythonw.exe"
pythonExe = pythonPath & "\python.exe"

If fso.FileExists(pythonwExe) Then
    ' Use pythonw.exe - no console window at all
    pythonToUse = pythonwExe
ElseIf fso.FileExists(pythonExe) Then
    ' Fallback to python.exe with VBScript hidden window
    pythonToUse = pythonExe
Else
    WScript.Echo "ERROR: Python installation not found at: " & pythonPath
    WScript.Echo "Please run install.bat again to select a different installation."
    WScript.Quit 1
End If

' Change to script directory
objShell.CurrentDirectory = scriptDir

' Run the application (no console window needed - app uses file logging only)
' Use Run method with 0 (hidden window) to run without showing a console
' The third parameter (False) means don't wait for the process to finish
objShell.Run """" & pythonToUse & """ -m src.main", 0, False

' Script exits immediately, application runs in background
' No console window will appear at all
