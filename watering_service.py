from gpiozero import LED
from time import sleep
import contextlib
from datetime import datetime, timedelta
import logging

import paho.mqtt.client as mqtt


class IrrigatorModel(object):
    @contextlib.contextmanager
    def active(self):
        #do stuff
        try:
            yield
        except:
            #handle error
            pass
        finally:
            #cleanup
            pass
        

class GPIOMotorModel(IrrigatorModel):
    def __init__(self, en_pin, drive_pin):
        super().__init__()
        
        self.logger         = logging.getLogger('MotorController')
        self.logger.setLevel(logging.DEBUG)
        self.logger.debug(f'Creating MotorModel object with en_pin:{en_pin}, drive_pin:{drive_pin}')       

        self.__en_pin       = en_pin
        self.__drive_pin    = drive_pin
        self.__en           = LED(en_pin)
        self.__drive        = LED(drive_pin)
   
    @contextlib.contextmanager
    def active(self):
        try:
            self.__en.on()
            sleep(0.1)
            self.logger.debug('Motor is enabled.')
            self.__drive.on()        
            sleep(0.1)
            self.logger.debug('Motor is on.')

            yield
        except:
            self.logger.exception('Execution raised while the motor was running.')
        finally:
            self.__drive.off()
            sleep(0.1)
            self.logger.debug('Motor is off.')
            self.__en.off()
            sleep(0.1)
            self.logger.debug('Motor is disabled.')


class IrrigatorController(object):
    log_update_period_sec = 3600
    
    def __init__(self, model, viewers=[]):
        self.__model    = model
        self.__viewers  = viewers
        self.logger     = logging.getLogger('IrrigatorController')
        self.logger.setLevel(logging.DEBUG)

    def _irrigate(self, irrigation_time):
        with self.__model.active():            
            for viewer in self.__viewers:
                viewer.state_changed(is_active=True)

            self.logger.info(f'Watering for {irrigation_time}sec.')
            sleep(irrigation_time)
            self.logger.info('Watering done')

            for viewer in self.__viewers:
                viewer.state_changed(is_active=False)
    
    @contextlib.contextmanager
    def open_viewers(self):
        try:
            for viewer in self.__viewers:
                viewer.open()

            yield
        except:
            self.logger.exception("Exception occured while the irrigator controller was active")
        finally:
            for viewer in self.__viewers:
                viewer.close()


    def do_periodic_irrigation(self, hour, minute, length_sec):
        with self.open_viewers():        
            self.logger.debug(f'Scheduler created with target time: {hour}h. {minute}min')
            self.hour   = hour
            self.minute = minute

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
                    if time_left_sec > self.log_update_period_sec:
                        wait_time = self.log_update_period_sec
                    else:
                        wait_time = time_left_sec
    
                    if wait_time > 0:
                        self.logger.debug(f'Remaining wait time: {time_left_sec}sec.')
                        sleep(wait_time)
    
                    now = datetime.today()


                # do the task
                self.logger.debug('Wait time ready.')
                self._irrigate(length_sec)


class IrrigatorViewer(object):
    def open(self):
        pass

    def close(self):
        pass

    def state_changed(self, is_active=False):
        pass

    def error_handler(self, error_message):
        pass


class HassViewer(IrrigatorViewer):
    def __init__(self, broker_address):
        self._name = "Irrigator"
        self._broker_address = broker_address       

        self.logger     = logging.getLogger('HassViewer')
        self.logger.setLevel(logging.DEBUG)

        self._config_topic  = f"homeassistant/binary_sensor/{self._name}/config"
        self._state_topic   = f"homeassistant/binary_sensor/{self._name}/state"

        self.logger.debug('Home Assistant irrigator viewer created.')
       
    def open(self):
        self.logger.info('Opening the viewer.')
        self._client = mqtt.Client("Irrigator")
        self._client.connect(self._broker_address)
        self.logger.info("Connected to the MQTT broker.")
        self._hass_register()
        self.logger.info("Home Assistant entitiy registered.")

    def _hass_register(self):
        topic = self._config_topic
        payload = '{' + f'''
                         "name": "{self._name}", 
                         "device_class": "moisture", 
                         "state_topic": "{self._state_topic}",
                         "payload_on": "1",
                         "payload_off": "0"
                         ''' + '}'

        self.logger.debug(f'Hass register: topic:{topic}, payload:{payload}')
        self._client.publish(topic, payload)
        sleep(0.5)

    def _hass_deregister(self):
        topic = self._config_topic
        payload = ""
        self.logger.debug('Hass deregister.')
        self._client.publish(topic, payload)

    def close(self):
        self.logger.info('Closing the viewer.')
        self._hass_deregister()
        self._client.disconnect()
        self._client = None

    def state_changed(self, is_active=False):
        topic = self._state_topic
        if is_active is True:
            payload = "1"
        else:
            payload = "0"
        self.logger.debug(f'Hass publish: topic:{topic}, payload:{payload}')
        self._client.publish(topic, payload)
        

    def error_handler(self, error_message):
        pass


if __name__ == '__main__':
    logging.basicConfig(format='%(asctime)-15s %(name)-12s %(levelname)-8s %(message)s')

    motor = GPIOMotorModel(en_pin=20, drive_pin=21)
    viewers = [ HassViewer("192.168.1.100") ]
    controller = IrrigatorController(model=motor, viewers = viewers)

    default_irrigation_time_sec = 10
    controller.do_periodic_irrigation(8, 30, default_irrigation_time_sec)
    

