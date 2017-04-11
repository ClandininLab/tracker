// FlyVR
// http://flyvisionlab.weebly.com/
// Contact: Steven Herbst <sherbst@stanford.edu>

// OgreApplication is based on the OGRE3D tutorial framework
// http://www.ogre3d.org/wiki/

#include <chrono>

#define _USE_MATH_DEFINES
#include <math.h>

#include <SimpleIni.h>

#include "OgreApplication.h"
#include "StimManager.h"

using namespace std::chrono;
using namespace OgreConstants;

// Path to folder containing CFG files
// TODO: determine this automatically
auto ResourcePath = "";

// Global variables used to manage access to real and virtual viewer position
std::mutex g_ogreMutex;
Pose3D g_realPose = { 0, 0, 0, 0, 0, 0 };
Pose3D g_virtPose = { 0, 0, 0, 0, 0, 0 };

// Variables used to manage graphics thread
bool kill3D = false;
std::thread graphicsThread;

// Variables used to signal when the graphics thread has started up
bool readyFor3D = false;
std::mutex gfxReadyMutex;
std::condition_variable gfxCV;

// High-level management of the graphics thread
void StartGraphicsThread(void){
	// Graphics setup;
	graphicsThread = std::thread(GraphicsThread);

	// Wait for 3D engine to be up and running
	std::unique_lock<std::mutex> lck(gfxReadyMutex);
	gfxCV.wait(lck, []{return readyFor3D; });
}

void StopGraphicsThread(void){
	// Kill the 3D graphics thread
	kill3D = true;

	// Wait for graphics thread to terminate
	graphicsThread.join();
}

// Thread used to handle graphics operations
void GraphicsThread(void){

	OgreApplication app;

	app.go();
	StimManager stim(app);

	// Let the main thread know that the 3D application is up and running
	{
		std::lock_guard<std::mutex> lck(gfxReadyMutex);
		readyFor3D = true;
	}
	gfxCV.notify_one();

	while (!kill3D){
		// Record iteration start time
		auto loopStart = high_resolution_clock::now();

		// Read out real pose and virtual pose
		Pose3D realPose, virtPose;

		{
			std::unique_lock<std::mutex> lck{ g_ogreMutex };
			realPose = g_realPose;
			virtPose = g_virtPose;
		}

		// Update the stimulus
		stim.Update();

		// Move scene based on difference between real position and virtual position
		app.setRootPos(realPose.x - virtPose.x, 
			           realPose.y - virtPose.y, 
					   realPose.z - virtPose.z);

		// Rotate scene based on difference between real orientation and virtual orientation
		app.setRootRot(realPose.pitch - virtPose.pitch, 
			           realPose.yaw - virtPose.yaw, 
					   realPose.roll - virtPose.roll);

		// Update the projection matrices based on eye position
		app.updateProjMatrices(realPose.x, realPose.y, realPose.z);

		// Render the frame
		app.renderOneFrame();

		// Record iteration stop time
		auto loopStop = high_resolution_clock::now();

		// Aim for a target frame rate
		auto loopDuration = duration<double>(loopStop - loopStart).count();
		if (loopDuration >= TargetLoopDuration){
			std::cout << "Slow frame (" << loopDuration << " s)\n";
		}
		else {
			auto stopTime = loopStart + duration<double>(TargetLoopDuration);
			std::this_thread::sleep_until(stopTime);
		}
	}
}

OgreApplication::OgreApplication(void)
	: mRoot(nullptr),
	mSceneMgr(nullptr),
	mResourcesCfg(Ogre::StringUtil::BLANK),
	mPluginsCfg(Ogre::StringUtil::BLANK),
	mOverlaySystem(nullptr),
	mResourcePath(ResourcePath)
{
}

OgreApplication::~OgreApplication(void)
{
	delete mRoot;
}

void OgreApplication::clear(void){
	mSceneMgr->clearScene();
}

void OgreApplication::createLight(double x, double y, double z){
	Ogre::Light *light = mSceneMgr->createLight();
	light->setPosition(Ogre::Real(x), Ogre::Real(y), Ogre::Real(z));
	mSceneMgr->getRootSceneNode()->attachObject(light);
}

void OgreApplication::setAmbientLight(double r, double g, double b){
	Ogre::SceneNode *rootNode = mSceneMgr->getRootSceneNode();
	mSceneMgr->setAmbientLight(Ogre::ColourValue(r, g, b));
}

void OgreApplication::setRootPos(double x, double y, double z){
	Ogre::SceneNode *rootNode = mSceneMgr->getRootSceneNode();
	rootNode->setPosition(Ogre::Vector3(x, y, z));
}

void OgreApplication::setRootRot(double pitch, double yaw, double roll){
	Ogre::SceneNode *rootNode = mSceneMgr->getRootSceneNode();
	rootNode->setOrientation(rootNode->getInitialOrientation());
	rootNode->pitch(Ogre::Radian(pitch));
	rootNode->yaw(Ogre::Radian(yaw));
	rootNode->roll(Ogre::Radian(roll));
}

Ogre::SceneNode* OgreApplication::createRootChild(void){
	return mSceneMgr->getRootSceneNode()->createChildSceneNode();
}

Ogre::Entity* OgreApplication::createEntity(std::string meshName){
	return mSceneMgr->createEntity(meshName);
}

void OgreApplication::configure(void)
{
	// Show the configuration dialog and initialise the system.
	// You can skip this and use root.restoreConfig() to load configuration
	// settings if you were sure there are valid ones saved in ogre.cfg.
	if (mRoot->restoreConfig())
	{
		// Create multiple render windows
		createWindows();
	}
	else
	{
		throw std::runtime_error("Could not restore Ogre3D config.");
	}
}

bool OgreApplication::createWindows(void)
{
	// Multiple window code modified from PlayPen.cpp

	// Initialize root, but do not create a render window yet
	mRoot->initialise(false);

	// Create all render windows
	for (unsigned i = 0; i < DisplayCount; i++)
	{
		unsigned monitorIndex = DisplayList[i];

		Ogre::String strWindowName = "Window" + Ogre::StringConverter::toString(monitorIndex);

		// Select the desired monitor for this render window
		Ogre::NameValuePairList nvList;
		nvList["monitorIndex"] = Ogre::StringConverter::toString(monitorIndex);

		// Create the new render window and set it up
		mWindows[i] = mRoot->createRenderWindow(strWindowName,
			DisplayWidthPixels, DisplayHeightPixels, DisplayFullscreen, &nvList);
		mWindows[i]->setDeactivateOnFocusChange(false);
	}

	return true;
}

void OgreApplication::chooseSceneManager(void)
{
	// Get the SceneManager, in this case a generic one
	mSceneMgr = mRoot->createSceneManager(Ogre::ST_GENERIC);

	// Initialize the OverlaySystem (changed for Ogre 1.9)
	mOverlaySystem = new Ogre::OverlaySystem();
	mSceneMgr->addRenderQueueListener(mOverlaySystem);
}

void OgreApplication::renderOneFrame(void)
{
	mRoot->renderOneFrame();
}

void OgreApplication::defineMonitors(void){
	// Width and height of each monitor
	double W = DisplayWidthMeters;
	double H = DisplayHeightMeters;

	// North monitor
	mMonitors[North].pa = Ogre::Vector3(-W / 2., -H / 2., -W / 2.);
	mMonitors[North].pb = mMonitors[North].pa + Ogre::Vector3(W, 0, 0);
	mMonitors[North].pc = mMonitors[North].pa + Ogre::Vector3(0, H, 0);

	// West monitor
	mMonitors[West].pa = Ogre::Vector3(-W / 2., -H / 2., W / 2.);
	mMonitors[West].pb = mMonitors[West].pa + Ogre::Vector3(0, 0, -W);
	mMonitors[West].pc = mMonitors[West].pa + Ogre::Vector3(0, H, 0);

	// East monitor
	mMonitors[East].pa = Ogre::Vector3(W / 2., -H / 2., -W / 2.);
	mMonitors[East].pb = mMonitors[East].pa + Ogre::Vector3(0, 0, W);
	mMonitors[East].pc = mMonitors[East].pa + Ogre::Vector3(0, H, 0);
}

void OgreApplication::createCameras(void)
{
	// Define the monitor geometry
	defineMonitors();

	// Create all cameras
	for (unsigned i = 0; i < DisplayCount; i++){
		Ogre::String strCameraName = "Camera" + Ogre::StringConverter::toString(i);

		mCameras[i] = mSceneMgr->createCamera(strCameraName);
	}

	// Update the projection matrices assuming the eye is at the origin
	updateProjMatrices(0, 0, 0);
}

void OgreApplication::updateProjMatrices(double x, double y, double z){
	// Update project matrix used for each display
	// Reference: http://csc.lsu.edu/~kooima/articles/genperspective/

	// Vector corresponding to eye position
	Ogre::Vector3 pe(x, y, z);

	// Update projection matrix for each display
	for (unsigned i = 0; i < DisplayCount; i++){
		// Determine monitor coordinates
		Ogre::Vector3 pa = mMonitors[i].pa;
		Ogre::Vector3 pb = mMonitors[i].pb;
		Ogre::Vector3 pc = mMonitors[i].pc;

		// Determine monitor unit vectors
		Ogre::Vector3 vr = pb - pa;
		vr.normalise();
		Ogre::Vector3 vu = pc - pa;
		vu.normalise();
		Ogre::Vector3 vn = vr.crossProduct(vu);
		vn.normalise();

		// Determine frustum extents
		Ogre::Vector3 va = pa - pe;
		Ogre::Vector3 vb = pb - pe;
		Ogre::Vector3 vc = pc - pe;

		// Compute distance to screen
		Ogre::Real d = -vn.dotProduct(va);

		// Set clipping distance to screen distance
		Ogre::Real n = Ogre::Real(NearClipDist);
		Ogre::Real f = Ogre::Real(FarClipDist);

		// Compute screen coordinates
		Ogre::Real l = vr.dotProduct(va)*n / d;
		Ogre::Real r = vr.dotProduct(vb)*n / d;
		Ogre::Real b = vu.dotProduct(va)*n / d;
		Ogre::Real t = vu.dotProduct(vc)*n / d;

		// Create the composite projection matrix

		// Original projection matrix
		Ogre::Matrix4 P = Ogre::Matrix4(
			(2.0*n) / (r - l), 0, (r + l) / (r - l), 0,
			0, (2.0*n) / (t - b), (t + b) / (t - b), 0,
			0, 0, -(f + n) / (f - n), -(2.0*f*n) / (f - n),
			0, 0, -1, 0);

		// Rotation matrix
		Ogre::Matrix4 M = Ogre::Matrix4(
			vr.x, vu.x, vn.x, 0,
			vr.y, vu.y, vn.y, 0,
			vr.z, vu.z, vn.z, 0,
			0, 0, 0, 1);

		// Translation matrix
		Ogre::Matrix4 T = Ogre::Matrix4(
			1, 0, 0, -pe.x,
			0, 1, 0, -pe.y,
			0, 0, 1, -pe.z,
			0, 0, 0, 1);

		Ogre::Matrix4 offAxis = P*M.transpose()*T;

		mCameras[i]->setCustomProjectionMatrix(true, offAxis);
	}
}

void OgreApplication::createViewports(void)
{
	// Attach each camera to each respective window
	for (unsigned int i = 0; i < DisplayCount; i++){
		mViewports[i] = mWindows[i]->addViewport(mCameras[i]);
	}
}

void OgreApplication::setBackground(double r, double g, double b){
	// Configure the viewport
	for (unsigned int i = 0; i < DisplayCount; i++){
		mViewports[i]->setBackgroundColour(Ogre::ColourValue(r, g, b));
	}
}

void OgreApplication::setupResources(void)
{
	// Load resource paths from config file
	Ogre::ConfigFile cf;
	cf.load(mResourcesCfg);

	// Go through all sections & settings in the file
	Ogre::ConfigFile::SectionIterator seci = cf.getSectionIterator();

	Ogre::String secName, typeName, archName;
	while (seci.hasMoreElements())
	{
		secName = seci.peekNextKey();
		Ogre::ConfigFile::SettingsMultiMap *settings = seci.getNext();
		Ogre::ConfigFile::SettingsMultiMap::iterator i;
		for (i = settings->begin(); i != settings->end(); ++i)
		{
			typeName = i->first;
			archName = i->second;

			Ogre::ResourceGroupManager::getSingleton().addResourceLocation(
				archName, typeName, secName);
		}
	}
}

void OgreApplication::loadResources(void)
{
	Ogre::ResourceGroupManager::getSingleton().initialiseAllResourceGroups();
}

void OgreApplication::go(void)
{
	mResourcesCfg = mResourcePath + "resources.cfg";
	mPluginsCfg = mResourcePath + "plugins.cfg";

	setup();
}

bool OgreApplication::setup(void)
{
	mRoot = new Ogre::Root(mPluginsCfg);

	setupResources();

	configure();

	chooseSceneManager();
	createCameras();
	createViewports();

	// Set default mipmap level (NB some APIs ignore this)
	Ogre::TextureManager::getSingleton().setDefaultNumMipmaps(5);

	// Load resources
	loadResources();

	return true;
};
