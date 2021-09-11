from gpiozero import LED
import time
import contextlib
from datetime import datetime, timedelta
import logging
import queue
import threading
import paho.mqtt.client as mqtt


class IrrigationHardwareModel(object):
    @contextlib.contextmanager
    def active(self):
        # do stuff
        try:
            yield
        except:
            # handle error
            pass
        finally:
            # cleanup
            pass
        

class GPIOMotorModel(IrrigationHardwareModel):
    def __init__(self, ch1, ch2, ch3, ch4):
        super().__init__()
        
        self.logger = logging.getLogger('MotorController')
        self.logger.setLevel(logging.DEBUG)

        self.__gpio_num = [ch1, ch2, ch3, ch4]
        self.__gpio =  [ LED(ch) for ch in self.__gpio_num ]

        self.logger.info('GPIOMotorModel created with pins: {self.__gpio_num}')
    
    @contextlib.contextmanager
    def active(self):
        try:
            self.__gpio[0].on()
            time.sleep(0.1)
            self.logger.debug('Motor is on.')

            yield
        except:
            self.logger.exception('Execution raised while the motor was running.')
        finally:
            self.__gpio[0].off()
            time.sleep(0.1)
            self.logger.debug('Motor is off.')


class IrrigationSystemController(object):
    log_update_period_sec = 3600
    
    def __init__(self, model, viewers=()):
        self._queue = queue.Queue()
        self._watchdog_thread = threading.Thread(target=self._watchdog_func)
        self._watchdog_stop_event = threading.Event()
        self._watchdog_check_time = [8, 30]
        self._gardener_thread = threading.Thread(target=self._gardener_func)
        self._gardener_stop_event = threading.Event()

        self.__model = model
        self.__viewers = viewers
        self.logger = logging.getLogger('IrrigationSystemController')
        self.logger.setLevel(logging.DEBUG)

        self.watering_time_sec = 10
        self.watering_blackout_time_sec = 5
        self.watering_wet_time_sec = 5
        self.last_watering_time = datetime.now()

        self._state = 'Dry'
    
    @contextlib.contextmanager
    def open_viewers(self):
        try:
            for viewer in self.__viewers:
                viewer.open(self._queue)

                self.notify_viewers(False)

            yield
        except:
            self.logger.exception("Exception occured while the irrigator controller was active")
        finally:
            for viewer in self.__viewers:
                viewer.close()

    def notify_viewers(self, new_state):
        try:
            for viewer in self.__viewers:
                viewer.set_state(new_state)
        except:
            pass

    def irrigate(self):
        with self.__model.active():
            self.notify_viewers(new_state=True)

            self.logger.info(f'Watering for {self.watering_time_sec}sec.')
            time.sleep(self.watering_time_sec)
            self.logger.info('Watering done')

            self.notify_viewers(new_state=False)

        self.last_watering_time = datetime.now()

    def _watchdog_func(self):
        hour = self._watchdog_check_time[0]
        minute = self._watchdog_check_time[1]
        self.logger.debug(f'Scheduler created with target time: {hour}h. {minute}min')

        while not self._watchdog_stop_event.isSet():
            # generate the new target datetime
            now = datetime.today()
            future = datetime(now.year, now.month, now.day, hour, minute)
            if future <= now:
                future += timedelta(days=1)
                self.logger.info(f'New target datetime: {future}')
                self.logger.info(f'Total wait time: {(future-now).total_seconds()}sec')

            # wait for the target datetime in small units
            while not self._watchdog_stop_event.isSet() and (future > now):
                time_left_sec = (future - now).total_seconds()
                if time_left_sec > self.log_update_period_sec:
                    wait_time = self.log_update_period_sec
                else:
                    wait_time = time_left_sec

                if wait_time > 0:
                    self.logger.debug(f'Remaining wait time: {time_left_sec}sec.')
                    self._watchdog_stop_event.wait(wait_time)

                now = datetime.today()

            # do the task
            if not self._watchdog_stop_event.isSet():
                self.logger.debug('Wait time ready.')
                self._queue.put('Watchdog')

        self.logger.info('Exiting watchdog')

    def _gardener_func(self):
        with self.open_viewers():
            while not self._gardener_stop_event.isSet():

                if self._state == 'Watering':
                    self.logger.info('State: Watering')
                    self.irrigate()
                    self._state = 'Blackout'

                elif self._state == "Blackout":
                    self.logger.info('State: Blackout')
                    enter_time = datetime.now()
                    while True:
                        time_left = 10 - (datetime.now() - enter_time).total_seconds()
                        if time_left < 0:
                            time_left = 0
                        try:
                            cmd = self._queue.get(timeout=time_left)
                            self._queue.task_done()
                        except queue.Empty:
                            cmd = 'TO'

                        if cmd == 'TO':
                            self._state = 'Wet'
                            break
                        if cmd is not None:
                            self.logger.warning(f'Skipping cmd:"{cmd}" in state:"{self._state}"')
                        else:
                            break

                elif self._state == 'Wet':
                    self.logger.info('State: Wet')
                    enter_time = datetime.now()
                    while True:
                        time_left = 30*60 - (datetime.now() - enter_time).total_seconds()
                        if time_left < 0:
                            time_left = 0

                        try:
                            cmd = self._queue.get(timeout=time_left)
                            self._queue.task_done()
                        except queue.Empty:
                            cmd = 'TO'

                        if cmd == 'Trigger':
                            self._state = 'Watering'
                            break
                        elif cmd == 'TO':
                            self._state = 'Dry'
                            break
                        elif cmd is not None:
                            self.logger.warning(f'Skipping cmd:"{cmd}" in state:"{self._state}"')
                        else:
                            break

                elif self._state == 'Dry':
                    self.logger.info('State: Dry')
                    while True:
                        cmd = self._queue.get()
                        self._queue.task_done()

                        if cmd == 'Trigger' or cmd == 'Watchdog':
                            self._state = 'Watering'
                            break
                        elif cmd is not None:
                            self.logger.warning(f'Skipping cmd:"{cmd}" in state:"{self._state}"')
                        else:
                            break

        self.logger.info('Exiting gardener')

    def start(self):
        self._gardener_thread.start()
        self._watchdog_thread.start()

    def stop(self):
        self._watchdog_stop_event.set()
        self._watchdog_thread.join()

        self._gardener_stop_event.set()
        self._queue.put(None)
        self._gardener_thread.join()


class IrrigationSystemMonitor(object):
    def __init__(self, *args, **kwargs):
        self._in_event_queue = queue.Queue()
        self._worker = threading.Thread(target=self._worker_func)
        # Creating a class logger
        self.logger = logging.getLogger('IrrigationSystemMonitor')
        self.logger.setLevel(logging.DEBUG)
 
# -----------------------------------------
# API functions
# -----------------------------------------
    def open(self, cmd_queue):
        self._worker.start()
        event = {'msg':'open', 'arg':cmd_queue}
        self._in_event_queue.put(event) 

    def set_state(self, new_state):
        event = {'msg':'set_state', 'arg':new_state}
        self._in_event_queue.put(event)

    def close(self):
        event = {'msg':'close', 'arg':None}
        self._in_event_queue.put(event)
        self._worker.join()

    def trigger(self):
        event={'msg':'Trigger', 'arg':None}
        self._in_event_queue.put(event)

# ----------------------------------------
# Internal worker and state machine
# ----------------------------------------
    def _worker_func(self):
        old_state = 'idle'
        state = 'idle'
        self._out_event_queue=None

        def get_event():
            event=self._in_event_queue.get()
            msg=event['msg']
            arg=event['arg']
            return msg, arg
            
        while True:
            if state != old_state:
                self.logger.info(f'State change: {old_state} -> {state}')
                old_state = state

            if state == 'idle':
                msg, arg = get_event()
                if msg == 'open':
                    self._out_event_queue = arg                               
                    state = 'connecting'
                elif msg  == 'close':
                    break

            elif state == 'connecting':
                try: 
                    msg, arg = get_event(Timeout=1)
                except:
                    msg = arg = None

                if msg == 'close':
                    break
                elif msg == None:
                    # try to connect
                    conn_ok = False
                    try:
                        self.on_open()
                        conn_ok = True
                    except:
                        conn_ok = False
                        self.logger.exception('Cannot open the monitor')
                        time.sleep(5)

                    if conn_ok == True:
                        # connection established
                        state = 'connected'

            elif state == 'connected':
                msg, arg = get_event()

                if msg == 'close':
                    try:
                        self.on_close()
                    except:
                        self.logger.exception('Exception raised during on_close handling.')
                    break
                elif msg == 'set_state':
                    try:
                        self.on_state_changed(is_active=arg)
                    except:
                        self.logger.exception('Exception raised during set_state handling.')
                        try:
                            self.on_close()
                        except:
                            self.logger.exception('Exception during closing on state changed event handling failure.')
                        state = 'connecting'
                elif msg == 'Trigger':
                    if self._out_event_queue is not None:
                        self._out_event_queue.put('Trigger')                                           
        
# ----------------------------------------
# Event handler functions to override
# ----------------------------------------
    def on_open(self):
        pass

    def on_state_changed(self, is_active=False):
        pass

    def on_error(self, error_message):
        pass

    def on_close(self):
        pass


class HassMonitor(IrrigationSystemMonitor):
    _state_mqtt_topic = "/irrigation/state"
    _trigger_mqtt_topic = "/irrigation/trigger"

    def __init__(self, broker_address):
        super().__init__()
        self._name = "IrrigationSystemMonitor"
        # Overriding the class logger
        self.logger = logging.getLogger('HassViewer')
        self.logger.setLevel(logging.DEBUG)
        # Basic MQTT and HASS parameters
        self._broker_address = broker_address
        self._config_topic = f"homeassistant/binary_sensor/{self._name}/config"
        self.logger.debug('Home Assistant irrigator viewer created.')
        # Creating an MQTT client
        self._client = mqtt.Client("IrrigatorClient")
        self._client.on_connect = self._on_mqtt_connect
        self._client.on_message = self._on_mqtt_message

    def _on_mqtt_connect(self, client: mqtt.Client, _userdata, _flags, _rc):
        self.logger.debug("Boker connection OK.")

        self.logger.debug("Registering to the HomeAssistant MQTT discovery")        
        topic = self._config_topic
        payload = '{' + f'''
                         "name": "{self._name}", 
                         "device_class": "moisture", 
                         "state_topic": "{self._state_mqtt_topic}",
                         "payload_on": "1",
                         "payload_off": "0"
                         ''' + '}'

        self.logger.debug(f'Hass register: topic:{topic}, payload:{payload}')
        self._client.publish(topic, payload)
        time.sleep(0.5)
        self.logger.info("Home Assistant entitiy registered.")

        self.logger.debug(f"Subscribint to the trigger mqtt topic: {self._trigger_mqtt_topic}")
        client.subscribe(self._trigger_mqtt_topic)

    def _on_mqtt_message(self, _client, _userdata, msg):
        topic = msg.topic
        payload = msg.payload
        self.logger.debug(f'MQTT message received: topic:"{topic}", payload:"{payload}"')
        if topic == self._trigger_mqtt_topic:
            self.logger.info("Tiggering watering.")
            self.trigger()

    def on_open(self):
        self.logger.info('Opening the viewer.')
        self.logger.debug("Connecting to the broker.")
        self._client.connect(self._broker_address)
        self.logger.debug("Starting the event loop.")
        self._client.loop_start()

    def on_close(self):
        self.logger.info('Closing the viewer.')
        self._client.loop_stop()
        self._client.disconnect()
        self._client = None

    def on_state_changed(self, is_active=False):
        topic = self._state_mqtt_topic
        if is_active is True:
            payload = "1"
        else:
            payload = "0"
        self.logger.debug(f'Hass publish: topic:{topic}, payload:{payload}')
        self._client.publish(topic, payload)

    def on_error(self, error_message):
        pass


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)-15s %(name)-12s %(levelname)-8s %(message)s')

    motor = GPIOMotorModel( ch1=5, ch2=6, ch3=13, ch4=26)
    viewers = [HassMonitor("192.168.1.100")]
    controller = IrrigationSystemController(model=motor, viewers=viewers)

    controller.start()

