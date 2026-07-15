' Lanza autostart_server.bat sin mostrar ninguna ventana de consola.
' Usado por la tarea programada de Windows para arrancar Finanzas Local al iniciar sesion.
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.Run """" & scriptDir & "\autostart_server.bat""", 0, False
