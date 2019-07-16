import cv2
import copy
import numpy as np
import sys

from pypylon import pylon
from math import pi, sqrt, hypot
from time import time
from threading import Lock
import numpy as np
from time import sleep

from flyvr.service import Service

from vrcam.train_angle import AnglePredictor
from vrcam.finder import FlyFinder
from vrcam.image import bound_point
from leap.leap import LeapModel

class CamThread(Service):
    def __init__(self, defaultThresh=150, maxTime=12e-3, bufX=200, bufY=200):
        # Serial I/O interface to CNC
        self.cam = Camera()

        # Lock for communicating fly pose changes
        self.flyDataLock = Lock()
        self.flyData = None

        # Lock for communicating debugging frame changes
        self.frameDataLock = Lock()
        self.frameData = None
        self.bufX=bufX
        self.bufY=bufY

        # Lock for communicating the threshold
        self.threshLock = Lock()
        self.threshold = defaultThresh

        # Lock for the output frame
        self._saveFrame = None
        self.saveFrameLock = Lock()
        self.drawFrame = None

        # File handle for logging
        self.logLock = Lock()
        self.logFile = None
        self.logFull = None
        self.logState = False

        self.show_threshold = False
        self.draw_contours = True

        self.flyPresent = False
        self.fly = None

        self.leap_model = None # gets assigned at setup()

        # call constructor from parent        
        super().__init__(maxTime=maxTime)

    def setup(self):
        self.leap_model = LeapModel()

    @property
    def saveFrame(self):
        with self.saveFrameLock:
            return self._saveFrame

    @saveFrame.setter
    def saveFrame(self, value):
        with self.saveFrameLock:
            self._saveFrame = value

    # overriding method from parent...
    def loopBody(self):
        
        # read and process frame
        self.fly, self.saveFrame, self.drawFrame = self.cam.processNext(leap_model=self.leap_model)

        if self.fly.fly_present:
            self.flyPresent = True
        else:
            self.flyPresent = False

        # # write logs
        # with self.logLock:
        #     if self.logState:
        #         if self.fly is not None:
        #             logStr = (str(time()) + ',' +
        #                       str(self.fly.centerX) + ',' +
        #                       str(self.fly.centerY) + ',' +
        #                       str(self.fly.angle) + '\n')
        #             self.logFile.write(logStr)
        #         if self.saveFrame is not None and self.saveFrame.shape != 0:
        #             self.logFull.write(self.saveFrame)

    @property
    def flyData(self):
        with self.flyDataLock:
            return self._flyData

    @flyData.setter
    def flyData(self, val):
        with self.flyDataLock:
            self._flyData = val

    @property
    def frameData(self):
        with self.frameDataLock:
            return self._frameData

    @frameData.setter
    def frameData(self, val):
        with self.frameDataLock:
            self._frameData = val

    @property
    def threshold(self):
        with self.threshLock:
            return self._threshold

    @threshold.setter
    def threshold(self, val):
        with self.threshLock:
            self._threshold = val

    def startLogging(self, logFile, logFull):
        with self.logLock:
            # save log state
            self.logState = True

            # close previous log file
            if self.logFile is not None:
                self.logFile.close()

            # close previous full log video
            if self.logFull is not None:
                self.logFull.release()

            # open new log file
            self.logFile = open(logFile, 'w')
            self.logFile.write('t,x,y,angle\n')

            # compressed full video
            fourcc_compr = cv2.VideoWriter_fourcc('M', 'J', 'P', 'G')

            # get camera image width/height
            cam_width = self.cam.grab_width
            cam_height = self.cam.grab_height

            self.logFull = cv2.VideoWriter(logFull, fourcc_compr, 124.2, (cam_width, cam_height))

    def stopLogging(self):
        with self.logLock:
            # save log state
            self.logState = False

            # close previous log file
            if self.logFile is not None:
                self.logFile.close()

            # close previous full log video
            if self.logFull is not None:
                self.logFull.release()

    def cleanup(self):
        self.cam.camera.StopGrabbing()

class Camera:
    def __init__(self, px_per_m = 37023.1016957): # calibrated for 2x on 2/6/2018):
        # Instaniate fly finder and predictor from vrcam package
        self.angle_predictor = AnglePredictor()
        self.fly_finder = FlyFinder()

        # Store the number of pixels per meter
        self.px_per_m = px_per_m

        # Open the capture stream
        self.camera = pylon.InstantCamera(pylon.TlFactory.GetInstance().CreateFirstDevice())
        self.camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)

        # Grab a dummy frame to get the width and height
        grabResult = self.camera.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
        self.grab_width = int(grabResult.Width)
        self.grab_height = int(grabResult.Height)
        grabResult.Release()
        print('Camera grab dimensions: ({}, {})'.format(self.grab_width, self.grab_height))

        # Set up image converter
        self.converter = pylon.ImageFormatConverter()
        self.converter.OutputPixelFormat = pylon.PixelType_BGR8packed
        self.converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

    def flyCandidate(self, ellipse):
        return ((self.ma_min <= ellipse.ma <= self.ma_max) and
                (self.MA_min <= ellipse.MA <= self.MA_max) and
                (self.r_min <= ellipse.ma/ellipse.MA <= self.r_max))

    def arrow_from_point(self, img, point, angle, length=30, thickness=3, color=(0, 0, 255)):
        ax = point[0] + length * np.cos(angle)
        ay = point[1] - length * np.sin(angle)
        tip = bound_point((ax, ay), img)
        cv2.arrowedLine(img, point, tip, color, thickness, tipLength=0.3)


    def processNext(self, leap_model=None):
        if not self.camera.IsGrabbing():
            return None, None

        # Capture a single frame
        grabResult = self.camera.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
        image = self.converter.Convert(grabResult)
        inFrame = image.GetArray().copy()
        grabResult.Release()

        # Convert frame to grayscale
        grayFrame = cv2.cvtColor(inFrame, cv2.COLOR_BGR2GRAY)

        # Save frame for video output
        saveFrame = inFrame #cv2.cvtColor(grayFrame, cv2.COLOR_GRAY2BGR)

        # Find fly using LEAP
        fly = leap_model.find_points(grayFrame)
        print('confidences {}'.format(fly.confidences))

        rows, cols = grayFrame.shape

        drawFrame = saveFrame.copy()

        if fly.fly_present:
            fly.centerX = -(fly.body[0] - (cols / 2.0)) / self.px_per_m
            fly.centerY = -(fly.body[1] - (rows / 2.0)) / self.px_per_m
            cv2.circle(drawFrame, fly.body, 5, color=(0, 0, 150), thickness=2, lineType=8, shift=0)
            cv2.circle(drawFrame, fly.head, 5, color=(150, 0, 0), thickness=2, lineType=8, shift=0)
        else:
            fly.centerX = 0
            fly.centerY = 0
            print('no fly')

        return fly, saveFrame, drawFrame

    def __del__(self):
        # When everything done, release the capture handle
        self.camera.StopGrabbing()