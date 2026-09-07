; QCnext NSIS installer hooks — ensure the Python backend sidecar does not
; block updates. The backend (qualcoder-backend.exe) is a child of the
; frontend (qcnext.exe) and outlives a plain taskkill of the frontend,
; leaving file locks in $INSTDIR\backend that make the update fail.
;
; The main binary is already handled by Tauri's own CheckIfAppIsRunning
; call. These hooks silently terminate the backend before any file copy
; (install) or removal (uninstall) so the directory can be replaced.

!macro NSIS_HOOK_PREINSTALL
  ; Silent backend kill — no extra prompt, just ensure it doesn't block.
  !if "${INSTALLMODE}" == "currentUser"
    nsis_tauri_utils::FindProcessCurrentUser "qualcoder-backend.exe"
  !else
    nsis_tauri_utils::FindProcess "qualcoder-backend.exe"
  !endif
  Pop $R0
  ${If} $R0 == 0
    !if "${INSTALLMODE}" == "currentUser"
      nsis_tauri_utils::KillProcessCurrentUser "qualcoder-backend.exe"
    !else
      nsis_tauri_utils::KillProcess "qualcoder-backend.exe"
    !endif
    Pop $R0
    Sleep 500
  ${EndIf}
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !if "${INSTALLMODE}" == "currentUser"
    nsis_tauri_utils::FindProcessCurrentUser "qualcoder-backend.exe"
  !else
    nsis_tauri_utils::FindProcess "qualcoder-backend.exe"
  !endif
  Pop $R0
  ${If} $R0 == 0
    !if "${INSTALLMODE}" == "currentUser"
      nsis_tauri_utils::KillProcessCurrentUser "qualcoder-backend.exe"
    !else
      nsis_tauri_utils::KillProcess "qualcoder-backend.exe"
    !endif
    Pop $R0
    Sleep 500
  ${EndIf}
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; A full install is a new baseline: drop derived delta state (downloaded
  ; patches, staged plans, backups) so a stale overlay can never pin the
  ; old UI or sources over the fresh install. User data (projects,
  ; settings.json) lives directly under .qualcoder and is untouched.
  ; $PROFILE is the installing user's profile (installMode is currentUser).
  ClearErrors
  RMDir /r "$PROFILE\.qualcoder\hotpatch"
  RMDir /r "$PROFILE\.qualcoder\patches"
!macroend
