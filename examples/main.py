import cv2
import os
import os.path
import itertools
import xmlrpc.client

from time import strftime, perf_counter, time, sleep
from pynput import keyboard
from pynput.keyboard import Key, KeyCode

from flyvr.cnc import CncThread, cnc_home
from flyvr.camera import CamThread
from flyvr.tracker import TrackThread, ManualVelocity
from flyvr.service import Service
from flyvr.servo import ServoGate

from threading import Lock

class Smooth:
    def __init__(self, n):
        self.n = n
        self.hist = [0]*n

    def update(self, value):
        self.hist = [float(value)] + self.hist[:-1]
        return sum(self.hist)/self.n

def nothing(x):
    pass

class TrialThread(Service):
    def __init__(self, exp_dir, cam, loopTime=10e-3, fly_lost_timeout=1, fly_found_timeout=1):
        self.trial_count = itertools.count(1)
        self.state = 'startup'

        self.cam = cam
        self.cnc = None
        self.servo = None
        self.tracker = None
        self.timer_start = None

        self.exp_dir = exp_dir
        self.fly_lost_timeout = fly_lost_timeout
        self.fly_found_timeout = fly_found_timeout

        # set up access to the thread-ending signal
        self.manualLock = Lock()
        self._manualCmd = None

        self.trialDirLock = Lock()
        self._trial_dir = None

        # call constructor from parent
        super().__init__(minTime=loopTime, maxTime=loopTime)

    @property
    def manualCmd(self):
        with self.manualLock:
            return self._manualCmd

    def resetManual(self):
        with self.manualLock:
            self._manualCmd = None

    def manual(self, *args):
        with self.manualLock:
            self._manualCmd = args

    def stop(self):
        super().stop()
        self.tracker.stop()
        self.cnc.stop()

    @property
    def trial_dir(self):
        with self.trialDirLock:
            return self._trial_dir

    def _start_trial(self):
        trial_num = next(self.trial_count)
        print('Started trial ' + str(trial_num))
        folder = 'trial-' + str(trial_num) + '-' + strftime('%Y%m%d-%H%M%S')
        _trial_dir = os.path.join(self.exp_dir, folder)
        os.makedirs(_trial_dir)

        self.cnc.startLogging(os.path.join(_trial_dir, 'cnc.txt'))
        self.cam.startLogging(os.path.join(_trial_dir, 'cam.txt'),
                              os.path.join(_trial_dir, 'cam_uncompr.mkv'),
                              os.path.join(_trial_dir, 'cam_compr.mkv'))

        self._trial_dir = _trial_dir

    def _stop_trial(self):
        print('Stopped trial.')

        self.cnc.stopLogging()
        self.cam.stopLogging()
        self.tracker.stopTracking()

    def loopBody(self):
        if self.state == 'startup':
            print('** startup **')

            # Open connection to servo
            # self.servo = ServoGate(debug=True)

            # Open connection to CNC rig
            cnc_home()
            self.cnc = CncThread()
            self.cnc.start()
            sleep(0.1)

            # Start tracker thread
            self.tracker = TrackThread(cncThread=self.cnc, camThread=self.cam)
            self.tracker.start()
            self.tracker.move_to_center()

            # go to the manual control state
            self.resetManual()
            self.state = 'manual'
            print('** manual **')
        elif self.state == 'started':
            if self.manualCmd is not None:
                # self.servo.close()
                self.state = 'manual'
                print('** manual **')
            elif self.cam.flyData.flyPresent:
                print('Fly possibly found...')
                self.timer_start = time()
                self.state = 'fly_found'
                print('** fly_found **')
                self.tracker.startTracking()
        elif self.state == 'fly_found':
            if self.manualCmd is not None:
                # self.servo.close()
                self.tracker.stopTracking()
                self.state = 'manual'
                print('** manual **')
            elif not self.cam.flyData.flyPresent:
                print('Fly lost.')
                self.state = 'started'
                print('** started **')
                self.tracker.stopTracking()
                self.tracker.move_to_center()
            elif (time() - self.timer_start) >= self.fly_found_timeout:
                print('Fly found.')
                # self.servo.close()
                self._start_trial()
                self.state = 'run'
                print('** run **')
        elif self.state == 'run':
            if self.manualCmd is not None:
                self._stop_trial()
                self.state = 'manual'
                print('** manual **')
            elif not self.cam.flyData.flyPresent:
                print('Fly possibly lost...')
                self.timer_start = time()
                self.state = 'fly_lost'
                print('** fly_lost **')
        elif self.state == 'fly_lost':
            if self.manualCmd is not None:
                self._stop_trial()
                self.state = 'manual'
                print('** manual **')
            elif self.cam.flyData.flyPresent:
                print('Fly located again.')
                self.state = 'run'
                print('** run **')
            elif (time() - self.timer_start) >= self.fly_lost_timeout:
                print('Fly lost.')
                self._stop_trial()
                self.tracker.move_to_center()
                # self.servo.open()
                self.state = 'started'
                print('** started **')
        elif self.state == 'manual':
            manualCmd = self.manualCmd

            if manualCmd is None:
                pass
            elif manualCmd[0] == 'start':
                # self.servo.open()
                self.state = 'started'
                print('** started **')
            elif manualCmd[0] == 'stop':
                print('** manual: stop **')
            elif manualCmd[0] == 'center':
                print('** manual: center **')
                self.tracker.move_to_center()
            elif manualCmd[0] == 'nojog':
                print('** manual: nojog **')
                self.tracker.manualVelocity = None
            elif manualCmd[0] == 'jog':
                manualVelocity = ManualVelocity(velX=manualCmd[1], velY=manualCmd[2])
                self.tracker.manualVelocity = manualVelocity
            elif manualCmd[0] == 'open_servo':
                # self.servo.open()
                pass
            elif manualCmd[0] == 'close_servo':
                # self.servo.close()
                pass
            else:
                raise Exception('Invalid manual command.')

            if (manualCmd is not None) and (manualCmd[0] != 'jog'):
                self.resetManual()
        else:
            raise Exception('Invalid state.')

def main():
    # handler for key events
    keySet = set()
    def on_press(key):
        keySet.add(key)
    def on_release(key):
        keySet.remove(key)
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    prev_key_set = set()

    # create folder for data
    topdir = r'E:\FlyVR'
    folder = 'exp-'+strftime('%Y%m%d-%H%M%S')
    exp_dir = os.path.join(topdir, folder)
    os.makedirs(exp_dir)

    # settings for UI
    tLoop = 1/24
    draw_contour = True
    draw_details = False
    absJogVel = 0.01

    # create the UI
    cv2.namedWindow('image')
    cv2.createTrackbar('threshold', 'image', 115, 254, nothing)
    cv2.createTrackbar('imageType', 'image', 0, 2, nothing)

    # level related settings
    cv2.createTrackbar('level', 'image', 0, 255, nothing)
    lastLevel = -1

    # servo settings
    # cv2.createTrackbar('open', 'image', 180, 180, nothing)
    # cv2.createTrackbar('closed', 'image', 130, 180, nothing)
    # lastOpenPos = 180
    # lastClosedPos = 130

    # fly detection settings
    # cv2.createTrackbar('ma_min', 'image', 6, 25, nothing)
    # cv2.createTrackbar('ma_max', 'image', 11, 25, nothing)
    # cv2.createTrackbar('MA_min', 'image', 22, 50, nothing)
    # cv2.createTrackbar('MA_max', 'image', 33, 50, nothing)
    cv2.createTrackbar('r_min', 'image', 2, 10, nothing)
    cv2.createTrackbar('r_max', 'image', 5, 10, nothing)

    # loop gain settings
    cv2.createTrackbar('loop_gain', 'image', 100, 750, nothing)

    # Open connection to camera
    cam = CamThread()
    cam.start()

    # Run trial manager
    trialThread = TrialThread(exp_dir=exp_dir, cam=cam)
    trialThread.start()

    focus_smoother = Smooth(12)
    ma_smoother = Smooth(12)
    MA_smoother = Smooth(12)

    # open the connection to display service
    print('opening display proxy...')
    display_proxy = xmlrpc.client.ServerProxy("http://127.0.0.1:54357/")
    print('done.')

    # main program loop
    while keyboard.Key.esc not in keySet:
        # handle keypress events
        new_keys = keySet - prev_key_set
        prev_key_set = set(keySet)

        if KeyCode.from_char('f') in new_keys:
            draw_details = not draw_details
        if KeyCode.from_char('d') in new_keys:
            draw_contour = not draw_contour
        if KeyCode.from_char('r') in new_keys:
            cncStatus = trialThread.cnc.status
            if cncStatus is not None:
                posX, posY = cncStatus.posX, cncStatus.posY
                trialThread.tracker.set_center_pos(posX=posX, posY=posY)
            print('new center position set...')
        if KeyCode.from_char('s') in new_keys:
            if trialThread.cnc is not None:
                cncStatus = trialThread.cnc.status
                if cncStatus is not None:
                    print('cncX: {}, cncY: {}'.format(cncStatus.posX, cncStatus.posY))


        # manual control options
        if Key.space in new_keys:
            trialThread.manual('stop')
        if Key.enter in new_keys:
            trialThread.manual('start')
        if KeyCode.from_char('c') in new_keys:
            trialThread.manual('center')
        if KeyCode.from_char('o') in new_keys:
            # trialThread.manual('open_servo')
            pass
        if KeyCode.from_char('l') in new_keys:
            # trialThread.manual('close_servo')
            pass

        # handle up/down keyboard input
        if Key.up in keySet:
            manVelY = +absJogVel
        elif Key.down in keySet:
            manVelY = -absJogVel
        else:
            manVelY = 0

        # handle left/right keyboard input
        if Key.right in keySet:
            manVelX = -absJogVel
        elif Key.left in keySet:
            manVelX = +absJogVel
        else:
            manVelX = 0

        if (manVelX != 0) or (manVelY != 0):
            trialThread.manual('jog', manVelX, manVelY)
        else:
            manualCmd = trialThread.manualCmd
            if (manualCmd is not None) and manualCmd[0] == 'jog':
                trialThread.manual('nojog')

        # read out level
        levelTrack = cv2.getTrackbarPos('level', 'image')
        if levelTrack != lastLevel:
            newLevel = levelTrack/255
            display_proxy.set_level(newLevel)
        lastLevel = levelTrack

        # read out servo settings
        # TODO: add proper locking
        # openPos = cv2.getTrackbarPos('open', 'image')
        # if openPos != lastOpenPos:
        #    trialThread.servo.opened_pos = openPos
        # lastOpenPos = openPos
        # closedPos = cv2.getTrackbarPos('closed', 'image')
        # if closedPos != lastClosedPos:
        #    trialThread.servo.closed_pos = closedPos
        # lastClosedPos = closedPos

        # set camera detection settings
        #ma_min=cv2.getTrackbarPos('ma_min', 'image')
        #ma_max=cv2.getTrackbarPos('ma_max', 'image')
        #MA_min=cv2.getTrackbarPos('MA_min', 'image')
        #MA_max=cv2.getTrackbarPos('MA_max', 'image')
        r_min=cv2.getTrackbarPos('r_min', 'image')
        r_max=cv2.getTrackbarPos('r_max', 'image')
        # cam.cam.ma_min=ma_min
        # cam.cam.ma_max = ma_max
        # cam.cam.MA_min = MA_min
        # cam.cam.MA_max = MA_max
        cam.cam.r_min = r_min/10.0
        cam.cam.r_max = r_max/10.0

        # read out tracker settings
        loop_gain = 0.1 * cv2.getTrackbarPos('loop_gain', 'image')
        if trialThread.tracker is not None:
            # check needed since tracker may not have been initialized yet
            trialThread.tracker.a = loop_gain

        trial_dir = trialThread.trial_dir
        if trial_dir is not None:
            with open(os.path.join(trial_dir, 'display.txt'), 'a') as f:
                f.write(str(perf_counter()) + ', ' + str(lastLevel) + '\n')

        # compute new thresholds
        threshTrack = cv2.getTrackbarPos('threshold', 'image')
        threshold = threshTrack + 1

        # issue threshold command
        cam.threshold = threshold

        # determine the type of image that should be displayed
        typeTrack = cv2.getTrackbarPos('imageType', 'image')

        # get raw fly position
        frameData = cam.frameData
        
        if frameData is not None:
            # get the image to display
            if typeTrack==0:
                outFrame = frameData.inFrame
            elif typeTrack==1:
                outFrame = cv2.cvtColor(frameData.grayFrame, cv2.COLOR_GRAY2BGR)
            elif typeTrack==2:
                outFrame = cv2.cvtColor(frameData.threshFrame, cv2.COLOR_GRAY2BGR)
            else:
                raise Exception('Invalid image type.')

            # get the fly contour
            flyContour = frameData.flyContour

            # draw the fly contour if status available
            drawFrame = outFrame.copy()
            if draw_contour and (flyContour is not None):
                cv2.drawContours(drawFrame, [flyContour], 0, (0, 255, 0), 2)

            # compute focus if needed
            if draw_details:
                flyData = cam.flyData
                if (flyData is not None) and flyData.flyPresent:
                    # compute center of region to use for focus calculation
                    rows, cols = frameData.grayFrame.shape
                    bufX = 50
                    bufY = 50
                    flyX_px = min(max(int(round(flyData.flyX_px)), bufX), cols - bufX)
                    flyY_px = min(max(int(round(flyData.flyY_px)), bufY), rows - bufY)

                    # select region to be used for focus calculation
                    focus_roi = frameData.grayFrame[flyY_px - bufY: flyY_px + bufY,
                                                    flyX_px - bufX: flyX_px + bufX]

                    # compute focus figure of merit
                    focus = focus_smoother.update(cv2.Laplacian(focus_roi, cv2.CV_64F).var())
                    focus_str = 'focus: {0:.3f}'.format(focus)

                    # display focus information
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    x0 = 0
                    y0 = 25
                    dy = 50
                    cv2.putText(drawFrame, focus_str, (x0, y0), font, 1, (0, 0, 0))

                    # display minor/major axis information
                    ma = ma_smoother.update(flyData.ma)
                    MA = MA_smoother.update(flyData.MA)
                    r = ma/MA
                    ellipse_str = '{:.1f}, {:.1f}, {:.3f}'.format(1e3*ma, 1e3*MA, r)
                    cv2.putText(drawFrame, ellipse_str, (x0, y0+dy), font, 1, (0, 0, 0))

            # show the image
            cv2.imshow('image', drawFrame)

        # display image
        cv2.waitKey(int(round(1e3*tLoop)))

    # stop the trial thread manager
    trialThread.stop()

    # stop camera thread
    cam.stop()
    print('Camera FPS: ', 1/cam.avePeriod)

    # close UI window
    cv2.destroyAllWindows()

    # close the keyboard listener
    listener.stop()
        
if __name__ == '__main__':
    main()