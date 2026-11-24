import sys

if __name__ == '__main__':
    if sys.argv[1:] == ['--lock-session']:
        from gaming_control.windows import lock_this_session
        sys.exit(lock_this_session())
    if len(sys.argv) == 4 and sys.argv[1] == '--focus-helper':
        from gaming_control.focus_session import helper_main
        sys.exit(helper_main(sys.argv[2], sys.argv[3]))
    if len(sys.argv) == 5 and sys.argv[1] == '--popup-helper':
        from gaming_control.popup_helper import popup_helper_main
        sys.exit(popup_helper_main(sys.argv[2], sys.argv[3], sys.argv[4]))
    import servicemanager
    import win32serviceutil
    from gaming_control.service import GamingService

    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(GamingService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(GamingService)
