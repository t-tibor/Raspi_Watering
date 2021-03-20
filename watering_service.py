from gpiozero import LED
from time import sleep
import contextlib
from datetime import datetime, timedelta
import logging


class Irrigator(object):
    def __init__(self, en_pin, drive_pin):
        self.logger = logging.getLogger('Irrigator')
        self.logger.setLevel(logging.DEBUG)

        self.logger.debug(f'Creating Irrigator object with en_pin:{en_pin}, drive_pin:{drive_pin}')

        self._en_pin = en_pin
        self._drive_pin = drive_pin

        self.en = LED(en_pin)
        self.drive = LED(drive_pin)

    @contextlib.contextmanager
    def _motor_enabled(self):
        self.en.on()
        sleep(0.1)
        self.logger.debug('Motor enabled')
        try:
            yield
        except:
            self.logger.error('Execution raised while the motor was enabled.')
            raise
        finally:
            self.en.off()
            sleep(0.1)
            self.logger.debug('Motor disabled')

    @contextlib.contextmanager
    def _motor_on(self):
        self.drive.on()
        sleep(0.1)
        self.logger.debug('Motor running')
        try:
            yield
        except:
            self.logger.error('Execution raised while the motor was on.')
            raise
        finally:
            self.drive.off()
            sleep(0.1)
            self.logger.debug('Motor stopped')

    def irrigate(self, irrigation_time):
        with self._motor_enabled():
            with self._motor_on():
                self.logger.info(f'Watering for {irrigation_time}sec.')
                sleep(irrigation_time)
                self.logger.info('Watering done')


class DailyScheduler(object):
    def __init__(self, hour, minute):
        self.logger = logging.getLogger('Scheduler')
        self.logger.setLevel(logging.DEBUG)

        self.logger.debug(f'Scheduler created with target time: {hour}h. {minute}min')

        self.hour = hour
        self.minute = minute

    def run_sync(self, task_func):
        self.logger.info('Starting job scheduler...')
        while True:
            # generate the new target datetime
            now = datetime.today()
            future = datetime(now.year, now.month, now.day, self.hour, self.minute)
            if future <= now:
                future += timedelta(days=1)
                self.logger.info(f'New target datetime: {future}')
                self.logger.info(f'Total wait time: {(future-now).total_seconds()}sec')								

           # wait for the target datetime in small units
            while future > now:
                time_left_sec = (future - now).total_seconds()
                if time_left_sec > 10:
                    wait_time = 10
                else:
                    wait_time = time_left_sec

                if wait_time > 0:
                    self.logger.debug(f'Remaining wait time: {time_left_sec}sec.')
                    sleep(wait_time)

                now = datetime.today()


            # do the task
            self.logger.info('Executing task function')
            task_func()
            self.logger.info('Task function finished')


if __name__ == '__main__':
    logging.basicConfig(format='%(asctime)-15s %(name)-12s %(levelname)-8s %(message)s')

    irrigator = Irrigator(en_pin=20, drive_pin=21)
    default_irrigation_time_sec = 5

    scheduler = DailyScheduler(hour=12, minute=0)


    def irrigation_task():
        irrigator.irrigate(irrigation_time=default_irrigation_time_sec)


    scheduler.run_sync(task_func=irrigation_task)

