#!/usr/bin/env python3
"""入口：启动邮件助手原生 macOS 窗口。"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import objc
from Foundation import NSObject
from AppKit import NSApplication

from ui.mail_window import MailWindow


class _AppDelegate(NSObject):

    def applicationDidFinishLaunching_(self, notification):
        self._win = MailWindow.alloc().init()
        self._win.show()

    def applicationShouldTerminateAfterLastWindowClosed_(self, app):
        return True


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(0)  # NSApplicationActivationPolicyRegular
    delegate = _AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.activateIgnoringOtherApps_(True)
    app.run()


if __name__ == "__main__":
    main()
