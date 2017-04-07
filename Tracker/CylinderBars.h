// FlyVR
// http://flyvisionlab.weebly.com/
// Contact: Steven Herbst <sherbst@stanford.edu>

#pragma once

#include <string>
#include <chrono>
#include <SimpleIni.h>

#include "OgreApplication.h"
#include <OgreSceneNode.h>
#include "Stimulus.h"

#define CUBE_SIDE_LENGTH 100.0

enum class CylinderBarStates {Init, WaitBefore, Active, WaitAfter};

class CylinderBars : public Stimulus{
	public:
		CylinderBars(std::string name, OgreApplication &app, CSimpleIniA &iniFile);
		~CylinderBars();
		void Setup();
		void Update();
		void Destroy();
	private:
		void CreateScene(void);

		std::string name;
		OgreApplication &app;
		CSimpleIniA &iniFile;

		Ogre::SceneNode *stimNode;

		CylinderBarStates currentState;

		std::chrono::system_clock::time_point lastTime;

		long numSpatialPeriod;
		double dutyCycle;

		double foreColorR;
		double foreColorG;
		double foreColorB;

		double backColorR;
		double backColorG;
		double backColorB;

		double backLightR;
		double backLightG;
		double backLightB;

		double lightHeight;

		double waitBefore;
		double activeDuration;
		double waitAfter;

		double rotationSpeed;

		double patternRadius;
		double panelHeight;
		double panelThickness;
};