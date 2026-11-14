from io import BytesIO
from threading import Event
from unittest import TestCase
from unittest.mock import Mock, patch

from PIL import Image

from wireless.console.device import Device
from wireless.console.observation import after_action
from wireless.console.screen import ScreenFrame


def frame(number, at, level=100):
    stream = BytesIO()
    Image.new('RGB', (96, 72), (level, level, level)).save(stream, 'JPEG')
    return ScreenFrame(number, at, stream.getvalue(), 96, 72)


class FeedbackReuseTests(TestCase):
    def setUp(self):
        self.source = Mock()
        self.source.get_frame.return_value = frame(1, 9.9)
        with patch('wireless.console.device.NetworkLink'), \
                patch('wireless.console.device.AirPlaySource', return_value=self.source), \
                patch('wireless.console.device.Thread'):
            self.device = Device()
        self.stop = Event()
        self.clock = patch('wireless.console.device.time.monotonic', return_value=10.1)
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)

    def click(self, result='changed'):
        observed = frame(8, 10.0, 150)

        def observe(*args):
            self.source.get_frame.return_value = observed
            return observed, result

        with patch('wireless.console.device.after_action', side_effect=observe):
            self.assertTrue(self.device.command('click', self.stop))
        return observed

    def test_returns_newest_unchanged_frame_once_without_waiting(self):
        self.click()
        newest = frame(9, 10.05, 150)
        self.source.get_frame.return_value = newest
        self.source.get_frame.reset_mock()
        self.assertIs(self.device.consume_observation_frame(self.stop), newest)
        self.source.get_frame.assert_called_once_with()
        self.assertIsNone(self.device.consume_observation_frame(self.stop))

    def test_later_transition_requires_normal_settle(self):
        self.click()
        self.source.get_frame.return_value = frame(9, 10.05, 190)
        self.assertIsNone(self.device.consume_observation_frame(self.stop))

    def test_expired_feedback_not_renewed_by_later_frame(self):
        self.click()
        self.now.return_value = 11.0
        self.source.get_frame.return_value = frame(30, 11.0, 150)
        self.assertIsNone(self.device.consume_observation_frame(self.stop))

    def test_feedback_not_shared_between_tasks(self):
        self.click()
        self.assertIsNone(self.device.consume_observation_frame(Event()))
        self.assertIsNone(self.device.consume_observation_frame(self.stop))

    def test_cancel_discards_result(self):
        self.click()
        self.stop.set()
        self.assertIsNone(self.device.consume_observation_frame(self.stop))

    def test_following_command_invalidates_feedback(self):
        self.click()
        self.device.command('move 1 0', self.stop)
        self.assertIsNone(self.device.consume_observation_frame(self.stop))

    def test_animation_timeout_is_not_settled_feedback(self):
        self.click('animating')
        self.assertIsNone(self.device.consume_observation_frame(self.stop))

    def test_outage_invalidates_feedback(self):
        self.click()
        self.source.get_frame.return_value = None
        self.assertIsNone(self.device.consume_observation_frame(self.stop))

    def test_intervening_command_during_observation_invalidates_feedback(self):
        observed = frame(8, 10.0, 150)

        def observe(*args):
            self.device.command('move 1 0')
            self.source.get_frame.return_value = observed
            return observed, 'changed'

        with patch('wireless.console.device.after_action', side_effect=observe):
            self.device.command('click', self.stop)
        self.assertIsNone(self.device.consume_observation_frame(self.stop))


class ObservationTests(TestCase):
    def observe(self, frames, timeout=.5):
        now = [10.0]
        source = Mock()
        pending = iter(frames)

        def next_frame(after, timeout):
            current = next(pending, None)
            now[0] = current.time if current else now[0] + timeout
            return current

        source.get_frame.side_effect = next_frame
        with patch('wireless.console.observation.time.monotonic', side_effect=lambda: now[0]):
            return after_action(source, frame(1, 9.9), 10.0, Event(), timeout=timeout)

    def test_old_decoder_frames_do_not_count_as_action_feedback(self):
        frames = [frame(2, 10.05, 150), frame(3, 10.10, 150)]
        frames += [frame(4 + n, 10.15 + n * .04, 150) for n in range(5)]
        observed, result = self.observe(frames)
        self.assertEqual(result, 'changed')
        self.assertGreaterEqual(observed.time, 10.29)

    def test_small_continuous_motion_timeout_is_not_unchanged(self):
        frames = [frame(2 + n, 10.13 + n * .04, 100 + n % 2) for n in range(10)]
        _, result = self.observe(frames)
        self.assertEqual(result, 'animating')

    def test_missing_post_action_frame_stops_execution(self):
        with self.assertRaisesRegex(RuntimeError, '未收到动作后的新画面'):
            self.observe([frame(2, 10.05)])
