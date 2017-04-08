// FlyVR
// http://flyvisionlab.weebly.com/
// Contact: Steven Herbst <sherbst@stanford.edu>

#pragma once

#include <random>
#include <vector>
#include <list>
#include <chrono>
#include <memory>

#include <SimpleIni.h>

#include "Stimulus.h"
#include "OgreApplication.h"

// Name of the stimulus configuration file
#define CONFIG_FILE_NAME "C:\\dev\\Tracker\\Tracker\\config.ini"

enum class StimManagerStates { Init, Interleave, Stimulus };

class StimManager{
public:
	StimManager(OgreApplication &app);
	~StimManager(void);
	void Update(void);
private:
	void PickNextStimulus(void);
	void MakeNextStimulus(std::string name);

	OgreApplication &app;

	double iColorR, iColorG, iColorB;
	double iDuration;
	long randomSeed;

	CSimpleIniA iniFile;
	StimManagerStates state;

	std::unique_ptr<Stimulus> currentStimulus;

	std::mt19937 randomGenerator;
	std::vector<std::string>::iterator currentStimName;
	std::vector<std::string> stimNames;

	std::chrono::system_clock::time_point lastTime;
};