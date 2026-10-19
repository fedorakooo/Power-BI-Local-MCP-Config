import unittest
from unittest.mock import Mock, patch

from pbirs_mcp.windows_worker import Win32Backend


class CaptureWindowTransitionTests(unittest.TestCase):
    def capture(self, foreground, valid_foreground):
        backend = Win32Backend.__new__(Win32Backend)
        backend.ensure_unlocked = Mock()
        backend.gui = Mock()
        backend.gui.GetForegroundWindow.return_value = foreground
        backend.gui.IsWindow.side_effect = lambda hwnd: hwnd == 7 or valid_foreground
        backend.gui.GetAncestor.side_effect = lambda hwnd, flag: 7 if hwnd == 7 else self.fail('Invalid foreground passed to GetAncestor')
        backend.gui.IsWindowVisible.return_value = True
        backend.gui.GetWindowRect.return_value = (0, 0, 100, 100)
        backend.gui.EnumWindows.return_value = None
        backend.gui.EnumChildWindows.return_value = None
        backend.Application = Mock()
        wrapper = backend.Application.return_value.connect.return_value.window.return_value.wrapper_object.return_value
        wrapper.children.return_value = []
        image = Mock(size=(100, 100), width=100, height=100)
        image.save.side_effect = lambda stream, **kwargs: stream.write(b'png')
        wrapper.capture_as_image.return_value = image
        with patch('ctypes.windll', create=True) as windll:
            windll.user32.GetLastActivePopup.return_value = 0
            state, png = backend.capture({'hwnd': 7, 'pid': 1})
        self.assertEqual(state['hwnd'], 7)
        self.assertEqual(png, b'png')
        wrapper.set_focus.assert_called()

    def test_no_foreground_window_captures_only_enrolled_main(self):
        self.capture(0, False)

    def test_stale_foreground_handle_is_not_dereferenced(self):
        self.capture(99, False)


if __name__ == '__main__':
    unittest.main()
