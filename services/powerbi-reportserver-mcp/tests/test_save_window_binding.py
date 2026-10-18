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
        self.backend.gui.GetAncestor.return_value = 7
        self.backend.gui.EnumChildWindows.side_effect = lambda hwnd, callback, arg: callback(42, arg)
        self.backend.process = Mock()
        self.backend.process.GetWindowThreadProcessId.side_effect = lambda hwnd: (1, 9972 if hwnd == 7 else 8888)
        self.backend.Application = Mock()
        self.application = self.backend.Application.return_value
        self.window = self.application.connect.return_value.window.return_value
        self.button = Mock()
        self.button.element_info.automation_id = 'save'
        self.button.is_enabled.return_value = True
        self.window.descendants.return_value = [self.button]

    def test_separate_webview_process_uses_native_handle_without_process_probe(self):
        method = self.backend.invoke_save({'hwnd': 7, 'pid': 9972})
        self.assertEqual(method, 'uia_button')
        self.application.connect.assert_called_once_with(handle=42)
        self.button.iface_invoke.Invoke.assert_called_once_with()

    def test_duplicate_save_controls_use_shortcut_on_verified_main_window(self):
        second = Mock()
        second.element_info.automation_id = 'save'
        second.is_enabled.return_value = True
        self.window.descendants.return_value = [self.button, second]
        result = self.backend.invoke_save({'hwnd': 7, 'pid': 9972})
        self.assertEqual(result, 'ctrl+s_fallback')
        self.application.connect.assert_any_call(handle=7)
        self.window.set_focus.assert_called_once_with()
        self.window.type_keys.assert_called_once_with('^s', set_foreground=True)
        self.button.iface_invoke.Invoke.assert_not_called()

    def test_no_save_control_uses_shortcut_on_verified_main_window(self):
        self.window.descendants.return_value = []
        result = self.backend.invoke_save({'hwnd': 7, 'pid': 9972})
        self.assertEqual(result, 'ctrl+s_fallback')
        self.window.type_keys.assert_called_once_with('^s', set_foreground=True)

    def test_reused_view_handle_cannot_save_another_process(self):
        self.backend.gui.GetAncestor.return_value = 99
        with self.assertRaisesRegex(RuntimeError, 'ownership changed'):
            self.backend.invoke_save({'hwnd': 7, 'pid': 9972})
        self.application.connect.assert_not_called()
        self.button.iface_invoke.Invoke.assert_not_called()

    def test_reused_main_handle_cannot_save_another_desktop_process(self):
        self.backend.process.GetWindowThreadProcessId.side_effect = lambda hwnd: (1, 1234)
        with self.assertRaisesRegex(RuntimeError, 'ownership changed'):
            self.backend.invoke_save({'hwnd': 7, 'pid': 9972})
        self.button.iface_invoke.Invoke.assert_not_called()


if __name__ == '__main__':
    unittest.main()
