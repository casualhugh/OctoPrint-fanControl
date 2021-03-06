# coding=utf-8
from __future__ import absolute_import

__author__ = "Hugh Ebeling <kantlivelong@gmail.com>"
__license__ = "GNU Affero General Public License http://www.gnu.org/licenses/agpl.html"
__copyright__ = "Copyright (C) 2017 Shawn Bruce - Released under terms of the AGPLv3 License"

import octoprint.plugin
from octoprint.server import user_permission
import time
import subprocess
import threading
import os
from flask import make_response, jsonify

try:
    from octoprint.util import ResettableTimer
except:
    class ResettableTimer(threading.Thread):
        def __init__(self, interval, function, args=None, kwargs=None, on_reset=None, on_cancelled=None):
            threading.Thread.__init__(self)
            self._event = threading.Event()
            self._mutex = threading.Lock()
            self.is_reset = True

            if args is None:
                args = []
            if kwargs is None:
                kwargs = dict()

            self.interval = interval
            self.function = function
            self.args = args
            self.kwargs = kwargs
            self.on_cancelled = on_cancelled
            self.on_reset = on_reset


        def run(self):
            while self.is_reset:
                with self._mutex:
                    self.is_reset = False
                self._event.wait(self.interval)

            if not self._event.isSet():
                self.function(*self.args, **self.kwargs)
            with self._mutex:
                self._event.set()

        def cancel(self):
            with self._mutex:
                self._event.set()

            if callable(self.on_cancelled):
                self.on_cancelled()

        def reset(self, interval=None):
            with self._mutex:
                if interval:
                    self.interval = interval

                self.is_reset = True
                self._event.set()
                self._event.clear()

            if callable(self.on_reset):
                self.on_reset()


class fanControl(octoprint.plugin.StartupPlugin,
                   octoprint.plugin.TemplatePlugin,
                   octoprint.plugin.AssetPlugin,
                   octoprint.plugin.SettingsPlugin,
                   octoprint.plugin.SimpleApiPlugin):

    def __init__(self):
        try:
            global GPIO
            import RPi.GPIO as GPIO
            self._hasGPIO = True
        except (ImportError, RuntimeError):
            self._hasGPIO = False

        self._pin_to_gpio_rev1 = [-1, -1, -1, 0, -1, 1, -1, 4, 14, -1, 15, 17, 18, 21, -1, 22, 23, -1, 24, 10, -1, 9, 25, 11, 8, -1, 7, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1 ]
        self._pin_to_gpio_rev2 = [-1, -1, -1, 2, -1, 3, -1, 4, 14, -1, 15, 17, 18, 27, -1, 22, 23, -1, 24, 10, -1, 9, 25, 11, 8, -1, 7, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1 ]
        self._pin_to_gpio_rev3 = [-1, -1, -1, 2, -1, 3, -1, 4, 14, -1, 15, 17, 18, 27, -1, 22, 23, -1, 24, 10, -1, 9, 25, 11, 8, -1, 7, -1, -1, 5, -1, 6, 12, 13, -1, 19, 16, 26, 20, -1, 21 ]

        self.GPIOMode = ''
        self.switchingMethod = ''
        self.onoffGPIOPin = 0
        self.invertonoffGPIOPin = False
        self.onGCodeCommand = ''
        self.offGCodeCommand = ''
        self.onSysCommand = ''
        self.offSysCommand = ''
        self.enablePseudoOnOff = False
        self.pseudoOnGCodeCommand = ''
        self.pseudoOffGCodeCommand = ''
        self.postOnDelay = 0.0
        self.autoOn = False
        self.autoOnTriggerGCodeCommands = ''
        self._autoOnTriggerGCodeCommandsArray = []
        self.enablePowerOffWarningDialog = True
        self.powerOffWhenIdle = False
        self.idleTimeout = 0
        self.idleIgnoreCommands = ''
        self._idleIgnoreCommandsArray = []
        self.idleTimeoutWaitTemp = 0
        self.disconnectOnPowerOff = False
        self.sensingMethod = ''
        self.sensePollingInterval = 0
        self.senseGPIOPin = 0
        self.invertsenseGPIOPin = False
        self.senseGPIOPinPUD = ''
        self.senseSystemCommand = ''
        self.isfanOn = False
        self._noSensing_isfanOn = False
        self._check_fan_state_thread = None
        self._check_fan_state_event= threading.Event()
        self._idleTimer = None
        self._waitForHeaters = False
        self._skipIdleTimer = False
        self._configuredGPIOPins = []


    def on_settings_initialized(self):
        self.GPIOMode = self._settings.get(["GPIOMode"])
        self._logger.debug("GPIOMode: %s" % self.GPIOMode)

        self.switchingMethod = self._settings.get(["switchingMethod"])
        self._logger.debug("switchingMethod: %s" % self.switchingMethod)

        self.onoffGPIOPin = self._settings.get_int(["onoffGPIOPin"])
        self._logger.debug("onoffGPIOPin: %s" % self.onoffGPIOPin)

        self.invertonoffGPIOPin = self._settings.get_boolean(["invertonoffGPIOPin"])
        self._logger.debug("invertonoffGPIOPin: %s" % self.invertonoffGPIOPin)

        self.onGCodeCommand = self._settings.get(["onGCodeCommand"])
        self._logger.debug("onGCodeCommand: %s" % self.onGCodeCommand)

        self.offGCodeCommand = self._settings.get(["offGCodeCommand"])
        self._logger.debug("offGCodeCommand: %s" % self.offGCodeCommand)

        self.onSysCommand = self._settings.get(["onSysCommand"])
        self._logger.debug("onSysCommand: %s" % self.onSysCommand)

        self.offSysCommand = self._settings.get(["offSysCommand"])
        self._logger.debug("offSysCommand: %s" % self.offSysCommand)

        self.enablePseudoOnOff = self._settings.get_boolean(["enablePseudoOnOff"])
        self._logger.debug("enablePseudoOnOff: %s" % self.enablePseudoOnOff)

        if self.enablePseudoOnOff and self.switchingMethod == 'GCODE':
            self._logger.warning("Pseudo On/Off cannot be used in conjunction with GCODE switching.")
            self.enablePseudoOnOff = False

        self.pseudoOnGCodeCommand = self._settings.get(["pseudoOnGCodeCommand"])
        self._logger.debug("pseudoOnGCodeCommand: %s" % self.pseudoOnGCodeCommand)

        self.pseudoOffGCodeCommand = self._settings.get(["pseudoOffGCodeCommand"])
        self._logger.debug("pseudoOffGCodeCommand: %s" % self.pseudoOffGCodeCommand)

        self.postOnDelay = self._settings.get_float(["postOnDelay"])
        self._logger.debug("postOnDelay: %s" % self.postOnDelay)

        self.disconnectOnPowerOff = self._settings.get_boolean(["disconnectOnPowerOff"])
        self._logger.debug("disconnectOnPowerOff: %s" % self.disconnectOnPowerOff)

        self.sensingMethod = self._settings.get(["sensingMethod"])
        self._logger.debug("sensingMethod: %s" % self.sensingMethod)

        self.sensePollingInterval = self._settings.get_int(["sensePollingInterval"])
        self._logger.debug("sensePollingInterval: %s" % self.sensePollingInterval)

        self.senseGPIOPin = self._settings.get_int(["senseGPIOPin"])
        self._logger.debug("senseGPIOPin: %s" % self.senseGPIOPin)

        self.invertsenseGPIOPin = self._settings.get_boolean(["invertsenseGPIOPin"])
        self._logger.debug("invertsenseGPIOPin: %s" % self.invertsenseGPIOPin)

        self.senseGPIOPinPUD = self._settings.get(["senseGPIOPinPUD"])
        self._logger.debug("senseGPIOPinPUD: %s" % self.senseGPIOPinPUD)

        self.senseSystemCommand = self._settings.get(["senseSystemCommand"])
        self._logger.debug("senseSystemCommand: %s" % self.senseSystemCommand)

        self.autoOn = self._settings.get_boolean(["autoOn"])
        self._logger.debug("autoOn: %s" % self.autoOn)

        self.autoOnTriggerGCodeCommands = self._settings.get(["autoOnTriggerGCodeCommands"])
        self._autoOnTriggerGCodeCommandsArray = self.autoOnTriggerGCodeCommands.split(',')
        self._logger.debug("autoOnTriggerGCodeCommands: %s" % self.autoOnTriggerGCodeCommands)

        self.enablePowerOffWarningDialog = self._settings.get_boolean(["enablePowerOffWarningDialog"])
        self._logger.debug("enablePowerOffWarningDialog: %s" % self.enablePowerOffWarningDialog)

        self.powerOffWhenIdle = self._settings.get_boolean(["powerOffWhenIdle"])
        self._logger.debug("powerOffWhenIdle: %s" % self.powerOffWhenIdle)

        self.idleTimeout = self._settings.get_int(["idleTimeout"])
        self._logger.debug("idleTimeout: %s" % self.idleTimeout)

        self.idleIgnoreCommands = self._settings.get(["idleIgnoreCommands"])
        self._idleIgnoreCommandsArray = self.idleIgnoreCommands.split(',')
        self._logger.debug("idleIgnoreCommands: %s" % self.idleIgnoreCommands)

        self.idleTimeoutWaitTemp = self._settings.get_int(["idleTimeoutWaitTemp"])
        self._logger.debug("idleTimeoutWaitTemp: %s" % self.idleTimeoutWaitTemp)

        if self.switchingMethod == 'GCODE':
            self._logger.info("Using G-Code Commands for On/Off")
        elif self.switchingMethod == 'GPIO':
            self._logger.info("Using GPIO for On/Off")
        elif self.switchingMethod == 'SYSTEM':
            self._logger.info("Using System Commands for On/Off")
            
        if self.sensingMethod == 'INTERNAL':
            self._logger.info("Using internal tracking for fan on/off state.")
        elif self.sensingMethod == 'GPIO':
            self._logger.info("Using GPIO for tracking fan on/off state.")
        elif self.sensingMethod == 'SYSTEM':
            self._logger.info("Using System Commands for tracking fan on/off state.")
            
        if self.switchingMethod == 'GPIO' or self.sensingMethod == 'GPIO':
            self._configure_gpio()

        self._check_fan_state_thread = threading.Thread(target=self._check_fan_state)
        self._check_fan_state_thread.daemon = True
        self._check_fan_state_thread.start()

        self._start_idle_timer()

    def _gpio_board_to_bcm(self, pin):
        if GPIO.RPI_REVISION == 1:
            pin_to_gpio = self._pin_to_gpio_rev1
        elif GPIO.RPI_REVISION == 2:
            pin_to_gpio = self._pin_to_gpio_rev2
        else:
            pin_to_gpio = self._pin_to_gpio_rev3

        return pin_to_gpio[pin]

    def _gpio_bcm_to_board(self, pin):
        if GPIO.RPI_REVISION == 1:
            pin_to_gpio = self._pin_to_gpio_rev1
        elif GPIO.RPI_REVISION == 2:
            pin_to_gpio = self._pin_to_gpio_rev2
        else:
            pin_to_gpio = self._pin_to_gpio_rev3

        return pin_to_gpio.index(pin)

    def _gpio_get_pin(self, pin):
        if (GPIO.getmode() == GPIO.BOARD and self.GPIOMode == 'BOARD') or (GPIO.getmode() == GPIO.BCM and self.GPIOMode == 'BCM'):
            return pin
        elif GPIO.getmode() == GPIO.BOARD and self.GPIOMode == 'BCM':
            return self._gpio_bcm_to_board(pin)
        elif GPIO.getmode() == GPIO.BCM and self.GPIOMode == 'BOARD':
            return self._gpio_board_to_bcm(pin)
        else:
            return 0

    def _configure_gpio(self):
        if not self._hasGPIO:
            self._logger.error("RPi.GPIO is required.")
            return
        
        self._logger.info("Running RPi.GPIO version %s" % GPIO.VERSION)
        if GPIO.VERSION < "0.6":
            self._logger.error("RPi.GPIO version 0.6.0 or greater required.")
        
        GPIO.setwarnings(False)

        for pin in self._configuredGPIOPins:
            self._logger.debug("Cleaning up pin %s" % pin)
            try:
                GPIO.cleanup(self._gpio_get_pin(pin))
            except (RuntimeError, ValueError) as e:
                self._logger.error(e)
        self._configuredGPIOPins = []

        if GPIO.getmode() is None:
            if self.GPIOMode == 'BOARD':
                GPIO.setmode(GPIO.BOARD)
            elif self.GPIOMode == 'BCM':
                GPIO.setmode(GPIO.BCM)
            else:
                return
        
        if self.sensingMethod == 'GPIO':
            self._logger.info("Using GPIO sensing to determine fan on/off state.")
            self._logger.info("Configuring GPIO for pin %s" % self.senseGPIOPin)

            if self.senseGPIOPinPUD == 'PULL_UP':
                pudsenseGPIOPin = GPIO.PUD_UP
            elif self.senseGPIOPinPUD == 'PULL_DOWN':
                pudsenseGPIOPin = GPIO.PUD_DOWN
            else:
                pudsenseGPIOPin = GPIO.PUD_OFF
    
            try:
                GPIO.setup(self._gpio_get_pin(self.senseGPIOPin), GPIO.IN, pull_up_down=pudsenseGPIOPin)
                self._configuredGPIOPins.append(self.senseGPIOPin)
            except (RuntimeError, ValueError) as e:
                self._logger.error(e)
        
        if self.switchingMethod == 'GPIO':
            self._logger.info("Using GPIO for On/Off")
            self._logger.info("Configuring GPIO for pin %s" % self.onoffGPIOPin)
            try:
                if not self.invertonoffGPIOPin:
                    initial_pin_output=GPIO.LOW
                else:
                    initial_pin_output=GPIO.HIGH
                GPIO.setup(self._gpio_get_pin(self.onoffGPIOPin), GPIO.OUT, initial=initial_pin_output)
                self._configuredGPIOPins.append(self.onoffGPIOPin)
            except (RuntimeError, ValueError) as e:
                self._logger.error(e)

    def check_fan_state(self):
        self._check_fan_state_event.set()

    def _check_fan_state(self):
        while True:
            old_isfanOn = self.isfanOn

            if self.sensingMethod == 'GPIO':
                if not self._hasGPIO:
                    return

                self._logger.debug("Polling fan state...")

                r = 0
                try:
                    r = GPIO.input(self._gpio_get_pin(self.senseGPIOPin))
                except (RuntimeError, ValueError) as e:
                    self._logger.error(e)
                self._logger.debug("Result: %s" % r)

                if r==1:
                    new_isfanOn = True
                elif r==0:
                    new_isfanOn = False

                if self.invertsenseGPIOPin:
                    new_isfanOn = not new_isfanOn

                self.isfanOn = new_isfanOn
            elif self.sensingMethod == 'SYSTEM':
                new_isfanOn = False

                p = subprocess.Popen(self.senseSystemCommand, shell=True)
                self._logger.debug("Sensing system command executed. PID=%s, Command=%s" % (p.pid, self.senseSystemCommand))
                while p.poll() is None:
                    time.sleep(0.1)
                r = p.returncode
                self._logger.debug("Sensing system command returned: %s" % r)

                if r==0:
                    new_isfanOn = True
                elif r==1:
                    new_isfanOn = False

                self.isfanOn = new_isfanOn
            elif self.sensingMethod == 'INTERNAL':
                self.isfanOn = self._noSensing_isfanOn
            else:
                return
            
            self._logger.debug("isfanOn: %s" % self.isfanOn)

            if (old_isfanOn != self.isfanOn) and self.isfanOn:
                self._start_idle_timer()
            elif (old_isfanOn != self.isfanOn) and not self.isfanOn:
                self._stop_idle_timer()

            self._plugin_manager.send_plugin_message(self._identifier, dict(hasGPIO=self._hasGPIO, isfanOn=self.isfanOn))

            self._check_fan_state_event.wait(self.sensePollingInterval)
            self._check_fan_state_event.clear()

    def _start_idle_timer(self):
        self._stop_idle_timer()
        
        if self.powerOffWhenIdle and self.isfanOn:
            self._idleTimer = ResettableTimer(self.idleTimeout * 60, self._idle_poweroff)
            self._idleTimer.start()

    def _stop_idle_timer(self):
        if self._idleTimer:
            self._idleTimer.cancel()
            self._idleTimer = None

    def _reset_idle_timer(self):
        try:
            if self._idleTimer.is_alive():
                self._idleTimer.reset()
            else:
                raise Exception()
        except:
            self._start_idle_timer()

    def _idle_poweroff(self):
        if not self.powerOffWhenIdle:
            return
        
        if self._waitForHeaters:
            return
        
        if self._printer.is_printing() or self._printer.is_paused():
            return

        self._logger.info("Idle timeout reached after %s minute(s). Turning heaters off prior to shutting off fan." % self.idleTimeout)
        if self._wait_for_heaters():
            self._logger.info("Heaters below temperature.")
            self.turn_fan_off()
        else:
            self._logger.info("Aborted fan shut down due to activity.")

    def _wait_for_heaters(self):
        self._waitForHeaters = True
        heaters = self._printer.get_current_temperatures()
        
        for heater, entry in heaters.items():
            target = entry.get("target")
            if target is None:
                # heater doesn't exist in fw
                continue

            try:
                temp = float(target)
            except ValueError:
                # not a float for some reason, skip it
                continue

            if temp != 0:
                self._logger.info("Turning off heater: %s" % heater)
                self._skipIdleTimer = True
                self._printer.set_temperature(heater, 0)
                self._skipIdleTimer = False
            else:
                self._logger.debug("Heater %s already off." % heater)

        while True:
            if not self._waitForHeaters:
                return False
            
            heaters = self._printer.get_current_temperatures()
            
            highest_temp = 0
            heaters_above_waittemp = []
            for heater, entry in heaters.items():
                if not heater.startswith("tool"):
                    continue

                actual = entry.get("actual")
                if actual is None:
                    # heater doesn't exist in fw
                    continue

                try:
                    temp = float(actual)
                except ValueError:
                    # not a float for some reason, skip it
                    continue

                self._logger.debug("Heater %s = %sC" % (heater,temp))
                if temp > self.idleTimeoutWaitTemp:
                    heaters_above_waittemp.append(heater)
                
                if temp > highest_temp:
                    highest_temp = temp
                
            if highest_temp <= self.idleTimeoutWaitTemp:
                self._waitForHeaters = False
                return True
            
            self._logger.info("Waiting for heaters(%s) before shutting off fan..." % ', '.join(heaters_above_waittemp))
            time.sleep(5)

    def hook_gcode_queuing(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
        skipQueuing = False

        if gcode:
            if self.enablePseudoOnOff:
                if gcode == self.pseudoOnGCodeCommand:
                    self.turn_fan_on()
                    comm_instance._log("fanControl: ok")
                    skipQueuing = True
                elif gcode == self.pseudoOffGCodeCommand:
                    self.turn_fan_off()
                    comm_instance._log("fanControl: ok")
                    skipQueuing = True

            if (not self.isfanOn and self.autoOn and (gcode in self._autoOnTriggerGCodeCommandsArray)):
                self._logger.info("Auto-On - Turning fan On (Triggered by %s)" % gcode)
                self.turn_fan_on()

            if self.powerOffWhenIdle and self.isfanOn and not self._skipIdleTimer:
                if not (gcode in self._idleIgnoreCommandsArray):
                    self._waitForHeaters = False
                    self._reset_idle_timer()

            if skipQueuing:
                return (None,)

    def turn_fan_on(self):
        if self.switchingMethod == 'GCODE' or self.switchingMethod == 'GPIO' or self.switchingMethod == 'SYSTEM':
            self._logger.info("Switching fan On")
            if self.switchingMethod == 'GCODE':
                self._logger.debug("Switching fan On Using GCODE: %s" % self.onGCodeCommand)
                self._printer.commands(self.onGCodeCommand)
            elif self.switchingMethod == 'SYSTEM':
                self._logger.debug("Switching fan On Using SYSTEM: %s" % self.onSysCommand)

                p = subprocess.Popen(self.onSysCommand, shell=True)
                self._logger.debug("On system command executed. PID=%s, Command=%s" % (p.pid, self.onSysCommand))
                while p.poll() is None:
                    time.sleep(0.1)
                r = p.returncode

                self._logger.debug("On system command returned: %s" % r)
            elif self.switchingMethod == 'GPIO':
                if not self._hasGPIO:
                    return

                self._logger.debug("Switching fan On Using GPIO: %s" % self.onoffGPIOPin)
                if not self.invertonoffGPIOPin:
                    pin_output=GPIO.HIGH
                else:
                    pin_output=GPIO.LOW

                try:
                    GPIO.output(self._gpio_get_pin(self.onoffGPIOPin), pin_output)
                except (RuntimeError, ValueError) as e:
                    self._logger.error(e)

            if self.sensingMethod not in ('GPIO','SYSTEM'):
                self._noSensing_isfanOn = True
         
            time.sleep(0.1 + self.postOnDelay)
            self.check_fan_state()
        
    def turn_fan_off(self):
        if self.switchingMethod == 'GCODE' or self.switchingMethod == 'GPIO' or self.switchingMethod == 'SYSTEM':
            self._logger.info("Switching fan Off")
            if self.switchingMethod == 'GCODE':
                self._logger.debug("Switching fan Off Using GCODE: %s" % self.offGCodeCommand)
                self._printer.commands(self.offGCodeCommand)
            elif self.switchingMethod == 'SYSTEM':
                self._logger.debug("Switching fan Off Using SYSTEM: %s" % self.offSysCommand)

                p = subprocess.Popen(self.offSysCommand, shell=True)
                self._logger.debug("Off system command executed. PID=%s, Command=%s" % (p.pid, self.offSysCommand))
                while p.poll() is None:
                    time.sleep(0.1)
                r = p.returncode

                self._logger.debug("Off system command returned: %s" % r)
            elif self.switchingMethod == 'GPIO':
                if not self._hasGPIO:
                    return

                self._logger.debug("Switching fan Off Using GPIO: %s" % self.onoffGPIOPin)
                if not self.invertonoffGPIOPin:
                    pin_output=GPIO.LOW
                else:
                    pin_output=GPIO.HIGH

                try:
                    GPIO.output(self._gpio_get_pin(self.onoffGPIOPin), pin_output)
                except (RuntimeError, ValueError) as e:
                    self._logger.error(e)

            if self.disconnectOnPowerOff:
                self._printer.disconnect()
                
            if self.sensingMethod not in ('GPIO','SYSTEM'):
                self._noSensing_isfanOn = False
                        
            time.sleep(0.1)
            self.check_fan_state()

    def get_api_commands(self):
        return dict(
            turnfanOn=[],
            turnfanOff=[],
            togglefan=[],
            getfanState=[]
        )

    def on_api_get(self, request):
        return self.on_api_command("getfanState", [])

    def on_api_command(self, command, data):
        if not user_permission.can():
            return make_response("Insufficient rights", 403)
        
        if command == 'turnfanOn':
            self.turn_fan_on()
        elif command == 'turnfanOff':
            self.turn_fan_off()
        elif command == 'togglefan':
            if self.isfanOn:
                self.turn_fan_off()
            else:
                self.turn_fan_on()
        elif command == 'getfanState':
            return jsonify(isfanOn=self.isfanOn)

    def get_settings_defaults(self):
        return dict(
            GPIOMode = 'BOARD',
            switchingMethod = 'GCODE',
            onoffGPIOPin = 0,
            invertonoffGPIOPin = False,
            onGCodeCommand = 'M80', 
            offGCodeCommand = 'M81', 
            onSysCommand = '',
            offSysCommand = '',
            enablePseudoOnOff = False,
            pseudoOnGCodeCommand = 'M80',
            pseudoOffGCodeCommand = 'M81',
            postOnDelay = 0.0,
            disconnectOnPowerOff = False,
            sensingMethod = 'INTERNAL',
            senseGPIOPin = 0,
            sensePollingInterval = 5,
            invertsenseGPIOPin = False,
            senseGPIOPinPUD = '',
            senseSystemCommand = '',
            autoOn = False,
            autoOnTriggerGCodeCommands = "G0,G1,G2,G3,G10,G11,G28,G29,G32,M104,M106,M109,M140,M190",
            enablePowerOffWarningDialog = True,
            powerOffWhenIdle = False,
            idleTimeout = 30,
            idleIgnoreCommands = 'M105',
            idleTimeoutWaitTemp = 50
        )

    def on_settings_save(self, data):
        old_GPIOMode = self.GPIOMode
        old_onoffGPIOPin = self.onoffGPIOPin
        old_sensingMethod = self.sensingMethod
        old_senseGPIOPin = self.senseGPIOPin
        old_invertsenseGPIOPin = self.invertsenseGPIOPin
        old_senseGPIOPinPUD = self.senseGPIOPinPUD
        old_switchingMethod = self.switchingMethod

        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        
        self.GPIOMode = self._settings.get(["GPIOMode"])
        self.switchingMethod = self._settings.get(["switchingMethod"])
        self.onoffGPIOPin = self._settings.get_int(["onoffGPIOPin"])
        self.invertonoffGPIOPin = self._settings.get_boolean(["invertonoffGPIOPin"])
        self.onGCodeCommand = self._settings.get(["onGCodeCommand"])
        self.offGCodeCommand = self._settings.get(["offGCodeCommand"])
        self.onSysCommand = self._settings.get(["onSysCommand"])
        self.offSysCommand = self._settings.get(["offSysCommand"])
        self.enablePseudoOnOff = self._settings.get_boolean(["enablePseudoOnOff"])
        self.pseudoOnGCodeCommand = self._settings.get(["pseudoOnGCodeCommand"])
        self.pseudoOffGCodeCommand = self._settings.get(["pseudoOffGCodeCommand"])
        self.postOnDelay = self._settings.get_float(["postOnDelay"])
        self.disconnectOnPowerOff = self._settings.get_boolean(["disconnectOnPowerOff"])
        self.sensingMethod = self._settings.get(["sensingMethod"])
        self.senseGPIOPin = self._settings.get_int(["senseGPIOPin"])
        self.sensePollingInterval = self._settings.get_int(["sensePollingInterval"])
        self.invertsenseGPIOPin = self._settings.get_boolean(["invertsenseGPIOPin"])
        self.senseGPIOPinPUD = self._settings.get(["senseGPIOPinPUD"])
        self.senseSystemCommand = self._settings.get(["senseSystemCommand"])
        self.autoOn = self._settings.get_boolean(["autoOn"])
        self.autoOnTriggerGCodeCommands = self._settings.get(["autoOnTriggerGCodeCommands"])
        self._autoOnTriggerGCodeCommandsArray = self.autoOnTriggerGCodeCommands.split(',')
        self.powerOffWhenIdle = self._settings.get_boolean(["powerOffWhenIdle"])
        self.idleTimeout = self._settings.get_int(["idleTimeout"])
        self.idleIgnoreCommands = self._settings.get(["idleIgnoreCommands"])
        self.enablePowerOffWarningDialog = self._settings.get_boolean(["enablePowerOffWarningDialog"])
        self._idleIgnoreCommandsArray = self.idleIgnoreCommands.split(',')
        self.idleTimeoutWaitTemp = self._settings.get_int(["idleTimeoutWaitTemp"])

        #GCode switching and PseudoOnOff are not compatible.
        if self.switchingMethod == 'GCODE' and self.enablePseudoOnOff:
            self.enablePseudoOnOff = False
            self._settings.set_boolean(["enablePseudoOnOff"], self.enablePseudoOnOff)
            self._settings.save()


        if ((old_GPIOMode != self.GPIOMode or
             old_onoffGPIOPin != self.onoffGPIOPin or
             old_senseGPIOPin != self.senseGPIOPin or
             old_sensingMethod != self.sensingMethod or
             old_invertsenseGPIOPin != self.invertsenseGPIOPin or
             old_senseGPIOPinPUD != self.senseGPIOPinPUD or
             old_switchingMethod != self.switchingMethod) and
            (self.switchingMethod == 'GPIO' or self.sensingMethod == 'GPIO')):
            self._configure_gpio()

        self._start_idle_timer()

    def get_settings_version(self):
        return 3

    def on_settings_migrate(self, target, current=None):
        if current is None:
            current = 0

        if current < 2:
            # v2 changes names of settings variables to accomidate system commands.
            cur_switchingMethod = self._settings.get(["switchingMethod"])
            if cur_switchingMethod is not None and cur_switchingMethod == "COMMAND":
                self._logger.info("Migrating Setting: switchingMethod=COMMAND -> switchingMethod=GCODE")
                self._settings.set(["switchingMethod"], "GCODE")

            cur_onCommand = self._settings.get(["onCommand"])
            if cur_onCommand is not None:
                self._logger.info("Migrating Setting: onCommand={0} -> onGCodeCommand={0}".format(cur_onCommand))
                self._settings.set(["onGCodeCommand"], cur_onCommand)
                self._settings.remove(["onCommand"])
            
            cur_offCommand = self._settings.get(["offCommand"])
            if cur_offCommand is not None:
                self._logger.info("Migrating Setting: offCommand={0} -> offGCodeCommand={0}".format(cur_offCommand))
                self._settings.set(["offGCodeCommand"], cur_offCommand)
                self._settings.remove(["offCommand"])

            cur_autoOnCommands = self._settings.get(["autoOnCommands"])
            if cur_autoOnCommands is not None:
                self._logger.info("Migrating Setting: autoOnCommands={0} -> autoOnTriggerGCodeCommands={0}".format(cur_autoOnCommands))
                self._settings.set(["autoOnTriggerGCodeCommands"], cur_autoOnCommands)
                self._settings.remove(["autoOnCommands"])

        if current < 3:
            # v3 adds support for multiple sensing methods
            cur_enableSensing = self._settings.get_boolean(["enableSensing"])
            if cur_enableSensing is not None and cur_enableSensing:
                self._logger.info("Migrating Setting: enableSensing=True -> sensingMethod=GPIO")
                self._settings.set(["sensingMethod"], "GPIO")
                self._settings.remove(["enableSensing"])

    def get_template_configs(self):
        return [
            dict(type="settings", custom_bindings=True)
        ]

    def get_assets(self):
        return {
            "js": ["js/fancontrol.js"],
            "less": ["less/fancontrol.less"],
            "css": ["css/fancontrol.min.css"]

        } 

    def get_update_information(self):
        return dict(
            fancontrol=dict(
                displayName="fan Control",
                displayVersion=self._plugin_version,

                # version check: github repository
                type="github_release",
                user="kantlivelong",
                repo="OctoPrint-fanControl",
                current=self._plugin_version,

                # update method: pip w/ dependency links
                pip="https://github.com/kantlivelong/OctoPrint-fanControl/archive/{target_version}.zip"
            )
        )

__plugin_name__ = "fan Control"
__plugin_pythoncompat__ = ">=2.7,<4"

def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = fanControl()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.comm.protocol.gcode.queuing": __plugin_implementation__.hook_gcode_queuing,
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
    }
