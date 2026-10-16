import unittest
from unittest.mock import Mock

from pbirs_mcp.windows_worker import Win32Backend


class SaveWindowBindingTests(unittest.TestCase):
    def setUp(self):
        self.backend = Win32Backend.__new__(Win32Backend)
        self.backend.ensure_unlocked = Mock()
        self.backend.gui = Mock()
        self.backend.gui.IsWindowEnabled.return_value = True
        self.backend.gui.GetClassName.return_value = 'Chrome_WidgetWin_1'
        self.backend.gui.GetWindowText.return_value = 'ms-pbi.pbi.microsoft.com/minerva/reportView.html'
        self.backend.gui.EnumChildWindows.side_effect = lambda hwnd, callback, arg: callback(42, arg)
        self.backend.process = Mock()
        self.backend.process.GetWindowThreadProcessId.return_value = (1, 9972)
        self.backend.Application = Mock()
        self.application = self.backend.Application.return_value
        self.window = self.application.connect.return_value.window.return_value
        self.button = Mock()
        self.button.element_info.automation_id = 'save'
        self.button.is_enabled.return_value = True
        self.window.descendants.return_value = [self.button]

    def test_native_handle_binding_does_not_probe_process_access_rights(self):
        self.backend.invoke_save({'hwnd': 7, 'pid': 9972})
        self.application.connect.assert_called_once_with(handle=42)
        self.button.iface_invoke.Invoke.assert_called_once_with()

    def test_reused_view_handle_cannot_save_another_process(self):
        self.backend.process.GetWindowThreadProcessId.return_value = (1, 1234)
        with self.assertRaisesRegex(RuntimeError, 'process changed'):
            self.backend.invoke_save({'hwnd': 7, 'pid': 9972})
        self.application.connect.assert_not_called()
        self.button.iface_invoke.Invoke.assert_not_called()


if __name__ == '__main__':
    unittest.main()
